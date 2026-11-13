"""R058: Complete final 34 decisions (rounds 20-25) to achieve full 25 rounds on Seed 31991.
Replays 342 historical wire records (116 delivered decisions across rounds 1-19 and 2 of round 20)
with exact message checks.
Fresh calls complete remaining 34 decisions to achieve 150 total decisions.
"""
import sys
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import json
import time
from urllib.error import HTTPError, URLError
from unittest.mock import patch
import yaml
from research import goedel_cohort as g
from research.goedel_backoff_persistent import PersistentBackoffAgent
from sim.llm.usage import RequestPacer

OLD_BACK = g.BASE / 'runs/goedel_seed2_backoff_20261109'
OLD_DET = g.BASE / 'runs/goedel_seed2_detached_20261109'
OLD_EXP = g.BASE / 'runs/goedel_seed2_expbackoff_20261109'
OLD_FULL = g.BASE / 'runs/goedel_seed2_full25_20261109'
OLD_FINAL = g.BASE / 'runs/goedel_seed2_final_20261109'
ROOT = g.BASE / 'runs/goedel_seed2_finish25_20261109'


class RecordedThenLive(g.GoedelClient):
    cursor = 0
    tape = []

    def chat(self, messages, temperature=.3, max_tokens=2048, json_mode=True, retries=1):
        if type(self).cursor >= len(self.tape):
            return super().chat(messages, temperature, max_tokens, json_mode, retries)
        i = type(self).cursor
        x = self.tape[i]
        expected = dict(model=g.MODEL, messages=messages, temperature=temperature,
                        max_tokens=max_tokens, chat_template_kwargs={'thinking': False}, stream=False)
        assert x['request'] == expected, ('Recorded prefix request mismatch', i)
        type(self).cursor += 1
        self.last_usage = None
        self.last_response_metadata = {}
        self.last_error_metadata = {}
        with (ROOT / 'replayed_prefix.jsonl').open('a', encoding='utf-8') as f:
            f.write(json.dumps({'index': i, 'historical_not_fresh': True, 'request_matches': True}) + '\n')
        if 'error' in x:
            self.last_error_metadata = x['error']
            headers = {'Retry-After': str(x['error'].get('retry_after_seconds') or 2)}
            raise HTTPError(g.URL, x['error']['http_status'], 'Recorded historical error', headers, None)
        elif 'error_type' in x or 'response' not in x:
            raise URLError(x.get('error_type', 'Recorded transport error'))
        d = x['response']
        u = d['usage']
        self.last_usage = dict(prompt_tokens=u['prompt_tokens'], completion_tokens=u['completion_tokens'],
                               total_tokens=u['total_tokens'], source='provider')
        self.total_tokens += u['total_tokens']
        c = d['choices'][0]
        self.last_response_metadata = dict(model=d['model'], finish_reason=c['finish_reason'])
        return c['message']['content']


def main():
    auth = g.read(g.BASE.parent / 'DATA_COLLECTION_AUTHORIZATION.json')
    assert auth['status'] == 'active_finish25_seed31991_continuation'
    assert (OLD_FINAL / 'summary.json').exists()
    g.validate(OLD_BACK)
    g.validate(OLD_DET)
    g.validate(OLD_EXP)
    g.validate(OLD_FULL)
    g.validate(OLD_FINAL)

    ROOT.mkdir(exist_ok=False)

    # Build combined prefix: OLD_FINAL prefix (325 records) + OLD_FINAL fresh slice up to decision 116 (17 records)
    t_pre = [json.loads(l) for l in (OLD_FINAL / 'prefix_transport.jsonl').read_text().splitlines()]
    t_fresh = [json.loads(l) for l in (OLD_FINAL / 'provider_transport.jsonl').read_text().splitlines()][:17]
    combined_tape = t_pre + t_fresh
    assert len(combined_tape) == 342
    assert sum('response' in x for x in combined_tape) == 116

    RecordedThenLive.cursor = 0
    RecordedThenLive.tape = combined_tape

    # Save prefix transport tape
    with (ROOT / 'prefix_transport.jsonl').open('w', encoding='utf-8') as f:
        for item in combined_tape:
            f.write(json.dumps(item) + '\n')

    # Config: expanded limits for completing full 25 rounds
    cfg = yaml.safe_load((OLD_FINAL / 'config.yaml').read_text())
    cfg['llm_limits']['max_requests'] = 2000
    cfg['llm_limits']['max_reserved_tokens'] = 20000000
    (ROOT / 'config.yaml').write_text(yaml.safe_dump(cfg), encoding='utf-8')

    protocol = g.read(OLD_FINAL / 'protocol.json')
    for k in ('source_sha256', 'source_zip_sha256', 'created_utc', 'working_tree_status'):
        protocol.pop(k, None)

    protocol.update(
        version='R058_seed31991_finish25_continuation_v1',
        study='R058 R056 second-seed final 25-round finish',
        config_sha256=g.digest(ROOT / 'config.yaml'),
        recovery='Continuation from 116 delivered decisions across 342 historical prefix records. Excludes terminal 429 attempts on Prakash Rao so agent restarts cleanly with 0 retries. Robust exponential backoff delay with 60-retry ceiling.',
        prefix_sha256=g.digest(ROOT / 'prefix_transport.jsonl'),
        historical_prefix_decisions=116,
        historical_prefix_http_records=342,
        limits=dict(normal_calls=150, max_http_attempts=2000, max_reserved_tokens=20000000,
                    requests_per_minute=10, input_estimate_tokens_per_minute=60000, timeout_seconds=180,
                    max_429_retries_per_decision=60, max_server_retries=15)
    )
    for old_root in (OLD_BACK, OLD_DET, OLD_EXP, OLD_FULL, OLD_FINAL):
        protocol['inputs_sha256'].update({p.relative_to(g.BASE).as_posix(): g.digest(p) for p in old_root.rglob('*') if p.is_file()})

    g.freeze(ROOT, protocol, [
        'research/goedel_backoff_persistent.py',
        'research/goedel_finish25.py'
    ])

    original_pace = RequestPacer.acquire
    original_sleep = time.sleep

    def pace(pacer, *args, **kwargs):
        if RecordedThenLive.cursor < len(RecordedThenLive.tape):
            return 0
        return original_pace(pacer, *args, **kwargs)

    def sleep(seconds):
        if RecordedThenLive.cursor >= len(RecordedThenLive.tape):
            original_sleep(seconds)

    # Cached deliveries skip pacing & sleeping; live requests use pacing and persistent backoff.
    with patch.object(g, 'CappedAgent', PersistentBackoffAgent), \
         patch.object(g, 'GoedelClient', RecordedThenLive), \
         patch.object(RequestPacer, 'acquire', pace), \
         patch.object(time, 'sleep', sleep):
        g.execute(ROOT)

    assert RecordedThenLive.cursor == len(RecordedThenLive.tape)
    fresh_path = ROOT / 'provider_transport.jsonl'
    fresh = [json.loads(l) for l in fresh_path.read_text().splitlines()] if fresh_path.exists() else []
    g.write(ROOT / 'delivery_origin.json', dict(
        historical_prefix_http_records=len(RecordedThenLive.tape),
        historical_prefix_decisions=116,
        fresh_http_attempts=len(fresh),
        fresh_delivered_decisions=sum('response' in x for x in fresh),
        note='summary usage includes historical replay metadata. Only provider_transport.jsonl in this root represents new HTTP attempts. Prefix metadata must not be counted twice.'
    ))
    g.write(ROOT / 'output_manifest.json', {
        p.relative_to(ROOT).as_posix(): g.digest(p)
        for p in ROOT.rglob('*') if p.is_file() and p.name != 'output_manifest.json'
    })


if __name__ == '__main__':
    main()
