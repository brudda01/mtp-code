import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
import yaml

from sim.engine import run
from sim.market import Order
from sim.news_pilot import market_recipe
from sim.news_components import (NEWS, comparisons, component_agent, execute,
    execution_interval, messages, observation, prepare_controls, recipe, validate)


class NoDelay:
    def __init__(self, rpm, tpm):
        self.requests_per_minute = rpm; self.input_tokens_per_minute = tpm
    def acquire(self, estimate): return 0


class ScriptedClient:
    calls = 0
    fail_on = None
    empty_reflection = False
    malformed = False

    def __init__(self, model, base_url, reasoning_effort=None, send_temperature=True, **kwargs):
        self.model = model; self.base_url = base_url; self.reasoning_effort = reasoning_effort
        self.send_temperature = send_temperature; self.api_key = "offline-only"
        self.total_tokens = 0; self.last_usage = None
        self.last_response_metadata = {}; self.last_error_metadata = {}

    def chat(self, messages, json_mode=True, **kwargs):
        type(self).calls += 1
        if type(self).calls == type(self).fail_on:
            raise HTTPError("https://example.invalid", 429, "quota", {}, None)
        self.last_usage = dict(source="estimated_mock", prompt_tokens=8, completion_tokens=2, total_tokens=10)
        self.last_response_metadata = dict(model=self.model, finish_reason="stop")
        if not json_mode:
            return "" if type(self).empty_reflection else f"Reflection{self.calls}: actual history, fills differ from accepted orders."
        if type(self).malformed: return "[]"
        user = messages[1]["content"]
        side = "sell" if "20% fall" in user else "buy" if "20% rise" in user else "hold"
        qty = 0 if side == "hold" else 3 if "Your reflection (beliefs may be wrong)" in user else 2 if "Computed facts" in user else 1
        return json.dumps(dict(action=side, quantity=qty, limit_price=None))


class ComponentTests(unittest.TestCase):
    def setUp(self):
        scratch = Path(__file__).resolve().parents[1] / ".tmp"
        scratch.mkdir(exist_ok=True)
        tmp = tempfile.TemporaryDirectory(dir=scratch)
        self.root = Path(tmp.name)
        assert self.root.resolve().is_relative_to(scratch.resolve())
        self.addCleanup(tmp.cleanup)
        ScriptedClient.calls = 0; ScriptedClient.fail_on = None
        ScriptedClient.empty_reflection = ScriptedClient.malformed = False
        controls = {}
        with patch("sim.engine.LLMClient", ScriptedClient), contextlib.redirect_stdout(io.StringIO()):
            for seed in (1441, 2882):
                cfg = market_recipe(seed, "control", "qwen").to_dict()
                cfg["llm_limits"]["requests_per_minute"] = None
                cfg["llm_limits"]["input_tokens_per_minute"] = None
                config_path = self.root / f"source_{seed}.yaml"
                config_path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
                controls[seed] = Path(run(config_path, output_root=self.root / "source_markets"))
            self.study = prepare_controls(controls, self.root)
        ScriptedClient.calls = 0

    def execute_offline(self):
        with patch("sim.news_components.LLMClient", ScriptedClient), \
             patch("sim.news_components.RequestPacer", NoDelay), contextlib.redirect_stdout(io.StringIO()):
            return execute(self.study)

    def test_three_modes_have_same_information_and_only_intended_additions(self):
        protocol, frames, _ = validate(self.study)
        self.assertEqual((len(frames), len(protocol["schedule"])), (4, 12))
        self.assertEqual(recipe().llm_limits.max_requests, 264)
        for f in frames:
            for news in NEWS:
                obs = observation(f, news)
                a, b, c = [messages(component_agent(f, mode, diary="actual generated reflection"), obs) for mode in "ABC"]
                self.assertEqual(a[0], b[0]); self.assertEqual(b[0], c[0])
                self.assertNotIn("Computed facts", a[1]["content"])
                self.assertIn("Computed facts", b[1]["content"])
                self.assertNotIn("actual generated reflection", b[1]["content"])
                self.assertEqual(c[1]["content"].replace("Your reflection (beliefs may be wrong): actual generated reflection\n", ""), b[1]["content"])
                self.assertIsNone(obs.fundamental_hint)
            self.assertEqual([r["round"] for r in f["reflection_windows"]["5"]], [1,2,3,4,5])
            self.assertEqual(f["reflection_windows"]["10"], f["memory"])
            silent, neg = observation(f, "silent"), observation(f, "negative")
            raw = copy.deepcopy(neg.__dict__); raw["news"] = []
            self.assertEqual(raw, silent.__dict__)
        for fid in [f["frame_id"] for f in frames]:
            blocks = [b for b in protocol["schedule"] if b["frame_id"] == fid]
            self.assertEqual({b["choices"][0]["condition"] for b in blocks}, set("ABC"))
            self.assertEqual({b["choices"][0]["news"] for b in blocks}, set(NEWS))

    def test_full_schedule_uses_actual_history_and_shares_each_pre_news_diary(self):
        self.execute_offline()
        summary = json.loads((self.study / "summary.json").read_text())
        self.assertEqual((summary["status"], summary["completed_decisions"], summary["completed_reflections"]), ("completed",108,24))
        self.assertEqual(ScriptedClient.calls, 132)
        rows = [json.loads(s) for s in (self.study / "llm_requests.jsonl").read_text().splitlines()]
        calls = [r for r in rows if r["record_type"] == "model_call"]
        self.assertEqual(len({r["call_id"] for r in calls}), 132)
        ref = [r for r in calls if r["operation"] == "reflection"]
        self.assertEqual(ref[0]["temperature_sent"], 0)
        self.assertIn("Previous reflection (fallible): none", ref[0]["messages"][1]["content"])
        self.assertIn("Reflection1", ref[1]["messages"][1]["content"])
        inputs = [json.loads(s) for s in (self.study / "decision_inputs.jsonl").read_text().splitlines()]
        for fid in {r["frame_id"] for r in inputs}:
            for n in (1,2,3):
                group = [r for r in inputs if r["frame_id"] == fid and r["repetition"] == n]
                self.assertEqual(len({r["diary"] for r in group if r["condition"] == "C"}), 1)
                self.assertTrue(all(r["diary"] is None for r in group if r["condition"] != "C"))
        results = json.loads((self.study / "results.json").read_text())
        self.assertTrue(all(r["executions"] is None for r in results))
        contrasts = json.loads((self.study / "contrasts.json").read_text())
        self.assertEqual(len(contrasts["news_minus_silent"]), 72)
        self.assertTrue(all(r["accepted_signed_quantity"] > 0 for r in contrasts["adjacent_mode_contrasts"] if r["news"] == "positive"))
        with self.assertRaisesRegex(ValueError, "already started"): execute(self.study)

    def test_changed_inputs_block_calls(self):
        (self.study / "frames.json").write_text("[]")
        with self.assertRaisesRegex(ValueError, "drift"): self.execute_offline()
        self.assertEqual(ScriptedClient.calls, 0)
        self.assertFalse((self.study / "execution.json").exists())

    def test_changed_source_evidence_blocks_calls(self):
        (self.study / "sources/1441/agent_outcomes.jsonl").write_text("modified")
        with self.assertRaisesRegex(ValueError, "evidence drift"): self.execute_offline()
        self.assertEqual(ScriptedClient.calls, 0)

    def test_terminal_reflection_provider_failure_stops_before_any_decision(self):
        ScriptedClient.fail_on = 1; self.execute_offline()
        summary = json.loads((self.study / "summary.json").read_text())
        self.assertEqual((summary["status"], summary["completed_decisions"]), ("provider_error",0))
        self.assertEqual(summary["llm_usage"]["unknown_usage_requests"], 1)
        self.assertEqual(ScriptedClient.calls, 1)
        contrasts = json.loads((self.study / "contrasts.json").read_text())
        self.assertTrue(all(r["accepted_signed_quantity"] is None for r in contrasts["news_minus_silent"]))

    def test_empty_reflection_stops_without_using_a_blank_C_treatment(self):
        ScriptedClient.empty_reflection = True; self.execute_offline()
        summary = json.loads((self.study / "summary.json").read_text())
        self.assertEqual((summary["status"], summary["completed_decisions"]), ("reflection_failure",0))
        self.assertEqual(ScriptedClient.calls, 1)

    def test_malformed_decision_stops_and_is_missing_preference_not_hold(self):
        ScriptedClient.malformed = True; self.execute_offline()
        summary = json.loads((self.study / "summary.json").read_text())
        self.assertEqual((summary["status"], summary["completed_decisions"]), ("parse_failure",1))
        result = json.loads((self.study / "results.json").read_text())[0]
        self.assertFalse(result["valid_choice"])
        self.assertIsNone(result["accepted_signed_quantity"])
        self.assertEqual(ScriptedClient.calls, 4)  # Two real reflections, decision + JSON repair.

    def test_accepted_order_interval_does_not_invent_a_fill(self):
        self.assertEqual(execution_interval(Order("a", "buy", 10, 70), 100), [])
        self.assertEqual(execution_interval(Order("a", "buy", 10, 100.09), 100), [80,100])
        self.assertEqual(execution_interval(Order("a", "sell", 10, 100.01), 100), [100.1,120])
        self.assertIsNone(execution_interval(Order("a", "hold"), 100))


if __name__ == "__main__": unittest.main()
