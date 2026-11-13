"""Independent announcement/state controls and private-to-observation separation."""
import contextlib
import copy
import csv
import io
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import yaml

from sim.assets import Asset
from sim.config import ConfigError, parse_config
from sim.engine import run
from sim.news_controls import CELLS,recipe


class AnnouncementConfigTests(unittest.TestCase):
    def test_factorial_configs_change_only_the_named_news_factors(self):
        configs=[recipe(cell,211).to_dict() for cell in CELLS]
        reference=None
        for (cell,(shift,announce)),raw in zip(CELLS.items(),configs):
            self.assertFalse(raw["reveal_fundamental"])
            self.assertEqual(raw["news"][0]["announce"],announce)
            self.assertEqual("effect" in raw["news"][0],shift)
            if not announce:self.assertNotIn("headline",raw["news"][0])
            remainder={k:v for k,v in raw.items() if k not in ("name","news")}
            if reference is None:reference=remainder
            else:self.assertEqual(remainder,reference)

    def test_rule_only_controls_cannot_spend_an_llm_request(self):
        for cell in CELLS:
            cfg=recipe(cell,211)
            self.assertEqual(cfg.llm_limits.max_requests,0)
            self.assertTrue(all(group.type!="llm" for group in cfg.agents))

    def test_hidden_effect_can_omit_text_and_normalized_config_roundtrips(self):
        raw={"rounds":4,"agents":[{"type":"zero_intelligence"}],
             "news":[{"round":2,"announce":False,"effect":{"dbar_mult":1.2}}]}
        cfg=parse_config(raw)
        self.assertIsNone(cfg.news[0].headline)
        self.assertFalse(cfg.news[0].announce)
        self.assertEqual(cfg,parse_config(cfg.to_dict()))

    def test_old_events_remain_announced_by_default(self):
        cfg=parse_config({"agents":[{"type":"zero_intelligence"}],"news":[{"round":1,"headline":"public"}]})
        self.assertTrue(cfg.news[0].announce)

    def test_ambiguous_visibility_and_missing_public_text_are_rejected(self):
        for event in [{"round":1},{"round":1,"announce":True},
                      {"round":1,"announce":"false","headline":"x"},
                      {"round":1,"announce":0,"headline":"x"},
                      {"round":1,"announce":False,"headline":""}]:
            with self.subTest(event=event),self.assertRaises(ConfigError):
                parse_config({"agents":[{"type":"zero_intelligence"}],"news":[event]})


class AnnouncementAssetTests(unittest.TestCase):
    @staticmethod
    def asset(events):
        return Asset({"model":"iid_permanent","risk_free":.0002,
                      "dividend":{"mean":.02,"relative_noise":.2}},
                     np.random.default_rng(31),news_events=events)

    def test_visibility_does_not_change_cashflows_or_rng(self):
        hidden=self.asset([{"round":3,"announce":False,"effect":{"dbar_mult":1.2}}])
        visible=self.asset([{"round":3,"headline":"forecast","effect":{"dbar_mult":1.2}}])
        for rnd in range(1,12):
            a=hidden.open_round(rnd);b=visible.open_round(rnd)
            self.assertEqual(a,[])
            self.assertEqual(b,["forecast"] if rnd==3 else [])
            self.assertEqual(hidden.draw_dividend(),visible.draw_dividend())
            self.assertEqual(hidden.fundamental(rnd),visible.fundamental(rnd))

    def test_audit_preserves_multiple_events_and_resets_next_round(self):
        asset=self.asset([{"round":1,"announce":False,"headline":"private label","effect":{"dbar_mult":1.2}},
                          {"round":1,"headline":"forecast","effect":{"dbar_mult":.9}}])
        self.assertEqual(asset.open_round(1),["forecast"])
        self.assertEqual([e["event_index"] for e in asset.round_events],[0,1])
        first,second=asset.round_events
        self.assertIsNone(first["public_headline"])
        self.assertEqual(first["configured_headline"],"private label")
        self.assertAlmostEqual(first["regime_benchmark_before"],100)
        self.assertAlmostEqual(first["regime_benchmark_after"],120)
        self.assertAlmostEqual(second["regime_benchmark_before"],120)
        self.assertAlmostEqual(second["regime_benchmark_after"],108)
        asset.draw_dividend();asset.open_round(2)
        self.assertEqual(asset.round_events,[])

    def test_direct_asset_usage_cannot_treat_a_false_string_as_hidden(self):
        with self.assertRaises(ValueError):
            self.asset([{"round":1,"announce":"false","headline":"x"}])


class AnnouncementEngineTests(unittest.TestCase):
    def setUp(self):
        scratch=Path(__file__).resolve().parents[1]/".tmp"
        scratch.mkdir(exist_ok=True)
        temporary=tempfile.TemporaryDirectory(dir=scratch)
        self.root=Path(temporary.name)
        assert self.root.resolve().is_relative_to(scratch.resolve())
        self.addCleanup(temporary.cleanup)

    def execute(self,raw):
        path=self.root/"config.yaml";path.write_text(yaml.safe_dump(raw))
        with contextlib.redirect_stdout(io.StringIO()):return Path(run(path,output_root=self.root/"runs"))

    @staticmethod
    def records(path):
        return [json.loads(x) for x in path.read_text().splitlines()]

    def test_hidden_marker_never_enters_decisions_reflections_or_memory(self):
        raw={"rounds":3,"seed":37,"reveal_fundamental":False,
             "agents":[{"type":"llm","llm":{"condition":"C","reflect_every":1,"memory_window":2}}]}
        control=self.execute(raw)
        quiet=copy.deepcopy(raw)
        quiet["news"]=[{"round":2,"announce":False,"headline":"PRIVATE_HIDDEN_EVENT_MARKER",
                        "effect":{"dbar_mult":1.2}}]
        shocked=self.execute(quiet)
        for name in ["llm_requests.jsonl","llm_calls.jsonl","agent_outcomes.jsonl"]:
            self.assertNotIn("PRIVATE_HIDDEN_EVENT_MARKER",(shocked/name).read_text())
        decisions=lambda path:{r["round"]:r for r in self.records(path/"llm_calls.jsonl") if r["record_type"]=="decision"}
        a,b=decisions(control),decisions(shocked)
        self.assertEqual(a[2]["prompt"],b[2]["prompt"])  # Current payout is not yet visible.
        self.assertNotIn("Analyst fair-value estimate",b[2]["prompt"])
        self.assertNotEqual(a[3]["prompt"],b[3]["prompt"])  # Paid income is legitimate evidence.
        with (shocked/"events.csv").open(newline="") as f:self.assertEqual(list(csv.DictReader(f)),[])
        audit=self.records(shocked/"event_audit.jsonl")
        self.assertEqual(len(audit),1)
        self.assertFalse(audit[0]["announce"])
        self.assertAlmostEqual(audit[0]["regime_benchmark_after"],120)
        summary=json.loads((shocked/"summary.json").read_text())
        self.assertEqual((summary["event_records"],summary["announcements_available"]),(1,0))

    def test_explicit_value_disclosure_is_an_independent_information_channel(self):
        raw={"rounds":2,"reveal_fundamental":True,
             "agents":[{"type":"llm"}],
             "news":[{"round":2,"announce":False,"effect":{"dbar_mult":1.2}}]}
        output=self.execute(raw)
        decisions=[r for r in self.records(output/"llm_calls.jsonl") if r["record_type"]=="decision"]
        self.assertIn("Analyst fair-value estimate: 120",decisions[-1]["prompt"])
        self.assertNotIn("News today:",decisions[-1]["prompt"])

    def test_public_events_keep_legacy_csv_rows_and_private_audit(self):
        raw={"rounds":3,"agents":[{"type":"zero_intelligence"}],
             "news":[{"round":2,"headline":"public forecast","effect":{"dbar_mult":1.2}}]}
        output=self.execute(raw)
        with (output/"events.csv").open(newline="") as f:rows=list(csv.DictReader(f))
        self.assertEqual([(r["round"],r["event_type"],r["headline"]) for r in rows],[("2","news","public forecast")])
        self.assertEqual(self.records(output/"event_audit.jsonl")[0]["public_headline"],"public forecast")


if __name__=="__main__":unittest.main()
