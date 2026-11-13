"""Research-adapter checks; scripted replies are software evidence only."""
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
from runs import horizon_pilot_20261104 as driver


class CapturedClient(ScriptedClient):
    sent=[]
    def chat(self,messages,**kwargs):
        type(self).sent.append([dict(m) for m in messages])
        return super().chat(messages,**kwargs)


class FirstDouble503(CapturedClient):
    def chat(self,*args,**kwargs):
        if type(self).calls<2:
            type(self).calls+=1
            raise HTTPError("https://example.invalid",503,"unavailable",{},None)
        return super().chat(*args,**kwargs)


class HorizonChecks(unittest.TestCase):
    def setUp(self):
        scratch=BASE/".tmp";scratch.mkdir(exist_ok=True)
        temp=tempfile.TemporaryDirectory(dir=scratch);self.output=Path(temp.name);self.addCleanup(temp.cleanup)
        for cls in (CapturedClient,FirstDouble503):
            cls.calls=0;cls.sent=[];cls.fail_on=None;cls.empty_reflection=cls.malformed=False
        with contextlib.redirect_stdout(io.StringIO()):
            self.root=driver.prepare(self.output);driver.baselines(self.root)

    def offline(self,cls=CapturedClient):
        with patch("sim.engine.LLMClient",cls),patch.object(driver,"RequestPacer",NoDelay),patch("sim.agents.llm_agent.time.sleep") as sleeps,contextlib.redirect_stdout(io.StringIO()):driver.execute(self.root)
        self.assertIs(driver.engine.LLMAgent,driver.LLMAgent)
        return driver.read(self.root/"summary.json"),sleeps

    def test_transmitted_prompts_logged_exactly_and_only_prefix_changes(self):
        s,_=self.offline();self.assertEqual((s["status"],CapturedClient.calls),("completed",192))
        by={};allcalls=[]
        for e in driver.read(self.root/"runs.json"):
            path=self.root/e["run_path"];driver.verify_market(path)
            rows=[json.loads(l) for l in (path/"llm_requests.jsonl").read_text().splitlines()]
            calls=[r for r in rows if r["record_type"]=="model_call"];allcalls.extend(calls)
            self.assertEqual(len(calls),48)
            self.assertTrue(all(r["horizon_visibility"]==e["visibility"] and r["research_adapter_version"]==driver.VERSION and r["base_prompt_version"]=="simple_A_v2" for r in rows))
            by[e["seed"],e["visibility"]]=(path,calls)
        self.assertEqual([r["messages"] for r in allcalls],CapturedClient.sent)
        for seed in driver.SEEDS:
            shown,hidden=(by[seed,c] for c in ("shown","hidden"))
            for x,y in zip(shown[1],hidden[1]):
                self.assertEqual(x["messages"][0],y["messages"][0])
                prefix=f"Round {x['round']}/24."
                self.assertTrue(x["messages"][1]["content"].startswith(prefix))
                self.assertEqual(f"Round {x['round']}."+x["messages"][1]["content"][len(prefix):],y["messages"][1]["content"])
            for name in ("prices.csv","trades.csv","agents_state.csv"):
                self.assertEqual((shown[0]/name).read_bytes(),(hidden[0]/name).read_bytes())
        driver.validate(self.root)
        with self.assertRaisesRegex(ValueError,"already started"):driver.execute(self.root)

    def test_only_double503_continues_and_does_not_replay(self):
        s,sleeps=self.offline(FirstDouble503)
        self.assertEqual((s["status"],s["recorded_markets"],s["completed_markets"]),("completed_with_missing",4,3))
        self.assertEqual(FirstDouble503.calls,146)
        self.assertIn(unittest.mock.call(60),sleeps.call_args_list)
        self.assertEqual(driver.read(self.root/"runs.json")[0]["rounds"],0)

    def test_quota_stops_instead_of_advancing(self):
        CapturedClient.fail_on=1;s,_=self.offline()
        self.assertEqual((s["status"],s["recorded_markets"],CapturedClient.calls),("stopped",1,1))

    def test_config_drift_blocks_without_api(self):
        e=driver.read(self.root/"protocol.json")["arms"][0];path=self.root/e["config"]
        path.write_text(path.read_text()+"\n# drift\n")
        with self.assertRaisesRegex(ValueError,"config drift"):self.offline()
        self.assertEqual(CapturedClient.calls,0)


if __name__=="__main__":unittest.main()
