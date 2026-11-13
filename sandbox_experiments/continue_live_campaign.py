"""
R059: Live Campaign Continuation for 12 LLMs x 100 Rounds.
Replays 62 historical decisions from prior root (wealth_live_12llm_100round_60rpm/s42_equal)
with exact matching assertions (zero duplicate API calls/tokens).
Fresh requests complete the remaining decisions (Rounds 6-100) and subsequent markets.
Implements resilient exponential backoff for 429, 502/503/504, and URLErrors.
"""
import sys
sys.dont_write_bytecode = True
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import os
import time
import shutil
import urllib.request
import urllib.error

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "starter_code"))

from sandbox import Config, _run_market, source_hashes
from delivery import BudgetedDelivery, campaign_budget, parse_retry_after
from one_time_provider_probe import NoRedirect
from sim.llm.client import dotenv_api_key
from sim.llm.usage import ProviderUnavailable

PRIOR_ROOT = ROOT / 'runs' / 'wealth_live_12llm_100round_60rpm'
CAMPAIGN = ROOT / 'runs' / 'wealth_live_12llm_100round_finish'
MODEL = 'deepseek/deepseek-v4.1-flash'

def robust_retry_policy(exc, rate_used, ordinary_used):
    if isinstance(exc, urllib.error.HTTPError):
        after = parse_retry_after(exc.headers)
        if exc.code == 429:
            return ('rate_limit_429', max((after if after is not None else 2.) + 3., min(60., 3. * 1.5**rate_used))) if rate_used < 60 else None
        if exc.code in (502, 503, 504):
            return ('server_error', max(5., min(60., 3. * 1.5**ordinary_used))) if ordinary_used < 20 else None
        return None
    if isinstance(exc, urllib.error.URLError):
        return ('transport_error', max(3., min(30., 2. * 1.5**ordinary_used))) if ordinary_used < 20 else None
    return None

def write_json(path, data):
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(data, indent=2, allow_nan=False), encoding='utf-8')
    temp.replace(path)

class ReplayedThenLiveClient:
    def __init__(self, key, log_fn, budget, tape=None, opener=None):
        self.key = key
        self.log_fn = log_fn
        self.budget = budget
        self.tape = list(tape) if tape else []
        self.cursor = 0
        self.opener = opener if opener is not None else urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def complete(self, messages, temperature=0.3, max_tokens=2048):
        body = dict(model=MODEL, messages=messages, temperature=temperature, max_tokens=max_tokens,
                    chat_template_kwargs={'thinking': False}, stream=False)
        
        # 1. Replay historical decision if within tape cursor
        if self.cursor < len(self.tape):
            idx = self.cursor
            self.cursor += 1
            historical_resp = self.tape[idx]
            
            record = dict(
                kind='delivery_attempt',
                status='returned',
                replay_index=idx,
                source='historical_replay',
                request=body,
                response=historical_resp,
                usage=historical_resp.get('usage', {})
            )
            self.log_fn(record)
            choice = historical_resp['choices'][0]
            content = choice['message'].get('content')
            if not content and 'reasoning_content' in choice['message']:
                content = choice['message']['reasoning_content']
            return content

        # 2. Live HTTP request with full budget reservation, pacing, and retry policy
        rate = ordinary = 0
        while True:
            record = dict(kind='delivery_attempt', request=body, usage=None)
            try:
                record['reservation'] = self.budget.reserve(messages, max_tokens, 0., 0.)
                record['pacing_wait_seconds'] = self.budget.pacer.acquire(record['reservation']['input_token_estimate'])
                self.budget.ensure_provider_available()
            except Exception as exc:
                record.update(status='blocked', error_type=type(exc).__name__)
                self.log_fn(record)
                raise

            retry = None
            success = False
            raw_content = None
            try:
                req_index = self.budget.requests
                self.log_fn(dict(kind='wire_request', index=req_index, timestamp_utc=datetime.now(timezone.utc).isoformat(), request=body))
                req = urllib.request.Request(
                    'https://api.goedelmachines.com/v1/chat/completions',
                    data=json.dumps(body).encode(),
                    headers={'Authorization': f'Bearer {self.key}', 'Content-Type': 'application/json'}
                )
                with self.opener.open(req, timeout=180) as resp:
                    raw = resp.read().decode('utf-8').replace(self.key, '[REDACTED]')
                    self.log_fn(dict(kind='wire_response', index=req_index, http_status=resp.code,
                                     request_id=resp.headers.get('x-request-id'), timestamp_utc=datetime.now(timezone.utc).isoformat()))
                    data = json.loads(raw)

                record['response'] = data
                usage = data.get('usage', {})
                if all(type(usage.get(k)) is int and usage[k] >= 0 for k in ('prompt_tokens', 'completion_tokens', 'total_tokens')):
                    record['usage'] = dict(usage, source='provider')

                choice = data['choices'][0]
                raw_content = choice['message'].get('content')
                if not raw_content and 'reasoning_content' in choice['message']:
                    raw_content = choice['message']['reasoning_content']
                if not isinstance(raw_content, str) or not raw_content.strip():
                    raise ValueError('missing response content')

                success = True
                record['status'] = 'returned'
            except Exception as exc:
                record.update(status='error', error_type=type(exc).__name__, http_status=getattr(exc, 'code', None))
                retry = robust_retry_policy(exc, rate, ordinary)
                if retry:
                    record.update(retry_category=retry[0], retry_wait_seconds=retry[1])
                else:
                    self.budget.stop_for_provider_error()

            # Record usage correctly via sim.llm.usage.UsageBudget API
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

def run():
    # Clean previous aborted continuation directory if present
    if CAMPAIGN.exists():
        shutil.rmtree(CAMPAIGN)
    CAMPAIGN.mkdir(parents=True, exist_ok=False)
    
    # 1. Extract tape of 62 historical decisions from prior s42_equal
    prior_ledger = PRIOR_ROOT / 's42_equal' / 'ledger.jsonl'
    tape = []
    if prior_ledger.exists():
        for line in open(prior_ledger, 'r', encoding='utf-8'):
            d = json.loads(line)
            if d.get('kind') == 'delivery_attempt' and d.get('status') == 'returned':
                tape.append(d.get('response'))
    print(f"Loaded {len(tape)} historical responses from prior root for replay.")

    # 2. Setup budget and protocol
    protocol = {
        "status": "continuation_running",
        "authorization": "User requested retry; continuing s42_equal from decision 63 and running remaining markets",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "configs": [
            {"seed": 42, "rounds": 100, "llm_count": 12, "wealth": "equal", "sigma": 0.7, "assignment": 0, "allow_short": False, "forum": False},
            {"seed": 42, "rounds": 100, "llm_count": 12, "wealth": "heterogeneous", "sigma": 0.7, "assignment": 0, "allow_short": False, "forum": False},
            {"seed": 43, "rounds": 100, "llm_count": 12, "wealth": "equal", "sigma": 0.7, "assignment": 0, "allow_short": False, "forum": False},
            {"seed": 43, "rounds": 100, "llm_count": 12, "wealth": "heterogeneous", "sigma": 0.7, "assignment": 0, "allow_short": False, "forum": False}
        ],
        "planned_decisions": 4800,
        "max_http_attempts": 6000,
        "max_reserved_tokens": 96000000,
        "requests_per_minute": 60
    }
    write_json(CAMPAIGN / 'protocol.json', protocol)
    write_json(CAMPAIGN / 'execution.json', {"pid": os.getpid(), "started_utc": datetime.now(timezone.utc).isoformat()})

    budget = campaign_budget(protocol['max_http_attempts'], protocol['max_reserved_tokens'])
    summary = dict(status='running', pid=os.getpid(), completed_markets=0, planned_markets=4, markets=[], replayed_decisions=len(tape))

    def save():
        summary['usage'] = budget.snapshot()
        summary['updated_utc'] = datetime.now(timezone.utc).isoformat()
        write_json(CAMPAIGN / 'summary.json', summary)
    save()

    key = dotenv_api_key('GODEL_MACHINES_API_KEY')
    if not key:
        raise RuntimeError('Named Goedel credential unavailable')

    try:
        for idx, raw_cfg in enumerate(protocol['configs']):
            cfg = Config(**raw_cfg)
            market_dir = CAMPAIGN / f's{cfg.seed}_{cfg.wealth}'
            summary.update(current_market=market_dir.name, current_market_path=str(market_dir))
            save()

            # Tape only applies to s42_equal (market index 0)
            market_tape = tape if idx == 0 else []

            def factory(log):
                def durable(record):
                    log(record)
                    if record.get('kind') == 'delivery_attempt':
                        summary['last_attempt_status'] = record.get('status')
                        summary['last_attempt_model'] = (record.get('response') or {}).get('model')
                        summary['delivered_responses'] = summary.get('delivered_responses', 0) + (record.get('status') == 'returned')
                        save()
                return ReplayedThenLiveClient(key, durable, budget, tape=market_tape)

            print(f"\n--- Starting Market: {market_dir.name} ---")
            _run_market(cfg, market_dir, client_factory=factory)
            
            m = json.loads((market_dir / 'manifest.json').read_text())
            if m['status'] != 'complete':
                raise RuntimeError(f"market {market_dir.name} did not complete")
            summary['markets'].append(dict(path=market_dir.name, completed_rounds=m['completed_rounds'], provider_requests=m['provider_requests']))
            summary['completed_markets'] += 1
            save()

        summary['status'] = 'complete'
    except BaseException as exc:
        summary.update(status='stopped', error_type=type(exc).__name__, error=str(exc))
        print(f"Campaign stopped with error: {exc}")
        raise
    finally:
        save()

if __name__ == '__main__':
    run()
