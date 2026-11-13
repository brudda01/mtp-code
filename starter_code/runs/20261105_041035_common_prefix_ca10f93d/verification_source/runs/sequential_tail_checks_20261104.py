"""Offline checks of R030 scheduling using the frozen real parent evidence."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

BASE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(BASE/"tests"))
from test_news_components import ScriptedClient,NoDelay
from runs import sequential_tail_20261104 as driver


class FirstDouble503(ScriptedClient):
    def chat(self,*args,**kwargs):
        if type(self).calls<2:
            type(self).calls+=1
            raise HTTPError("https://example.invalid",503,"unavailable",{},None)
        return super().chat(*args,**kwargs)


class TailChecks(unittest.TestCase):
    def setUp(self):
        scratch=BASE/".tmp";scratch.mkdir(exist_ok=True)
        temp=tempfile.TemporaryDirectory(dir=scratch);self.output=Path(temp.name);self.addCleanup(temp.cleanup)
        for cls in (ScriptedClient,FirstDouble503):
            cls.calls=0;cls.fail_on=None;cls.empty_reflection=cls.malformed=False
        with contextlib.redirect_stdout(io.StringIO()):self.phase=driver.prepare(self.output)

    def offline(self,client=ScriptedClient):
        with patch("sim.engine.LLMClient",client),patch.object(driver,"RequestPacer",NoDelay),patch("sim.agents.llm_agent.time.sleep") as sleeps,contextlib.redirect_stdout(io.StringIO()):
            driver.execute(self.phase)
        return driver.read(self.phase/"summary.json"),sleeps

    def test_all_four_once_actual_C_feedback_and_no_old_C_replay(self):
        summary,_=self.offline()
        self.assertEqual((summary["status"],summary["completed_markets"]),("completed",4))
        self.assertEqual(ScriptedClient.calls,200)
        index=driver.read(self.phase/"runs.json")
        self.assertEqual([(e["seed"],e["mode"]) for e in index],list(driver.SLOTS))
        c=self.phase/next(e["run_path"] for e in index if e["mode"]=="C")
        outcomes=[json.loads(s) for s in (c/"agent_outcomes.jsonl").read_text().splitlines()]
        refs=[r for s in (c/"llm_requests.jsonl").read_text().splitlines() if (r:=json.loads(s)).get("call_type")=="reflection" and r["record_type"]=="model_call"]
        self.assertEqual(len(refs),8)
        for call in refs:
            actual=json.loads(call["messages"][1]["content"].split("\nVerified recent outcomes: ",1)[1])
            expected=[r["outcome"] for r in outcomes if r["agent_id"]==call["agent_id"] and r["outcome"]["round"]<=call["round"]][-5:]
            self.assertEqual(actual,expected)
        driver.validate_tail(self.phase)
        with self.assertRaisesRegex(ValueError,"already started"):driver.execute(self.phase)
        with contextlib.redirect_stdout(io.StringIO()):other=driver.prepare(self.output)
        with self.assertRaisesRegex(ValueError,"another phase"):driver.execute(other)

    def test_only_terminal_double503_allows_next_independent_market_after_cooldown(self):
        summary,sleeps=self.offline(FirstDouble503)
        self.assertEqual((summary["status"],summary["recorded_markets"],summary["completed_markets"]),("completed_with_missing",4,3))
        rows=driver.read(self.phase/"runs.json")
        self.assertEqual((rows[0]["seed"],rows[0]["mode"],rows[0]["rounds"]),(5209,"A",0))
        self.assertTrue(rows[0]["terminal_double503"])
        self.assertEqual(FirstDouble503.calls,154)
        self.assertIn(unittest.mock.call(60),sleeps.call_args_list)

    def test_quota_error_stops_whole_phase_without_next_market(self):
        ScriptedClient.fail_on=1;summary,_=self.offline()
        self.assertEqual((summary["status"],summary["recorded_markets"],summary["completed_markets"]),("stopped",1,0))
        self.assertEqual(ScriptedClient.calls,1)

    def test_config_drift_blocks_before_any_call(self):
        a=driver.read(self.phase/"amendment.json");p=self.phase/a["arms"][0]["config"]
        p.write_text(p.read_text()+"\n# drift\n")
        with self.assertRaisesRegex(ValueError,"config drift"):self.offline()
        self.assertEqual(ScriptedClient.calls,0)


if __name__=="__main__":unittest.main()
