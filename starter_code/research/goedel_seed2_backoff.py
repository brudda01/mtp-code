"""R058 user-authorized fresh seed31991 run with fully budgeted HTTP429 retries."""
import argparse
from pathlib import Path
from unittest.mock import patch
import yaml
from research import goedel_cohort as g
from research.goedel_backoff import BackoffAgent

ROOT = g.BASE / 'runs/goedel_seed2_backoff_20261109'
AUTH = g.BASE.parent / 'DATA_COLLECTION_AUTHORIZATION.json'
DONOR = g.BASE / 'runs/goedel_cohort_20261108'


def authorized(root):
    record = g.read(AUTH)
    assert record['status'] == 'active_seed31991_exception'
    assert Path(root).resolve() == ROOT.resolve()
    assert record['only_authorized_root'] == ROOT.relative_to(g.BASE.parent).as_posix()


def recipe():
    cfg = yaml.safe_load((DONOR / 'config.yaml').read_text())
    cfg.update(seed=31991, name='goedel_6LLM_B_cap10_s31991_backoff')
    cfg['llm_limits'].update(max_requests=600, max_reserved_tokens=8000000)
    return cfg


def prepare(root):
    authorized(root);g.validate(DONOR)
    root = Path(root).resolve();root.mkdir(parents=True, exist_ok=False)
    (root / 'config.yaml').write_text(yaml.safe_dump(recipe()), encoding='utf-8')
    (root / 'authorization_snapshot.json').write_bytes(AUTH.read_bytes())
    old = g.read(DONOR / 'protocol.json')
    protocol = {k:old[k] for k in ('requested_profile','retention','costs','preservation')}
    inputs = dict(old['inputs_sha256'])
    for prior in ('goedel_cohort_20261108','goedel_second_seed_20261108','goedel_second_seed_retry_20261108'):
        for name in ('protocol.json','config.yaml','summary.json','output_manifest.json'):
            p = g.BASE / 'runs' / prior / name;inputs[p.relative_to(g.BASE).as_posix()] = g.digest(p)
    protocol.update(version='R058_seed31991_budgeted429_v1', study='R058 R056 second-seed completion',
        config_sha256=g.digest(root / 'config.yaml'), inputs_sha256=inputs,
        authorization_sha256=g.digest(root / 'authorization_snapshot.json'),
        design='Fresh initial-state seed31991; six identical personas, ModeB, cap10,25 sessions, same DeepSeek profile and economics as30841. Do not reuse the one previous unexecuted reply. No selection on resulting market outcomes; prior aborted attempts retained.',
        transport='HTTP429: identical messages/settings, sleep valid Retry-After seconds (including decimal or HTTP-date) plus1second. Missing/invalid header: exponential2,4,...60seconds plus1. At most10 consecutive429retries per logical request; shared600HTTP/8M reservations cap all attempts, no refunds. Existing one transport/503retry and JSON repair retained separately; unrecoverable errors stop. Every attempt raw-logged and budgeted; no hidden client retries.',
        limits=dict(normal_calls=150,max_http_attempts=600,max_reserved_tokens=8000000,rate_limit_retries_per_request=10,requests_per_minute=10,input_estimate_tokens_per_minute=60000),
        primary='Each seed separately: completion,price log-return SD,private-referencegap,drawdown,makerboundary/inventory,volume/LLM participation andperpersona BOTH-mark passiveexcess; equal-weight two-seed descriptive summary only.',
        limitations='Two market scenarios under matched settings, not a paired treatment contrast or identified model/count/cap effect. Unseeded provider draws and later backend time differ. Retry change is disclosed delivery-policy difference. Old failed attempts remain operational evidence, not market replications.',
        final_collection='User explicitly lifted prior freeze for this new run. Re-close collection after this attempt; no extra seed, model switch or R052 restart. Archived R057 marker remains historical; specific authorization controls only this root.')
    g.freeze(root, protocol, ['research/goedel_backoff.py','research/goedel_seed2_backoff.py','tests/test_goedel_backoff.py'])
    print(g.read(root / 'preparation.json'))


def execute(root):
    authorized(root);root = Path(root).resolve();p = g.validate(root)
    assert p['version'] == 'R058_seed31991_budgeted429_v1'
    assert yaml.safe_load((root / 'config.yaml').read_text()) == recipe()
    assert not (root / 'execution.json').exists(), 'Single use; never duplicate this run.'
    with patch.object(g,'CappedAgent',BackoffAgent):g.execute(root)


if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=('prepare','run'));parser.add_argument('--study',required=True)
    args=parser.parse_args();{'prepare':prepare,'run':execute}[args.action](args.study)
