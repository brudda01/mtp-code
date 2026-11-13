"""Fake-clock checks for the exact main pacer/budget and sandbox retry boundary."""
import unittest
from urllib.error import HTTPError
from datetime import datetime,timezone
from delivery import RequestPacer,UsageBudget,MODEL,BudgetedDelivery,retry_policy,parse_retry_after,campaign_budget

class FakeClock:
    def __init__(self): self.t=0.
    def now(self): return self.t
    def sleep(self,n): self.t+=n

class DeliveryTests(unittest.TestCase):
    def test_sandbox_sixty_rpm_budget_and_spacing(self):
        budget=campaign_budget()
        self.assertEqual(budget.pacer.requests_per_minute,60)
        self.assertEqual(budget.pacer.input_tokens_per_minute,60000)
        c=FakeClock()
        p=RequestPacer(budget.pacer.requests_per_minute,budget.pacer.input_tokens_per_minute,clock=c.now,sleep=c.sleep)
        p.acquire(100); p.acquire(100)
        self.assertEqual(c.t,1.)
    def test_shared_pacer_is_main_implementation(self):
        from sim.llm.usage import RequestPacer as Main
        self.assertIs(RequestPacer,Main)
        c=FakeClock(); p=RequestPacer(10,60000,clock=c.now,sleep=c.sleep)
        p.acquire(100); p.acquire(100)
        self.assertEqual(c.t,6)
    def test_rolling_input_limit(self):
        c=FakeClock(); p=RequestPacer(10,60000,clock=c.now,sleep=c.sleep)
        p.acquire(40000); p.acquire(40000)
        self.assertEqual(c.t,60)
    def test_retries_reserve_and_pace_every_attempt(self):
        c=FakeClock(); logs=[]; calls=[]
        budget=UsageBudget(max_requests=3,max_reserved_tokens=100000,stop_on_api_error=True)
        budget.pacer=RequestPacer(10,60000,clock=c.now,sleep=c.sleep)
        def transport(body):
            calls.append(body)
            if len(calls)==1: raise HTTPError('https://example.invalid',429,'capacity',{'Retry-After':'10'},None)
            return dict(model=MODEL,choices=[dict(finish_reason='stop',message=dict(content='{}'))])
        d=BudgetedDelivery(transport,logs.append,budget,c.sleep)
        self.assertEqual(d.complete([dict(role='user',content='test')]),'{}')
        self.assertEqual(budget.requests,2); self.assertEqual(budget.unknown_usage_requests,2)
        self.assertEqual(c.t,13); self.assertEqual(calls[0],calls[1]); self.assertEqual(len(logs),2)
    def test_retry_limits_and_categories(self):
        err=lambda code:HTTPError('https://example.invalid',code,'test',{},None)
        self.assertIsNone(retry_policy(err(429),60,0))
        self.assertIsNone(retry_policy(err(503),0,15))
        self.assertIsNone(retry_policy(err(401),0,0))
        self.assertEqual(retry_policy(err(429),0,0),('rate_limit_429',5.))
        self.assertEqual(retry_policy(err(504),0,0),('server',5.))
    def test_retry_after_date_and_fractional(self):
        self.assertEqual(parse_retry_after({'Retry-After':'1.5'}),1.5)
        self.assertEqual(parse_retry_after({'Retry-After':'Mon, 09 Nov 2026 00:01:00 GMT'},datetime(2026,11,9,tzinfo=timezone.utc)),60.)
        self.assertIsNone(parse_retry_after({'Retry-After':'invalid'}))

if __name__=='__main__': unittest.main(verbosity=2)
