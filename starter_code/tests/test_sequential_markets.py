import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import test_news_components as fixtures
from sim.evaluation import read_rows
from sim.sequential_markets import execute_block, prepare, recipe, validate


class OneMalformedDecision(fixtures.ScriptedClient):
    def chat(self,*args,**kwargs):
        raw=super().chat(*args,**kwargs)
        return "[]" if type(self).calls<=2 else raw


class SequentialMarketTests(unittest.TestCase):
    def setUp(self):
        scratch=Path(__file__).resolve().parents[1]/".tmp";scratch.mkdir(exist_ok=True)
        tmp=tempfile.TemporaryDirectory(dir=scratch);self.root=Path(tmp.name)
        assert self.root.resolve().is_relative_to(scratch.resolve())
        self.addCleanup(tmp.cleanup)
        background=patch("sim.sequential_markets.BACKGROUND_ROUNDS",30);background.start();self.addCleanup(background.stop)
        fixtures.ScriptedClient.calls=0;fixtures.ScriptedClient.fail_on=None
        fixtures.ScriptedClient.empty_reflection=fixtures.ScriptedClient.malformed=False
        with contextlib.redirect_stdout(io.StringIO()):self.study=prepare(self.root)
        self.protocol=validate(self.study)

    def offline(self,seed=None,client=fixtures.ScriptedClient):
        with patch("sim.engine.LLMClient",client),patch("sim.sequential_markets.RequestPacer",fixtures.NoDelay),contextlib.redirect_stdout(io.StringIO()):
            return execute_block(self.study,seed or self.protocol["seeds"][0])

    def test_common_profile_and_resources_differ_only_in_intended_conditions(self):
        configs=[recipe(4103,c).to_dict() for c in "ABC"]
        normalized=[]
        for c,cfg in zip("ABC",configs):
            llm=cfg["agents"][-1]["llm"]
            self.assertEqual(llm["max_tokens"],8192);self.assertEqual(llm["memory_window"],5)
            self.assertEqual(llm["reflect_every"],5 if c=="C" else 0)
            self.assertTrue(cfg["llm_limits"]["stop_on_api_error"])
            self.assertEqual(cfg["llm_limits"]["max_reserved_tokens"],1100000)
            cfg.pop("name");llm.pop("condition");llm.pop("reflect_every");normalized.append(cfg)
        self.assertEqual(normalized[0],normalized[1]);self.assertEqual(normalized[1],normalized[2])
        self.assertEqual([[a["mode"] for a in b["arms"]] for b in self.protocol["blocks"]],[list("ABC"),list("BCA"),list("CAB")])
        self.assertEqual(self.protocol["planned"]["campaign_requests"],456)

    def test_full_first_gate_has_real_own_C_outcomes_and_no_later_seed_calls(self):
        block=self.offline();summary=json.loads((block/"summary.json").read_text())
        self.assertEqual((summary["status"],summary["completed_markets"]),("completed",3))
        self.assertEqual(fixtures.ScriptedClient.calls,152)
        baseline=json.loads((self.study/"baseline_runs.json").read_text())
        self.assertEqual(len(baseline),9)
        for e in baseline:
            s=json.loads((self.study/e["run_path"]/"summary.json").read_text())
            self.assertEqual(s["llm_usage"]["requests_made"],0)
        runs=json.loads((block/"runs.json").read_text());personas=[]
        for e in runs:
            path=self.study/e["run_path"]
            self.assertEqual(len(read_rows(path/"prices.csv")),24)
            personas.append(json.loads((path/"personas.json").read_text()))
        self.assertEqual(personas[0],personas[1]);self.assertEqual(personas[1],personas[2])
        cpath=self.study/next(e["run_path"] for e in runs if e["mode"]=="C")
        outcomes=[json.loads(s) for s in (cpath/"agent_outcomes.jsonl").read_text().splitlines()]
        calls=[json.loads(s) for s in (cpath/"llm_requests.jsonl").read_text().splitlines() if json.loads(s)["record_type"]=="model_call"]
        reflections=[r for r in calls if r["call_type"]=="reflection"]
        self.assertEqual(len(reflections),8)
        for r in reflections:
            own=[o["outcome"] for o in outcomes if o["agent_id"]==r["agent_id"] and o["outcome"]["round"]<=r["round"]][-5:]
            actual=json.loads(r["messages"][1]["content"].split("\nVerified recent outcomes: ",1)[1])
            self.assertEqual(actual,own)
            self.assertTrue(all("fills" in row and "executed_buy_quantity" in row for row in actual))
            self.assertEqual(r["temperature_sent"],0)
        self.assertFalse((self.study/f"block_{self.protocol['seeds'][1]}").exists())
        with self.assertRaisesRegex(ValueError,"already started"):self.offline()

    def test_provider_failure_stops_first_arm_and_preserves_zero_round_evidence(self):
        fixtures.ScriptedClient.fail_on=1
        block=self.offline();s=json.loads((block/"summary.json").read_text())
        self.assertEqual((s["status"],s["recorded_markets"],s["completed_markets"]),("stopped",1,0))
        self.assertEqual(fixtures.ScriptedClient.calls,1)
        index=json.loads((block/"runs.json").read_text())
        self.assertEqual(index[0]["rounds"],0)
        self.assertTrue((self.study/index[0]["run_path"]/"llm_requests.jsonl").exists())

    def test_later_seed_cannot_skip_the_first_gate(self):
        with self.assertRaisesRegex(ValueError,"earlier block"):self.offline(self.protocol["seeds"][1])
        self.assertEqual(fixtures.ScriptedClient.calls,0)
        self.assertFalse((self.study/"baseline_execution.json").exists())

    def test_config_and_protocol_drift_block_calls(self):
        path=self.study/self.protocol["blocks"][0]["arms"][0]["config"]
        path.write_text(path.read_text()+"\n# changed\n")
        with self.assertRaisesRegex(ValueError,"config drift"):self.offline()
        self.assertEqual(fixtures.ScriptedClient.calls,0)

    def test_existing_safe_fallback_is_flagged_and_stops_later_arms(self):
        OneMalformedDecision.calls=0
        block=self.offline(client=OneMalformedDecision);s=json.loads((block/"summary.json").read_text())
        self.assertEqual((s["status"],s["recorded_markets"],s["failure_type"]),("stopped",1,"operational_fallback"))
        e=json.loads((block/"runs.json").read_text())[0]
        self.assertEqual(e["rounds"],24)
        self.assertEqual(e["operational_failures"]["parse_failures"],1)


if __name__=="__main__":unittest.main()
