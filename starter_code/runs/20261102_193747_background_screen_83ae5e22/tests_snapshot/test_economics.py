"""Cash-flow timing, regime valuation, and finite two-sided liquidity checks."""
import contextlib
import copy
import csv
import io
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import yaml

from sim.agents.base import Agent, Observation
from sim.agents.llm_agent import LLMAgent
from sim.agents.rule_agents import MarketMakerAgent
from sim.assets import Asset
from sim.config import ConfigError, load_config
from sim.engine import run
from sim.market import CallAuctionMarket, Order, settle


def obs():
    return Observation(1, 100, [100.0], 0, 0.02, 0.0002, None, [], [],
                       10000, 100, 100, 20000, [])


class AssetTests(unittest.TestCase):
    def asset(self, *, noise=0.2, news=None):
        return Asset({"model": "iid_permanent", "risk_free": 0.0002,
                      "dividend": {"mean": 0.02, "relative_noise": noise}},
                     np.random.default_rng(14), news_events=news)

    def test_iid_dividends_are_bounded_and_centered_at_the_declared_mean(self):
        asset = self.asset()
        payouts = np.array([asset.step(i)[0] for i in range(1, 10001)])
        self.assertGreaterEqual(payouts.min(), 0.016)
        self.assertLessEqual(payouts.max(), 0.024)
        self.assertAlmostEqual(float(payouts.mean()), 0.02, delta=0.0001)

    def test_permanent_news_changes_benchmark_and_payouts_from_announced_round(self):
        asset = self.asset(noise=0, news=[{"round": 3, "headline": "permanent improvement",
                                         "effect": {"dbar_mult": 1.2}}])
        for rnd in range(1, 8):
            headlines = asset.open_round(rnd)
            self.assertAlmostEqual(asset.fundamental(rnd), 100 if rnd < 3 else 120)
            self.assertEqual(bool(headlines), rnd == 3)
            self.assertAlmostEqual(asset.draw_dividend(), 0.02 if rnd < 3 else 0.024)

    def test_noise_news_changes_no_cashflows_or_benchmark(self):
        first, other = self.asset(), self.asset(news=[{"round": 3, "headline": "rumor"}])
        for rnd in range(1, 10):
            self.assertEqual(first.step(rnd)[0], other.step(rnd)[0])
            self.assertEqual(first.fundamental(rnd), other.fundamental(rnd))

    def test_current_payout_is_not_available_before_the_auction(self):
        asset = self.asset(noise=0)
        previous = asset.last_dividend
        asset.open_round(1)
        self.assertEqual(asset.last_dividend, previous)
        with self.assertRaisesRegex(ValueError, "sequentially"):
            asset.open_round(2)
        asset.draw_dividend()
        with self.assertRaises(ValueError):
            asset.draw_dividend()

    def test_legacy_temporary_effect_remains_explicitly_approximate(self):
        asset = Asset({"model": "legacy_ar1", "risk_free": 0.01,
                       "dividend": {"mean": 1, "rho": 0.6, "sigma": 0}},
                      np.random.default_rng(0),
                      news_events=[{"round": 1, "headline": "temporary", "effect": {"dbar_mult": 1.2, "duration": 2}}])
        values = []
        for rnd in range(1, 4):
            asset.step(rnd)
            values.append(asset.fundamental(rnd))
        self.assertEqual(values, [120, 120, 100])
        self.assertEqual(asset.benchmark_kind, "legacy_perpetuity_approximation")


class MarketMakerTests(unittest.TestCase):
    def maker(self, cash=10000, shares=100, limit=200):
        return MarketMakerAgent("mm", cash, shares, np.random.default_rng(0),
                                params={"inventory_limit": limit, "spread": 0.01,
                                        "inventory_skew": 0, "quote_size": 10})

    def test_quotes_both_sides_without_crossing(self):
        quotes = self.maker().decide(obs())
        self.assertEqual({q.side for q in quotes}, {"buy", "sell"})
        self.assertLess(quotes[0].limit_price, quotes[1].limit_price)

    def test_inventory_and_cash_constraints_suppress_unfunded_quotes(self):
        for cash, shares, expected in [(0, 100, {"sell"}), (10000, 0, {"buy"}),
                                       (10000, 200, {"sell"}), (0, 0, set())]:
            with self.subTest(cash=cash, shares=shares):
                quotes = self.maker(cash, shares).decide(obs())
                self.assertEqual({q.side for q in quotes if q.quantity}, expected)

    def test_inventory_cap_applies_to_partial_remaining_capacity(self):
        quotes = self.maker(shares=198).decide(obs())
        self.assertEqual(next(q.quantity for q in quotes if q.side == "buy"), 2)

    def test_two_sided_quotes_can_settle_without_self_trade(self):
        maker = self.maker()
        seller = Agent("s", 0, 10, np.random.default_rng(1))
        market = CallAuctionMarket()
        _, trades, _ = market.clear(maker.decide(obs()) + [Order("s", "sell", 10, 98)], 100, 1)
        settle(trades, {"mm": maker, "s": seller}, market)
        self.assertEqual(maker.shares, 110)
        self.assertTrue(all(t.buyer_id != t.seller_id for t in trades))

    def test_crossing_or_duplicate_own_quotes_are_rejected_before_clearing(self):
        maker = self.maker()
        for quotes in [[Order("mm", "buy", 1, 101), Order("mm", "sell", 1, 100)],
                       [Order("mm", "buy", 1, 99), Order("mm", "buy", 1, 98)]]:
            with self.subTest(quotes=quotes), self.assertRaises(ValueError):
                maker.validate_orders(quotes, 100)

    def test_quote_spread_is_an_explicit_batch_snapshot(self):
        stats = CallAuctionMarket().quote_statistics(
            [Order("b", "buy", 5, 101), Order("s", "sell", 5, 100)])
        self.assertEqual(stats["quoted_spread"], -1)
        self.assertEqual(stats["submitted_quantity"], 10)


class EconomicsEngineTests(unittest.TestCase):
    def setUp(self):
        scratch = Path(__file__).resolve().parents[2] / ".tmp"
        scratch.mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=scratch)
        self.root = Path(temporary.name)
        if not self.root.resolve().is_relative_to(scratch.resolve()):
            raise RuntimeError("test directory escaped the workspace")
        self.addCleanup(temporary.cleanup)

    def execute(self, cfg):
        path = self.root / "config.yaml"
        path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            return Path(run(path, output_root=self.root / "runs"))

    @staticmethod
    def rows(path):
        with path.open(newline="", encoding="utf-8") as source:
            return list(csv.DictReader(source))

    def test_no_trade_cash_growth_matches_closed_form_without_same_round_reinvestment(self):
        cfg = {"rounds": 300, "reveal_fundamental": True,
               "asset": {"model": "iid_permanent", "dividend": {"mean": 0.02, "relative_noise": 0}},
               "agents": [{"type": "fundamentalist", "count": 1, "cash": 10000, "shares": 100}]}
        output = self.execute(cfg)
        flows = self.rows(output / "cashflows.csv")
        self.assertAlmostEqual(float(flows[0]["cash_after"]), 10004)
        factor = (1.0002 ** 300)
        expected = 10000 * factor + 100 * 0.02 * (factor - 1) / 0.0002
        self.assertAlmostEqual(float(flows[-1]["cash_after"]), expected, places=6)
        self.assertTrue(all(abs(float(f["conservation_error"])) < 1e-7 for f in flows))
        summary = json.loads((output / "summary.json").read_text())
        self.assertEqual(summary["zero_volume_fraction"], 1)
        self.assertLess(summary["cash_only_interest_factor"], 1.07)

    def test_closing_holders_receive_dividends_and_remaining_cash_receives_interest(self):
        cfg = {"rounds": 1, "asset": {"model": "iid_permanent", "dividend": {"relative_noise": 0}},
               "agents": [{"type": "zero_intelligence", "count": 2, "cash": 10000, "shares": 100}]}
        def scripted(holder, observation):
            return Order(holder.agent_id, "buy" if holder.agent_id.endswith("000") else "sell", 10, 100, 1)
        with patch("sim.agents.rule_agents.ZeroIntelligenceAgent.decide", scripted):
            output = self.execute(cfg)
        states = self.rows(output / "agents_state.csv")
        buyer, seller = states
        self.assertEqual((int(buyer["shares"]), int(seller["shares"])), (110, 90))
        self.assertAlmostEqual(float(buyer["dividend_income"]), 2.2)
        self.assertAlmostEqual(float(seller["dividend_income"]), 1.8)
        self.assertAlmostEqual(float(buyer["interest_income"]), 1.8)
        self.assertAlmostEqual(float(seller["interest_income"]), 2.2)

    def test_taxed_multiquote_run_tracks_cashflows_and_inventory(self):
        base = Path(__file__).resolve().parents[1] / "configs/baseline_rules.yaml"
        cfg = yaml.safe_load(base.read_text(encoding="utf-8"))
        cfg["rounds"] = 200
        cfg["market"]["transaction_tax"] = 0.005
        output = self.execute(cfg)
        flows = self.rows(output / "cashflows.csv")
        states = self.rows(output / "agents_state.csv")
        maker = [s for s in states if s["agent_id"].startswith("mark")]
        self.assertTrue(all(0 <= int(s["shares"]) <= 300 for s in maker))
        self.assertTrue(all(float(s["cash"]) >= 0 for s in states))
        for f in flows:
            expected = float(f["cash_before"]) - float(f["tax_paid"]) + float(f["dividends_paid"]) + float(f["interest_paid"])
            self.assertAlmostEqual(float(f["cash_after"]), expected, places=6)
        summary = json.loads((output / "summary.json").read_text())
        self.assertGreater(summary["tax_collected"], 0)
        self.assertEqual(len(self.rows(output / "liquidity.csv")), 200)
        orders = self.rows(output / "orders.csv")
        first_quotes = [o for o in orders if o["agent_id"] == "mark_000" and o["round"] == "1"]
        self.assertEqual({o["side"] for o in first_quotes}, {"buy", "sell"})

    def test_invalid_config_creates_no_output(self):
        with self.assertRaises(ConfigError):
            self.execute({"agents": [{"type": "zero_intelligence"}], "unknown_flag": True})
        self.assertFalse((self.root / "runs").exists())

    def test_duplicate_yaml_keys_are_rejected(self):
        path = self.root / "duplicate.yaml"
        path.write_text("rounds: 1\nrounds: 2\nagents: [{type: zero_intelligence}]\n", encoding="utf-8")
        with self.assertRaisesRegex(ConfigError, "duplicate YAML key"):
            load_config(path)

    def test_all_shipped_configs_load_and_normalized_copies_reload(self):
        for path in (Path(__file__).resolve().parents[1] / "configs").glob("*.yaml"):
            cfg = load_config(path)
            normalized = self.root / "roundtrip.yaml"
            normalized.write_text(yaml.safe_dump(cfg.to_dict()), encoding="utf-8")
            with self.subTest(path=path):
                self.assertEqual(load_config(normalized), cfg)

    def test_raw_prompt_keeps_small_rates_visible_and_states_payout_timing(self):
        trader = LLMAgent("a", 10000, 100, np.random.default_rng(0))
        self.assertIn("0.0002 per round", trader.user_prompt(obs()))
        self.assertIn("After the auction", trader.system_prompt("KGP"))
        self.assertIn("one trading session", trader.system_prompt("KGP"))


if __name__ == "__main__":
    unittest.main()
