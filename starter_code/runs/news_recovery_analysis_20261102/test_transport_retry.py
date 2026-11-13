import copy
import ssl
import unittest
from unittest.mock import patch
from urllib.error import HTTPError,URLError

import numpy as np

from sim.agents.base import Observation
from sim.agents.llm_agent import LLMAgent
from sim.config import ConfigError,parse_config
from sim.llm.usage import OutputLimitExceeded,ProviderUnavailable,UsageBudget,UsageLimitExceeded


HOLD='{"action":"hold","quantity":0,"limit_price":null}'


class ScriptedClient:
    reasoning_effort="low"
    send_temperature=True
    def __init__(self,responses):
        self.responses=iter(responses);self.calls=[]
        self.last_usage=None;self.last_response_metadata={};self.last_error_metadata={}
    def chat(self,messages,**kwargs):
        self.calls.append(copy.deepcopy(messages))
        value=next(self.responses)
        if isinstance(value,Exception):raise value
        return value


class TransportRetryTests(unittest.TestCase):
    def setUp(self):
        self.obs=Observation(4,20,[100]*4,10,.02,.0002,None,[],[],10000,100,100,20000,[])
        self.sleep=patch("sim.agents.llm_agent.time.sleep",return_value=None);self.sleep.start()
        self.addCleanup(self.sleep.stop)

    def agent(self,responses,limit=1,budget=None):
        records=[];client=ScriptedClient(responses)
        a=LLMAgent("a",10000,100,np.random.default_rng(0),
            params={"condition":"A","transport_retries":limit},client=client,
            budget=budget if budget is not None else UsageBudget(stop_on_api_error=True),log_fn=records.append)
        return a,client,records

    def test_recovery_preserves_input_and_counts_every_attempt_unknown_usage(self):
        a,c,records=self.agent([URLError(ConnectionResetError(10054,"secret error text")),HOLD])
        self.assertEqual(a.decide(self.obs).side,"hold")
        self.assertEqual(c.calls[0],c.calls[1])
        calls=[r for r in records if r["record_type"]=="model_call"]
        self.assertEqual([r["transport_attempt"] for r in calls],[1,2])
        self.assertEqual(len({r["call_id"] for r in calls}),2)
        self.assertEqual(calls[0]["request_group_id"],calls[1]["request_group_id"])
        self.assertEqual(calls[0]["transport_diagnostics"]["reason_type"],"ConnectionResetError")
        self.assertNotIn("secret error text",str(records))
        self.assertEqual((a.transport_retries,a.json_repairs,a.api_failures),(1,0,0))
        self.assertEqual(a.budget.snapshot()["requests_made"],2)
        self.assertEqual(a.budget.snapshot()["failed_requests"],1)
        self.assertEqual(a.budget.snapshot()["unknown_usage_requests"],2)

    def test_default_zero_and_exhausted_retry_stop(self):
        for limit,expected in ((0,1),(1,2)):
            a,c,records=self.agent([URLError("offline"),URLError("offline"),HOLD],limit)
            with self.assertRaises(ProviderUnavailable):a.decide(self.obs)
            self.assertEqual(len(c.calls),expected)
            self.assertTrue(a.budget.snapshot()["provider_stopped"])

    def test_http_and_certificate_errors_never_retry(self):
        errors=[HTTPError("https://example.invalid",code,"secret",{},None) for code in (401,403,429,500,503)]
        errors += [URLError(ssl.SSLCertVerificationError(1,"secret"))]
        for error in errors:
            with self.subTest(error=type(error).__name__):
                a,c,_=self.agent([error,HOLD])
                with self.assertRaises(ProviderUnavailable):a.decide(self.obs)
                self.assertEqual(len(c.calls),1)

    def test_retry_cannot_bypass_budget_or_refund_failed_attempt(self):
        budget=UsageBudget(max_requests=1,stop_on_api_error=True)
        a,c,records=self.agent([TimeoutError("offline"),HOLD],budget=budget)
        with self.assertRaises(UsageLimitExceeded):a.decide(self.obs)
        self.assertEqual(len(c.calls),1)
        self.assertEqual(a.transport_retries,0)
        self.assertEqual(budget.snapshot()["failed_requests"],1)
        self.assertGreater(budget.snapshot()["reserved_tokens"],0)
        self.assertEqual(records[-1]["record_type"],"request_blocked")

    def test_pacer_applies_to_retry_and_json_repair_is_separate(self):
        budget=UsageBudget(stop_on_api_error=True)
        with patch.object(budget.pacer,"acquire",return_value=0) as pacer:
            a,c,records=self.agent([URLError("offline"),"[]",HOLD],budget=budget)
            self.assertEqual(a.decide(self.obs).side,"hold")
            self.assertEqual(pacer.call_count,3)
        calls=[r for r in records if r["record_type"]=="model_call"]
        self.assertEqual([r["attempt_kind"] for r in calls],["initial","transport_retry","json_repair"])
        self.assertEqual([r["json_attempt"] for r in calls],[1,1,2])
        self.assertEqual((a.transport_retries,a.json_repairs),(1,1))
        self.assertEqual(c.calls[0],c.calls[1]);self.assertNotEqual(c.calls[1],c.calls[2])

    def test_output_cap_is_not_retried(self):
        a,c,_=self.agent([HOLD,HOLD]);c.last_response_metadata={"finish_reason":"length"}
        with self.assertRaises(OutputLimitExceeded):a.decide(self.obs)
        self.assertEqual(len(c.calls),1)

    def test_configuration_is_opt_in_and_bounded(self):
        self.assertEqual(parse_config({"agents":[{"type":"llm"}]}).agents[0].llm.transport_retries,0)
        self.assertEqual(parse_config({"agents":[{"type":"llm","llm":{"transport_retries":1}}]}).agents[0].llm.transport_retries,1)
        for value in (-1,2,True,1.5,"1"):
            with self.subTest(value=value),self.assertRaises(ConfigError):
                parse_config({"agents":[{"type":"llm","llm":{"transport_retries":value}}]})
