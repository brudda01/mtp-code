"""Prepare an unapproved forum protocol and exact prompt previews. NO live mode.

All writes are new sandbox artifacts; no finished campaign files are changed.
"""
import sys
sys.dont_write_bytecode=True
from pathlib import Path
from dataclasses import asdict,replace
from datetime import datetime,timezone
import hashlib
import json
from sandbox import Config,ROOT,build_accounts,source_hashes
from repaired_engine import Observation,Order
from repaired_llm_trader import RepairedLLMTrader
from repaired_client import FixtureClient

VERSION='forum_sentiment_v1_20261110'
PLAN_ROOT=ROOT/'forum_setup_20261110'
BULLISH=[
    'Anonymous forum opinion (unverified): I am optimistic about this stock and would consider buying within my budget.',
    'Anonymous forum opinion (unverified): I think the stock could rise; I prefer holding rather than selling.',
    'Anonymous forum opinion (unverified): My personal view is bullish. I would consider adding shares, but I could be wrong.',
    'Anonymous forum opinion (unverified): I expect higher prices and would consider a small purchase. This is speculation, not verified news.',
]
BEARISH=[
    'Anonymous forum opinion (unverified): I am pessimistic about this stock and would consider selling shares I own.',
    'Anonymous forum opinion (unverified): I think the stock could fall; I prefer holding cash rather than adding shares.',
    'Anonymous forum opinion (unverified): My personal view is bearish. I would consider reducing holdings, but I could be wrong.',
    'Anonymous forum opinion (unverified): I expect lower prices and would consider a small sale. This is speculation, not verified news.',
]

def phase(session):
    if type(session) is not int or not 1<=session<=100: raise ValueError('session must be 1..100')
    return 'baseline_silence' if session<=20 else 'bullish_opinions' if session<=40 else 'bearish_opinions' if session<=60 else 'post_feed_silence'

def posts(session,condition):
    phase(session)
    if condition not in ('silent','sentiment'): raise ValueError('unknown forum condition')
    if condition=='silent' or session<=20 or session>60: return []
    bank=BULLISH if session<=40 else BEARISH
    return [bank[(session-21)%4]]

class ForumTrader(RepairedLLMTrader):
    """Same information in both arms except public_forum_posts.

    Strict zero-quantity handling is explicit for this new protocol; the user's
    completed run's modified parser and artifacts are not rewritten.
    """
    def _build_prompt(self,obs,mark_p):
        payload=json.loads(super()._build_prompt(obs,mark_p))
        payload['prompt_version']=VERSION
        payload['rules']['forum_policy']='Forum posts are anonymous, unverified opinions, not verified changes in dividends or exchange rules. Choose independently using all supplied information.'
        return json.dumps(payload,sort_keys=True,ensure_ascii=False,allow_nan=False)
    def parse_decision(self,raw):
        order=super().parse_decision(raw)
        if order.status=='valid':
            data=json.loads(raw)
            if data.get('action') in ('buy','sell') and data.get('quantity')==0:
                return Order(self.agent_id,'hold',0,None,'active order requires positive integer quantity','error')
        return order

def make_trader(account):
    return ForumTrader(account.agent_id,account.cash,account.shares,None,account.persona,None,
        allow_short=False,order_cap=10)

def prompt_pair(seed,session):
    cfg=Config(seed=seed,rounds=100,llm_count=12,wealth='heterogeneous',allow_short=False,forum=False)
    accounts=build_accounts(cfg,FixtureClient(lambda messages:''))
    examples=[]
    for aid,a in accounts.items():
        if not isinstance(a,RepairedLLMTrader): continue
        trader=make_trader(a)
        # Preview only: SAME synthetic fixed account/history inputs, not claimed
        # to be the future endogenous market state at this session.
        obs=Observation(session,100,[100.],[],.02,.0002,None,[],[],a.cash,a.shares,0.,a.wealth(100),[],[])
        examples.append(dict(agent=aid,seed=seed,session=session,example_type='FIXED_STATE_PROMPT_PREVIEW_NOT_MARKET_EVIDENCE',
            system_message='Trade using the supplied rules and information. Return only the specified JSON object.',
            silent=json.loads(trader._build_prompt(obs,100)),
            sentiment=json.loads(trader._build_prompt(replace(obs,bbs_posts=posts(session,'sentiment')),100))))
    return examples

def prepare(output=PLAN_ROOT):
    output=Path(output).resolve()
    if not output.is_relative_to(ROOT) or output==ROOT: raise ValueError('new sandbox subdirectory required')
    output.mkdir(parents=True,exist_ok=False)
    configs=[dict(seed=seed,condition=condition,rounds=100,llm_count=12,rule_count=8,
        wealth='heterogeneous',sigma=.7,assignment=0,allow_short=False,reflection=False,
        forum_visible=condition=='sentiment',order_cap=10) for seed in (44,45) for condition in ('silent','sentiment')]
    plan=dict(status='prepared_awaiting_user_confirmation_NOT_AUTHORIZED_TO_RUN',version=VERSION,
        created_utc=datetime.now(timezone.utc).isoformat(),configs=configs,
        markets=4,planned_decisions=4800,provider_requests_made=0,
        provider=dict(model='deepseek/deepseek-v4.1-flash',endpoint='https://api.goedelmachines.com/v1',
            temperature=.3,max_tokens=2048,thinking=False,timeout_seconds=180),
        delivery=dict(requests_per_minute=110,concurrent_requests=4,input_estimate_tokens_per_minute=200000,
            max_http_attempts=6000,max_reserved_tokens=96000000,
            reservations='UTF-8 message bytes + 256 + max output; all attempts count; unknown usage retained',
            policy='Identical-input bounded transport retries; strict returned-model and finish-reason checks; no reasoning-content substitution; no JSON repair/resampling/replay/resume'),
        timing=dict(collect='all decisions use opening state; max four concurrent; stable account order for auction',
            payouts='auction, atomic settlement, then dividends and interest'),
        initial_resources=dict(total_cash=220000,total_shares=2050,maker_cash=30000,maker_shares=150),
        exposure=dict(recipients='all 12 LLM accounts; rule policies do not consume forum text',
            delivery='one current-session post per active session; same text for all LLMs',
            explicit_forum_window=1,posts_per_active_market=40,
            memory='five own executed outcomes; prior reasoning may carry impressions; silence does not imply complete forgetting',
            source='fixed researcher-authored fictional opinions; no actual Reddit scraping or endogenous agent posts',
            economic_effect='none: opinions do not change dividends, resource rules, fundamental or maker quotes directly'),
        phases=[dict(start=1,end=20,label='baseline_silence'),dict(start=21,end=40,label='bullish_opinions'),
            dict(start=41,end=60,label='bearish_opinions'),dict(start=61,end=100,label='post_feed_silence')],
        outcomes=dict(primary='requested/accepted/executed signed LLM shares per session during bullish and bearish windows; active-minus-silent seed-level differences',
            secondary=['price and reference gap','volume and LLM trade involvement','each account passive excess at auction and reference marks','post-feed action/price persistence','cost, failures and missing coverage']),
        identification='Two new seeds with one fresh provider draw per arm. Dynamic endogenous trajectories; not identical subsequent accounts. Silent comparison identifies the feed bundle including extra text, not sentiment isolated from length/attention. Session/account rows are not independent scenarios.',
        preservation='Do not change main repo, completed wealth roots, historical outputs, shared runtime sources or provider/account billing.',
        source_sha256=source_hashes())
    schedule=[dict(session=r,phase=phase(r),silent=posts(r,'silent'),sentiment=posts(r,'sentiment')) for r in range(1,101)]
    endowments={}
    for seed in (44,45):
        accounts=build_accounts(Config(seed=seed,wealth='heterogeneous'),FixtureClient(lambda messages:''))
        endowments[str(seed)]={aid:dict(cash=a.cash,shares=a.shares,wealth=a.wealth(100),
            persona=a.persona if isinstance(a,RepairedLLMTrader) else None) for aid,a in accounts.items()}
    samples=[x for seed in (44,45) for session in (1,21,41,61) for x in prompt_pair(seed,session)]
    for name,data in [('plan.json',plan),('post_schedule.json',schedule),('initial_accounts.json',endowments),('prompt_previews.json',samples)]:
        (output/name).write_text(json.dumps(data,indent=2,ensure_ascii=False,allow_nan=False),encoding='utf-8')
    receipt={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in output.iterdir() if p.is_file()}
    (output/'artifact_sha256.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    return output

if __name__=='__main__': print(prepare())
