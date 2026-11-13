"""A/B/C comparability, actual-outcome memory, usage limits, and run provenance."""
from concurrent.futures import ThreadPoolExecutor
import contextlib
import copy
import csv
from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
import zipfile

import numpy as np
import yaml

from sim.agents.base import Observation
from sim.agents.llm_agent import LLMAgent
from sim.config import ConfigError, parse_config
from sim.engine import run
from sim.llm.client import LLMClient
from sim.llm.usage import UsageBudget, UsageLimitExceeded
from sim.market import Order, Trade


HOLD = '{"action":"hold","quantity":0,"limit_price":null}'


def observation(rnd=1):
    return Observation(rnd, 30, [100, 99, 98, 97, 96, 95], 10, 0.02, 0.0002,
                       None, [], [], 10000, 100, 100, 19500, [])


class FixedClient:
    def __init__(self, **kwargs):
        self.total_tokens = 0
        self.last_usage = None
        self.last_response_metadata = {"model": "fixed-test-client"}
        self.calls = []

    def chat(self, messages, **kwargs):
        self.calls.append((copy.deepcopy(messages), kwargs))
        response = HOLD if kwargs.get("json_mode", True) else "Observations: no fill. Beliefs: uncertain. Plan: wait."
        self.last_usage = {"prompt_tokens": 10, "completion_tokens": 5,
                           "total_tokens": 15, "source": "estimated_mock"}
        self.total_tokens += 15
        return response


class ConditionTests(unittest.TestCase):
    def trader(self, condition="A", client=None, **kwargs):
        records = []
        trader = LLMAgent("a", 10000, 100, np.random.default_rng(1),
                          params={"condition": condition, "memory_window": 2,
                                  "reflect_every": 2 if condition == "C" else 0},
                          persona={"name": "Test", "risk_tolerance": "low"},
                          client=client or FixedClient(), log_fn=records.append, **kwargs)
        return trader, records

    def test_conditions_share_system_and_raw_inputs_and_c_starts_identical_to_b(self):
        a, _ = self.trader("A")
        b, _ = self.trader("B")
        c, _ = self.trader("C")
        self.assertEqual(a.system_prompt("KGP"), b.system_prompt("KGP"))
        self.assertEqual(b.system_prompt("KGP"), c.system_prompt("KGP"))
        self.assertNotIn("Computed facts", a.user_prompt(observation()))
        self.assertIn("Computed facts", b.user_prompt(observation()))
        self.assertEqual(b.user_prompt(observation()), c.user_prompt(observation()))
        b_lines = [line for line in b.user_prompt(observation()).splitlines()
                   if not line.startswith("Computed facts")]
        self.assertEqual("\n".join(b_lines), a.user_prompt(observation()))

    def test_computed_facts_use_only_disclosed_inputs(self):
        trader, _ = self.trader("B")
        facts = trader.factual_summary(observation())
        self.assertAlmostEqual(facts["price_change_pct"], -5)
        self.assertAlmostEqual(facts["stock_weight_pct"], 9500 / 19500 * 100)
        self.assertEqual(facts["unrealized_gain_loss_amount"], -500)
        self.assertNotIn("price_gap_vs_disclosed_value_pct", facts)
        self.assertNotIn("Analyst", trader.user_prompt(observation()))
        revealed = replace(observation(), fundamental_hint=100)
        self.assertAlmostEqual(trader.factual_summary(revealed)["price_gap_vs_disclosed_value_pct"], -5)

    def test_empty_account_and_short_history_do_not_create_nonfinite_features(self):
        trader, _ = self.trader("B")
        obs = replace(observation(), price_history=[100], my_cash=0, my_shares=0,
                      my_avg_cost=0, my_wealth=0)
        features = trader.factual_summary(obs)
        self.assertIsNone(features["stock_weight_pct"])
        self.assertIsNone(features["price_change_pct"])
        json.dumps(features, allow_nan=False)

    def test_unfilled_order_is_not_remembered_as_a_purchase(self):
        trader, _ = self.trader()
        order = Order("a", "buy", 5, 80, 1)
        trader.end_round(observation(), order, 95, reflect=False)
        memory = trader.memory[-1]
        self.assertEqual(memory["requested_order"]["quantity"], 5)
        self.assertEqual(memory["executed_buy_quantity"], 0)
        self.assertEqual(memory["fills"], [])
        self.assertEqual((trader.cash, trader.shares), (10000, 100))

    def test_partial_fills_and_cash_income_are_kept_distinct_from_requests(self):
        trader, _ = self.trader()
        trades = [Trade(1, "a", "other", 2, 95), Trade(1, "unrelated", "private", 7, 90)]
        trader.end_round(observation(), Order("a", "buy", 5, 95, 1), 95,
                         fills=trades, dividend_income=2.04, interest_income=1.9, reflect=False)
        memory = trader.memory[-1]
        self.assertEqual(memory["executed_buy_quantity"], 2)
        self.assertEqual(memory["dividend_income"], 2.04)
        self.assertNotIn("private", json.dumps(memory))
        self.assertNotIn("other", json.dumps(memory))

    def test_reflection_is_logged_but_cannot_mutate_verified_accounts_or_persona(self):
        trader, records = self.trader("C")
        persona = copy.deepcopy(trader.persona)
        for rnd in (1, 2):
            trader.end_round(observation(rnd), Order("a", "hold", round=rnd), 95)
        self.assertEqual(len(trader.client.calls), 1)
        self.assertFalse(trader.client.calls[0][1]["json_mode"])
        self.assertEqual(trader.client.calls[0][1]["temperature"], 0)
        self.assertEqual((trader.cash, trader.shares, trader.persona), (10000, 100, persona))
        self.assertEqual(records[-1]["record_type"], "reflection")
        self.assertIn("Your reflection", trader.user_prompt(observation(3)))
        self.assertEqual(len(trader.memory), 2)
        trader.reflect_if_due(observation(2))
        self.assertEqual(len(trader.client.calls), 1)

    def test_failed_reflection_keeps_previous_diary_and_is_counted(self):
        class Broken(FixedClient):
            def chat(self, *args, **kwargs):
                raise RuntimeError("offline failure")
        trader, records = self.trader("C", client=Broken())
        trader.diary = "Earlier belief"
        trader.end_round(observation(2), Order("a", "hold", round=2), 95)
        self.assertEqual(trader.diary, "Earlier belief")
        self.assertEqual(trader.reflection_failures, 1)
        self.assertEqual(records[-1]["failure_type"], "reflection_failed")

    def test_no_reflection_is_bought_after_the_final_decision(self):
        trader, records = self.trader("C")
        final = replace(observation(2), total_rounds=2)
        trader.end_round(final, Order("a", "hold", round=2), 95)
        self.assertEqual(trader.client.calls, [])
        self.assertEqual(records[-1]["record_type"], "outcome")

    def test_budget_blocks_before_the_client_is_called(self):
        client = FixedClient()
        trader, records = self.trader(client=client, budget=UsageBudget(max_requests=0))
        with self.assertRaises(UsageLimitExceeded):
            trader.decide(observation())
        self.assertEqual(client.calls, [])
        self.assertEqual(records[-1]["record_type"], "request_blocked")

    def test_unknown_provider_usage_is_not_reported_as_known_zero_usage(self):
        class NoUsage(FixedClient):
            def chat(self, *args, **kwargs):
                return HOLD
        trader, records = self.trader(client=NoUsage())
        trader.decide(observation())
        self.assertIsNone(records[-1]["attempts"][0]["usage"])
        self.assertEqual(trader.budget.snapshot()["unknown_usage_requests"], 1)


class RequestTests(unittest.TestCase):
    def test_shared_budget_reservations_are_atomic(self):
        budget = UsageBudget(max_requests=3)
        def attempt(_):
            try:
                budget.reserve([], 10, 0, 0)
                return True
            except UsageLimitExceeded:
                return False
        with ThreadPoolExecutor(max_workers=10) as pool:
            result = list(pool.map(attempt, range(10)))
        self.assertEqual(sum(result), 3)
        self.assertEqual(budget.snapshot()["blocked_requests"], 7)

    def test_declared_cost_and_token_limits_block_requests(self):
        for budget in [UsageBudget(max_cost_usd=0), UsageBudget(max_reserved_tokens=1)]:
            with self.subTest(budget=budget), self.assertRaises(UsageLimitExceeded):
                budget.reserve([{"role": "user", "content": "test"}], 10, 1, 1)

    def test_provider_response_usage_and_actual_model_are_retained_without_secrets(self):
        payload = {"model": "actual-test-model", "system_fingerprint": "fp_test",
                   "usage": {"prompt_tokens": 12, "completion_tokens": 5, "total_tokens": 17},
                   "choices": [{"message": {"content": HOLD}}]}
        client = LLMClient(model="alias", api_key="test-secret", timeout=17)
        with patch("urllib.request.urlopen", return_value=io.BytesIO(json.dumps(payload).encode())) as call:
            self.assertEqual(client.chat([], max_tokens=50), HOLD)
        self.assertEqual(call.call_args.kwargs["timeout"], 17)
        self.assertEqual(client.last_usage["source"], "provider")
        self.assertEqual(client.total_tokens, 17)
        self.assertEqual(client.last_response_metadata["model"], "actual-test-model")
        self.assertNotIn("test-secret", json.dumps(client.last_response_metadata))

    def test_http_failure_does_not_trigger_hidden_retries(self):
        client = LLMClient()
        with patch("urllib.request.urlopen", side_effect=HTTPError("https://example.invalid", 429, "limited", {}, None)) as call:
            with self.assertRaises(HTTPError):
                client.chat([])
        self.assertEqual(call.call_count, 1)
        self.assertIsNone(client.last_usage)

    def test_live_configuration_requires_prices_and_limits(self):
        base = {"agents": [{"type": "llm", "llm": {"provider": "openai_compatible", "model": "test"}}]}
        with self.assertRaises(ConfigError):
            parse_config(base)
        base["agents"][0]["llm"].update(input_usd_per_million=0, output_usd_per_million=0)
        with self.assertRaises(ConfigError):
            parse_config(base)
        base["llm_limits"] = {"max_requests": 10, "max_cost_usd": 0}
        self.assertEqual(parse_config(base).llm_limits.max_requests, 10)

    def test_condition_and_reflection_configuration_must_agree(self):
        for llm in [{"condition": "B", "reflect_every": 2}, {"condition": "C", "reflect_every": 0},
                    {"condition": "C", "reflect_every": 5, "memory_window": 2}, {"condition": "D"}]:
            with self.subTest(llm=llm), self.assertRaises(ConfigError):
                parse_config({"agents": [{"type": "llm", "llm": llm}]})


class ComparableRunTests(unittest.TestCase):
    def setUp(self):
        scratch = Path(__file__).resolve().parents[2] / ".tmp"
        scratch.mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=scratch)
        self.root = Path(temporary.name)
        if not self.root.resolve().is_relative_to(scratch.resolve()):
            raise RuntimeError("test path escaped workspace")
        self.addCleanup(temporary.cleanup)

    def cfg(self, mode="A", rounds=3):
        return {"rounds": rounds, "agents": [{"type": "llm", "count": 1,
                "llm": {"provider": "mock", "condition": mode,
                        "memory_window": 2, "reflect_every": 1 if mode == "C" else 0}}]}

    def execute(self, cfg):
        path = self.root / "config.yaml"
        path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            return Path(run(path, output_root=self.root / "runs"))

    @staticmethod
    def rows(path):
        with path.open(newline="", encoding="utf-8") as source:
            return list(csv.DictReader(source))

    def test_identical_replies_keep_markets_matching_across_conditions(self):
        outputs = []
        with patch("sim.engine.MockLLMClient", FixedClient):
            for mode in ("A", "B", "C"):
                outputs.append(self.execute(self.cfg(mode)))
        for filename in ("prices.csv", "trades.csv", "agents_state.csv", "initial_state.csv", "personas.json"):
            self.assertEqual(len({(p / filename).read_bytes() for p in outputs}), 1)
        counts = [json.loads((p / "summary.json").read_text())["llm_usage"]["requests_made"] for p in outputs]
        self.assertEqual(counts, [3, 3, 5])

    def test_reflection_budget_stop_keeps_the_whole_settled_round(self):
        cfg = self.cfg("C")
        cfg["llm_limits"] = {"max_requests": 1}
        output = self.execute(cfg)
        summary = json.loads((output / "summary.json").read_text())
        self.assertEqual((summary["status"], summary["rounds"]), ("budget_exhausted", 1))
        self.assertEqual(len(self.rows(output / "prices.csv")), 1)
        self.assertEqual(len(self.rows(output / "cashflows.csv")), 1)
        self.assertEqual(len(self.rows(output / "agents_state.csv")), 1)
        outcomes = [json.loads(line) for line in (output / "agent_outcomes.jsonl").read_text().splitlines()]
        self.assertEqual(len(outcomes), 1)
        self.assertGreater(outcomes[0]["outcome"]["dividend_income"], 0)

    def test_decision_budget_stop_clears_no_partial_round(self):
        cfg = self.cfg()
        cfg["agents"][0]["count"] = 2
        cfg["llm_limits"] = {"max_requests": 1}
        output = self.execute(cfg)
        summary = json.loads((output / "summary.json").read_text())
        self.assertEqual((summary["status"], summary["rounds"]), ("budget_exhausted", 0))
        self.assertEqual(self.rows(output / "prices.csv"), [])
        self.assertEqual(self.rows(output / "agents_state.csv"), [])
        self.assertEqual(summary["initial_cash"], summary["final_cash"])

    def test_first_bad_reply_survives_when_the_repair_request_is_blocked(self):
        class Invalid(FixedClient):
            def chat(self, *args, **kwargs):
                return "not json"
        cfg = self.cfg()
        cfg["llm_limits"] = {"max_requests": 1}
        with patch("sim.engine.MockLLMClient", Invalid):
            output = self.execute(cfg)
        requests = [json.loads(line) for line in (output / "llm_requests.jsonl").read_text().splitlines()]
        self.assertEqual([r["record_type"] for r in requests], ["model_call", "request_blocked"])
        self.assertEqual(requests[0]["raw"], "not json")
        self.assertEqual(len(requests[1]["attempts"][0]["messages"]), 4)
        summary = json.loads((output / "summary.json").read_text())
        self.assertEqual((summary["status"], summary["rounds"]), ("budget_exhausted", 0))

    def test_manifest_snapshot_and_output_hashes_are_consistent(self):
        output = self.execute(self.cfg())
        manifest = json.loads((output / "manifest.json").read_text())
        self.assertEqual((manifest["status"], manifest["completed_rounds"]), ("completed", 3))
        with zipfile.ZipFile(output / "source.zip") as source:
            for path, digest in manifest["source_sha256"].items():
                self.assertEqual(hashlib.sha256(source.read(path)).hexdigest(), digest)
        for filename, digest in manifest["output_sha256"].items():
            self.assertEqual(hashlib.sha256((output / filename).read_bytes()).hexdigest(), digest)

    def test_runtime_failure_is_preserved_and_reraised(self):
        with patch("sim.engine.CallAuctionMarket.clear", side_effect=RuntimeError("test-private-error")):
            with self.assertRaises(RuntimeError):
                self.execute(self.cfg())
        output = next((self.root / "runs").iterdir())
        summary = json.loads((output / "summary.json").read_text())
        self.assertEqual(summary["status"], "failed")
        self.assertEqual(summary["rounds"], 0)
        self.assertNotIn("test-private-error", (output / "manifest.json").read_text())


if __name__ == "__main__":
    unittest.main()
