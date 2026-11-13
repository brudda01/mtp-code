"""Configuration contracts: reject ignored switches and preserve run recipes."""
import copy
from dataclasses import asdict
import unittest

import numpy as np

from sim.config import ConfigError, RunConfig, parse_config
from sim.engine import build_agents, make_rngs


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.raw = {"name": "test", "rounds": 20,
                    "agents": [{"type": "zero_intelligence", "count": 2}]}

    def test_minimal_recipe_has_explicit_coherent_defaults(self):
        cfg = parse_config(self.raw)
        self.assertIsInstance(cfg, RunConfig)
        self.assertEqual(cfg.asset.model, "iid_permanent")
        self.assertEqual(cfg.time.round_unit, "trading_session")
        self.assertAlmostEqual(cfg.asset.dividend.mean / cfg.asset.risk_free, 100)
        self.assertEqual(cfg.market.mechanism, "call_auction")

    def test_normalized_config_round_trips_without_changing_semantics(self):
        for changes in [{}, {"time": {"round_unit": "experimental_period", "periods_per_year": None}},
                        {"agents": [{"type": "llm", "count": 2, "cash_dist": "lognormal(9.2, 0.5)"}]},
                        {"asset": {"model": "legacy_ar1", "dividend": {"mean": 1, "rho": 0.6, "sigma": 0.3}}}]:
            raw = {**self.raw, **changes}
            with self.subTest(raw=raw):
                cfg = parse_config(raw)
                self.assertEqual(asdict(parse_config(cfg.to_dict())), asdict(cfg))

    def test_unknown_and_unimplemented_switches_are_errors(self):
        cases = [
            {"typo": 1}, {"rounds": 0}, {"rounds": True}, {"seed": -1},
            {"name": "../escape"}, {"market": {"mechanism": "lob"}},
            {"market": {"tick": 0}}, {"market": {"price_band": 1}},
            {"market": {"transaction_tax": -0.1}},
            {"market": {"circuit_breaker": {"threshold": 0.07}}},
            {"asset": {"risk_free": 0}}, {"asset": {"risk_free": float("nan")}},
            {"asset": {"initial_price": 100.04}},
            {"asset": {"model": "iid_permanent", "dividend": {"rho": 0.6}}},
            {"asset": {"dividend": {"relative_noise": 1.1}}},
            {"asset": {"smith_bubble_mode": True}},
            {"observation": {"price_history_len": 0}},
            {"observation": {"bbs_sample": 5}},
            {"execution": {"max_workers": 0}}, {"reveal_fundamental": "false"},
            {"news": [{"round": 30, "headline": "too late"}]},
            {"news": [{"round": 1, "headline": "x", "effect": {"duration": 3}}]},
            {"agents": [{"type": "zero_intelligence", "count": -1}]},
            {"agents": [{"type": "zero_intelligence", "count": 0}]},
            {"agents": [{"type": "noise"}]},
            {"agents": [{"type": "fundamentalist", "params": {"risk_aversion": 0.5}}]},
            {"agents": [{"type": "momentum", "params": {"window": 20}}]},
            {"agents": [{"type": "market_maker", "shares": 500}]},
            {"agents": [{"type": "zero_intelligence", "llm": {}}]},
            {"agents": [{"type": "llm", "llm": {"temperature": 3}}]},
            {"agents": [{"type": "llm", "llm": {"provider": "typo"}}]},
            {"agents": [{"type": "llm", "llm": {"provider": "openai_compatible"}}]},
            {"agents": [{"type": "llm", "llm": {"max_tokens": 0}}]},
            {"agents": [{"type": "llm", "persona_source": "generic"}]},
            {"agents": [{"type": "llm", "llm": {"api_key": "do-not-store-keys"}}]},
        ]
        for changes in cases:
            with self.subTest(changes=changes):
                with self.assertRaises(ConfigError):
                    parse_config({**self.raw, **changes})

    def test_invalid_types_and_nonfinite_parameters_are_rejected(self):
        for changes in [{"agents": "two"}, {"asset": []}, {"news": None},
                        {"agents": [{"type": "fundamentalist", "params": {"aggressiveness": float("inf")}}]},
                        {"agents": [{"type": "zero_intelligence", "shares": 1.5}]}]:
            with self.subTest(changes=changes), self.assertRaises(ConfigError):
                parse_config({**self.raw, **changes})

    def test_log_normal_endowments_are_seeded_and_isolated_from_environment(self):
        raw = {**self.raw, "agents": [{"type": "zero_intelligence", "count": 5,
                                       "cash_dist": "lognormal(9.2, 0.5)"}]}
        cfg = parse_config(raw)
        first, second = make_rngs(42), make_rngs(42)
        agents_a = build_agents(cfg, first["population"])
        agents_b = build_agents(cfg, second["population"])
        self.assertEqual([a.cash for a in agents_a.values()], [a.cash for a in agents_b.values()])
        self.assertGreater(len({a.cash for a in agents_a.values()}), 1)
        untouched = make_rngs(42)["environment"].normal(size=10)
        np.testing.assert_array_equal(first["environment"].normal(size=10), untouched)

    def test_distribution_parser_never_evaluates_code(self):
        for expression in ["__import__('os').getcwd()", "lognormal(0,-1)",
                           "lognormal(nan,1)", "normal(0,1)", "lognormal(1.2.3,1)"]:
            raw = copy.deepcopy(self.raw)
            raw["agents"][0]["cash_dist"] = expression
            with self.subTest(expression=expression), self.assertRaises(ConfigError):
                parse_config(raw)

    def test_ambiguous_cash_and_distribution_are_rejected(self):
        raw = copy.deepcopy(self.raw)
        raw["agents"][0].update(cash=100, cash_dist="lognormal(9.2,0.5)")
        with self.assertRaisesRegex(ConfigError, "either cash or cash_dist"):
            parse_config(raw)

    def test_permanent_and_noise_news_are_supported(self):
        raw = {**self.raw, "news": [{"round": 5, "headline": "new regime",
                                    "effect": {"dbar_mult": 1.2}},
                                   {"round": 10, "headline": "unverified rumor"}]}
        cfg = parse_config(raw)
        self.assertIsNone(cfg.news[0].effect.duration)
        self.assertIsNone(cfg.news[1].effect)


if __name__ == "__main__":
    unittest.main()
