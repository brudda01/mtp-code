"""Offline sandbox integration harness. Every model response is a labeled fixture.

No provider adapter, credentials, main launchers or scientific live collection.
All writes are confined to new directories under sandbox_experiments/.
"""
from dataclasses import dataclass, asdict, replace
from pathlib import Path
import hashlib
import json
import math
import uuid
import numpy as np
from repaired_engine import RepairedMarginAgent, RepairedMarginFundamentalist, Order, Observation, atomic_settle, MarginBreach, integer
from repaired_market_sim import CallAuction, DecoupledAsset
from repaired_llm_trader import RepairedLLMTrader
from repaired_client import FixtureClient
from wealth import endowments, gini
from personas import library

ROOT=Path(__file__).resolve().parent
POSTS={4:['Fictional forum rumor: traders expect a rally.'],
       5:['Fictional bullish opinion: buy and hold; price may rise.'],
       6:['Fictional bearish opinion: I expect prices to fall.'],
       7:['Fictional bearish opinion: I plan to sell.']}

@dataclass(frozen=True)
class Config:
    seed: int = 42
    rounds: int = 100
    llm_count: int = 12
    wealth: str = 'equal'
    sigma: float = .7
    assignment: int = 0
    allow_short: bool = False
    forum: bool = False
    def validate(self):
        integer(self.seed,'seed',0); integer(self.rounds,'rounds',1)
        if self.rounds>100: raise ValueError('mock integration limit is 100 sessions')
        integer(self.llm_count,'LLM count')
        if self.llm_count not in (6,12): raise ValueError('supported LLM counts are six or twelve')
        if type(self.allow_short) is not bool or type(self.forum) is not bool: raise ValueError('boolean switches required')
        endowments(self.seed,self.wealth,self.sigma,self.assignment,nonmaker_count=self.llm_count+7)

def fixture_policy(messages):
    """Deliberately simple input-sensitive test fixture, NOT LLM behavior evidence."""
    data=json.loads(messages[-1]['content']); obs=data['observation']; aid=data['persona']['name']
    session=obs['session']; posts=obs['public_forum_posts']
    side='sell' if any('bearish' in p for p in posts) else 'buy' if posts else ('buy' if session%2 else 'sell')
    quantity=3+(sum(map(ord,aid))%5)
    return json.dumps(dict(action=side,quantity=quantity,limit_price=None,reasoning='OFFLINE FIXTURE: deterministic integration exercise'))

def build_accounts(cfg,client):
    resources=endowments(cfg.seed,cfg.wealth,cfg.sigma,cfg.assignment,nonmaker_count=cfg.llm_count+7)
    seeds=np.random.SeedSequence([cfg.seed,902]).spawn(cfg.llm_count+8)
    ids=['maker']+[f'fund_{i}' for i in range(3)]+[f'mom_{i}' for i in range(2)]+[f'zi_{i}' for i in range(2)]+[f'llm_{i}' for i in range(cfg.llm_count)]
    personas=library(cfg.llm_count,cfg.seed)
    accounts={}
    for i,(aid,(cash,shares)) in enumerate(zip(ids,resources)):
        common=dict(rng=np.random.default_rng(seeds[i]),allow_short=cfg.allow_short and aid!='maker')
        if aid.startswith('llm'):
            a=RepairedLLMTrader(aid,cash,shares,persona=personas[i-8],client=client,**common)
        elif aid.startswith('fund'): a=RepairedMarginFundamentalist(aid,cash,shares,**common)
        else: a=RepairedMarginAgent(aid,cash,shares,**common)
        accounts[aid]=a
    return accounts

def rule_decision(a,obs):
    p=obs.price_history[-1]; aid=a.agent_id
    if aid=='maker':
        center=p*(1-.02*max(-1,min(1,(a.shares-150)/300)))
        quotes=[]
        if a.shares<300: quotes.append(Order(aid,'buy',min(10,300-a.shares),center*.995, 'maker bid'))
        if a.shares>0: quotes.append(Order(aid,'sell',min(10,a.shares),center*1.005,'maker ask'))
        return quotes or [Order(aid,'hold',0,reasoning='maker bounds')]
    if aid.startswith('fund'): return a.decide(obs)
    if aid.startswith('zi'):
        if a.rng.random()>.8: return Order(aid,'hold',0,reasoning='ZI inactive')
        return Order(aid,'buy' if a.rng.random()<.5 else 'sell',int(a.rng.integers(1,11)),p*a.rng.uniform(.9,1.1),'ZI fixture background')
    if len(obs.price_history)<=5: return Order(aid,'hold',0,reasoning='momentum warmup')
    trend=(p-obs.price_history[-6])/obs.price_history[-6]
    if abs(trend)<.005: return Order(aid,'hold',0,reasoning='weak trend')
    return Order(aid,'buy' if trend>0 else 'sell',max(1,int(abs(trend)*.5*200)),p*(1.02 if trend>0 else .98),'momentum')

def source_hashes():
    files=list(ROOT.glob('*.py'))+list((ROOT.parent/'starter_code'/'sim').rglob('*.py'))
    return {str(p.relative_to(ROOT.parent)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}

def run_mock(cfg,output=None,policy=fixture_policy):
    return _run_market(cfg,output,policy)

def _run_market(cfg,output=None,policy=fixture_policy,client_factory=None):
    """Shared financial loop; live access is gated by the separate live worker."""
    cfg.validate()
    path=Path(output).resolve() if output is not None else ROOT/'runs'/('mock_'+uuid.uuid4().hex)
    if not path.is_relative_to(ROOT) or path==ROOT or path.is_relative_to(ROOT/'history'): raise ValueError('output must be a new sandbox directory')
    path.mkdir(parents=True,exist_ok=False)
    live=client_factory is not None
    manifest=dict(status='running',evidence_type='LIVE_SANDBOX_MARKET' if live else 'OFFLINE_MOCK_NOT_BEHAVIORAL_DATA',config=asdict(cfg),source_sha256=source_hashes(),provider_requests=0)
    def save_manifest():
        (path/'manifest.json').write_text(json.dumps(manifest,indent=2,allow_nan=False),encoding='utf-8')
    save_manifest()
    rows=[]; outcomes={}; price_history=[100.]; volume_history=[]; client=None; start_requests=0
    try:
        with (path/'ledger.jsonl').open('x',encoding='utf-8') as ledger:
            def log(record):
                ledger.write(json.dumps(record,allow_nan=False,ensure_ascii=False)+'\n'); ledger.flush()
            client=client_factory(log) if live else FixtureClient(policy,log)
            start_requests=client.budget.requests if live else 0
            accounts=build_accounts(cfg,client)
            initial={aid:dict(cash=a.cash,shares=a.shares,avg_cost=a.avg_cost,
                        wealth=a.wealth(100),allow_short=a.allow_short,type=type(a).__name__) for aid,a in accounts.items()}
            initial_total=math.fsum(a.cash for a in accounts.values()); total_shares=sum(a.shares for a in accounts.values())
            log(dict(kind='initial',accounts=initial))
            passive={aid:[a.cash,a.shares] for aid,a in accounts.items()}
            outcomes={aid:[] for aid in accounts}
            asset=DecoupledAsset(np.random.SeedSequence([cfg.seed,904]))
            auction=CallAuction(np.random.SeedSequence([cfg.seed,905]))
            for rnd in range(1,cfg.rounds+1):
                p=price_history[-1]; opening={aid:dict(cash=a.cash,shares=a.shares) for aid,a in accounts.items()}
                orders=[]; accepted_by={}; requested_by={}
                for aid,a in accounts.items():
                    obs=Observation(rnd,cfg.rounds,list(price_history),list(volume_history),asset.dividend_history[-1] if asset.dividend_history else .02,
                        .0002,None,POSTS.get(rnd,[]) if cfg.forum else [],[],a.cash,a.shares,a.get_required_collateral(p),a.wealth(p),[],outcomes[aid][-5:])
                    if isinstance(a,RepairedLLMTrader):
                        accepted=[a.decide(obs)]; requested=a.last_requested_order
                        log(dict(kind='decision',round=rnd,agent=aid,raw=a.last_raw_response,requested=requested,accepted=[asdict(o) for o in accepted]))
                        if accepted[0].status in ('missing','error'): raise RuntimeError(f'missing/invalid decision for {aid}; stop without auction')
                    else:
                        dec=rule_decision(a,obs); requested=[asdict(o) for o in (dec if isinstance(dec,list) else [dec])]
                        accepted=a.validate_orders(dec,p)
                        log(dict(kind='decision',round=rnd,agent=aid,requested=requested,accepted=[asdict(o) for o in accepted]))
                    orders.extend(accepted); requested_by[aid]=requested; accepted_by[aid]=[asdict(o) for o in accepted]
                clearing,volume,trades=auction.match(rnd,orders,p)
                log(dict(kind='auction',round=rnd,price=clearing,volume=volume,trades=[asdict(t) for t in trades]))
                atomic_settle(trades,accounts,auction)
                if volume!=sum(t.quantity for t in trades): raise ArithmeticError('volume mismatch')
                div=asset.draw_dividend()
                # Stage income for all accounts before committing any payout.
                income={aid:(a.shares*div,a.cash*.0002) for aid,a in accounts.items()}
                expected={aid:a.cash+sum(income[aid]) for aid,a in accounts.items()}
                if any(not math.isfinite(c) or c<0 for c in expected.values()): raise MarginBreach('income insolvency')
                closing={}
                for aid,a in accounts.items():
                    di,interest=a.pay_income(div,.0002)
                    if abs(a.cash-expected[aid])>1e-7: raise ArithmeticError('individual cash residual')
                    passive[aid][0]=passive[aid][0]*(1+.0002)+passive[aid][1]*div
                    bought=sum(t.quantity for t in trades if t.buyer_id==aid); sold=sum(t.quantity for t in trades if t.seller_id==aid)
                    if a.shares!=opening[aid]['shares']+bought-sold: raise ArithmeticError('individual share residual')
                    expected_cash=opening[aid]['cash']+(sold-bought)*clearing+di+interest
                    if abs(a.cash-expected_cash)>1e-7: raise ArithmeticError('individual cash audit')
                    closing[aid]=dict(cash=a.cash,shares=a.shares,avg_cost=a.avg_cost,wealth=a.wealth(clearing),dividend_income=di,interest_income=interest,
                        collateral=a.get_required_collateral(clearing),maintenance=a.get_required_collateral(clearing,a.maint_margin_ratio))
                    outcomes[aid].append(dict(round=rnd,requested=requested_by[aid],accepted=accepted_by[aid],executed_buys=bought,executed_sells=sold,
                        opening=opening[aid],closing=closing[aid]))
                cash=math.fsum(a.cash for a in accounts.values())
                before=math.fsum(v['cash'] for v in opening.values())
                error=cash-before-total_shares*div-math.fsum(v[1] for v in income.values())
                if abs(error)>1e-7 or sum(a.shares for a in accounts.values())!=total_shares: raise ArithmeticError('aggregate cash/share audit')
                row=dict(kind='round',round=rnd,opening=opening,closing=closing,price=clearing,volume=volume,dividend=div,cash_residual=error)
                log(row); rows.append(row); price_history.append(clearing); volume_history.append(volume)
                for a in accounts.values(): a.check_maintenance(clearing)
            endpoints={}
            for aid,a in accounts.items():
                base=initial[aid]['wealth']
                endpoints[aid]=dict(final_cash=a.cash,final_shares=a.shares,
                    auction_excess_pp=100*(a.wealth(price_history[-1])-(passive[aid][0]+passive[aid][1]*price_history[-1]))/base,
                    reference_excess_pp=100*(a.wealth(100)-(passive[aid][0]+passive[aid][1]*100))/base)
            log(dict(kind='endpoints',accounts=endpoints))
            manifest.update(status='complete',completed_rounds=len(rows),initial_cash=initial_total,initial_shares=total_shares,
                initial_nonmaker_wealth_gini=gini([v['wealth'] for k,v in initial.items() if k!='maker']),
                **({'delivered_provider_responses':sum(r.get('status')=='returned' for r in client.request_ledger)} if live else {'mock_decisions':len(client.request_ledger)}),financial_account_rounds=len(rows)*len(accounts))
    except Exception as exc:
        manifest.update(status='stopped',completed_rounds=len(rows),error=type(exc).__name__+': '+str(exc))
        raise
    finally:
        if live and client is not None:
            manifest.update(provider_requests=client.budget.requests-start_requests,usage_budget_campaign_snapshot=client.budget.snapshot())
        manifest['artifacts_sha256']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in path.iterdir() if p.is_file() and p.name!='manifest.json'}
        save_manifest()
    return path
