"""Offline audit: saved CSV checks and synthetic unit cases; never imports live drivers.

Run from repo root: python -B sandbox_experiments/audit_saved.py
No markets, credentials, provider calls, or existing output writes.
"""
import ast
import csv
import hashlib
import json
import math
import socket
from collections import Counter
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
def blocked(*args, **kwargs):
    raise RuntimeError('Network disabled by audit')
socket.socket = blocked
socket.create_connection = blocked
import numpy as np
from prototype_engine import MarginAgent, MarginFundamentalist, Order, Trade, Observation, CallAuctionMarket, settle_with_short

def agent(cash=1000, shares=10, allow=True):
    return MarginAgent('a', cash, shares, np.random.default_rng(1), allow_short=allow)

out = {'scope': 'Saved evidence and synthetic unit cases only', 'cases': {}}
c = out['cases']
a = agent(shares=0)
a._add_shares(-10, 100)
a._add_shares(5, 120)
c['partial_short_cover_cost_basis'] = {'actual': a.avg_cost, 'expected_remaining_entry_basis': 100}
a = agent()
a._add_shares(-5, 120)
c['partial_long_sale_cost_basis'] = {'actual': a.avg_cost, 'expected': 100}
a = agent(shares=0)
a.cash, a.shares = 2000, -10
c['existing_short_not_reserved'] = {'accepted_new_short': a.validate_orders(Order('a', 'sell', 100), 100)[0].quantity,
    'cash': a.cash, 'existing_short': a.shares, 'required_ceiling_collateral_existing': 1800}
a = agent(shares=0)
a.shares = -10
c['buy_can_spend_short_collateral'] = a.validate_orders(Order('a', 'buy', 10, 100), 100)[0].quantity
a = agent(allow=False)
c['duplicate_sells_reuse_shares'] = [o.quantity for o in a.validate_orders([Order('a','sell',10,100),Order('a','sell',10,100)],100)]
a = agent()
c['wrong_agent_id_accepted'] = a.validate_orders(Order('someone_else','buy',1,100),100)[0].agent_id
c['negative_quantity_accepted'] = a.validate_orders(Order('a','buy',-5,100),100)[0].quantity
a = agent(shares=0)
f = MarginFundamentalist('f', 30000, 0, np.random.default_rng(1), allow_short=True)
obs = Observation(2, 10, [120.0], 0, .02, .0002, 100, [], [], 30000, 0, 0, 30000, [])
o = f.decide(obs)
c['fundamentalist_cannot_initiate_short'] = {'side': o.side, 'quantity': o.quantity,
    'mro': [t.__name__ for t in type(f).__mro__]}
a, b = agent(cash=1, shares=0), MarginAgent('b',0,1,np.random.default_rng(1),allow_short=False)
settle_with_short([Trade(1,'a','b',1,100)], {'a':a,'b':b}, CallAuctionMarket())
c['unfunded_settlement_passes_conservation'] = {'buyer_cash': a.cash,'seller_cash': b.cash}
a,b = agent(cash=1000,shares=0,allow=False), MarginAgent('b',0,0,np.random.default_rng(1),allow_short=False)
settle_with_short([Trade(1,'a','b',1,100)], {'a':a,'b':b}, CallAuctionMarket())
c['banned_short_settlement_passes'] = b.shares

# Extract only agent class ASTs. Do not execute live-module credential loaders.
out['mock_parser_cases'] = {}
for filename, classname in [('run_reddit_meme_experiment.py','SandboxLLMAgent'),
                             ('run_short_sale_live_comparison.py','LiveLLMTrader')]:
    tree = ast.parse((ROOT/filename).read_text(encoding='utf-8'))
    node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == classname)
    ns = dict(MarginAgent=MarginAgent, Observation=Observation, Order=Order, math=math,json=json)
    exec(compile(ast.Module(body=[node],type_ignores=[]),filename,'exec'), ns)
    class FakeClient:
        raw = ''
        def complete(self,*args,**kwargs):
            return self.raw
    client = FakeClient()
    persona = dict(name='Mock', age=30, occupation='test',risk_tolerance='low',strategy_inclination='test')
    trader = ns[classname]('a',1000,10,np.random.default_rng(1),persona,client)
    cases = {}
    for label, payload in [('fractional_quantity',dict(action='buy',quantity=2.9,limit_price=100)),
                           ('invalid_limit',dict(action='buy',quantity=2,limit_price=-1)),
                           ('empty_object',{}),('boolean_quantity',dict(action='buy',quantity=True,limit_price=100))]:
        client.raw = json.dumps(payload)
        order = trader.decide(obs)
        cases[label] = dict(side=order.side,quantity=order.quantity,limit_price=order.limit_price,reasoning=order.reasoning)
    out['mock_parser_cases'][filename] = cases

def rows(rel):
    with (ROOT/rel).open(encoding='utf-8', newline='') as f:
        return list(csv.DictReader(f))
market = rows('results/reddit_market.csv')
orders = rows('results/reddit_orders.csv')
comparison = rows('results_short_sale_comparison/market_comparison.csv')
out['reddit'] = {'rounds': len(market), 'orders': len(orders),
 'complete_six_per_round': all(Counter(int(o['round']) for o in orders)[r] == 6 for r in range(1,17)),
 'unique_round_agent_pairs':len({(o['round'],o['agent']) for o in orders}),
 'sides':dict(Counter(o['side'] for o in orders)),
 'fallback_rows': [o for o in orders if 'fallback' in o['reasoning'].lower()],
 'price_min':min(float(r['price']) for r in market),'price_max':max(float(r['price']) for r in market),
 'total_volume':sum(int(r['volume']) for r in market)}
out['comparison'] = {'rounds':len(comparison), 'max_short_interest': max(int(r['short_interest']) for r in comparison)}
for key in ('no_short','short_allowed'):
    p = [float(r['price_'+key]) for r in comparison]
    out['comparison'][key] = {'mean_price':sum(p)/len(p),'mean_absolute_gap_percent':sum(abs(x-100) for x in p)/len(p),
       'total_volume':sum(int(r['vol_'+key]) for r in comparison), 'zero_volume_rounds':sum(int(r['vol_'+key])==0 for r in comparison)}
out['source_parse'] = {}
for p in ROOT.glob('*.py'):
    ast.parse(p.read_text(encoding='utf-8'))
    out['source_parse'][p.name] = 'OK'
out['evidence_sha256'] = {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
 for p in ROOT.rglob('*') if p.is_file() and p.suffix in ('.py','.csv','.png') and p.name != Path(__file__).name}
result = json.dumps(out, indent=2)
if '--save' in sys.argv:
    with (ROOT/'AUDIT_CHECKS.json').open('x',encoding='utf-8') as f:
        f.write(result+'\n')
print(result)
