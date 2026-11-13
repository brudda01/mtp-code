"""R058 Option B: Seed 31991 continuation with exponential backoff and higher retry ceiling.
Replays 64 historical wire records (35 delivered decisions) with exact message checks.
Fresh calls use exponential backoff (min 5s up to 60s cap, max 25 retries).
"""
import sys
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import json
import time
from urllib.error import HTTPError
from unittest.mock import patch
import yaml
from research import goedel_cohort as g
from research.goedel_backoff_exp import ExpBackoffAgent
from sim.llm.usage import RequestPacer

OLD1 = g.BASE / 'runs/goedel_seed2_backoff_20261109'
OLD2 = g.BASE / 'runs/goedel_seed2_detached_20261109'
ROOT = g.BASE / 'runs/goedel_seed2_expbackoff_20261109'


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
    assert auth['status'] == 'active_expbackoff_seed31991_continuation'
    assert (OLD2 / 'summary.json').exists()
    g.validate(OLD1)
    g.validate(OLD2)

    ROOT.mkdir(exist_ok=False)

    # Build combined prefix: OLD1 all records (38) + OLD2 successful prefix up to decision 35 (26 records)
    t1 = [json.loads(l) for l in (OLD1 / 'provider_transport.jsonl').read_text().splitlines()]
    t2 = [json.loads(l) for l in (OLD2 / 'provider_transport.jsonl').read_text().splitlines()][:26]
    combined_tape = t1 + t2
    assert len(combined_tape) == 64
    assert sum('response' in x for x in combined_tape) == 35

    RecordedThenLive.cursor = 0
    RecordedThenLive.tape = combined_tape

    # Save prefix transport tape
    with (ROOT / 'prefix_transport.jsonl').open('w', encoding='utf-8') as f:
        for item in combined_tape:
            f.write(json.dumps(item) + '\n')

    # Config: increase budget ceiling for exponential backoff retries
    cfg = yaml.safe_load((OLD2 / 'config.yaml').read_text())
    cfg['llm_limits']['max_requests'] = 1000
    cfg['llm_limits']['max_reserved_tokens'] = 12000000
    (ROOT / 'config.yaml').write_text(yaml.safe_dump(cfg), encoding='utf-8')

    protocol = g.read(OLD2 / 'protocol.json')
    for k in ('source_sha256', 'source_zip_sha256', 'created_utc', 'working_tree_status'):
        protocol.pop(k, None)

    protocol.update(
        version='R058_seed31991_expbackoff_continuation_v1',
        study='R058 R056 second-seed exponential backoff completion',
        config_sha256=g.digest(ROOT / 'config.yaml'),
        recovery='Continuation from 35 delivered decisions across 64 historical prefix records (38 from initial backoff run, 26 from detached run). Failed Lakshmi Nair 429 attempts excluded so agent restarts with 0 retries. Exponential backoff delay with max 25 retries and 60s window cap.',
        prefix_sha256=g.digest(ROOT / 'prefix_transport.jsonl'),
        historical_prefix_decisions=35,
        historical_prefix_http_records=64,
        limits=dict(normal_calls=150, max_http_attempts=1000, max_reserved_tokens=12000000,
                    requests_per_minute=10, input_estimate_tokens_per_minute=60000, timeout_seconds=180,
                    max_429_retries_per_decision=25)
    )
    protocol['inputs_sha256'].update({p.relative_to(g.BASE).as_posix(): g.digest(p) for p in OLD1.rglob('*') if p.is_file()})
    protocol['inputs_sha256'].update({p.relative_to(g.BASE).as_posix(): g.digest(p) for p in OLD2.rglob('*') if p.is_file()})

    g.freeze(ROOT, protocol, [
        'research/goedel_backoff_exp.py',
        'research/goedel_expbackoff_continuation.py',
        'tests/test_goedel_backoff_exp.py'
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

    # Cached deliveries skip pacing & sleeping; live requests use pacing and exponential backoff.
    with patch.object(g, 'CappedAgent', ExpBackoffAgent), \
         patch.object(g, 'GoedelClient', RecordedThenLive), \
         patch.object(RequestPacer, 'acquire', pace), \
         patch.object(time, 'sleep', sleep):
        g.execute(ROOT)

    assert RecordedThenLive.cursor == len(RecordedThenLive.tape)
    fresh_path = ROOT / 'provider_transport.jsonl'
    fresh = [json.loads(l) for l in fresh_path.read_text().splitlines()] if fresh_path.exists() else []
    g.write(ROOT / 'delivery_origin.json', dict(
        historical_prefix_http_records=len(RecordedThenLive.tape),
        historical_prefix_decisions=35,
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
