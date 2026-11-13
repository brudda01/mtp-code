"""Shared disclosure must match the existing exchange, not change its policy."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from sim.agents.base import Observation
from sim.agents.llm_agent import LLMAgent
from sim.capability_check import cases, grade_objective, memory_fixture, prepare, run_battery
from sim.engine import build_agents, make_rngs
from sim.llm.client import LLMClient
from sim.market import CallAuctionMarket, Order


class DisclosureTests(unittest.TestCase):
    def test_configured_rules_reach_the_common_system_prompt(self):
        cfg = {"market":{"tick":.25,"price_band":.125,"transaction_tax":.013},
               "agents":[{"type":"llm","llm":{"condition":c,"reflect_every":2 if c=="C" else 0}} for c in "ABC"]}
        agents = list(build_agents(cfg,make_rngs(1)["population"]).values())
        for agent in agents:
            agent.persona = dict(agents[0].persona)
        prompts = [a.system_prompt("KGP") for a in agents]
        self.assertEqual(prompts[0],prompts[1])
        self.assertEqual(prompts[1],prompts[2])
        for fact in ("price tick 0.25","fractional price band 0.125","tax rate 0.013",
                     "RAW prices BEFORE tick rounding","not an executed trade"):
            self.assertIn(fact,prompts[0])

    def test_raw_reservation_and_tick_execution_can_have_different_boundaries(self):
        trader = LLMAgent("a",120.11,0,np.random.default_rng(1))
        market = CallAuctionMarket(tick=.1,price_band=.2)
        self.assertEqual(market.price_bounds(100.1),(80.1,120.1))
        self.assertEqual(trader.validate(Order("a","buy",1,None),100.1).quantity,0)
        self.assertEqual(trader.validate(Order("a","buy",1,120.1),100.1).quantity,1)

    def test_taxed_limit_reserves_before_tick_rounding(self):
        trader = LLMAgent("a",153.24,0,np.random.default_rng(1),transaction_tax=.02,price_band=.1)
        market = CallAuctionMarket(tick=.25,price_band=.1,transaction_tax=.02)
        order = trader.validate(Order("a","buy",2,75.12),75)
        self.assertEqual(order.quantity,1)
        self.assertEqual(market._normalise(order).limit_price,75)

    def test_raw_account_precision_is_not_silently_rounded(self):
        trader = LLMAgent("a",120.11000001,0,np.random.default_rng(1))
        obs = Observation(1,10,[100.1],0,.03,.0004,None,[],[],120.11000001,0,0,120.11000001,[])
        self.assertIn("120.11000001",trader.user_prompt(obs))

    def test_nvidia_key_is_inferred_only_for_its_own_https_endpoint(self):
        with patch.dict(os.environ,{"NVIDIA_API_KEY":"nvidia-test","API_KEY":"bharat-test"},clear=True):
            self.assertEqual(LLMClient(base_url="https://integrate.api.nvidia.com/v1").api_key,"nvidia-test")
            self.assertEqual(LLMClient(base_url="https://integrate.api.nvidia.com.evil.invalid/v1").api_key,"")
            self.assertEqual(LLMClient(base_url="http://integrate.api.nvidia.com/v1").api_key,"")
        with patch.dict(os.environ,{"API_KEY":"bharat-test"},clear=True), patch("sim.llm.client.dotenv_api_key",return_value=""):
            self.assertEqual(LLMClient(base_url="https://integrate.api.nvidia.com/v1").api_key,"")


class CapabilityTests(unittest.TestCase):
    def test_fixture_separates_requested_accepted_and_executed(self):
        record = memory_fixture()
        self.assertEqual(record["requested_order"]["quantity"],12)
        self.assertEqual(record["accepted_order"]["quantity"],9)
        self.assertEqual(record["executed_buy_quantity"],3)
        self.assertEqual(record["shares"],83)
        self.assertAlmostEqual(record["cash"],496.9377)

    def test_objective_grading_does_not_reward_hold_boolean_or_nonfinite_output(self):
        for raw in ('{"action":"hold","quantity":0}','{"n":true}','{"n":NaN}','{"n":Infinity}',""):
            self.assertFalse(grade_objective(raw,{"n":1})["all_correct"])
        self.assertTrue(grade_objective('{"n":1.00000001}',{"n":1})["all_correct"])

    def temporary(self):
        scratch = Path(__file__).resolve().parents[1]/".tmp"
        scratch.mkdir(exist_ok=True)
        directory = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(directory.cleanup)
        return Path(directory.name)

    def test_battery_has_three_repeats_and_is_stable_and_one_trait_at_a_time(self):
        with contextlib.redirect_stdout(io.StringIO()):
            directory = prepare(self.temporary())
        battery = json.loads((directory/"battery.json").read_text())
        self.assertEqual(len(battery["cases"]),14)
        self.assertEqual(len(battery["schedule"]),42)
        for case in battery["cases"]:
            self.assertEqual(sum(x["case_id"]==case["case_id"] for x in battery["schedule"]),3)
        by_id = {c["case_id"]:c for c in cases()}
        low,high = by_id["risk_low"],by_id["risk_high"]
        self.assertEqual(low["observation"],high["observation"])
        self.assertEqual({k:v for k,v in low["persona"].items() if k!="risk_tolerance"},
                         {k:v for k,v in high["persona"].items() if k!="risk_tolerance"})

    def test_tampered_prompt_is_rejected_before_a_client_is_constructed(self):
        root = self.temporary()
        with contextlib.redirect_stdout(io.StringIO()):
            directory = prepare(root)
        path = directory/"battery.json"
        battery = json.loads(path.read_text())
        battery["cases"][0]["messages"][1]["content"] += " changed"
        path.write_text(json.dumps(battery))
        with patch("sim.capability_check.LLMClient") as client, self.assertRaises(ValueError):
            run_battery(directory,"qwen",root)
        client.assert_not_called()

    def test_offline_run_retains_unique_calls_and_separates_objective_failures(self):
        class HoldClient:
            def __init__(self,**kwargs):
                self.api_key="offline-test"
                self.last_usage=None
                self.last_response_metadata={"model":"scripted-test-client"}
            def chat(self,*args,**kwargs):
                return '{"action":"hold","quantity":0,"limit_price":null}'
        root = self.temporary()
        with contextlib.redirect_stdout(io.StringIO()):
            directory = prepare(root)
            with patch("sim.capability_check.LLMClient",HoldClient),patch("sim.llm.usage.RequestPacer.acquire",return_value=0):
                output = run_battery(directory,"qwen",root)
        summary = json.loads((output/"summary.json").read_text())
        results = json.loads((output/"results.json").read_text())
        calls = [json.loads(line) for line in (output/"llm_requests.jsonl").read_text().splitlines()]
        ids = [r["call_id"] for r in calls if r.get("record_type")=="model_call"]
        self.assertEqual(summary["completed_checks"],42)
        self.assertEqual(len(ids),len(set(ids)))
        self.assertTrue(all(not r["all_correct"] for r in results if r["kind"]=="objective"))
        self.assertTrue(all(r["resource_compliant"] for r in results if r["kind"]=="order"))

    def test_smaller_request_allowance_stops_and_is_saved_in_normalized_config(self):
        class HoldClient:
            def __init__(self,**kwargs):
                self.api_key="offline-test"
                self.last_usage=None
                self.last_response_metadata={"model":"scripted-test-client"}
            def chat(self,*args,**kwargs):
                return '{"action":"hold","quantity":0,"limit_price":null}'
        root=self.temporary()
        with contextlib.redirect_stdout(io.StringIO()):
            directory=prepare(root)
            with patch("sim.capability_check.LLMClient",HoldClient),patch("sim.llm.usage.RequestPacer.acquire",return_value=0):
                output=run_battery(directory,"qwen",root,max_requests=2,max_reserved_tokens=50000)
        summary=json.loads((output/"summary.json").read_text())
        self.assertEqual(summary["status"],"budget_exhausted")
        self.assertEqual(summary["completed_checks"],2)
        self.assertEqual(summary["llm_usage"]["max_requests"],2)
        self.assertEqual(summary["llm_usage"]["max_reserved_tokens"],50000)


if __name__ == "__main__":
    unittest.main()
