import contextlib
import csv
from dataclasses import replace
import io
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import yaml

from sim.agents.base import Observation
from sim.agents.rule_agents import FundamentalistAgent
from sim.background_check import slot_recipe
from sim.behaviour_check import cases
from sim.config import ConfigError,parse_config
from sim.engine import build_agents, make_rngs, run
from sim.evaluation import evaluate_run, passive_cash_path


class DividendMemoryTests(unittest.TestCase):
    def obs(self,rnd,dividend):
        return Observation(rnd,30,[100]*6,10,dividend,.0002,None,[],[],10000,100,100,20000,[])

    def test_average_uses_only_observed_payouts_and_once_per_round(self):
        a=FundamentalistAgent("f",10000,100,np.random.default_rng(0),params={"dividend_window":2,"delta":.001})
        a.decide(self.obs(1,.2))  # Initialization reference must not contaminate paid history.
        first=a.decide(self.obs(2,.024))
        self.assertEqual(first.side,"buy")
        a.decide(self.obs(2,.024))
        self.assertEqual(list(a._past_dividends),[.024])
        self.assertEqual(a.decide(self.obs(3,.016)).side,"hold")
        self.assertEqual(a.decide(self.obs(4,.016)).side,"sell")
        self.assertEqual(list(a._past_dividends),[.016,.016])

    def test_disclosed_value_overrides_noisy_proxy(self):
        a=FundamentalistAgent("f",10000,100,np.random.default_rng(0),params={"dividend_window":5})
        self.assertEqual(a.decide(replace(self.obs(2,.03),fundamental_hint=100)).side,"hold")

    def test_default_retains_original_last_payout_decisions(self):
        a=FundamentalistAgent("f",10000,100,np.random.default_rng(0))
        b=FundamentalistAgent("f",10000,100,np.random.default_rng(0),params={"dividend_window":1})
        for rnd,d in enumerate((.02,.024,.016,.021,.019),1):
            self.assertEqual(a.decide(self.obs(rnd,d)),b.decide(self.obs(rnd,d)))
        self.assertEqual(a.decide(self.obs(5,.03)).side,"buy")

    def test_window_validation(self):
        for window in (0,True,1.5):
            with self.subTest(window=window),self.assertRaises(ConfigError):
                parse_config({"agents":[{"type":"fundamentalist","params":{"dividend_window":window}}]})


class ResearchEvaluationTests(unittest.TestCase):
    def test_passive_cash_matches_hand_calculation_without_same_round_reinvestment(self):
        np.testing.assert_allclose(passive_cash_path(100,2,[3,4],.1),[116,135.6],rtol=0,atol=1e-12)

    def test_trading_excess_and_distinct_marks_match_manual_accounts(self):
        scratch=Path(__file__).resolve().parents[1]/".tmp"
        scratch.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as tmp:
            root=Path(tmp)
            self.assertTrue(root.resolve().is_relative_to(scratch.resolve()))
            def save(name,header,data):
                with (root/name).open("w",newline="") as f:
                    writer=csv.writer(f);writer.writerow(header);writer.writerows(data)
            (root/"config.yaml").write_text(yaml.safe_dump({"asset":{"initial_price":100,"risk_free":.1}}))
            (root/"summary.json").write_text(json.dumps({"rounds":1,"status":"completed"}))
            save("prices.csv",["round","price","volume","dividend","fundamental"],[[1,50,1,2,20]])
            save("initial_state.csv",["agent_id","type","cash","shares","wealth"],
                 [["a","Test",100,1,200],["b","Test",100,1,200]])
            # A buys B's share for 50, then both receive 10% cash interest and
            # post-trade holders receive dividend 2. Passive cash is 100*1.1+2.
            save("agents_state.csv",["round","agent_id","type","cash","shares"],
                 [[1,"a","Test",59,2],[1,"b","Test",165,0]])
            save("liquidity.csv",["round","market_maker_volume_fraction","fill_rate","at_price_band"],[[1,0,1,False]])
            result=evaluate_run(root)
            a=result["accounts"][0]["marks"]
            self.assertAlmostEqual(a["auction"]["active_wealth"],159)
            self.assertAlmostEqual(a["auction"]["passive_wealth"],162)
            self.assertAlmostEqual(a["auction"]["excess_return"],-3/200)
            self.assertAlmostEqual(a["regime_benchmark"]["active_minus_passive"],-33)
            for value in result["aggregate_active_minus_passive"].values():self.assertAlmostEqual(value,0)

    def test_passive_engine_no_trade_and_closed_market_excess(self):
        scratch=Path(__file__).resolve().parents[1]/".tmp"
        scratch.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as tmp:
            root=Path(tmp)
            self.assertTrue(root.resolve().is_relative_to(scratch.resolve()))
            raw={"rounds":4,"asset":{"dividend":{"mean":.02,"relative_noise":0}},
                 "agents":[{"type":"zero_intelligence","count":1,"cash":100,"shares":2,
                            "params":{"activity_prob":0}}]}
            path=root/"config.yaml";path.write_text(yaml.safe_dump(raw))
            with contextlib.redirect_stdout(io.StringIO()):market=Path(run(path,output_root=root/"runs"))
            before={p.name:p.read_bytes() for p in market.iterdir() if p.is_file()}
            result=evaluate_run(market)
            self.assertEqual(result["metrics"]["zero_volume_fraction"],1)
            for value in result["accounts"][0]["marks"].values():
                self.assertAlmostEqual(value["active_minus_passive"],0)
                self.assertAlmostEqual(value["excess_return"],0)
            self.assertEqual(before,{p.name:p.read_bytes() for p in market.iterdir() if p.is_file()})

    def test_equal_slots_preserve_background_resources_rng_and_information(self):
        cfgs=[slot_recipe(317,brain=brain,rounds=20) for brain in ("rules","mock")]
        populations=[]
        for cfg in cfgs:
            rng=make_rngs(cfg.seed)
            populations.append(list(build_agents(cfg,rng["population"]).values()))
        a,b=populations
        self.assertEqual(len(a),14)
        self.assertEqual([(x.cash,x.shares,x.avg_cost) for x in a],[(x.cash,x.shares,x.avg_cost) for x in b])
        self.assertEqual(sum(x.cash for x in a),160000)
        self.assertEqual(sum(x.shares for x in a),1450)
        for x,y in zip(a[:12],b[:12]):
            self.assertEqual((x.agent_id,type(x),x.params),(y.agent_id,type(y),y.params))
            self.assertEqual(x.rng.bit_generator.state,y.rng.bit_generator.state)
        self.assertEqual([x.agent_id[-3:] for x in a],[x.agent_id[-3:] for x in b])
        for key in ("market","asset","observation","news","reveal_fundamental"):
            self.assertEqual(cfgs[0].to_dict()[key],cfgs[1].to_dict()[key])


class BehaviourInputTests(unittest.TestCase):
    def test_risk_contrasts_change_only_one_profile_field(self):
        data=cases()
        self.assertEqual(len(data),16)
        risk=[c for c in data if c["family"]=="risk"]
        for a,b in zip(risk[::2],risk[1::2]):
            self.assertEqual(a["observation"],b["observation"])
            self.assertEqual({k:v for k,v in a["persona"].items() if k!="risk_tolerance"},
                             {k:v for k,v in b["persona"].items() if k!="risk_tolerance"})

    def test_gain_loss_changes_basis_not_market_wealth_and_is_crossed_with_trait(self):
        data=[c for c in cases() if c["family"]=="gain_loss"]
        self.assertEqual({c["observation"]["my_wealth"] for c in data},{20000})
        self.assertEqual({c["observation"]["my_avg_cost"] for c in data},{80,120})
        self.assertTrue(all(c["observation"]["fundamental_hint"] is None and not c["observation"]["news"] for c in data))
        self.assertEqual(len({(c["factors"]["wording"],c["factors"]["account_basis"],c["factors"]["trait"]) for c in data}),8)
