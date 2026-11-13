import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from sim.news_controls import HEADLINE
from sim.news_pilot import SEEDS, extract_probes, execute, load_study, market_recipe, prepare, run_probes


class NoDelayPacer:
    def __init__(self,rpm,tpm):self.requests_per_minute=rpm;self.input_tokens_per_minute=tpm
    def acquire(self,estimate):return 0


class OfflineQwen:
    calls=0
    fail=False
    def __init__(self,model,base_url,reasoning_effort=None,send_temperature=True,**kwargs):
        self.model=model;self.base_url=base_url;self.reasoning_effort=reasoning_effort
        self.send_temperature=send_temperature;self.api_key="offline-only";self.total_tokens=0
        self.last_usage=None;self.last_response_metadata={};self.last_error_metadata={}
    def chat(self,messages,**kwargs):
        type(self).calls+=1
        if type(self).fail:raise HTTPError("https://example.invalid",429,"quota",{},None)
        self.total_tokens+=10
        self.last_usage=dict(source="estimated_mock",prompt_tokens=8,completion_tokens=2,total_tokens=10)
        self.last_response_metadata=dict(model=self.model,finish_reason="stop")
        action="buy" if "Meera Iyer" in messages[0]["content"] else "sell"
        return json.dumps(dict(action=action,quantity=1,limit_price=100))


class NewsRecipeTests(unittest.TestCase):
    def test_four_cells_change_only_event_factors(self):
        reference=None
        for cell in ("control","headline_only","fundamentals_only","combined"):
            cfg=market_recipe(1441,cell,"qwen").to_dict()
            event=cfg.pop("news")[0];cfg.pop("name")
            self.assertEqual(event["announce"],cell in ("headline_only","combined"))
            self.assertEqual("effect" in event,cell in ("fundamentals_only","combined"))
            self.assertFalse(cfg["reveal_fundamental"])
            if reference is None:reference=cfg
            else:self.assertEqual(reference,cfg)
        self.assertEqual(reference["llm_limits"]["max_requests"],80)
        self.assertEqual(reference["agents"][-1]["llm"]["max_tokens"],4096)

    def test_rule_and_qwen_templates_have_same_fourteen_endowments(self):
        def slots(cfg):return [(g.cash,g.shares) for g in cfg.agents for _ in range(g.count)]
        rules=market_recipe(1441,"combined","rules");qwen=market_recipe(1441,"combined","qwen")
        self.assertEqual(slots(rules),slots(qwen));self.assertEqual(len(slots(rules)),14)
        for field in ("market","asset","observation","news","reveal_fundamental","execution"):
            self.assertEqual(getattr(rules,field),getattr(qwen,field))


class NewsExecutionTests(unittest.TestCase):
    def setUp(self):
        scratch=Path(__file__).resolve().parents[1]/".tmp";scratch.mkdir(exist_ok=True)
        temporary=tempfile.TemporaryDirectory(dir=scratch);self.root=Path(temporary.name)
        assert self.root.resolve().is_relative_to(scratch.resolve())
        self.addCleanup(temporary.cleanup)
        OfflineQwen.calls=0;OfflineQwen.fail=False
        with contextlib.redirect_stdout(io.StringIO()):self.study=prepare(self.root)

    def run_offline(self):
        with patch("sim.news_pilot.LLMClient",OfflineQwen),patch("sim.engine.LLMClient",OfflineQwen), \
             patch("sim.news_pilot.RequestPacer",NoDelayPacer),contextlib.redirect_stdout(io.StringIO()):
            return execute(self.study)

    def test_config_drift_blocks_execution(self):
        study=load_study(self.study)
        path=self.study/study["schedule"][0]["config"]
        path.write_text(path.read_text()+"\n# changed\n")
        with self.assertRaisesRegex(ValueError,"config drift"):load_study(self.study)
        self.assertFalse((self.study/"execution.json").exists())

    def test_full_offline_schedule_preserves_snapshots_and_separates_fills(self):
        self.run_offline()
        summary=json.loads((self.study/"summary.json").read_text())
        self.assertEqual((summary["status"],summary["completed_markets"]),("completed",16))
        self.assertEqual(OfflineQwen.calls,344)
        runs=json.loads((self.study/"runs.json").read_text())
        for seed in SEEDS:
            control=next(r for r in runs if r["brain"]=="qwen" and r["cell"]=="control" and r["seed"]==seed)
            cases=extract_probes(self.study/control["run_path"],seed)
            self.assertEqual(len(cases),4)
            for a,b in zip(cases[::2],cases[1::2]):
                self.assertEqual(a["memory"],b["memory"])
                self.assertTrue(all(row["round"]<11 for row in a["memory"]))
                obs_a=copy.deepcopy(a["observation"]);obs_b=copy.deepcopy(b["observation"])
                self.assertEqual(obs_a.pop("news"),[]);self.assertEqual(obs_b.pop("news"),[HEADLINE])
                self.assertEqual(obs_a,obs_b);self.assertIsNone(obs_a["fundamental_hint"])
                self.assertEqual(a["messages"][0],b["messages"][0])
        probe=json.loads((self.study/"same_state_probes/summary.json").read_text())
        self.assertEqual(probe["completed_decisions"],24)
        requests=[json.loads(line) for line in (self.study/"same_state_probes/llm_requests.jsonl").read_text().splitlines()]
        calls=[r for r in requests if r["record_type"]=="model_call"]
        self.assertEqual(len({r["call_id"] for r in calls}),24)
        for result in json.loads((self.study/"same_state_probes/results.json").read_text()):
            self.assertIsNone(result["executions"])
        metrics=json.loads((self.study/"metrics_qwen_combined_1441.json").read_text())
        self.assertEqual(len(metrics["target_rounds"]),40)
        self.assertEqual(len(metrics["event_decisions"]),2)
        for metric in ("target_union_volume_share","target_trade_leg_share"):
            self.assertTrue(0<=metrics["event_metrics"][metric]<=1)
        # Query-first scheduling must label a single-seed subset honestly.
        partial=self.root/"single_seed";partial.mkdir()
        with patch("sim.news_pilot.LLMClient",OfflineQwen):
            subset=run_probes(partial,cases,NoDelayPacer(10,60000),max_requests=24,max_reserved_tokens=500000)
        self.assertEqual((subset["planned_decisions"],subset["completed_decisions"]),(12,12))
        self.assertEqual(subset["llm_usage"]["max_requests"],24)
        with self.assertRaisesRegex(ValueError,"already started"):execute(self.study)

    def test_first_provider_failure_stops_all_later_markets_and_probes(self):
        OfflineQwen.fail=True;self.run_offline()
        summary=json.loads((self.study/"summary.json").read_text())
        self.assertEqual(summary["status"],"stopped")
        self.assertEqual(summary["completed_markets"],8)
        self.assertEqual(summary["recorded_market_arms"],9)  # Failed arm is retained, not counted complete.
        self.assertEqual(OfflineQwen.calls,1)
        self.assertFalse((self.study/"same_state_probes").exists())
        runs=json.loads((self.study/"runs.json").read_text())
        self.assertEqual(runs[-1]["status"],"provider_error")
