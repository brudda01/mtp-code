"""Controlled endowment allocation, independent of agent decisions and dividends."""
import math
import numpy as np
from repaired_engine import integer, number

def allocate(total,weights):
    """Exact integer budget using largest remainders and stable index ties."""
    integer(total,'total',0)
    w=np.asarray(weights,dtype=float)
    if w.ndim!=1 or not len(w) or not np.all(np.isfinite(w)) or np.any(w<=0): raise ValueError('positive finite weights required')
    raw=w/w.sum()*total
    base=np.floor(raw).astype(int)
    for i in sorted(range(len(w)),key=lambda i: (-(raw[i]-base[i]),i))[:total-int(base.sum())]: base[i]+=1
    return [int(x) for x in base]

def endowments(seed,profile='equal',sigma=.7,assignment=0):
    """14-account resources: maker fixed at 30k/150, other 13 total 130k/1300.

    Heterogeneous weights scale both cash and shares. Cash-only sensitivity
    retains 100 shares each. Values are laboratory choices, not demographic fits.
    Assignment rotates the same wealth multiset across roles/personas.
    """
    integer(seed,'seed',0); integer(assignment,'assignment',0); number(sigma,'sigma')
    if profile not in ('equal','heterogeneous','cash_only') or sigma>2: raise ValueError('invalid profile/sigma')
    if profile=='equal': weights=np.ones(13)
    else: weights=np.random.default_rng(np.random.SeedSequence([seed,901])).lognormal(0,sigma,13)
    weights=np.roll(weights,assignment%13)
    cents=allocate(13000000,weights)
    shares=allocate(1300,weights) if profile=='heterogeneous' else [100]*13
    return [(30000.,150)]+[(c/100,q) for c,q in zip(cents,shares)]

def gini(values):
    x=sorted(values); n=len(x); total=math.fsum(x)
    return 0. if total==0 else 2*math.fsum((i+1)*v for i,v in enumerate(x))/(n*total)-(n+1)/n
