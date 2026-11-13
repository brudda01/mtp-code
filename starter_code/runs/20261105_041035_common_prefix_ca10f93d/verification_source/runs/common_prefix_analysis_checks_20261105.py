"""Offline post-prefix metrics and missing-outcome accounting checks."""
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from runs import common_prefix_20261105 as d
from runs import common_prefix_analysis_20261105 as analysis
from runs.quiet_components_checks_20261105 import TradingClient,NoDelay


class Checks(unittest.TestCase):
    def setUp(self):
        scratch=d.BASE/'.tmp';scratch.mkdir(exist_ok=True);tmp=tempfile.TemporaryDirectory(dir=scratch);self.addCleanup(tmp.cleanup);self.out=Path(tmp.name)
        with contextlib.redirect_stdout(io.StringIO()):self.root=d.prepare(self.out)
        TradingClient.calls=0;TradingClient.fail_on=None;TradingClient.empty_reflection=TradingClient.malformed=False
    def execute(self):
        with patch('sim.engine.LLMClient',TradingClient),patch.object(d,'RequestPacer',NoDelay),contextlib.redirect_stdout(io.StringIO()):
            d.execute(self.root);return analysis.analyze(self.root,self.out/'analysis')
    def test_complete_primary_controls_both_marks_and_zero_sum_from_common5(self):
        r=self.execute()
        self.assertEqual((len(r['arms']),len(r['prefix_contrasts']),r['audit']['fresh_request_history_checks'],r['audit']['cached_prefix_requests']),(24,6,384,240))
        self.assertTrue(all(c['available'] for c in r['prefix_contrasts']))
        self.assertTrue(all(s['two_prefix_average_available'] for s in r['within_seed_two_prefix_means']))
        for arm in r['arms']:
            ev=arm['postprefix_primary'];self.assertEqual(ev['continuation_rounds'],7)
            for mark in ['auction','regime_benchmark']:self.assertAlmostEqual(ev['aggregate_active_minus_passive'][mark],0,places=7)
        for pid in {a['prefix_id'] for a in r['arms']}:
            accounts=[[ (x['opening5_cash'],x['opening5_shares'],x['opening5_auction_wealth']) for x in a['postprefix_primary']['accounts']] for a in r['arms'] if a['prefix_id']==pid]
            self.assertTrue(all(x==accounts[0] for x in accounts))
    def test_first_provider_failure_leaves_postprefix_endpoint_missing(self):
        TradingClient.fail_on=1;r=self.execute()
        self.assertEqual((len(r['arms']),len(r['not_attempted'])),(1,23))
        self.assertTrue(all(not c['available'] for c in r['prefix_contrasts']))
        self.assertIsNone(r['arms'][0]['observed_postprefix']);self.assertIsNone(r['arms'][0]['postprefix_primary'])
        self.assertEqual(r['summary']['usage']['requests_made'],1)
    def test_common5_passive_differs_from_initial0_when_prefix_traded(self):
        r=self.execute()
        for arm in r['arms']:
            path=self.root/arm['run_path'];states=d.prior.base.read_rows(path/'agents_state.csv')
            expected={s['agent_id']:s for s in states if s['round']=='5'}
            for account in arm['postprefix_primary']['accounts']:
                self.assertEqual(account['opening5_cash'],float(expected[account['agent_id']]['cash']))
                self.assertEqual(account['opening5_shares'],int(expected[account['agent_id']]['shares']))


if __name__=='__main__':unittest.main()
