"""
Fast Concurrent Delivery Client for Student Pass Tier.
Limits: 110 RPM, 4 Concurrent Requests, 200k TPM.
Fresh-only correction adapter. Historical fast_delivery.py is preserved.
Same pacing and retry policy; rejects every replay tape and incomplete/wrong-model replies.
"""
import sys
sys.dont_write_bytecode = True
from pathlib import Path
from datetime import datetime, timezone
import json
import time
import math
import threading
import urllib.request
import urllib.error

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "starter_code"))

from delivery import parse_retry_after
from one_time_provider_probe import NoRedirect
from sim.llm.usage import ProviderUnavailable

MODEL = "deepseek/deepseek-v4.1-flash"

def fast_retry_policy(exc, rate_used, ordinary_used):
    if isinstance(exc, urllib.error.HTTPError):
        after = parse_retry_after(exc.headers)
        if exc.code == 429:
            return ('rate_limit_429', max((after if after is not None else 2.) + 2., min(30., 2. * 1.5**rate_used))) if rate_used < 60 else None
        if exc.code in (502, 503, 504):
            return ('server_error', max(3., min(30., 2. * 1.5**ordinary_used))) if ordinary_used < 20 else None
        return None
    if isinstance(exc, urllib.error.URLError):
        return ('transport_error', max(2., min(20., 1.5 * 1.5**ordinary_used))) if ordinary_used < 20 else None
    return None

class FreshOnlyDelivery:
    """Thread-safe client supporting up to 4 concurrent workers at 110 RPM."""
    def __init__(self, key, log_fn, budget, tape=None, opener=None):
        self.key = key
        self.log_fn = log_fn
        self.budget = budget
        if tape is not None:
            raise ValueError("Replay disabled: correction requires fresh provider responses")
        self.cursor = 0
        self.lock = threading.Lock()
        self.opener = opener if opener is not None else urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def complete(self, messages, temperature=0.3, max_tokens=2048):
        body = dict(model=MODEL, messages=messages, temperature=temperature, max_tokens=max_tokens,
                    chat_template_kwargs={'thinking': False}, stream=False)

        # 2. Live Concurrent HTTP request with thread-safe rate limiter
        rate = ordinary = 0
        while True:
            record = dict(kind='delivery_attempt', request=body, usage=None)
            with self.lock:
                try:
                    record['reservation'] = self.budget.reserve(messages, max_tokens, 0., 0.)
                    record['pacing_wait_seconds'] = self.budget.pacer.acquire(record['reservation']['input_token_estimate'])
                    self.budget.ensure_provider_available()
                    req_index = self.budget.requests
                    self.log_fn(dict(kind='wire_request', index=req_index, timestamp_utc=datetime.now(timezone.utc).isoformat(), request=body))
                except Exception as exc:
                    record.update(status='blocked', error_type=type(exc).__name__)
                    self.log_fn(record)
                    raise

            retry = None
            success = False
            raw_content = None
            try:
                req = urllib.request.Request(
                    'https://api.goedelmachines.com/v1/chat/completions',
                    data=json.dumps(body).encode(),
                    headers={'Authorization': f'Bearer {self.key}', 'Content-Type': 'application/json'}
                )
                with self.opener.open(req, timeout=120) as resp:
                    raw = resp.read().decode('utf-8').replace(self.key, '[REDACTED]')
                    with self.lock:
                        self.log_fn(dict(kind='wire_response', index=req_index, http_status=resp.code,
                                         request_id=resp.headers.get('x-request-id'), timestamp_utc=datetime.now(timezone.utc).isoformat()))
                    data = json.loads(raw)

                record['response'] = data
                usage = data.get('usage', {})
                if all(type(usage.get(k)) is int and usage[k] >= 0 for k in ('prompt_tokens', 'completion_tokens', 'total_tokens')):
                    record['usage'] = dict(usage, source='provider')

                if data.get('model') != MODEL:
                    raise ValueError('unexpected response model')
                choice = data['choices'][0]
                if choice.get('finish_reason') != 'stop':
                    raise ValueError('incomplete response')
                raw_content = choice['message'].get('content')
                if not raw_content and 'reasoning_content' in choice['message']:
                    raw_content = choice['message']['reasoning_content']
                if not isinstance(raw_content, str) or not raw_content.strip():
                    raise ValueError('missing response content')

                success = True
                record['status'] = 'returned'
            except Exception as exc:
                record.update(status='error', error_type=type(exc).__name__, http_status=getattr(exc, 'code', None))
                retry = fast_retry_policy(exc, rate, ordinary)
                if retry:
                    record.update(retry_category=retry[0], retry_wait_seconds=retry[1])
                else:
                    with self.lock:
                        self.budget.stop_for_provider_error()

            with self.lock:
                self.budget.record(record['usage'], success, 0., 0.)
                self.log_fn(record)

            if success:
                return raw_content

            if retry is None:
                raise ProviderUnavailable('provider failure; no replacement sample')
            if retry[0] == 'rate_limit_429':
                rate += 1
            else:
                ordinary += 1
            print(f" [Retry {ordinary + rate}: {retry[0]} - waiting {retry[1]:.1f}s...]")
            time.sleep(retry[1])
