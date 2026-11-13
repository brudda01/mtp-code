"""Shared main-repo pacing/budget classes; latest R058 retry policy.

No credentials or network transport is supplied here. The injectable transport
is exercised with synthetic replies/errors only until live collection is approved.
"""
import math
import re
import ssl
import time
from datetime import datetime,timezone
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError,URLError
import repaired_market_sim  # establishes read-only main-module path; no launcher
from sim.llm.usage import RequestPacer,UsageBudget,ProviderUnavailable

MODEL='deepseek/deepseek-v4.1-flash'

def parse_retry_after(headers,now=None):
    raw=(headers or {}).get('Retry-After'); delay=None
    if isinstance(raw,str):
        raw=raw.strip()
        try:
            if re.fullmatch(r'[0-9]+(?:\.[0-9]+)?',raw): delay=float(raw)
            else:
                date=parsedate_to_datetime(raw)
                if date.tzinfo is not None: delay=max(0.,(date-(now or datetime.now(timezone.utc))).total_seconds())
        except (ValueError,TypeError,OverflowError): pass
    return delay if delay is not None and math.isfinite(delay) and delay>=0 else None

def retry_policy(exc,rate_used,ordinary_used):
    if isinstance(exc,HTTPError):
        after=parse_retry_after(exc.headers)
        if exc.code==429:
            return ('rate_limit_429',max((after if after is not None else 2.)+3.,min(60.,3.*1.5**rate_used))) if rate_used<60 else None
        if exc.code in (502,503,504):
            return ('server',max(5.,min(60.,after if after is not None else 5.))) if ordinary_used<15 else None
        return None
    reason=getattr(exc,'reason',None)
    if isinstance(exc,(URLError,TimeoutError,ConnectionError)) and not isinstance(exc,ssl.SSLCertVerificationError) and not isinstance(reason,ssl.SSLCertVerificationError) and ordinary_used<1:
        return ('transport',2.)
    return None

def campaign_budget(max_requests=6000,max_reserved_tokens=96000000,requests_per_minute=60):
    return UsageBudget(max_requests=max_requests,max_reserved_tokens=max_reserved_tokens,
        requests_per_minute=requests_per_minute,input_tokens_per_minute=60000,stop_on_api_error=True)

class BudgetedDelivery:
    """Sequential delivery; caller must share one instance/budget across markets.

    transport(body) must return decoded raw response or raise a transport error.
    Every attempt is reserved, paced and journaled; retries keep identical inputs.
    """
    def __init__(self,transport,log_fn,budget=None,sleep=time.sleep):
        self.transport=transport; self.log_fn=log_fn
        self.budget=budget if budget is not None else campaign_budget()
        self.sleep=sleep

    def complete(self,messages,temperature=.3,max_tokens=2048):
        body=dict(model=MODEL,messages=messages,temperature=temperature,max_tokens=max_tokens,
                  chat_template_kwargs={'thinking':False},stream=False)
        rate=ordinary=0
        while True:
            record=dict(kind='delivery_attempt',request=body,usage=None)
            try:
                record['reservation']=self.budget.reserve(messages,max_tokens,0.,0.)
                record['pacing_wait_seconds']=self.budget.pacer.acquire(record['reservation']['input_token_estimate'])
                self.budget.ensure_provider_available()
            except Exception as exc:
                record.update(status='blocked',error_type=type(exc).__name__)
                self.log_fn(record); raise
            retry=None; success=False
            try:
                data=self.transport(body); record['response']=data
                usage=data.get('usage',{})
                if all(type(usage.get(k)) is int and usage[k]>=0 for k in ('prompt_tokens','completion_tokens','total_tokens')) and usage['total_tokens']>=usage['prompt_tokens']+usage['completion_tokens']:
                    record['usage']=dict(usage,source='provider')
                if data.get('model') not in (MODEL,'deepseek-v4.1-flash'): raise ValueError('unexpected returned model')
                choice=data['choices'][0]
                if choice.get('finish_reason')!='stop': raise ValueError('incomplete or unknown finish reason')
                raw=choice['message'].get('content')
                if not isinstance(raw,str) or not raw.strip(): raise ValueError('missing response content')
                success=True; record['status']='returned'
            except Exception as exc:
                record.update(status='error',error_type=type(exc).__name__,http_status=getattr(exc,'code',None))
                retry=retry_policy(exc,rate,ordinary)
                if retry: record.update(retry_category=retry[0],retry_wait_seconds=retry[1])
                else: self.budget.stop_for_provider_error()
            self.budget.record(record['usage'],success,0.,0.)
            self.log_fn(record)
            if success: return raw
            if retry is None: raise ProviderUnavailable('provider failure; no replacement sample')
            if retry[0]=='rate_limit_429': rate+=1
            else: ordinary+=1
            self.sleep(retry[1])
