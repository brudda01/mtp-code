"""Read-only adapters to the established thesis auction and bounded dividends."""
import sys
from pathlib import Path
import numpy as np
from repaired_engine import Order, Trade
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'starter_code'))
from sim.market import CallAuctionMarket, Order as CoreOrder
from sim.assets import Asset

class DecoupledAsset:
    def __init__(self,seed,mean_div=.02,noise_ratio=.2,rf_rate=.0002):
        self.rf_rate=rf_rate; self.mean_div=mean_div
        self.asset=Asset(dict(model='iid_permanent',dividend=dict(mean=mean_div,relative_noise=noise_ratio),risk_free=rf_rate),np.random.default_rng(seed))
        self.dividend_history=[]
    def draw_dividend(self):
        self.asset.open_round(len(self.dividend_history)+1)
        div=self.asset.draw_dividend(); self.dividend_history.append(div)
        return div

class CallAuction:
    def __init__(self,seed,tick=.1,price_band=.2,transaction_tax=0.):
        self.core=CallAuctionMarket(tick=tick,price_band=price_band,transaction_tax=transaction_tax,rng=np.random.default_rng(seed))
    @property
    def transaction_tax(self): return self.core.transaction_tax
    @property
    def tax_collected(self): return self.core.tax_collected
    @tax_collected.setter
    def tax_collected(self,value): self.core.tax_collected=value
    def match(self,round_num,orders,last_price):
        seen=set(); grouped={}
        for o in orders:
            if o.status not in ('valid','clipped'): raise ValueError('failed order in auction')
            if o.side in ('buy','sell'):
                key=(o.agent_id,o.side)
                if key in seen: raise ValueError('duplicate quote')
                seen.add(key); grouped.setdefault(o.agent_id,{})[o.side]=o
        for pair in grouped.values():
            if len(pair)==2:
                b,s=pair['buy'],pair['sell']
                if b.limit_price is None or s.limit_price is None or b.limit_price>=s.limit_price: raise ValueError('crossed self quotes')
        converted=[CoreOrder(o.agent_id,o.side,o.quantity,o.limit_price,round_num,o.reasoning) for o in orders]
        price,trades,_=self.core.clear(converted,last_price,round_num)
        return price,sum(t.quantity for t in trades),[Trade(t.round,t.buyer_id,t.seller_id,t.quantity,t.price) for t in trades]
