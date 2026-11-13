import copy
from datetime import datetime,timezone
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
import numpy as np
from research.goedel_backoff import BackoffAgent,parse_retry_after
from sim.agents.base import Observation
from sim.llm.usage import UsageBudget,UsageLimitExceeded,ProviderUnavailable

HOLD='{"action":"hold","quantity":0,"limit_price":null}'
class Client:
    send_temperature=True
    def __init__(self,values):
        self.values=iter(values);self.calls=[];self.last_usage=None;self.last_response_metadata={};self.last_error_metadata={}
    def chat(self,messages,**kwargs):
        self.calls.append((copy.deepcopy(messages),dict(kwargs)));x=next(self.values)
        if isinstance(x,Exception):raise x
        return x

def error(code=429,header='2.0'):return HTTPError('https://example.invalid',code,'test',{'Retry-After':header},None)

class BackoffTests(unittest.TestCase):
    def agent(self,values,budget=None):
        log=[];client=Client(values)
        a=BackoffAgent('llm_008',10000,100,np.random.default_rng(0),params={'condition':'B','transport_retries':1,'retry_http_503':True,'max_tokens':2048},client=client,budget=budget or UsageBudget(stop_on_api_error=True),log_fn=log.append)
        obs=Observation(1,25,[100],0,.02,.0002,None,[],[],10000,100,100,20000,[])
        return a,client,log,obs
    def test_decimal_date_and_invalid_headers(self):
        self.assertEqual(parse_retry_after({'Retry-After':'2.0'})['retry_after_seconds'],2)
        self.assertEqual(parse_retry_after({'Retry-After':'Mon, 09 Nov 2026 00:00:03 GMT'},datetime(2026,11,9,tzinfo=timezone.utc))['retry_after_seconds'],3)
        for x in ('nan','-2','inf','bad'):self.assertFalse(parse_retry_after({'Retry-After':x})['retry_after_valid'])
    def test_repeated429_budgeted_identical_and_plus1(self):
        a,c,log,obs=self.agent([error(),error(),HOLD])
        with patch('research.goedel_backoff.time.sleep') as sleep:
            self.assertEqual(a.decide(obs).side,'hold')
        self.assertEqual(sleep.call_args_list,[((3.0,),),((3.0,),)])
        self.assertTrue(all(x==c.calls[0] for x in c.calls))
        self.assertEqual(a.budget.snapshot()['requests_made'],3)
        self.assertEqual(a.budget.snapshot()['failed_requests'],2)
        self.assertFalse(a.budget.snapshot()['provider_stopped'])
        calls=[x for x in log if x['record_type']=='model_call']
        self.assertEqual(len(calls),3);self.assertEqual(calls[1]['attempt_kind'],'rate_limit_retry')
    def test_attempt_budget_stops_before_extra_http(self):
        a,c,log,obs=self.agent([error(),HOLD],UsageBudget(max_requests=1,stop_on_api_error=True))
        with patch('research.goedel_backoff.time.sleep'),self.assertRaises(UsageLimitExceeded):a.decide(obs)
        self.assertEqual(len(c.calls),1)
    def test_bounded_rate_retries_and_no_auth_retry(self):
        for values,n in (([error()]*11,11),([error(401)],1)):
            a,c,log,obs=self.agent(values)
            with patch('research.goedel_backoff.time.sleep'),self.assertRaises(ProviderUnavailable):a.decide(obs)
            self.assertEqual(len(c.calls),n)
    def test_missing_header_fallback(self):
        a,c,log,obs=self.agent([error(header='bad'),error(header='bad'),HOLD])
        with patch('research.goedel_backoff.time.sleep') as sleep:a.decide(obs)
        self.assertEqual([x.args[0] for x in sleep.call_args_list],[3,5])

if __name__=='__main__':unittest.main()
