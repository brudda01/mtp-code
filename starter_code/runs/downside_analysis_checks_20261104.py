"""R041 audit checks distinguish full, missing and late-censored endpoints."""
import contextlib
import io
import unittest
from runs.downside_confirmation_checks_20261104 import Checks as Fixture,ScriptedClient
from runs.downside_confirmation_analysis_20261104 import analyze


class Checks(unittest.TestCase):
    def fixture(self,fail_on):
        case=Fixture();case.setUp();self.addCleanup(case.doCleanups);ScriptedClient.fail_on=fail_on
        summary=case.execute()
        with contextlib.redirect_stdout(io.StringIO()):report=analyze(case.root,case.out/"analysis")
        return summary,report
    def test_all_planned_endpoints_and_actual_history_controls(self):
        summary,r=self.fixture(None)
        self.assertEqual(summary["completed_markets"],16);self.assertEqual(r["audit"]["actual_history_request_checks"],256)
        self.assertEqual(r["audit"]["initial_messages_checked"],32);self.assertFalse(r["unattempted"])
        self.assertTrue(all(x["early3_available"] and x["full8_available"] for x in r["headline_contrasts"]))
        self.assertTrue(all(x["available"] for x in r["background_response_differences"]))
    def test_no_financial_rounds_is_missing_not_zero_response(self):
        summary,r=self.fixture(1)
        self.assertEqual(summary["completed_markets"],0);self.assertEqual(len(r["unattempted"]),15)
        self.assertTrue(all(not x["early3_available"] and x["combined_executed"] is None for x in r["headline_contrasts"]))
    def test_later_stop_keeps_primary_but_not_full8_or_uncleared_fill(self):
        summary,r=self.fixture(56)
        self.assertEqual(summary["completed_markets"],3);last=r["arms"][-1]
        self.assertEqual(last["rounds"],3);self.assertEqual(len(last["uncleared_choices"]),1)
        self.assertIsNone(last["full_horizon_evaluation"]);self.assertIsNotNone(last["observed_prefix_evaluation"])
        comparison=r["headline_contrasts"][1]
        self.assertTrue(comparison["early3_available"]);self.assertFalse(comparison["full8_available"])
        self.assertIsNone(comparison["passive_excess_contrasts"]);self.assertTrue(r["background_response_differences"][0]["available"])


if __name__=="__main__":unittest.main()
