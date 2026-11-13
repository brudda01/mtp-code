"""Regression tests and labeled mock integration cases, never empirical markets."""
import dataclasses
import hashlib
import json
import math
from pathlib import Path
import socket
import unittest
from unittest.mock import patch
import uuid
import numpy as np
from repaired_engine import RepairedMarginAgent as Agent,RepairedMarginFundamentalist,Order,Trade,Observation,atomic_settle,MarginBreach
from repaired_market_sim import CallAuction,DecoupledAsset,CallAuctionMarket,CoreOrder
from repaired_llm_trader import RepairedLLMTrader
from repaired_client import FixtureClient,RepairedResilientClient,LiveCollectionClosed
from wealth import endowments,gini
from sandbox import ROOT,Config,run_mock,source_hashes
from verify_mock_run import verify

def observation(**kwargs):
    return dataclasses.replace(Observation(1,10,[100.],[],.02,.0002,None,[],[],1000,10,0,2000,[]),**kwargs)

class EngineTests(unittest.TestCase):
    def test_basis_all_transitions(self):
        for start,delta,expected,basis in [(10,-5,5,100),(0,-10,-10,120),(-10,5,-5,100),(10,-20,-10,120),(-10,20,10,120),(10,-10,0,0),(10,10,20,110),(-10,-10,-20,110)]:
            a=Agent('a',10000,start,allow_short=start<0)
            a._add_shares(delta,120)
            self.assertEqual((a.shares,a.avg_cost),(expected,basis))
    def test_invalid_initial_values(self):
        for cash,shares in [(float('nan'),1),(-1,1),(1,True),(1,1.5),(1,-1)]:
            with self.assertRaises(ValueError): Agent('a',cash,shares)
    def test_initial_margin_parameters(self):
        for kwargs in [dict(initial_margin_ratio=0),dict(maint_margin_ratio=2),dict(price_band=1),dict(transaction_tax=1),dict(allow_short=1)]:
            with self.assertRaises(ValueError): Agent('a',1000,1,**kwargs)
    def test_short_initiation(self):
        a=RepairedMarginFundamentalist('a',10000,0,allow_short=True)
        o=a.decide(observation(price_history=[120],fundamental_hint=100))
        self.assertEqual(o.side,'sell'); self.assertGreater(o.quantity,0)
    def test_existing_collateral_reserved(self):
        a=Agent('a',2000,-10,allow_short=True)
        self.assertEqual(a.validate_orders(Order('a','sell',100),100)[0].quantity,1)
    def test_cover_releases_collateral(self):
        a=Agent('a',1800,-10,allow_short=True)
        self.assertEqual(a.validate_orders(Order('a','buy',10,100),100)[0].quantity,10)
        b=Agent('b',0,10)
        atomic_settle([Trade(1,'a','b',10,100)],dict(a=a,b=b))
        self.assertEqual((a.cash,a.shares),(800,0))
    def test_validation_rejects_invalid(self):
        a=Agent('a',1000,10)
        for o in [Order('wrong','buy',1),Order('a','buy',True),Order('a','buy',1.5),Order('a','buy',-1),Order('a','buy',1,float('nan')),Order('a','hold',1),Order('a','buy',1,status='missing')]:
            with self.assertRaises(ValueError): a.validate_orders(o,100)
    def test_duplicates_and_crossing(self):
        a=Agent('a',1000,10)
        for orders in [[Order('a','sell',10),Order('a','sell',10)],[Order('a','buy',1,101),Order('a','sell',1,100)]]:
            with self.assertRaises(ValueError): a.validate_orders(orders,100)
    def test_band_buy_reservation(self):
        a=Agent('a',1200,0)
        self.assertEqual(a.validate_orders(Order('a','buy',100,1000),100)[0].quantity,10)
    def test_atomic_unfunded_batch(self):
        a,b,c=Agent('a',100,0),Agent('b',0,1),Agent('c',0,1)
        with self.assertRaises(ValueError): atomic_settle([Trade(1,'a','b',1,100),Trade(1,'a','c',1,100)],dict(a=a,b=b,c=c))
        self.assertEqual((a.cash,a.shares,b.cash,c.cash),(100,0,0,0))
    def test_no_same_batch_finance(self):
        a,b,c=Agent('a',0,1),Agent('b',100,0),Agent('c',0,1)
        with self.assertRaises(ValueError): atomic_settle([Trade(1,'b','a',1,100),Trade(1,'a','c',1,100)],dict(a=a,b=b,c=c))
        self.assertEqual(a.cash,0); self.assertEqual(a.shares,1)
    def test_bad_trades_leave_accounts_unchanged(self):
        for trade in [Trade(1,'a','b',.5,100),Trade(1,'a','b',True,100),Trade(1,'a','a',1,100),Trade(1,'a','unknown',1,100),Trade(1,'a','b',1,float('nan'))]:
            a,b=Agent('a',1000,0),Agent('b',0,10)
            with self.assertRaises(ValueError): atomic_settle([trade],dict(a=a,b=b))
            self.assertEqual((a.cash,a.shares,b.cash,b.shares),(1000,0,0,10))
    def test_banned_short_and_collateral(self):
        for allow,cash in [(False,1000),(True,100)]:
            a,b=Agent('a',1000,0),Agent('b',cash,0,allow_short=allow)
            with self.assertRaises(ValueError): atomic_settle([Trade(1,'a','b',1,100)],dict(a=a,b=b))
            self.assertEqual(a.cash,1000)
    def test_short_execution_and_dividend(self):
        a,b=Agent('a',1000,0),Agent('b',200,0,allow_short=True)
        atomic_settle([Trade(1,'a','b',1,100)],dict(a=a,b=b))
        self.assertEqual((b.cash,b.shares),(300,-1))
        d,i=b.pay_income(.02,.0002)
        self.assertEqual(d,-.02); self.assertAlmostEqual(i,.06)
        self.assertAlmostEqual(b.cash,300.04)
    def test_tax_conservation(self):
        auction=CallAuction(0,transaction_tax=.01)
        a,b=Agent('a',1000,0),Agent('b',0,10)
        atomic_settle([Trade(1,'a','b',2,100)],dict(a=a,b=b),auction)
        self.assertEqual((a.cash,b.cash,auction.tax_collected),(798,198,4))
    def test_income_timing(self):
        a=Agent('a',100,1); a.pay_income(.02,.0002)
        self.assertAlmostEqual(a.cash,100.04)
    def test_invalid_income_and_maintenance(self):
        a=Agent('a',1500,-10,allow_short=True)
        with self.assertRaises(MarginBreach): a.check_maintenance(120)
        for d,r in [(-1,0),(0,-1),(float('nan'),0)]:
            with self.assertRaises(ValueError): a.pay_income(d,r)

class AuctionTests(unittest.TestCase):
    def test_market_orders_respect_band_and_limits(self):
        for orders in [[Order('a','buy',1),Order('b','sell',1,150)], [Order('a','buy',1,50),Order('b','sell',1)],[Order('a','buy',1,200),Order('b','sell',1,200)]]:
            p,v,tr=CallAuction(0).match(1,orders,100)
            self.assertEqual((p,v,tr),(100,0,[]))
    def test_tick(self):
        p,v,tr=CallAuction(0).match(1,[Order('a','buy',1,100.1),Order('b','sell',1,100)],100)
        self.assertEqual(p,100); self.assertEqual(v,1)
    def test_faithful_core_adapter(self):
        rng=np.random.default_rng(891)
        for i in range(100):
            orders=[Order(str(j),'buy' if j%2 else 'sell',int(rng.integers(1,40)),float(rng.uniform(75,125))) for j in range(8)]
            p,v,tr=CallAuction(i).match(1,orders,100)
            core=CallAuctionMarket(rng=np.random.default_rng(i))
            cp,ct,_=core.clear([CoreOrder(o.agent_id,o.side,o.quantity,o.limit_price,1) for o in orders],100,1)
            self.assertEqual(p,cp); self.assertEqual(v,sum(t.quantity for t in ct))
            self.assertEqual([dataclasses.asdict(t) for t in tr],[dataclasses.asdict(t) for t in ct])
    def test_self_crossing_and_duplicate(self):
        for orders in [[Order('a','buy',1,101),Order('a','sell',1,100)],[Order('a','buy',1,100),Order('a','buy',2,100)]]:
            with self.assertRaises(ValueError): CallAuction(0).match(1,orders,100)
    def test_dividends_uniform_and_independent(self):
        a,b=DecoupledAsset(7),DecoupledAsset(7)
        values=[a.draw_dividend() for _ in range(100)]
        np.random.default_rng(4).random(12345)
        self.assertEqual(values,[b.draw_dividend() for _ in range(100)])
        self.assertTrue(all(.016<=v<=.024 for v in values))

class AgentTests(unittest.TestCase):
    def trader(self,client=None): return RepairedLLMTrader('a',1000,10,None,dict(name='Mock',age=30,occupation='tester',horizon='long',bias_clauses='test bias'),client)
    def test_forum_history_and_outcomes_reach_prompt(self):
        a=self.trader(); base=a._build_prompt(observation(),100)
        for obs,marker in [(observation(bbs_posts=['UNIQUE_POST']),'UNIQUE_POST'),(observation(own_outcomes=[{'reason':'UNIQUE_FILL'}]),'UNIQUE_FILL')]:
            p=a._build_prompt(obs,100); self.assertNotEqual(p,base); self.assertIn(marker,p)
        self.assertNotEqual(a._build_prompt(observation(price_history=[80,90,100]),100),base)
        self.assertIn('test bias',base); self.assertNotIn('total_rounds',base)
    def test_strict_schema(self):
        a=self.trader(); valid=dict(action='buy',quantity=2,limit_price=100,reasoning='test')
        for change in [dict(quantity=2.9),dict(quantity=2.),dict(quantity=True),dict(quantity='2'),dict(limit_price=-1),dict(limit_price='100'),dict(reasoning=None),dict(action='hold',quantity=True,limit_price=-1)]:
            self.assertEqual(a.parse_decision(json.dumps(valid|change)).status,'error')
        for raw in ['{}','[]','null','{"action":"buy","action":"hold"}',json.dumps(valid|{'quantity':float('nan')})]:
            self.assertEqual(a.parse_decision(raw).status,'error')
        self.assertEqual(a.parse_decision(json.dumps(valid)).status,'valid')
    def test_failure_and_raw_reset(self):
        calls=0
        def policy(messages):
            nonlocal calls
            calls+=1
            if calls==2: raise TimeoutError('fixture interruption')
            return json.dumps(dict(action='buy',quantity=1000,limit_price=100,reasoning='test'))
        client=FixtureClient(policy); a=self.trader(client)
        o=a.decide(observation()); self.assertEqual(o.status,'clipped'); self.assertEqual(a.last_status,'clipped')
        self.assertEqual(a.last_requested_order['quantity'],1000); self.assertEqual(o.quantity,10)
        o=a.decide(observation()); self.assertEqual(o.status,'missing'); self.assertIsNone(a.last_raw_response)
        self.assertEqual(len(client.request_ledger),2); self.assertIsNone(client.request_ledger[0]['usage'])
    def test_live_boundary_closed(self):
        with self.assertRaises(LiveCollectionClosed): RepairedResilientClient(api_key='dummy')

class WealthTests(unittest.TestCase):
    def test_totals_and_maker_fixed(self):
        for seed in [0,42,31991]:
            for profile in ['equal','heterogeneous','cash_only']:
                values=endowments(seed,profile)
                self.assertEqual(values[0],(30000,150))
                self.assertEqual(math.fsum(c for c,s in values),160000)
                self.assertEqual(sum(s for c,s in values),1450)
    def test_reproducible_and_assignment(self):
        values=endowments(42,'heterogeneous')
        self.assertEqual(values,endowments(42,'heterogeneous'))
        self.assertEqual(sorted(values[1:]),sorted(endowments(42,'heterogeneous',assignment=1)[1:]))
        self.assertNotEqual(values,endowments(42,'heterogeneous',assignment=1))
        self.assertGreater(gini([c+s*100 for c,s in values[1:]]),0)
    def test_sigma_zero_and_cash_only(self):
        self.assertEqual(endowments(42,'equal'),endowments(42,'heterogeneous',sigma=0))
        self.assertEqual([s for c,s in endowments(42,'cash_only')][1:],[100]*13)

class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.output=ROOT/'runs'/('test_'+uuid.uuid4().hex)
    def test_mock_factorial_and_logged_accounting(self):
        for wealth in ['equal','heterogeneous','cash_only']:
            for short in [False,True]:
                for forum in [False,True]:
                    path=run_mock(Config(rounds=10,wealth=wealth,allow_short=short,forum=forum),self.output/f'{wealth}_{short}_{forum}')
                    m=json.loads((path/'manifest.json').read_text()); self.assertEqual(m['status'],'complete')
                    self.assertEqual(m['provider_requests'],0); self.assertEqual(m['mock_decisions'],60)
                    rows=[json.loads(x) for x in (path/'ledger.jsonl').read_text(encoding='utf-8').splitlines()]
                    self.assertEqual(len([r for r in rows if r['kind']=='mock']),60)
                    for r in rows:
                        if r['kind']=='round':
                            self.assertLessEqual(abs(r['cash_residual']),1e-7)
                            self.assertEqual(sum(a['shares'] for a in r['closing'].values()),1450)
                            if not short: self.assertTrue(all(a['shares']>=0 for a in r['closing'].values()))
                    self.assertEqual(hashlib.sha256((path/'ledger.jsonl').read_bytes()).hexdigest(),m['artifacts_sha256']['ledger.jsonl'])
                    self.assertEqual(verify(path)['account_rounds'],140)
    def test_partial_failure_is_persisted(self):
        path=self.output/'failure'
        with self.assertRaises(RuntimeError): run_mock(Config(rounds=2),path,lambda m:'{}')
        m=json.loads((path/'manifest.json').read_text()); self.assertEqual(m['status'],'stopped'); self.assertEqual(m['completed_rounds'],0)
        self.assertTrue((path/'ledger.jsonl').read_text())
    def test_100_round_mock_support(self):
        path=run_mock(Config(rounds=100,wealth='heterogeneous',forum=True),self.output/'long_mock')
        self.assertEqual(verify(path)['account_rounds'],1400)
    def test_output_boundaries(self):
        with self.assertRaises(ValueError): run_mock(Config(),ROOT.parent/'bad')
        path=run_mock(Config(rounds=1),self.output/'exclusive')
        with self.assertRaises(FileExistsError): run_mock(Config(rounds=1),path)

if __name__=='__main__':
    with patch.object(socket,'create_connection',side_effect=RuntimeError('network forbidden in tests')),patch.object(socket.socket,'connect',side_effect=RuntimeError('network forbidden in tests')):
        suite=unittest.defaultTestLoader.loadTestsFromModule(__import__('__main__'))
        result=unittest.TextTestRunner(verbosity=2).run(suite)
        receipt=dict(status='passed' if result.wasSuccessful() else 'failed',tests_run=result.testsRun,
            failures=len(result.failures),errors=len(result.errors),
            mock_outputs=str(IntegrationTests.output.relative_to(ROOT)),
            evidence_type='OFFLINE_MOCK_NOT_BEHAVIORAL_DATA',provider_requests=0,
            source_sha256=source_hashes())
        target=IntegrationTests.output/'validation_receipt.json'
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(json.dumps(receipt,indent=2),encoding='utf-8')
        print('Validation receipt:',target)
        raise SystemExit(0 if result.wasSuccessful() else 1)
