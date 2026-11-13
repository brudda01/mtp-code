import contextlib
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_news_components as fixtures
from sim.component_continuation import execute, key, prepare, validate


class ContinuationTests(unittest.TestCase):
    def setUp(self):
        fixture = fixtures.ComponentTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.parent=fixture.study; self.root=fixture.root
        fixtures.ScriptedClient.fail_on=43
        fixture.execute_offline()
        summary=json.loads((self.parent/"summary.json").read_text())
        self.assertEqual((summary["status"],summary["completed_decisions"]),("provider_error",34))
        fixtures.ScriptedClient.calls=0; fixtures.ScriptedClient.fail_on=None
        with contextlib.redirect_stdout(io.StringIO()):self.study=prepare(self.parent,self.root)

    def execute_offline(self):
        with patch("sim.component_continuation.LLMClient",fixtures.ScriptedClient), \
             patch("sim.component_continuation.RequestPacer",fixtures.NoDelay),contextlib.redirect_stdout(io.StringIO()):
            return execute(self.study)

    def test_plan_keeps_only_missing_choices_and_actual_remaining_allowance(self):
        plan,_,_=validate(self.study)
        self.assertEqual((plan["planned_decisions"],plan["planned_reflections"]),(74,16))
        original=json.loads((self.parent/"results.json").read_text())
        done={key(r) for r in original}
        pending={(b["frame_id"],b["repetition"],c["condition"],c["news"]) for b in plan["blocks"] for c in b["choices"]}
        self.assertFalse(done & pending);self.assertEqual(len(done|pending),108)
        self.assertEqual(plan["blocks"][0]["inherited_chain"]["steps"][-1]["round"],10)
        cfg=json.loads((self.study/"manifest.json").read_text())["usage_limits"]
        prior=plan["prior_usage"]
        self.assertEqual(cfg["max_requests"]+prior["requests_made"],264)
        self.assertEqual(cfg["max_reserved_tokens"]+prior["reserved_tokens"],4000000)

    def test_complete_continuation_preserves_pending_C_prompt_without_regenerating_diary(self):
        original_manifest=(self.parent/"manifest.json").read_bytes()
        self.execute_offline()
        summary=json.loads((self.study/"summary.json").read_text())
        self.assertEqual((summary["status"],summary["completed_decisions"],summary["completed_reflections"]),("completed",74,16))
        self.assertEqual((summary["cumulative_decisions"],summary["cumulative_reflections"]),(108,24))
        self.assertEqual(fixtures.ScriptedClient.calls,90)
        self.assertEqual(original_manifest,(self.parent/"manifest.json").read_bytes())
        old=[json.loads(s) for s in (self.parent/"llm_requests.jsonl").read_text().splitlines() if json.loads(s)["record_type"]=="model_call"]
        new=[json.loads(s) for s in (self.study/"llm_requests.jsonl").read_text().splitlines() if json.loads(s)["record_type"]=="model_call"]
        self.assertEqual(new[0]["call_type"],"decision")
        self.assertEqual(new[0]["messages"],old[-1]["messages"])
        self.assertFalse({r["call_id"] for r in old}&{r["call_id"] for r in new})
        self.assertEqual(sum(r["call_type"]=="reflection" for r in new),16)
        with self.assertRaisesRegex(ValueError,"already started"):execute(self.study)

    def test_parent_drift_stops_before_any_call(self):
        path=self.parent/"summary.json";path.write_text(path.read_text()+"\n")
        with self.assertRaisesRegex(ValueError,"parent drift"):self.execute_offline()
        self.assertEqual(fixtures.ScriptedClient.calls,0)
        self.assertFalse((self.study/"execution.json").exists())

    def test_failed_first_pending_call_stops_with_inherited_diary_and_prior_usage_retained(self):
        fixtures.ScriptedClient.fail_on=1;self.execute_offline()
        summary=json.loads((self.study/"summary.json").read_text())
        self.assertEqual((summary["status"],summary["completed_decisions"],summary["completed_reflections"]),("provider_error",0,0))
        self.assertEqual(summary["cumulative_decisions"],34)
        self.assertEqual(summary["inherited_reflection_steps"],2)
        self.assertEqual(fixtures.ScriptedClient.calls,1)
        self.assertEqual(summary["llm_usage"]["unknown_usage_requests"],1)


if __name__=="__main__":unittest.main()
