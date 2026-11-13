"""User-authorized fresh seed-42 equal replacement; never resume or overwrite.

Imports only the original concurrent market function, never its destructive run().
Keeps fast campaign seed offsets, economics, prompts and 110 RPM/4 workers/200k TPM.
"""
import sys
sys.dont_write_bytecode = True
import json
import os
import hashlib
import time
import threading
from pathlib import Path
from datetime import datetime, timezone
from dataclasses import asdict
from run_fast_campaign import run_concurrent_market
from sandbox import Config, source_hashes
from fresh_correction_delivery import FreshOnlyDelivery
from sim.llm.usage import UsageBudget
from sim.llm.client import dotenv_api_key
from personas import library

def safe_write_json(path, data):
    payload = json.dumps(data, indent=2, allow_nan=False)
    temporary = path.with_suffix(path.suffix + f'.{os.getpid()}.{threading.get_ident()}.tmp')
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

write_json = safe_write_json

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT/'runs'/'wealth_s42_equal_fresh_correction_20261110'
KEY_NAME = 'ANOTHER_GODEL_MACHINES_API_KEY'
CONFIG = Config(seed=42, rounds=100, llm_count=12, wealth='equal', sigma=.7,
                assignment=0, allow_short=False, forum=False)

def now(): return datetime.now(timezone.utc).isoformat()

def verify_saved(path):
    """Independent financial and request-provenance checks; no simulator replay."""
    rows=[json.loads(s) for s in (path/'ledger.jsonl').read_text(encoding='utf-8').splitlines()]
    initial=rows[0]['accounts']; previous=initial; max_error=0.; rounds=0
    auctions={x['round']:x for x in rows if x['kind']=='auction'}
    dec={(x['round'],x['agent']):x for x in rows if x['kind']=='decision'}
    attempts=[x for x in rows if x['kind']=='delivery_attempt' and x['status']=='returned']
    assert len(attempts)==1200 and all(x.get('source')!='historical_replay' for x in attempts)
    names={f'llm_{i}':p['name'] for i,p in enumerate(library(12,42))}
    index={}
    for i,x in enumerate(attempts):
        body=json.loads(x['request']['messages'][-1]['content'])
        key=(body['observation']['session'],body['persona']['name'])
        assert key not in index
        index[key]=(i,body,x)
    used=set()
    for row in (x for x in rows if x['kind']=='round'):
        rounds+=1; assert row['round']==rounds
        trades=auctions[rounds]['trades']; p=row['price']; d=row['dividend']
        assert row['volume']==sum(t['quantity'] for t in trades)
        for aid,op in row['opening'].items():
            cl=row['closing'][aid]
            assert op['cash']==previous[aid]['cash'] and op['shares']==previous[aid]['shares']
            b=sum(t['quantity'] for t in trades if t['buyer_id']==aid)
            s=sum(t['quantity'] for t in trades if t['seller_id']==aid)
            assert b*p<=op['cash']+1e-7 and s<=op['shares']
            sh=op['shares']+b-s; cash=op['cash']+(s-b)*p
            err=abs(cl['cash']-(cash*1.0002+sh*d)); max_error=max(max_error,err)
            assert err<1e-7 and sh==cl['shares'] and cl['cash']>=0 and sh>=0
            if aid.startswith('llm'):
                decision=dec[rounds,aid]
                i,body,x=index[rounds,names[aid]]
                assert x['response']['choices'][0]['message']['content']==decision['raw']
                assert i not in used; used.add(i)
                assert body['account']['cash']==op['cash'] and body['account']['shares']==op['shares']
        assert sum(x['shares'] for x in row['closing'].values())==2050
        previous=row['closing']
    assert rounds==100 and len(used)==1200
    result=dict(status='passed',account_rounds=2000,delivered_fresh_decisions=1200,
                max_individual_cash_error=max_error,completed_rounds=rounds)
    write_json(path.parent/'financial_verification.json',result)
    return result

def run():
    if OUTPUT.exists():
        raise FileExistsError('Correction root already exists; inspect it, never overwrite or restart')
    key=dotenv_api_key(KEY_NAME)
    if not key: raise RuntimeError('Required named credential unavailable')
    CONFIG.validate()
    OUTPUT.mkdir(exist_ok=False)
    protocol=dict(status='authorized',authority='Latest user explicitly requested replay defect correction using ANOTHER_GODEL_MACHINES_API_KEY and unchanged RPM settings.',
        scope='One fresh seed42 equal market only; no replay, no other arms, no automatic restart.',
        supersedes='Older collection freeze only for this named correction; historical markers and roots preserved.',
        config=asdict(CONFIG),planned_decisions=1200,requests_per_minute=110,max_workers=4,
        input_tokens_per_minute=200000,max_http_attempts=1500,max_reserved_tokens=24000000,
        budget_note='One-quarter of original four-market total ceilings; pacing unchanged.',
        credential_variable=KEY_NAME,created_utc=now(),source_sha256=source_hashes(),
        invalidated_path='wealth_live_12llm_100round_fast110/s42_equal',
        interpretation='New provider realization after audit; does not retrospectively repair original path. Credential/date change disclosed.')
    write_json(OUTPUT/'protocol.json',protocol)
    write_json(OUTPUT/'execution.json',dict(pid=os.getpid(),started_utc=now()))
    budget=UsageBudget(max_requests=1500,max_reserved_tokens=24000000,
        requests_per_minute=110,input_tokens_per_minute=200000,stop_on_api_error=True)
    summary=dict(status='running',delivered_responses=0,replayed_decisions=0,completed_rounds=0,pid=os.getpid())
    state_lock = threading.Lock()
    def save():
        try:
            with state_lock:
                summary.update(usage=budget.snapshot(), updated_utc=now())
                safe_write_json(OUTPUT / 'summary.json', summary)
        except Exception:
            pass
    def factory(log):
        def durable(record):
            try:
                log(record)
            except Exception:
                pass
            try:
                if record.get('kind') == 'delivery_attempt':
                    with state_lock:
                        summary['delivered_responses'] += (record.get('status') == 'returned')
                        summary['last_attempt_status'] = record.get('status')
                    save()
                elif record.get('kind') == 'round':
                    with state_lock:
                        summary['completed_rounds'] = record['round']
                    save()
            except Exception:
                pass
        # Market loop uses its own log for rounds; progress also derives from ledger.
        return FreshOnlyDelivery(key, durable, budget)
    save()
    try:
        run_concurrent_market(CONFIG, OUTPUT / 's42_equal', factory)
        verification = verify_saved(OUTPUT / 's42_equal')
        manifest = json.loads((OUTPUT / 's42_equal' / 'manifest.json').read_text(encoding='utf-8'))
        manifest.update(provider_requests=budget.requests, delivered_provider_responses=1200,
                        replayed_decisions=0, evidence_type='FRESH_CORRECTION_110RPM')
        safe_write_json(OUTPUT / 's42_equal' / 'manifest.json', manifest)
        with state_lock:
            summary.update(status='complete', completed_rounds=100, verification=verification)
    except BaseException as exc:
        with state_lock:
            summary.update(status='stopped', error_type=type(exc).__name__)
        raise
    finally:
        save()
        try:
            protocol.update(status='closed_' + summary.get('status', 'stopped'), closed_utc=now())
            safe_write_json(OUTPUT / 'protocol.json', protocol)
            hashes = {str(p.relative_to(OUTPUT)): hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in OUTPUT.rglob('*') if p.is_file() and not p.name.endswith('.tmp')}
            safe_write_json(OUTPUT / 'output_hashes.json', hashes)
        except Exception:
            pass

if __name__=='__main__': run()
