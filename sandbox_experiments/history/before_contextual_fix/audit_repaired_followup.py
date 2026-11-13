"""Synthetic regression probes only; no live drivers, credentials or market paths.

python -B sandbox_experiments/audit_repaired_followup.py
"""
import dataclasses
import hashlib
import json
import socket
from pathlib import Path

def blocked(*args, **kwargs):
    raise RuntimeError('Network disabled for audit')
socket.socket = blocked
socket.create_connection = blocked

from repaired_engine import RepairedMarginAgent as Agent, Order, Trade, Observation, atomic_settle
from repaired_market_sim import CallAuction
from repaired_llm_trader import RepairedLLMTrader

results = {}
obs = Observation(4,16,[100.0],[0],.02,.0002,100,[],[],1000,10,0,2000,[])
t = RepairedLLMTrader('a',1000,10,None,dict(name='Mock',age=30,occupation='tester'),None)
silent = t._build_prompt(obs,100)
active = t._build_prompt(dataclasses.replace(obs,bbs_posts=['UNIQUE_TEST_POST_BUY']),100)
results['forum_prompts_identical'] = silent == active
results['forum_post_absent'] = 'UNIQUE_TEST_POST_BUY' not in active
results['price_history_ignored'] = silent == t._build_prompt(dataclasses.replace(obs,price_history=[80,90,100]),100)

p,v,tr = CallAuction(1).match(1,[Order('buyer','buy',1,None),Order('seller','sell',1,150)],100)
results['market_buy_violates_sell_limit'] = dict(price=p,ask=150,volume=v)
p,v,tr = CallAuction(1).match(1,[Order('buyer','buy',1,200),Order('seller','sell',1,200)],100)
results['price_band_not_enforced'] = dict(price=p,previous=100,expected_upper_bound=120)
p,v,tr = CallAuction(1).match(1,[Order('buyer','buy',1,100.1),Order('seller','sell',1,100)],100)
results['tick_not_enforced'] = dict(price=p,expected_tick=.1)

a,b = Agent('a',1000,0),Agent('b',0,1,allow_short=False)
tr = atomic_settle([Trade(1,'a','b',.5,100)],{'a':a,'b':b})
results['fractional_trade_cash_without_share_transfer'] = dict(executed=len(tr),buyer_cash=a.cash,buyer_shares=a.shares,seller_shares=b.shares)
a,b,c = Agent('a',100,0),Agent('b',0,1,allow_short=False),Agent('c',0,1,allow_short=False)
tr = atomic_settle([Trade(1,'a','b',1,100),Trade(1,'a','c',1,100)],dict(a=a,b=b,c=c))
results['batch_partially_settles'] = dict(executed=len(tr),buyer_cash=a.cash,buyer_shares=a.shares)
a,b,c = Agent('a',0,1,allow_short=False),Agent('b',100,0),Agent('c',0,1,allow_short=False)
tr = atomic_settle([Trade(1,'b','a',1,100),Trade(1,'a','c',1,100)],dict(a=a,b=b,c=c))
results['same_batch_sale_proceeds_finance_buy'] = dict(executed=len(tr),initial_buyer_cash=0)
a = Agent('a',1000,10)
tr = atomic_settle([Trade(1,'a','a',1,100)],dict(a=a))
results['self_trade_accepted'] = len(tr)
a = Agent('a',1800,-10)
orders = a.validate_orders(Order('a','buy',10,100),100)
results['fully_funded_short_cover_blocked'] = [dataclasses.asdict(o) for o in orders]
results['hold_bypasses_schema_checks'] = dataclasses.asdict(t.parse_decision('{"action":"hold","quantity":true,"limit_price":-1}'))
a = Agent('a',100,1)
a.pay_dividend(.02)
a.pay_risk_free_interest(.0002)
results['interest_paid_on_current_dividend'] = dict(actual_cash=a.cash,thesis_timing_cash=100*(1+.0002)+.02)

root = Path(__file__).resolve().parent
old = json.loads((root/'AUDIT_CHECKS.json').read_text())['evidence_sha256']
results['original_sandbox_files_changed_since_first_audit'] = [n for n,h in old.items() if hashlib.sha256((root/n).read_bytes()).hexdigest()!=h]
results['current_source_sha256'] = {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in root.glob('*repaired*.py')}
print(json.dumps(results,indent=2))
if '--save' in __import__('sys').argv:
    with (root/'REPAIRED_FOLLOWUP_CHECKS.json').open('x',encoding='utf-8') as f:
        json.dump(results,f,indent=2)
