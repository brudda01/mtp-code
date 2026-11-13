"""ONE user-requested availability/header probe, separate from closed markets.

Fixed exclusive output path prevents an accidental second execution. No retry,
redirect, market history or fictional persona is sent. Main closure stays closed.
"""
import sys
sys.dont_write_bytecode=True
from pathlib import Path
import json
import time
from datetime import datetime,timezone
import urllib.request
import urllib.error

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent/'starter_code'))
from sim.llm.client import dotenv_api_key
from sim.llm.usage import UsageBudget

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise RuntimeError('Redirect refused; no second provider request')

def main():
    output=ROOT/'runs'/'provider_limit_probe_20261109_once'
    output.mkdir(parents=True,exist_ok=False)
    record=dict(authorization='User explicitly requested one limit/availability test after reviewing pricing URL.',
        scope='one minimal provider POST; no retries, markets, or sustained/burst load test',
        evidence_type='EXTERNAL_AVAILABILITY_PROBE_NOT_MARKET_DATA',
        started_utc=datetime.now(timezone.utc).isoformat(),status='preparing',http_attempts=0)
    target=output/'result.json'
    def save(): target.write_text(json.dumps(record,indent=2,allow_nan=False),encoding='utf-8')
    save()
    budget=UsageBudget(max_requests=1,max_reserved_tokens=8192,requests_per_minute=10,input_tokens_per_minute=60000,stop_on_api_error=True)
    key=None
    started=time.monotonic()
    try:
        key=dotenv_api_key('GODEL_MACHINES_API_KEY')
        if not key: raise RuntimeError('Named Goedel credential unavailable')
        endpoint='https://api.goedelmachines.com/v1/chat/completions'
        body=dict(model='deepseek/deepseek-v4.1-flash',messages=[dict(role='user',content='Reply with exactly OK.')],
            temperature=0,max_tokens=32,chat_template_kwargs={'thinking':False},stream=False)
        record['request']=body; record['endpoint']=endpoint
        reservation=budget.reserve(body['messages'],body['max_tokens'],0.,0.)
        record['reservation']=reservation
        record['pacing_wait_seconds']=budget.pacer.acquire(reservation['input_token_estimate'])
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
        request=urllib.request.Request(endpoint,data=json.dumps(body).encode(),
            headers={'Content-Type':'application/json','Authorization':'Bearer '+key})
        record.update(status='request_started',http_attempts=1); save()
        response=None
        try:
            response=opener.open(request,timeout=180)
        except urllib.error.HTTPError as exc:
            response=exc
        try:
            record['http_status']=response.code
            # Allow-list only quota/request headers, never cookies/auth headers.
            record['rate_limit_headers']={k:v for k,v in response.headers.items()
                if k.lower().startswith(('x-ratelimit','ratelimit','x-rate-limit')) or k.lower() in ('retry-after','x-request-id')}
            raw=response.read(1024*1024).decode('utf-8',errors='replace')
            if key: raw=raw.replace(key,'[REDACTED]')
            try: record['response']=json.loads(raw)
            except ValueError: record['response_text']=raw
        finally: response.close()
        record['status']='returned' if record['http_status']==200 else 'provider_error'
        data=record.get('response',{})
        usage=data.get('usage') if isinstance(data,dict) else None
        valid=isinstance(usage,dict) and all(type(usage.get(k)) is int and usage[k]>=0 for k in ('prompt_tokens','completion_tokens','total_tokens'))
        budget.record(dict(usage,source='provider') if valid else None,record['http_status']==200,0.,0.)
    except Exception as exc:
        record.update(status='failed',error_type=type(exc).__name__)
        reason=str(exc)
        record['error']=reason.replace(key,'[REDACTED]') if key else reason
        if record['http_attempts']: budget.record(None,False,0.,0.)
    finally:
        record.update(elapsed_seconds=time.monotonic()-started,finished_utc=datetime.now(timezone.utc).isoformat(),usage_budget=budget.snapshot())
        save()
    print(json.dumps(record,indent=2,allow_nan=False))

if __name__=='__main__': main()
