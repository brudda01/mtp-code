"""Sandbox accounts: no cash borrowing; conservative initial short collateral.

Cash includes collateral. New shorts reserve 150% at the upper price band,
without using sale proceeds. Closing maintenance is 130%; breach stops the run
without inventing forced fills. Covers may spend collateral they release.
"""
from __future__ import annotations
from dataclasses import dataclass, field, replace
from numbers import Integral, Real
import copy
import math
import numpy as np

def number(value, name, minimum=0, positive=False):
    if isinstance(value,bool) or not isinstance(value,Real) or not math.isfinite(value):
        raise ValueError(f'{name} must be finite numeric')
    if value<minimum or (positive and value==minimum): raise ValueError(f'invalid {name}')
    return float(value)

def integer(value,name,minimum=None):
    if isinstance(value,bool) or not isinstance(value,Integral) or (minimum is not None and value<minimum):
        raise ValueError(f'invalid integer {name}')
    return int(value)

@dataclass
class Order:
    agent_id: str
    side: str
    quantity: int
    limit_price: float | None = None
    reasoning: str = ''
    status: str = 'valid'

@dataclass
class Trade:
    round: int
    buyer_id: str
    seller_id: str
    quantity: int
    price: float

@dataclass
class Observation:
    round: int
    total_rounds: int
    price_history: list
    volume_history: list
    last_dividend: float
    risk_free_rate: float
    fundamental_hint: float | None
    bbs_posts: list
    order_book: list
    cash: float
    shares: int
    locked_collateral: float
    wealth: float
    peer_trades: list
    own_outcomes: list = field(default_factory=list)

class MarginBreach(RuntimeError): pass

class RepairedMarginAgent:
    def __init__(self,agent_id,cash,shares,rng=None,allow_short=False,
                 initial_margin_ratio=1.5,maint_margin_ratio=1.3,
                 initial_price=100.,price_band=.2,transaction_tax=0.):
        if not isinstance(agent_id,str) or not agent_id: raise ValueError('agent ID required')
        if type(allow_short) is not bool: raise ValueError('allow_short must be boolean')
        self.agent_id=agent_id; self.cash=number(cash,'cash'); self.shares=integer(shares,'shares')
        self.allow_short=allow_short
        self.initial_margin_ratio=number(initial_margin_ratio,'initial margin',1,True)
        self.maint_margin_ratio=number(maint_margin_ratio,'maintenance margin',1,True)
        if self.maint_margin_ratio>self.initial_margin_ratio: raise ValueError('maintenance exceeds initial margin')
        self.price_band=number(price_band,'band'); self.transaction_tax=number(transaction_tax,'tax')
        if self.price_band>=1 or self.transaction_tax>=1: raise ValueError('band/tax must be below one')
        self.last_mark=number(initial_price,'initial price',positive=True)
        self.avg_cost=self.last_mark if self.shares else 0.
        self.rng=rng if rng is not None else np.random.default_rng(0)
        self.recent_trades=[]
        if self.shares<0 and (not allow_short or self.cash<self.get_required_collateral(self.last_mark)):
            raise ValueError('initial short must be permitted and collateralized')

    def get_required_collateral(self,p,ratio=None):
        p=number(p,'mark',positive=True)
        r=self.initial_margin_ratio if ratio is None else number(ratio,'ratio',1,True)
        return max(0,-self.shares)*p*r
    def get_free_cash_at_price(self,p): return max(0.,self.cash-self.get_required_collateral(p))
    @property
    def free_cash(self): return self.get_free_cash_at_price(self.last_mark)
    def wealth(self,p): return self.cash+self.shares*number(p,'price',positive=True)

    def _add_shares(self,q,p):
        q=integer(q,'share delta'); p=number(p,'execution price',positive=True)
        old,new=self.shares,self.shares+q
        if not q: return
        if not new: self.avg_cost=0.
        elif not old or old*new<0: self.avg_cost=p
        elif old*q>0: self.avg_cost=(abs(old)*self.avg_cost+abs(q)*p)/abs(new)
        self.shares=new

    def validate_orders(self,decisions,mark_price):
        p=number(mark_price,'mark',positive=True); self.last_mark=p
        orders=[decisions] if isinstance(decisions,Order) else decisions
        if not isinstance(orders,list) or not orders: raise ValueError('nonempty order list required')
        seen=set()
        for o in orders:
            if not isinstance(o,Order) or o.agent_id!=self.agent_id: raise ValueError('invalid identity/type')
            integer(o.quantity,'quantity',0)
            if o.side not in ('buy','sell','hold'): raise ValueError('invalid side')
            if o.limit_price is not None: number(o.limit_price,'limit',positive=True)
            if o.status not in ('valid','clipped'): raise ValueError('failed decision in auction')
            if o.side=='hold' and (o.quantity or o.limit_price is not None): raise ValueError('invalid HOLD')
            if o.side in ('buy','sell'):
                if o.side in seen: raise ValueError('one quote per side required')
                seen.add(o.side)
        if len(seen)==2:
            if self.allow_short or self.shares<0: raise ValueError('two-sided quotes require long-only account')
            b=next(o for o in orders if o.side=='buy'); s=next(o for o in orders if o.side=='sell')
            if b.limit_price is None or s.limit_price is None or b.limit_price>=s.limit_price: raise ValueError('self crossing')
        hi=p*(1+self.price_band); checked=[]
        for o in orders:
            q=o.quantity
            if o.side=='buy':
                unit=(min(o.limit_price,hi) if o.limit_price is not None else hi)*(1+self.transaction_tax)
                # Existing collateral is released by a cover; residual shorts cannot increase on BUY.
                q=min(q,math.floor(self.cash/unit+1e-12))
            elif o.side=='sell':
                owned=max(0,self.shares)
                if not self.allow_short: q=min(q,owned)
                else:
                    free=max(0.,self.cash-self.get_required_collateral(hi))
                    def feasible(n): return max(0,n-owned)*hi*self.initial_margin_ratio+n*hi*self.transaction_tax<=free+1e-9
                    lo,upper=0,q
                    while lo<upper:
                        mid=(lo+upper+1)//2
                        if feasible(mid): lo=mid
                        else: upper=mid-1
                    q=lo
            checked.append(replace(o,quantity=q,side=o.side if q else 'hold',limit_price=o.limit_price if q else None,
                                   status='clipped' if q!=o.quantity else o.status))
        return checked

    def pay_income(self,dividend,rate):
        d=number(dividend,'dividend'); r=number(rate,'rate')
        di,interest=self.shares*d,self.cash*r
        cash=self.cash+di+interest
        if not math.isfinite(cash) or cash<0: raise MarginBreach(f'{self.agent_id}: insolvent income update')
        self.cash=cash
        return di,interest

    def check_maintenance(self,p):
        self.last_mark=number(p,'mark',positive=True)
        required=self.get_required_collateral(p,self.maint_margin_ratio)
        if self.cash+1e-7<required: raise MarginBreach(f'{self.agent_id}: maintenance {self.cash} < {required}')

class RepairedMarginFundamentalist(RepairedMarginAgent):
    def __init__(self,*args,max_trade_size=10,sensitivity=.5,**kwargs):
        super().__init__(*args,**kwargs)
        self.max_trade_size=integer(max_trade_size,'max trade',1)
        self.sensitivity=number(sensitivity,'sensitivity',positive=True)
    def decide(self,obs):
        p=obs.price_history[-1]
        f=obs.fundamental_hint if obs.fundamental_hint is not None else obs.last_dividend/obs.risk_free_rate
        gap=(f-p)/p
        if abs(gap)<.05: return Order(self.agent_id,'hold',0,reasoning='within valuation threshold')
        q=min(self.max_trade_size,max(1,int(abs(gap)*self.sensitivity*100)))
        return Order(self.agent_id,'buy' if gap>0 else 'sell',q,p*(1+max(-.05,min(.05,gap/2))),'valuation proxy')

def atomic_settle(trades,accounts,market=None):
    """Stage full batch before commit; reject resource errors, never skip matches.

    Uniform price, integer quantities, no self trades and no same-auction finance.
    New shorts reserve full initial collateral without counting sale proceeds.
    """
    trades=list(trades)
    if not trades: return []
    tax=number(getattr(market,'transaction_tax',0.),'tax')
    buys={k:0 for k in accounts}; sells=buys.copy()
    spend={k:0. for k in accounts}; receipts=spend.copy(); prices=set()
    for t in trades:
        integer(t.quantity,'trade quantity',1); number(t.price,'trade price',positive=True); integer(t.round,'round',1)
        if t.buyer_id==t.seller_id or t.buyer_id not in accounts or t.seller_id not in accounts: raise ValueError('unknown account/self trade')
        prices.add(t.price); buys[t.buyer_id]+=t.quantity; sells[t.seller_id]+=t.quantity
        spend[t.buyer_id]+=t.quantity*t.price*(1+tax); receipts[t.seller_id]+=t.quantity*t.price*(1-tax)
    if len(prices)!=1: raise ValueError('nonuniform settlement')
    p=next(iter(prices))
    for aid,a in accounts.items():
        if aid!=a.agent_id: raise ValueError('account mapping mismatch')
        number(a.cash,'opening cash'); integer(a.shares,'opening shares')
        if spend[aid]>a.cash+1e-7: raise ValueError('opening cash exceeded')
        newshort=max(0,sells[aid]-max(0,a.shares))
        if newshort and not a.allow_short: raise ValueError('short banned')
        if a.allow_short and sells[aid] and buys[aid]: raise ValueError('two-sided margin batch')
        if newshort:
            reserve=(max(0,-a.shares)+newshort)*p*a.initial_margin_ratio
            if reserve+spend[aid]+sells[aid]*p*tax>a.cash+1e-7: raise ValueError('opening collateral exceeded')
    staged={aid:copy.copy(a) for aid,a in accounts.items()}
    for a in staged.values(): a.recent_trades=list(a.recent_trades)
    for t in trades:
        staged[t.buyer_id]._add_shares(t.quantity,t.price*(1+tax)); staged[t.seller_id]._add_shares(-t.quantity,t.price)
        for aid,side in ((t.buyer_id,'buy'),(t.seller_id,'sell')):
            staged[aid].recent_trades=(staged[aid].recent_trades+[dict(round=t.round,side=side,quantity=t.quantity,price=t.price)])[-5:]
    for aid,a in staged.items():
        a.cash=accounts[aid].cash-spend[aid]+receipts[aid]
        if a.cash<0: raise ValueError('negative cash')
    fee=math.fsum(t.quantity*t.price*2*tax for t in trades)
    residual=math.fsum(a.cash for a in staged.values())+fee-math.fsum(a.cash for a in accounts.values())
    if abs(residual)>1e-7 or sum(a.shares for a in staged.values())!=sum(a.shares for a in accounts.values()): raise ArithmeticError('conservation failure')
    for aid,a in staged.items():
        accounts[aid].cash=a.cash; accounts[aid].shares=a.shares; accounts[aid].avg_cost=a.avg_cost; accounts[aid].recent_trades=a.recent_trades
    if market is not None: market.tax_collected+=fee
    return trades
