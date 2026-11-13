"""Six canonical personas plus six explicit sandbox-only additions.

New archetypes follow the earlier twelve-agent proposal, without attaching
wealth to occupation or silently duplicating the main six persona records.
"""
from repaired_market_sim import np
from sim.agents.personas import get_personas

EXTRA=[
    dict(name='Rohan DayTrader',age=25,occupation='crypto and options trader',risk_tolerance='very high',strategy_inclination='breakout trader',horizon='short',bias_clauses='You focus on recent price moves.',backstory='You buy breakouts and exit when momentum stalls.'),
    dict(name='Rohit QuantDev',age=31,occupation='software engineer',risk_tolerance='medium',strategy_inclination='trend analysis',horizon='medium',bias_clauses='',backstory='You examine numerical trends and prefer systematic decisions.'),
    dict(name='Kavita Lawyer',age=39,occupation='corporate lawyer',risk_tolerance='medium-low',strategy_inclination='contrarian valuation',horizon='medium-long',bias_clauses='',backstory='You question rapid unsupported price rises and compare valuation signals.'),
    dict(name='Ananya Director',age=52,occupation='nonprofit director',risk_tolerance='low',strategy_inclination='fundamentalist',horizon='long',bias_clauses='',backstory='You prioritize prudence, stable income and fair valuation.'),
    dict(name='Devendra Builder',age=45,occupation='real estate developer',risk_tolerance='medium-high',strategy_inclination='value opportunist',horizon='medium',bias_clauses='',backstory='You seek undervalued assets and trim positions when prices look extended.'),
    dict(name='Vijay Investor',age=62,occupation='angel investor',risk_tolerance='medium',strategy_inclination='liquidity provision',horizon='long',bias_clauses='',backstory='You consider buying during panics and selling during euphoria, subject to resources.'),
]

def library(count,seed):
    if count not in (6,12): raise ValueError('supported populations: six or twelve LLM personas')
    canonical=get_personas(6,np.random.default_rng(np.random.SeedSequence([seed,903])))
    return canonical+([dict(p) for p in EXTRA] if count==12 else [])
