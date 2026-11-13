"""Run-specific offline controls against the immutable R028 parent, no API calls."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE/"tests"))
from test_news_components import ScriptedClient,NoDelay
from runs import sequential_next_20261103 as driver
from sim.provenance import sha256

PARENT=BASE/"runs/20261103_183126_sequential_markets_bb927356"


class LinkedSeedChecks(unittest.TestCase):
    def setUp(self):
        scratch=BASE/".tmp";scratch.mkdir(exist_ok=True)
        temp=tempfile.TemporaryDirectory(dir=scratch);self.output=Path(temp.name)
        self.addCleanup(temp.cleanup)
        ScriptedClient.calls=0;ScriptedClient.fail_on=None
        ScriptedClient.empty_reflection=ScriptedClient.malformed=False
        self.parent_summary=sha256(PARENT/"block_4103/summary.json")
        with contextlib.redirect_stdout(io.StringIO()):self.phase=driver.prepare(PARENT,self.output)

    def offline(self):
        with patch("sim.engine.LLMClient",ScriptedClient),patch.object(driver,"RequestPacer",NoDelay),contextlib.redirect_stdout(io.StringIO()):
            return driver.execute(self.phase)

    def test_full_fresh_seed_and_true_C_feedback_without_parent_or_future_calls(self):
        block=self.offline();summary=driver.read(block/"summary.json")
        self.assertEqual((summary["status"],summary["completed_markets"]),("completed",3))
        self.assertEqual(ScriptedClient.calls,152)
        rows=driver.read(block/"runs.json");self.assertEqual([r["mode"] for r in rows],list("BCA"))
        for row in rows:self.assertEqual(sha256(self.phase/row["config"]),row["config_sha256"])
        c=self.phase/next(r["run_path"] for r in rows if r["mode"]=="C")
        outcomes=[json.loads(s) for s in (c/"agent_outcomes.jsonl").read_text().splitlines()]
        calls=[json.loads(s) for s in (c/"llm_requests.jsonl").read_text().splitlines()]
        reflections=[r for r in calls if r.get("call_type")=="reflection" and r["record_type"]=="model_call"]
        self.assertEqual(len(reflections),8)
        for call in reflections:
            actual=json.loads(call["messages"][1]["content"].split("\nVerified recent outcomes: ",1)[1])
            expected=[r["outcome"] for r in outcomes if r["agent_id"]==call["agent_id"] and r["outcome"]["round"]<=call["round"]][-5:]
            self.assertEqual(actual,expected);self.assertEqual(call["temperature_sent"],0)
        self.assertEqual(sha256(PARENT/"block_4103/summary.json"),self.parent_summary)
        self.assertFalse((self.phase/"block_6317").exists())
        with self.assertRaisesRegex(ValueError,"already started"):self.offline()
        with contextlib.redirect_stdout(io.StringIO()):other=driver.prepare(PARENT,self.output)
        with self.assertRaisesRegex(ValueError,"another linked phase"):driver.execute(other)
        self.assertEqual(ScriptedClient.calls,152)

    def test_first_real_slot_failure_preserves_partial_and_stops_later_modes(self):
        ScriptedClient.fail_on=1;block=self.offline();summary=driver.read(block/"summary.json")
        self.assertEqual((summary["status"],summary["recorded_markets"],summary["completed_markets"]),("stopped",1,0))
        self.assertEqual(ScriptedClient.calls,1)
        row=driver.read(block/"runs.json")[0];self.assertEqual((row["mode"],row["rounds"]),("B",0))
        self.assertEqual(sha256(PARENT/"block_4103/summary.json"),self.parent_summary)

    def test_copied_config_drift_blocks_before_api(self):
        amendment=driver.read(self.phase/"amendment.json")
        path=self.phase/amendment["arms"][0]["config"];path.write_text(path.read_text()+"\n# drift\n")
        with self.assertRaisesRegex(ValueError,"config drift"):self.offline()
        self.assertEqual(ScriptedClient.calls,0)


if __name__=="__main__":unittest.main()
