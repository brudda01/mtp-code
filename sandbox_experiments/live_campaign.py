"""One explicitly authorized sandbox-only campaign. Exclusive launch; no resume.

No main configuration, closure marker, frozen market or manuscript is changed.
"""
import sys
sys.dont_write_bytecode=True
from pathlib import Path
from datetime import datetime,timezone
import hashlib
import json
import os
import urllib.request
import urllib.error
import zipfile
from sandbox import ROOT,Config,_run_market,source_hashes
from delivery import BudgetedDelivery,campaign_budget
from one_time_provider_probe import NoRedirect
from sim.llm.client import dotenv_api_key

CAMPAIGN=ROOT/'runs'/'wealth_live_12llm_100round_60rpm'

def write_json(path,data):
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(data,indent=2,allow_nan=False),encoding='utf-8')
    temporary.replace(path)

def prepare():
    CAMPAIGN.mkdir(parents=True,exist_ok=False)
    configs=[Config(seed=seed,rounds=100,llm_count=12,wealth=wealth) for seed in (42,43) for wealth in ('equal','heterogeneous')]
    from dataclasses import asdict
    sources=source_hashes()
    with zipfile.ZipFile(CAMPAIGN/'source.zip','x',zipfile.ZIP_DEFLATED) as z:
        for name in sources: z.write(ROOT.parent/name,name)
    protocol=dict(status='authorized_prepared',authorization='User: go ahead with 60 rpm then. just run it in the background and then stop to conserve tokens.',
        scope='ONLY these four new sandbox markets; no main repo edits or restart/resume of any older root',
        created_utc=datetime.now(timezone.utc).isoformat(),configs=[asdict(c) for c in configs],
        planned_decisions=4800,max_http_attempts=6000,max_reserved_tokens=96000000,
        requests_per_minute=60,input_estimate_tokens_per_minute=60000,max_in_flight=1,
        model='deepseek/deepseek-v4.1-flash',endpoint='https://api.goedelmachines.com/v1',temperature=.3,thinking=False,max_tokens=2048,timeout_seconds=180,
        transport='Shared main pacer/budget; final persistent R058 retry bounds; no JSON repairs, model changes, replacement samples, automatic resumes or cap increases.',
        retention='Fictional persona records and simulated account histories are sent to existing Goedel endpoint; free/student retention policy applies. No billing/tier change.',
        source_sha256=sources,source_zip_sha256=hashlib.sha256((CAMPAIGN/'source.zip').read_bytes()).hexdigest())
    write_json(CAMPAIGN/'protocol.json',protocol)
    write_json(CAMPAIGN/'summary.json',dict(status='prepared',planned_markets=4,completed_markets=0,planned_decisions=4800))
    return protocol

class LiveClient(BudgetedDelivery):
    def __init__(self,key,log_fn,budget,opener=None):
        self.request_ledger=[]
        self.key=key
        self.opener=opener if opener is not None else urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
        self.context=None
        def log(record):
            self.request_ledger.append(record)
            log_fn(dict(timestamp_utc=datetime.now(timezone.utc).isoformat(),**record))
        self.wire_log=log_fn
        super().__init__(self.send,log,budget)
    def send(self,body):
        index=self.budget.requests
        # Durable pre-send entry allows interrupted in-flight requests to remain explicit.
        self.wire_log(dict(kind='wire_request',index=index,timestamp_utc=datetime.now(timezone.utc).isoformat(),request=body))
        req=urllib.request.Request('https://api.goedelmachines.com/v1/chat/completions',data=json.dumps(body).encode(),
            headers={'Authorization':'Bearer '+self.key,'Content-Type':'application/json'})
        try:
            response=self.opener.open(req,timeout=180)
        except urllib.error.HTTPError as exc:
            raw=exc.read(1024*1024).decode('utf-8',errors='replace').replace(self.key,'[REDACTED]')
            self.wire_log(dict(kind='wire_error',index=index,http_status=exc.code,raw_response=raw,
                retry_after=exc.headers.get('Retry-After') if exc.headers else None,timestamp_utc=datetime.now(timezone.utc).isoformat()))
            raise
        except Exception as exc:
            self.wire_log(dict(kind='wire_error',index=index,error_type=type(exc).__name__,timestamp_utc=datetime.now(timezone.utc).isoformat()))
            raise
        with response:
            raw=response.read().decode('utf-8').replace(self.key,'[REDACTED]')
            self.wire_log(dict(kind='wire_response',index=index,http_status=response.code,raw_response=raw,
                request_id=response.headers.get('x-request-id'),timestamp_utc=datetime.now(timezone.utc).isoformat()))
        return json.loads(raw)

def run():
    protocol=json.loads((CAMPAIGN/'protocol.json').read_text(encoding='utf-8'))
    for name,digest in protocol['source_sha256'].items():
        if hashlib.sha256((ROOT.parent/name).read_bytes()).hexdigest()!=digest: raise RuntimeError('frozen source changed: '+name)
    if hashlib.sha256((CAMPAIGN/'source.zip').read_bytes()).hexdigest()!=protocol['source_zip_sha256']: raise RuntimeError('source archive changed')
    # Atomic exclusive claim prevents duplicate workers, including after a stop.
    with (CAMPAIGN/'execution.json').open('x',encoding='utf-8') as f:
        json.dump(dict(pid=os.getpid(),started_utc=datetime.now(timezone.utc).isoformat()),f)
    budget=campaign_budget(protocol['max_http_attempts'],protocol['max_reserved_tokens'])
    summary=dict(status='running',pid=os.getpid(),completed_markets=0,planned_markets=4,markets=[])
    def save():
        summary['usage']=budget.snapshot()
        summary['updated_utc']=datetime.now(timezone.utc).isoformat()
        write_json(CAMPAIGN/'summary.json',summary)
    save()
    try:
        key=dotenv_api_key('GODEL_MACHINES_API_KEY')
        if not key: raise RuntimeError('Named Goedel credential unavailable')
        for raw_cfg in protocol['configs']:
            cfg=Config(**raw_cfg)
            market=CAMPAIGN/f's{cfg.seed}_{cfg.wealth}'
            summary.update(current_market=market.name,current_market_path=str(market)); save()
            def factory(log):
                def durable(record):
                    log(record)
                    if record.get('kind')=='delivery_attempt':
                        summary['last_attempt_status']=record.get('status')
                        summary['last_attempt_model']=(record.get('response') or {}).get('model')
                        summary['delivered_responses']=summary.get('delivered_responses',0)+(record.get('status')=='returned')
                        save()
                return LiveClient(key,durable,budget)
            _run_market(cfg,market,client_factory=factory)
            m=json.loads((market/'manifest.json').read_text())
            if m['status']!='complete': raise RuntimeError('market did not complete')
            summary['markets'].append(dict(path=market.name,completed_rounds=m['completed_rounds'],provider_requests=m['provider_requests']))
            summary['completed_markets']+=1; save()
        summary['status']='complete'
    except BaseException as exc:
        summary.update(status='stopped',error_type=type(exc).__name__,error=str(exc))
        # No continuation, restart, next market or cap amendment after failure.
    finally:
        save()

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser(); p.add_argument('action',choices=['prepare','run'])
    action=p.parse_args().action
    if action=='prepare':
        prepare(); print(CAMPAIGN)
    else: run()
