"""R043 analysis checks: complete evidence, absent endpoints and affected paths."""
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from runs.quiet_components_checks_20261105 import TradingClient, NoDelay
from runs import quiet_components_20261105 as d
from runs import quiet_components_analysis_20261105 as analysis


class Checks(unittest.TestCase):
    def setUp(self):
        scratch=d.BASE/'.tmp';scratch.mkdir(exist_ok=True)
        temp=tempfile.TemporaryDirectory(dir=scratch);self.addCleanup(temp.cleanup);self.out=Path(temp.name)
        with contextlib.redirect_stdout(io.StringIO()):self.root=d.prepare(self.out)
        TradingClient.calls=0;TradingClient.fail_on=None
        TradingClient.empty_reflection=TradingClient.malformed=False
    def execute(self):
        with patch('sim.engine.LLMClient',TradingClient),patch.object(d,'RequestPacer',NoDelay),contextlib.redirect_stdout(io.StringIO()):
            d.execute(self.root)
            return analysis.analyze(self.root,self.out/'analysis')
    def test_all_arms_both_marks_costs_and_own_histories_are_retained(self):
        r=self.execute()
        self.assertEqual((len(r['arms']),len(r['contrasts']),len(r['within_seed_two_draw_averages'])),(18,12,6))
        self.assertTrue(all(c['available'] for c in r['contrasts']))
        self.assertTrue(all(c['two_draw_average_available'] for c in r['within_seed_two_draw_averages']))
        self.assertEqual((r['audit']['account_rounds'],r['audit']['history_request_checks'],r['audit']['genuine_completed_reflections']),(3528,456,24))
        self.assertEqual(sum(x['requests_made'] for x in r['costs_by_mode'].values()),456)
        for arm in r['arms']:
            for mark in ('auction','regime_benchmark'):
                self.assertAlmostEqual(sum(group[mark] for group in arm['counterpart_groups'].values()),0,places=7)
        self.assertEqual(set(r['contrasts'][0]['passive_excess_differences']['llm_012']),{'auction','regime_benchmark'})
    def test_zero_round_provider_failure_never_becomes_hold_or_terminal_null(self):
        TradingClient.fail_on=1;r=self.execute()
        self.assertEqual((len(r['arms']),len(r['not_attempted'])),(1,17))
        self.assertFalse(any(c['available'] for c in r['contrasts']))
        self.assertIsNone(r['arms'][0]['full_horizon_evaluation'])
        self.assertIsNone(r['arms'][0]['observed_prefix_evaluation'])
        self.assertEqual(r['summary']['usage']['unknown_usage_requests'],1)
    def test_failed_reflections_preserve_financial_prefix_but_not_clean_endpoint(self):
        TradingClient.empty_reflection=True;r=self.execute()
        self.assertEqual(sum(c['available'] for c in r['contrasts']),1)
        self.assertFalse(any(c['two_draw_average_available'] for c in r['within_seed_two_draw_averages']))
        c=r['arms'][-1]
        self.assertEqual((c['mode'],c['rounds'],c['full_clean']),('C',12,False))
        self.assertIsNone(c['full_horizon_evaluation'])
        self.assertIsNotNone(c['observed_prefix_evaluation'])


if __name__=='__main__':unittest.main()
