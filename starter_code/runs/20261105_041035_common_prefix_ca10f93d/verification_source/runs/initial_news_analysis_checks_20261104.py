"""Offline R036 audit checks: complete, absent and censored endpoints."""
import contextlib
import io
import unittest
from runs.initial_news_checks_20261104 import InitialNewsChecks, ScriptedClient
from runs.initial_news_analysis_20261104 import analyze


class AnalysisChecks(unittest.TestCase):
    def fixture(self, fail_on):
        case = InitialNewsChecks()
        case.setUp()
        self.addCleanup(case.doCleanups)
        ScriptedClient.fail_on = fail_on
        summary = case.offline()
        with contextlib.redirect_stdout(io.StringIO()):
            report = analyze(case.root, case.out / "analysis")
        return summary, report

    def test_complete_endpoints_and_initial_information_controls(self):
        summary, report = self.fixture(None)
        self.assertEqual(summary["completed_markets"], 10)
        self.assertEqual(report["audit"]["own_actual_history_checks"], 240)
        self.assertEqual(len(report["audit"]["available_initial_pair_checks"]), 8)
        self.assertFalse(report["unattempted"])
        for comparison in report["headline_contrasts"]:
            self.assertTrue(comparison["early3_available"])
            self.assertTrue(comparison["full12_available"])

    def test_first_request_failure_does_not_become_a_zero_response(self):
        summary, report = self.fixture(1)
        self.assertEqual(summary["completed_markets"], 0)
        self.assertEqual(len(report["unattempted"]), 9)
        for comparison in report["headline_contrasts"]:
            self.assertFalse(comparison["early3_available"])
            self.assertFalse(comparison["full12_available"])
            self.assertIsNone(comparison["combined_early3_executed"])

    def test_later_failure_preserves_early_endpoint_but_not_terminal(self):
        # Two complete markets (48 calls), then three cleared rounds (6),
        # one delivered choice, and the second actor's round4 failure.
        summary, report = self.fixture(56)
        self.assertEqual(summary["completed_markets"], 2)
        comparison = report["headline_contrasts"][0]
        self.assertTrue(comparison["early3_available"])
        self.assertFalse(comparison["full12_available"])
        self.assertIsNone(comparison["passive_excess_contrasts"])
        arm = report["arms"][-1]
        self.assertEqual(arm["rounds"], 3)
        self.assertEqual(len(arm["uncleared_choices"]), 1)
        self.assertIsNotNone(arm["observed_prefix_evaluation"])
        self.assertIsNone(arm["full_horizon_evaluation"])


if __name__ == "__main__":
    unittest.main()
