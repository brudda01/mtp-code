"""Authorized isolated forum campaign; no control rerun, tape replay or resume.

Reuses the completed concurrent market function WITHOUT invoking its destructive
campaign launcher. Only its in-memory post schedule is replaced for this worker.
"""
import sys
sys.dont_write_bytecode=True
from pathlib import Path
import json
import hashlib
import os
import threading
import zipfile
from datetime import datetime,timezone
from unittest.mock import patch
import urllib.request
from sandbox import ROOT,Config,source_hashes
from forum_heterogeneous import SETUP,controls
from forum_experiment import posts
import forum_market as existing_market
from live_campaign import LiveClient
from one_time_provider_probe import NoRedirect
from sim.llm.client import dotenv_api_key
from sim.llm.usage import UsageBudget

def safe_write_json(path, data):
    import time
    payload = json.dumps(data, indent=2, allow_nan=False)
    temporary = path.with_suffix(path.suffix + '.tmp')
    for attempt in range(10):
        try:
            temporary.write_text(payload, encoding='utf-8')
            temporary.replace(path)
            return
        except (PermissionError, OSError):
            time.sleep(0.05 * (attempt + 1))
    try:
        path.write_text(payload, encoding='utf-8')
    except Exception:
        pass

CAMPAIGN=ROOT/'runs'/'forum_heterogeneous_s42_s43_110rpm'

class LocalAttemptBudget:
    """Shared quota/pacer; a thread-local client's wire index uses its reservation.

    Prevents concurrent wire logs from reading another worker's request counter.
    """
    def __init__(self,shared): self.shared=shared; self.latest=0
    def reserve(self,*args):
        reservation=self.shared.reserve(*args); self.latest=reservation['reservation_id']
        return reservation
    @property
    def requests(self): return self.latest
    def __getattr__(self,name): return getattr(self.shared,name)

class TimeoutOpener:
    def __init__(self,opener=None):
        self.opener=opener or urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    def open(self,request,timeout): return self.opener.open(request,timeout=120)

class ConcurrentForumClient:
    def __init__(self,key,log,budget,opener_factory=None):
        self.key=key; self.log=log; self.budget=budget
        self.opener_factory=opener_factory or TimeoutOpener
        self.slots=threading.BoundedSemaphore(4)
    def complete(self,messages,**kwargs):
        with self.slots:
            client=LiveClient(self.key,self.log,LocalAttemptBudget(self.budget),self.opener_factory())
            return client.complete(messages,**kwargs)

class FinancialCheck:
    """Check each saved round without changing any prompt/outcome fields."""
    def __init__(self): self.initial=None; self.last=None; self.auction=None; self.count=0; self.passive={}
    def accept(self,r):
        if r['kind']=='initial':
            self.initial=r['accounts']; self.last={k:dict(cash=v['cash'],shares=v['shares']) for k,v in self.initial.items()}
            self.passive={k:[v['cash'],v['shares']] for k,v in self.initial.items()}
        elif r['kind']=='auction': self.auction=r
        elif r['kind']=='round':
            a=self.auction
            if a is None or a['round']!=r['round'] or r['round']!=self.count+1: raise ValueError('missing or nonsequential auction')
            if a['price']!=r['price'] or sum(t['quantity'] for t in a['trades'])!=r['volume']: raise ValueError('auction mismatch')
            for aid,start in self.last.items():
                if r['opening'][aid]!=start: raise ValueError('account continuity mismatch')
                buy=sum(t['quantity'] for t in a['trades'] if t['buyer_id']==aid)
                sell=sum(t['quantity'] for t in a['trades'] if t['seller_id']==aid)
                q=start['shares']+buy-sell
                cash=start['cash']+(sell-buy)*r['price']
                expected=cash*(1+.0002)+q*r['dividend']
                end=r['closing'][aid]
                if end['shares']!=q or abs(expected-end['cash'])>1e-7 or q<0 or end['cash']<0: raise ArithmeticError('account financial audit failed')
                self.passive[aid][0]=self.passive[aid][0]*(1+.0002)+self.passive[aid][1]*r['dividend']
            if sum(v['shares'] for v in r['closing'].values())!=2050: raise ArithmeticError('share conservation')
            self.last={k:dict(cash=v['cash'],shares=v['shares']) for k,v in r['closing'].items()}
            self.count+=1

def prepare():
    plan=json.loads((SETUP/'plan.json').read_text())
    # Verify the setup artifacts and historical controls before creating a root.
    expected=json.loads((SETUP/'artifact_sha256.json').read_text())
    for name,h in expected.items():
        if hashlib.sha256((SETUP/name).read_bytes()).hexdigest()!=h: raise ValueError('setup changed')
    refs=controls()
    if refs!=plan['historical_controls']: raise ValueError('historical controls changed')
    # Pin behavioral dependencies to the completed controls' recorded sources.
    dependencies=['sandbox.py','repaired_llm_trader.py','repaired_engine.py','repaired_market_sim.py','personas.py','wealth.py','run_fast_campaign.py']
    for ref in refs:
        manifest=json.loads((ROOT/ref['path']/'manifest.json').read_text())
        for name in dependencies:
            key=next(k for k in manifest['source_sha256'] if k.replace('\\','/')=='sandbox_experiments/'+name)
            if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=manifest['source_sha256'][key]: raise ValueError('control behavioral source changed: '+name)
    CAMPAIGN.mkdir(parents=True,exist_ok=False)
    protocol=dict(plan,authorization='User: all good to go? if yes, start it in background and then stop to conserve tokens.',
        status='authorized_prepared',source_sha256=source_hashes(),setup_plan_sha256=hashlib.sha256((SETUP/'plan.json').read_bytes()).hexdigest(),
        transport='Four workers; shared main pacer/budget at 110 RPM/200000 input-estimate TPM, strict returned model and stop finish reason; bounded identical-input retries; 120s timeout; no replay/resampling/JSON repair/resume.')
    with zipfile.ZipFile(CAMPAIGN/'source.zip','x',zipfile.ZIP_DEFLATED) as z:
        for n in protocol['source_sha256']: z.write(ROOT.parent/n,n)
    protocol['source_zip_sha256']=hashlib.sha256((CAMPAIGN/'source.zip').read_bytes()).hexdigest()
    safe_write_json(CAMPAIGN/'protocol.json',protocol)
    safe_write_json(CAMPAIGN/'summary.json',dict(status='prepared',planned_markets=2,planned_decisions=2400,completed_markets=0))
    return CAMPAIGN

def run():
    p=json.loads((CAMPAIGN/'protocol.json').read_text())
    for name,h in p['source_sha256'].items():
        if hashlib.sha256((ROOT.parent/name).read_bytes()).hexdigest()!=h: raise ValueError('frozen source changed')
    if hashlib.sha256((CAMPAIGN/'source.zip').read_bytes()).hexdigest()!=p['source_zip_sha256']: raise ValueError('archive changed')
    with (CAMPAIGN/'execution.json').open('x') as f: json.dump(dict(pid=os.getpid(),started_utc=datetime.now(timezone.utc).isoformat()),f)
    limits=p['delivery']
    budget=UsageBudget(max_requests=limits['max_http_attempts'],max_reserved_tokens=limits['max_reserved_tokens'],
        requests_per_minute=limits['rpm'],input_tokens_per_minute=limits['input_estimate_tpm'],stop_on_api_error=True)
    state=dict(status='running',pid=os.getpid(),planned_markets=2,planned_decisions=2400,completed_markets=0,delivered_responses=0,markets=[])
    lock=threading.Lock(); current_path=None; audit=None
    def save():
        try:
            state['usage']=budget.snapshot(); state['updated_utc']=datetime.now(timezone.utc).isoformat()
            safe_write_json(CAMPAIGN/'summary.json',state)
        except Exception: pass
    save()
    try:
        key=dotenv_api_key('GODEL_MACHINES_API_KEY')
        if not key: raise ValueError('named Goedel credential missing')
        for seed in (42,43):
            cfg=Config(seed=seed,wealth='heterogeneous',forum=True,rounds=100,llm_count=12)
            current_path=CAMPAIGN/f's{seed}_heterogeneous_posts'; audit=FinancialCheck()
            state.update(current_market=current_path.name,current_round=0); save()
            def on_record(record):
                with lock:
                    audit.accept(record)
                    if record.get('kind')=='delivery_attempt':
                        state['delivered_responses']+=record.get('status')=='returned'
                        state['last_attempt_status']=record.get('status')
                        state['last_model']=(record.get('response') or {}).get('model')
                        try: save()
                        except Exception: pass
                    elif record.get('kind')=='round':
                        state['current_round']=record['round']
                        try: save()
                        except Exception: pass
            def factory(log): return ConcurrentForumClient(key,log,budget)
            with patch.object(existing_market,'POSTS',{r:posts(r,'sentiment') for r in range(1,101)}):
                existing_market.run_concurrent_market(cfg,current_path,factory,on_record)
            manifest=json.loads((current_path/'manifest.json').read_text())
            manifest.update(evidence_type='LIVE_FORUM_HETEROGENEOUS',financial_account_rounds=audit.count*20,
                usage_campaign_snapshot=budget.snapshot(),historical_control=str((ROOT/p['historical_controls'][(0 if seed==42 else 1)]['path']).relative_to(ROOT)))
            manifest['artifacts_sha256']={'ledger.jsonl':hashlib.sha256((current_path/'ledger.jsonl').read_bytes()).hexdigest()}
            safe_write_json(current_path/'manifest.json',manifest)
            state['markets'].append(dict(path=current_path.name,completed_rounds=audit.count)); state['completed_markets']+=1; save()
        state['status']='complete'
    except BaseException as exc:
        state.update(status='stopped',error_type=type(exc).__name__,error=str(exc))
        if current_path is not None and (current_path/'manifest.json').exists():
            m=json.loads((current_path/'manifest.json').read_text()); m.update(status='stopped',completed_rounds=audit.count if audit else 0,error_type=type(exc).__name__)
            safe_write_json(current_path/'manifest.json',m)
    finally: save()

if __name__=='__main__':
    import argparse
    ap=argparse.ArgumentParser(); ap.add_argument('action',choices=['prepare','run'])
    if ap.parse_args().action=='prepare': print(prepare())
    else: run()
