"""User-authorized one-minute target-60-RPM probe. No markets/retries.

At most 60 minimal HTTP attempts, two in flight, starts paced one second apart.
Stop new requests after the first error. Exclusive output prevents repeat runs.
"""
import sys
sys.dont_write_bytecode=True
from pathlib import Path
import json
import time
import math
import threading
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timezone
import urllib.request
import urllib.error

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent/'starter_code'))
from sim.llm.client import dotenv_api_key
from sim.llm.usage import UsageBudget
from one_time_provider_probe import NoRedirect

def main():
    path=ROOT/'runs'/'provider_rpm60_probe_20261109_once'
    path.mkdir(parents=True,exist_ok=False)
    manifest=dict(status='preparing',authorization='User requested increase RPM and test around 60 RPM.',
        scope='at most 60 tiny requests, target 60 RPM, at most two in flight; no retries or market',
        started_utc=datetime.now(timezone.utc).isoformat(),evidence_type='EXTERNAL_RATE_PROBE_NOT_MARKET_DATA')
    target=path/'summary.json'
    def save(): target.write_text(json.dumps(manifest,indent=2,allow_nan=False),encoding='utf-8')
    save()
    key=dotenv_api_key('GODEL_MACHINES_API_KEY')
    if not key: raise RuntimeError('Named Goedel credential unavailable')
    budget=UsageBudget(max_requests=60,max_reserved_tokens=40000,requests_per_minute=60,input_tokens_per_minute=60000)
    lock=threading.Lock(); stop=threading.Event(); records=[]; active=0; peak=0
    started=time.monotonic()
    with (path/'events.jsonl').open('x',encoding='utf-8') as journal:
        def log(record):
            with lock:
                journal.write(json.dumps(record,allow_nan=False)+'\n'); journal.flush()
        def one(index):
            nonlocal active,peak
            if stop.is_set(): return
            body=dict(model='deepseek/deepseek-v4.1-flash',messages=[dict(role='user',content=f'Reply exactly OK. Test request {index:02d}.')],
                temperature=0,max_tokens=32,chat_template_kwargs={'thinking':False},stream=False)
            reservation=budget.reserve(body['messages'],32,0.,0.)
            wait=budget.pacer.acquire(reservation['input_token_estimate'])
            if stop.is_set(): return
            t=time.monotonic()
            with lock:
                active+=1; peak=max(peak,active)
            record=dict(index=index,start_seconds=t-started,request=body,reservation=reservation,pacing_wait_seconds=wait)
            log(dict(kind='request_started',**record))
            usage=None; success=False
            try:
                opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
                request=urllib.request.Request('https://api.goedelmachines.com/v1/chat/completions',data=json.dumps(body).encode(),
                    headers={'Content-Type':'application/json','Authorization':'Bearer '+key})
                try: response=opener.open(request,timeout=30)
                except urllib.error.HTTPError as exc: response=exc
                try:
                    record['http_status']=response.code
                    record['rate_limit_headers']={k:v for k,v in response.headers.items() if k.lower().startswith(('x-ratelimit','ratelimit','x-rate-limit')) or k.lower() in ('retry-after','x-request-id')}
                    raw=response.read(1024*1024).decode('utf-8',errors='replace').replace(key,'[REDACTED]')
                    try: data=json.loads(raw)
                    except ValueError: data=dict(response_text=raw)
                    record['response']=data
                finally: response.close()
                u=data.get('usage',{}) if isinstance(data,dict) else {}
                if all(type(u.get(k)) is int and u[k]>=0 for k in ('prompt_tokens','completion_tokens','total_tokens')):
                    usage=dict(u,source='provider')
                success=record['http_status']==200 and data.get('model') in ('deepseek/deepseek-v4.1-flash','deepseek-v4.1-flash') and data['choices'][0].get('finish_reason')=='stop' and data['choices'][0]['message'].get('content','').strip()=='OK'
                if not success: stop.set()
            except Exception as exc:
                stop.set(); record.update(error_type=type(exc).__name__,error=str(exc).replace(key,'[REDACTED]'))
            finally:
                budget.record(usage,success,0.,0.)
                record.update(success=success,end_seconds=time.monotonic()-started,latency_seconds=time.monotonic()-t)
                with lock: active-=1; records.append(record)
                log(dict(kind='request_finished',**record))
            return record
        manifest['status']='running'; save()
        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures=[executor.submit(one,i) for i in range(1,61)]
                for future in as_completed(futures):
                    r=future.result()
                    if r is not None and len(records)%10==0:
                        print(json.dumps(dict(completed=len(records),successful=sum(x['success'] for x in records),elapsed_seconds=round(time.monotonic()-started,2))),flush=True)
        finally:
            ordered=sorted(records,key=lambda r:r['start_seconds'])
            n=len(ordered); elapsed=time.monotonic()-started
            gaps=[b['start_seconds']-a['start_seconds'] for a,b in zip(ordered,ordered[1:])]
            manifest.update(status='complete' if n==60 and all(r['success'] for r in records) else 'stopped',
                http_attempts=n,successful=sum(r['success'] for r in records),http_429=sum(r.get('http_status')==429 for r in records),
                errors=sum(not r['success'] for r in records),elapsed_seconds=elapsed,peak_in_flight=peak,
                observed_start_rate_rpm=60*(n-1)/(ordered[-1]['start_seconds']-ordered[0]['start_seconds']) if n>1 else None,
                completion_throughput_rpm=60*n/elapsed if elapsed else None,
                minimum_start_interval_seconds=min(gaps) if gaps else None,
                mean_latency_seconds=sum(r['latency_seconds'] for r in records)/n if n else None,
                usage_budget=budget.snapshot(),finished_utc=datetime.now(timezone.utc).isoformat())
            save()
    print(json.dumps(manifest,indent=2))

if __name__=='__main__': main()
