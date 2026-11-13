import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from sim.agents.base import Observation
from sim.behaviour_check import cases, prepare
from sim.behaviour_run import contrasts, recipe, run_battery, scenario_agent, score_choice, validate_battery
from sim.config import parse_config
from sim.llm.usage import UsageBudget


class OfflineClient:
    api_key="offline-test-only"
    reasoning_effort="low"
    send_temperature=True
    last_usage=None
    last_response_metadata={"finish_reason":"stop"}
    last_error_metadata={}

    def __init__(self, responses=None):
        self.calls=[]
        self.responses=iter(responses or [])

    def chat(self,messages,**kwargs):
        self.calls.append(copy.deepcopy(messages))
        response=next(self.responses,'{"action":"hold","quantity":0,"limit_price":null}')
        if isinstance(response,Exception):raise response
        return response


class ActionScoringTests(unittest.TestCase):
    def test_clipping_keeps_raw_intent_and_normalizes_at_current_mark(self):
        case=cases()[0]
        client=OfflineClient(['{"action":"buy","quantity":250,"limit_price":null}'])
        agent=scenario_agent(case,client,UsageBudget())
        obs=Observation(**case["observation"])
        result=score_choice(agent,agent.decide(obs),obs)
        self.assertEqual(result["requested_signed_quantity"],250)
        self.assertEqual(result["accepted_signed_quantity"],83)  # floor(10000/120)
        self.assertTrue(result["resource_reduced"])
        self.assertAlmostEqual(result["accepted_notional_over_current_wealth"],.415)
        self.assertIsNone(result["executions"])

    def test_parse_failure_cannot_become_a_preference_hold(self):
        case=cases()[0];client=OfflineClient(['[]','[]'])
        agent=scenario_agent(case,client,UsageBudget())
        obs=Observation(**case["observation"])
        result=score_choice(agent,agent.decide(obs),obs)
        self.assertFalse(result["valid_choice"])
        self.assertEqual(result["accepted"]["side"],"hold")
        self.assertIsNone(result["accepted_signed_quantity"])
        self.assertIsNone(result["accepted_sell_quantity"])

    def test_contrasts_use_exposure_and_basis_by_trait_interaction(self):
        def row(case_id,q,sell=0,valid=True):
            return dict(case_id=case_id,repetition=1,valid_choice=valid,
                        requested_signed_quantity=q,accepted_signed_quantity=q,accepted_sell_quantity=sell)
        data=[row("risk_rising_label_high",10),row("risk_rising_label_low",-5),
              row("basis_pain_gain_loss_sensitive",-30,30),row("basis_pain_loss_loss_sensitive",-5,5),
              row("basis_pain_gain_neutral",-20,20),row("basis_pain_loss_neutral",-10,10)]
        result=contrasts(data,{})
        self.assertEqual(result["risk"][0]["high_minus_low_accepted"],15)
        self.assertEqual(result["gain_loss"][0]["trait_by_basis_sell_interaction"],15)
        self.assertIsNone(result["risk"][1]["high_minus_low_accepted"])
        data[0]["valid_choice"]=False
        self.assertIsNone(contrasts(data,{})["risk"][0]["high_minus_low_accepted"])


class FrozenRunnerTests(unittest.TestCase):
    def setUp(self):
        scratch=Path(__file__).resolve().parents[1]/".tmp"
        scratch.mkdir(exist_ok=True)
        self.temporary=tempfile.TemporaryDirectory(dir=scratch)
        self.root=Path(self.temporary.name)
        assert self.root.resolve().is_relative_to(scratch.resolve())
        self.addCleanup(self.temporary.cleanup)
        with contextlib.redirect_stdout(io.StringIO()):self.battery=prepare(self.root)

    def test_input_and_schedule_drift_are_rejected(self):
        battery=json.loads((self.battery/"battery.json").read_text())
        self.assertEqual(len(validate_battery(battery)),16)
        altered=copy.deepcopy(battery);altered["cases"][0]["messages"][0]["content"]+="changed"
        with self.assertRaisesRegex(ValueError,"drift"):validate_battery(altered)
        altered=copy.deepcopy(battery);altered["schedule"][0]=altered["schedule"][1]
        with self.assertRaisesRegex(ValueError,"duplicates"):validate_battery(altered)

    def execute(self,client):
        raw=recipe().to_dict()
        raw["llm_limits"].update(requests_per_minute=None,input_tokens_per_minute=None)
        with patch("sim.behaviour_run.recipe",return_value=parse_config(raw)), \
             patch("sim.behaviour_run.LLMClient",return_value=client), \
             contextlib.redirect_stdout(io.StringIO()):
            return run_battery(self.battery,self.root)

    def test_full_schedule_uses_frozen_messages_and_records_null_contrasts(self):
        client=OfflineClient();output=self.execute(client)
        battery=json.loads((self.battery/"battery.json").read_text())
        definitions={c["case_id"]:c for c in battery["cases"]}
        self.assertEqual(len(client.calls),48)
        for messages,item in zip(client.calls,battery["schedule"]):
            self.assertEqual(messages,definitions[item["case_id"]]["messages"])
        summary=json.loads((output/"summary.json").read_text())
        self.assertEqual((summary["status"],summary["valid_choices"]),("completed",48))
        contrast=json.loads((output/"contrasts.json").read_text())
        self.assertTrue(all(c["high_minus_low_accepted"]==0 for c in contrast["risk"]))
        self.assertTrue(all(c["trait_by_basis_sell_interaction"]==0 for c in contrast["gain_loss"]))

    def test_provider_error_stops_and_saves_unknown_usage(self):
        client=OfflineClient([HTTPError("https://example.invalid",429,"quota",{},None)])
        output=self.execute(client)
        self.assertEqual(len(client.calls),1)
        summary=json.loads((output/"summary.json").read_text())
        self.assertEqual(summary["status"],"provider_error")
        self.assertEqual(summary["completed_decisions"],0)
        self.assertEqual(summary["llm_usage"]["unknown_usage_requests"],1)
        records=[json.loads(s) for s in (output/"llm_requests.jsonl").read_text().splitlines()]
        self.assertEqual(records[0]["http_status"],429)
        self.assertEqual(records[0]["case_id"],json.loads((self.battery/"battery.json").read_text())["schedule"][0]["case_id"])
