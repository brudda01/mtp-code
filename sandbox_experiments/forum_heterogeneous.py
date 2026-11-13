"""Heterogeneous-only forum setup using completed silent controls. NO live mode.

Reuses the completed run's prompt/parser unchanged. The old fresh-control
proposal remains preserved; this module prepares its narrower replacement.
"""
import sys
sys.dont_write_bytecode=True
from pathlib import Path
from dataclasses import replace
from datetime import datetime,timezone
import hashlib
import json
from sandbox import ROOT,Config,build_accounts,source_hashes
from repaired_client import FixtureClient
from repaired_llm_trader import RepairedLLMTrader
from repaired_engine import Observation
from forum_experiment import posts,phase

SETUP=ROOT/'forum_heterogeneous_setup_20261110'
CONTROL_ROOT=ROOT/'runs'/'wealth_live_12llm_100round_fast110'

def controls():
    """Check configurations/initial accounts/first prompt, not market outcomes."""
    result=[]
    for seed in (42,43):
        path=CONTROL_ROOT/f's{seed}_heterogeneous'
        manifest=json.loads((path/'manifest.json').read_text())
        cfg=Config(seed=seed,rounds=100,llm_count=12,wealth='heterogeneous',forum=False)
        from dataclasses import asdict
        if manifest.get('status')!='complete' or manifest.get('completed_rounds')!=100 or manifest['config']!=asdict(cfg):
            raise ValueError('historical control configuration/completion mismatch')
        accounts=build_accounts(cfg,FixtureClient(lambda m:''))
        initial=first=None
        with (path/'ledger.jsonl').open(encoding='utf-8') as f:
            for line in f:
                r=json.loads(line)
                if r['kind']=='initial': initial=r['accounts']
                if r['kind']=='delivery_attempt' and r.get('status')=='returned': first=r; break
        if initial is None or first is None: raise ValueError('missing control provenance')
        for aid,a in accounts.items():
            if initial[aid]['cash']!=a.cash or initial[aid]['shares']!=a.shares or initial[aid]['avg_cost']!=a.avg_cost:
                raise ValueError('initial financial state mismatch')
        a=accounts['llm_0']
        obs=Observation(1,100,[100.],[],.02,.0002,None,[],[],a.cash,a.shares,0.,a.wealth(100),[],[])
        expected=dict(role='user',content=a._build_prompt(obs,100))
        # Concurrent completion can return any account first; find llm_0 by persona.
        with (path/'ledger.jsonl').open(encoding='utf-8') as f:
            matched=False
            for line in f:
                r=json.loads(line)
                if r.get('kind')!='delivery_attempt': continue
                body=r.get('request',{})
                messages=body.get('messages',[])
                if len(messages)==2:
                    payload=json.loads(messages[1]['content'])
                    if payload['observation']['session']==1 and payload['persona']['name']==a.persona['name']:
                        if messages[1]!=expected or messages[0]['content']!='Trade using the supplied rules and information. Return only the specified JSON object.':
                            raise ValueError('historical initial prompt mismatch')
                        if body['model']!='deepseek/deepseek-v4.1-flash' or body['temperature']!=.3 or body['max_tokens']!=2048 or body['chat_template_kwargs']!={'thinking':False}:
                            raise ValueError('historical provider profile mismatch')
                        matched=True; break
            if not matched: raise ValueError('initial prompt not found')
        result.append(dict(seed=seed,path=str(path.relative_to(ROOT)),completed_rounds=100,
            config=manifest['config'],initial_accounts_match=True,initial_prompt_match=True,
            environment_seed=seed+904,allocation_seed=seed+905,
            file_sha256={name:hashlib.sha256((path/name).read_bytes()).hexdigest() for name in ('manifest.json','ledger.jsonl')}))
    return result

def previews(seed,session):
    accounts=build_accounts(Config(seed=seed,wealth='heterogeneous'),FixtureClient(lambda m:''))
    result=[]
    for aid,a in accounts.items():
        if not isinstance(a,RepairedLLMTrader): continue
        obs=Observation(session,100,[100.],[],.02,.0002,None,[],[],a.cash,a.shares,0.,a.wealth(100),[],[])
        silent=json.loads(a._build_prompt(obs,100))
        active=json.loads(a._build_prompt(replace(obs,bbs_posts=posts(session,'sentiment')),100))
        result.append(dict(agent=aid,seed=seed,session=session,kind='FIXED_STATE_PREVIEW_NOT_MARKET_DATA',silent=silent,active=active))
    return result

def prepare(output=SETUP):
    references=controls()
    output=Path(output).resolve()
    if not output.is_relative_to(ROOT) or output==ROOT: raise ValueError('new sandbox output required')
    output.mkdir(parents=True,exist_ok=False)
    plan=dict(status='setup_only_no_live_launch',version='heterogeneous_forum_historical_controls_v2',
        scope_confirmation='User confirmed heterogeneous wealth only; reuse completed no-post controls.',
        created_utc=datetime.now(timezone.utc).isoformat(),wealth='heterogeneous',sigma=.7,assignment=0,
        new_markets=[dict(seed=s,condition='posts',rounds=100,llm_count=12,rule_count=8,
            environment_seed=s+904,allocation_seed=s+905) for s in (42,43)],
        historical_controls=references,new_market_count=2,new_decisions=2400,new_control_calls=0,
        total_cash=220000,total_shares=2050,short_selling=False,reflection=False,order_cap=10,
        prompt='EXACT completed-control builder sandbox_outcomes_v1; only current public_forum_posts changes at identical input state. No added forum-policy instruction or version token in the model input.',
        parser='Match completed control parser, including BUY/SELL quantity zero normalized to HOLD; preserve raw responses so the distinction remains auditable.',
        provider=dict(model='deepseek/deepseek-v4.1-flash',temperature=.3,thinking=False,max_tokens=2048,timeout_seconds=120),
        delivery=dict(rpm=110,concurrent_requests=4,input_estimate_tpm=200000,max_http_attempts=3000,max_reserved_tokens=48000000),
        schedule=[dict(start=1,end=20,label='silent'),dict(start=21,end=40,label='bullish opinion'),
            dict(start=41,end=60,label='bearish opinion'),dict(start=61,end=100,label='no new posts')],
        limitations='Historical controls, not contemporaneous paired provider draws. Same seeds do not force identical model responses or pre-post histories. Report baseline differences and do not call total divergence a pure causal sentiment effect. No neutral-text control; extra text/attention is part of the intervention. No completed wealth outcomes analyzed during setup.',
        preservation='All new files inside sandbox; no main edits, no equal-wealth trials, no reruns/replays/resumes of completed controls.',
        source_sha256=source_hashes())
    allocation={}
    for seed in (42,43):
        accounts=build_accounts(Config(seed=seed,wealth='heterogeneous'),FixtureClient(lambda m:''))
        allocation[str(seed)]={aid:dict(cash=a.cash,shares=a.shares,wealth=a.wealth(100)) for aid,a in accounts.items()}
    files={'plan.json':plan,'initial_accounts.json':allocation,
        'post_schedule.json':[dict(session=r,phase=phase(r),posts=posts(r,'sentiment')) for r in range(1,101)],
        'prompt_previews.json':[p for s in (42,43) for r in (1,21,41,61) for p in previews(s,r)]}
    for name,data in files.items(): (output/name).write_text(json.dumps(data,indent=2,ensure_ascii=False,allow_nan=False),encoding='utf-8')
    checks={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in output.iterdir() if p.is_file()}
    (output/'artifact_sha256.json').write_text(json.dumps(checks,indent=2),encoding='utf-8')
    return output

if __name__=='__main__': print(prepare())
