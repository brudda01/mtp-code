"""Financial-correctness regressions; runnable with unittest or pytest.

No provider credentials or live API calls are required. Filesystem integration
tests put their temporary files under the ignored workspace .tmp directory.
"""
from collections import Counter
import contextlib
import copy
import csv
import io
import json
import os
from pathlib import Path
import tempfile
import unittest

import numpy as np
import yaml

from sim.agents.base import Agent, Observation
from sim.agents.llm_agent import LLMAgent
from sim.engine import build_agents, make_rngs, run
from sim.market import CallAuctionMarket, Order, Trade, settle


def agent(aid="a", cash=10000, shares=100, **kwargs):
    return Agent(aid, cash, shares, np.random.default_rng(1), **kwargs)


def observation():
    return Observation(1, 20, [100.0], 0, 1.0, 0.01, None, [], [],
                       10000.0, 100, 100.0, 20000.0, [])


class ScriptedClient:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.calls = []
        self.total_tokens = 0

    def chat(self, messages, **kwargs):
        self.calls.append(copy.deepcopy(messages))
        reply = next(self.replies)
        if isinstance(reply, Exception):
            raise reply
        return reply


class BudgetTests(unittest.TestCase):
    def test_market_buy_uses_full_band_not_ten_percent(self):
        buyer = agent("b", 111, 0)
        order = buyer.validate(Order("b", "buy", 1), 100)
        self.assertEqual((order.side, order.quantity), ("hold", 0))
        self.assertEqual(buyer.cash, 111)

    def test_full_band_buy_and_tax_are_affordable_at_execution(self):
        market = CallAuctionMarket(transaction_tax=0.01)
        accounts = {"b": agent("b", 121.2, 0, transaction_tax=0.01),
                    "s": agent("s", 0, 1, transaction_tax=0.01)}
        buy = accounts["b"].validate(Order("b", "buy", 1), 100)
        price, trades, _ = market.clear([buy, Order("s", "sell", 1, 120)], 100, 1)
        self.assertEqual(price, 120)
        self.assertEqual(len(trades), 1)
        settle(trades, accounts, market)
        self.assertAlmostEqual(accounts["b"].cash, 0)
        self.assertAlmostEqual(accounts["s"].cash, 118.8)
        self.assertAlmostEqual(market.tax_collected, 2.4)
        self.assertAlmostEqual(accounts["b"].avg_cost, 121.2)

    def test_limit_buy_reserves_tax(self):
        buyer = agent("b", 100, 0, transaction_tax=0.01)
        order = buyer.validate(Order("b", "buy", 1, 100), 100)
        self.assertEqual(order.quantity, 0)

    def test_limit_above_band_reserves_only_possible_execution_cost(self):
        buyer = agent("b", 120, 0)
        self.assertEqual(buyer.validate(Order("b", "buy", 1, 1000), 100).quantity, 1)

    def test_sale_is_capped_at_held_shares(self):
        seller = agent("s", shares=3)
        self.assertEqual(seller.validate(Order("s", "sell", 9, 100), 100).quantity, 3)

    def test_bad_order_fields_become_hold(self):
        cases = [Order("a", "oops", 1, 100), Order("a", "buy", -1, 100),
                 Order("a", "buy", 1.5, 100), Order("a", "buy", True, 100),
                 Order("a", "buy", 1, float("nan")),
                 Order("a", "buy", 1, float("inf")),
                 Order("a", "buy", 1, -1), Order("a", "buy", 1, 0)]
        for order in cases:
            with self.subTest(order=order):
                checked = agent().validate(order, 100)
                self.assertEqual((checked.side, checked.quantity), ("hold", 0))
                self.assertTrue(checked.validation_note)

    def test_initial_and_weighted_acquisition_cost(self):
        holder = agent(shares=10, initial_price=80)
        self.assertEqual(holder.avg_cost, 80)
        holder._add_shares(10, 100)
        self.assertEqual(holder.avg_cost, 90)
        holder._add_shares(-5, 110)
        self.assertEqual(holder.avg_cost, 90)
        self.assertEqual(agent(shares=10, initial_cost=75).avg_cost, 75)

    def test_settlement_rejects_whole_batch_before_mutating(self):
        accounts = {"b": agent("b", 100, 0), "s": agent("s", 0, 2)}
        market = CallAuctionMarket()
        with self.assertRaises(ValueError):
            settle([Trade(1, "b", "s", 1, 50), Trade(1, "b", "s", 1, 60)],
                   accounts, market)
        self.assertEqual((accounts["b"].cash, accounts["b"].shares), (100, 0))
        self.assertEqual((accounts["s"].cash, accounts["s"].shares), (0, 2))
        self.assertEqual(accounts["b"].recent_trades, [])
        self.assertEqual(market.tax_collected, 0)

    def test_unreceived_proceeds_cannot_finance_buys(self):
        accounts = {"a": agent("a", 0, 1), "b": agent("b", 100, 1)}
        with self.assertRaises(ValueError):
            settle([Trade(1, "b", "a", 1, 100), Trade(1, "a", "b", 1, 100)],
                   accounts, CallAuctionMarket())
        self.assertEqual(accounts["a"].cash, 0)


class AuctionTests(unittest.TestCase):
    @staticmethod
    def fills(trades):
        result = Counter()
        for trade in trades:
            result[trade.buyer_id] += trade.quantity
        return result

    def test_equal_price_orders_share_marginal_volume(self):
        orders = [Order("a", "buy", 10, 100), Order("b", "buy", 10, 100),
                  Order("s", "sell", 10, 100)]
        _, trades, unmatched = CallAuctionMarket().clear(orders, 100, 1)
        self.assertEqual(self.fills(trades), {"a": 5, "b": 5})
        self.assertEqual(unmatched, 10)

    def test_price_priority_precedes_proportional_allocation(self):
        orders = [Order("best", "buy", 3, None), Order("a", "buy", 10, 100),
                  Order("b", "buy", 10, 100), Order("s", "sell", 13, 100)]
        _, trades, _ = CallAuctionMarket().clear(orders, 100, 1)
        self.assertEqual(self.fills(trades), {"best": 3, "a": 5, "b": 5})

    def test_integer_ties_are_seeded_and_input_order_independent(self):
        orders = [Order("a", "buy", 1, 100), Order("b", "buy", 1, 100),
                  Order("s", "sell", 1, 100)]
        winners = set()
        for seed in range(20):
            market = CallAuctionMarket(rng=np.random.default_rng(seed))
            other = CallAuctionMarket(rng=np.random.default_rng(seed))
            _, trades, _ = market.clear(orders, 100, 1)
            _, reversed_trades, _ = other.clear(list(reversed(orders)), 100, 1)
            self.assertEqual(trades, reversed_trades)
            winners.add(trades[0].buyer_id)
        self.assertEqual(winners, {"a", "b"})

    def test_tick_rounding_cannot_cross_original_limits(self):
        price, trades, _ = CallAuctionMarket().clear(
            [Order("b", "buy", 1, 100.04), Order("s", "sell", 1, 100.01)], 100, 1)
        self.assertEqual((price, trades), (100, []))
        price, trades, _ = CallAuctionMarket().clear(
            [Order("b", "buy", 1, 100.19), Order("s", "sell", 1, 100.01)], 100, 1)
        self.assertEqual(price, 100.1)
        self.assertEqual(len(trades), 1)

    def test_band_does_not_make_unwilling_seller_trade(self):
        price, trades, _ = CallAuctionMarket().clear(
            [Order("b", "buy", 1, 200), Order("s", "sell", 1, 130)], 100, 1)
        self.assertEqual((price, trades), (100, []))

    def test_band_boundaries_are_candidates_for_aggressive_orders(self):
        price, trades, _ = CallAuctionMarket().clear(
            [Order("b", "buy", 1, 200), Order("s", "sell", 1, 110.01)], 100, 1)
        self.assertEqual(price, 110.1)
        self.assertEqual(len(trades), 1)

    def test_price_bounds_round_inwards(self):
        market = CallAuctionMarket(tick=1, price_band=0.015)
        self.assertEqual(market.price_bounds(100), (99, 101))

    def test_randomized_taxed_settlement_conserves_resources(self):
        rng = np.random.default_rng(17)
        market = CallAuctionMarket(transaction_tax=0.005, rng=np.random.default_rng(18))
        accounts = {f"a{i}": agent(f"a{i}", 10000, 100, transaction_tax=0.005)
                    for i in range(10)}
        initial_cash = sum(a.cash for a in accounts.values())
        initial_shares = sum(a.shares for a in accounts.values())
        previous = 100
        for rnd in range(100):
            orders = []
            for aid, holder in accounts.items():
                side = "buy" if rng.random() < 0.5 else "sell"
                limit = None if rng.random() < 0.3 else previous * rng.uniform(0.7, 1.3)
                orders.append(holder.validate(Order(aid, side, int(rng.integers(1, 50)),
                                                   limit, rnd), previous))
            price, trades, _ = market.clear(orders, previous, rnd)
            by_id = {o.agent_id: o for o in orders}
            filled = Counter()
            for trade in trades:
                self.assertGreater(trade.quantity, 0)
                for aid, side in [(trade.buyer_id, "buy"), (trade.seller_id, "sell")]:
                    order = by_id[aid]
                    filled[aid] += trade.quantity
                    if order.limit_price is not None:
                        if side == "buy":
                            self.assertLessEqual(price, order.limit_price + 1e-8)
                        else:
                            self.assertGreaterEqual(price, order.limit_price - 1e-8)
                self.assertLessEqual(abs(price / previous - 1), 0.2 + 1e-10)
            for aid, quantity in filled.items():
                self.assertLessEqual(quantity, by_id[aid].quantity)
            settle(trades, accounts, market)
            self.assertTrue(all(a.cash >= 0 and a.shares >= 0 for a in accounts.values()))
            self.assertEqual(sum(a.shares for a in accounts.values()), initial_shares)
            self.assertAlmostEqual(sum(a.cash for a in accounts.values()) +
                                   market.tax_collected, initial_cash, places=6)
            previous = price


class LLMFailureTests(unittest.TestCase):
    def trader(self, replies):
        records = []
        client = ScriptedClient(replies)
        trader = LLMAgent("a", 10000, 100, np.random.default_rng(0),
                          client=client, log_fn=records.append)
        return trader, client, records

    def test_array_json_repair_and_failure_are_safe(self):
        trader, client, records = self.trader(["[1]", "[1]"])
        order = trader.decide(observation())
        self.assertEqual((order.side, order.reasoning), ("hold", "parse_failed"))
        self.assertEqual(trader.parse_failures, 1)
        self.assertEqual(len(client.calls), 2)
        records = [r for r in records if r["record_type"] == "decision"]
        self.assertEqual(len(records[0]["attempts"]), 2)

    def test_corrective_reply_is_used_and_both_attempts_are_logged(self):
        valid = '{"action":"buy","quantity":2,"limit_price":100}'
        trader, client, records = self.trader(["not json", valid])
        self.assertEqual(trader.decide(observation()).quantity, 2)
        self.assertIn("invalid", client.calls[1][-1]["content"])
        records = [r for r in records if r["record_type"] == "decision"]
        self.assertEqual(len(records[0]["attempts"]), 2)
        self.assertIsNone(records[0]["failure_type"])

    def test_invalid_numeric_fields_repair_instead_of_crashing(self):
        for fields in ['"quantity":1.5,"limit_price":100',
                       '"quantity":true,"limit_price":100',
                       '"quantity":1,"limit_price":NaN',
                       '"quantity":1,"limit_price":-10']:
            with self.subTest(fields=fields):
                trader, _, _ = self.trader([
                    '{"action":"buy",' + fields + '}',
                    '{"action":"hold","quantity":0,"limit_price":null}'])
                self.assertEqual(trader.decide(observation()).side, "hold")
                self.assertEqual(trader.parse_failures, 0)

    def test_api_exhaustion_is_a_distinct_logged_hold(self):
        trader, _, records = self.trader([RuntimeError("provider unavailable")])
        order = trader.decide(observation())
        self.assertEqual(order.reasoning, "api_failed")
        self.assertEqual((trader.api_failures, trader.parse_failures), (1, 0))
        records = [r for r in records if r["record_type"] == "decision"]
        self.assertEqual(records[0]["attempts"][0]["error_type"], "RuntimeError")

    def test_json_fences_and_surrounding_text_remain_supported(self):
        payload = '{"action":"hold","quantity":0,"limit_price":null}'
        for response in [payload, '```json\n' + payload + '\n```', 'Answer: ' + payload]:
            self.assertEqual(LLMAgent._extract_json(response)["action"], "hold")


class EngineTests(unittest.TestCase):
    def setUp(self):
        scratch = Path(__file__).resolve().parents[2] / ".tmp"
        scratch.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=scratch)
        self.root = Path(self.temporary.name)
        if not self.root.resolve().is_relative_to(scratch.resolve()):
            raise RuntimeError("test directory escaped the workspace scratch directory")
        self.addCleanup(self.temporary.cleanup)
        self.cfg = yaml.safe_load((Path(__file__).resolve().parents[1] /
                                   "configs/dev_mock.yaml").read_text(encoding="utf-8"))

    def execute(self, cfg):
        path = self.root / "config.yaml"
        path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            return Path(run(path, output_root=self.root / "runs"))

    @staticmethod
    def rows(path):
        with path.open(encoding="utf-8", newline="") as source:
            return list(csv.DictReader(source))

    def test_mock_demo_runs_with_news_and_repeatable_logs(self):
        first, second = self.execute(self.cfg), self.execute(self.cfg)
        for filename in ["prices.csv", "trades.csv", "orders.csv", "agents_state.csv"]:
            self.assertEqual((first / filename).read_bytes(), (second / filename).read_bytes())
        events = self.rows(first / "events.csv")
        self.assertEqual([(int(e["round"]), e["event_type"]) for e in events], [(30, "news")])
        prices = self.rows(first / "prices.csv")
        self.assertAlmostEqual(float(prices[29]["fundamental"]), 120)
        self.assertAlmostEqual(float(prices[49]["fundamental"]), 100)
        states = self.rows(first / "agents_state.csv")
        self.assertTrue(all(float(s["cash"]) >= 0 and int(s["shares"]) >= 0 for s in states))
        totals = Counter()
        for state in states:
            totals[int(state["round"])] += int(state["shares"])
        expected_shares = sum(g["count"] * g.get("shares", 100) for g in self.cfg["agents"])
        self.assertEqual(set(totals.values()), {expected_shares})
        calls = [json.loads(line) for line in (first / "llm_calls.jsonl").read_text().splitlines()]
        self.assertEqual(len(calls), 480)
        self.assertTrue(all(call["attempts"] for call in calls))
        summary = json.loads((first / "summary.json").read_text())
        self.assertEqual((summary["status"], summary["api_failures"]), ("completed", 0))

    def test_population_changes_do_not_change_environment_path(self):
        baseline = copy.deepcopy(self.cfg)
        baseline["rounds"] = 8
        baseline["news"] = []
        baseline["agents"] = [{"type": "zero_intelligence", "count": 2}]
        other = copy.deepcopy(baseline)
        other["agents"][0]["count"] = 15
        runs = [self.execute(cfg) for cfg in [baseline, other]]
        dividend_paths = [[p["dividend"] for p in self.rows(path / "prices.csv")]
                          for path in runs]
        self.assertEqual(*dividend_paths)

    def test_configured_cost_basis_and_market_rules_reach_all_agents(self):
        cfg = copy.deepcopy(self.cfg)
        cfg["asset"]["initial_price"] = 75
        cfg["market"].update(transaction_tax=0.02, price_band=0.1)
        streams = make_rngs(42)
        agents = build_agents(cfg, streams["population"], persona_rng=streams["personas"])
        self.assertTrue(all(a.avg_cost == 75 for a in agents.values()))
        self.assertTrue(all(a.transaction_tax == 0.02 and a.price_band == 0.1
                            for a in agents.values()))

    def test_environment_is_independent_of_population_and_allocation_draws(self):
        first, second = make_rngs(42), make_rngs(42)
        second["population"].random(1000)
        second["allocation"].random(1000)
        np.testing.assert_array_equal(first["environment"].normal(size=30),
                                      second["environment"].normal(size=30))

    def test_original_smoke_cases(self):
        import test_smoke
        test_smoke.test_clearing_textbook()
        test_smoke.test_no_cross_no_trade()
        test_smoke.test_conservation()

    def test_original_engine_smoke_case(self):
        import test_smoke

        class DirectoryChange:
            @staticmethod
            def chdir(path):
                os.chdir(path)

        previous = Path.cwd()
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                test_smoke.test_engine_end_to_end(self.root, DirectoryChange())
        finally:
            os.chdir(previous)


if __name__ == "__main__":
    unittest.main()
