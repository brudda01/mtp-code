"""Synthetic probes of the three reported concerns; no empirical markets/API."""
from dataclasses import replace
import json
import math
from repaired_engine import RepairedMarginAgent as Agent,RepairedMarginFundamentalist,Order,Observation,atomic_settle,MarginBreach
from repaired_market_sim import CallAuction

def check():
    obs=Observation(2,10,[100.],[],.016,.0002,None,[],[],30000,100,0,40000,[])
    f=RepairedMarginFundamentalist('f',30000,100)
    values=[dict(dividend=d,proxy=d/.0002,side=f.decide(replace(obs,last_dividend=d)).side) for d in [.016,.024]]
    anchored=[f.decide(replace(obs,last_dividend=d,fundamental_hint=100)).side for d in [.016,.024]]
    a=Agent('short',1500,-10,allow_short=True)
    try:
        a.check_maintenance(120)
        margin='no breach'
    except MarginBreach as exc: margin=str(exc)
    a,b=Agent('a',math.nextafter(100.,-math.inf),0),Agent('b',0,1)
    accepted=a.validate_orders(Order('a','buy',1,100),100)[0]
    p,v,tr=CallAuction(0).match(1,[accepted,Order('b','sell',1,100)],100)
    try:
        atomic_settle(tr,dict(a=a,b=b))
        settlement='accepted'
    except ValueError as exc: settlement='ValueError: '+str(exc)
    return dict(noisy_proxy=values,anchored_sides=anchored,maintenance=margin,
        boundary=dict(initial_cash=math.nextafter(100.,-math.inf),accepted_quantity=accepted.quantity,
                      settlement=settlement,final_cash=a.cash,final_shares=a.shares))

if __name__=='__main__': print(json.dumps(check(),indent=2))
