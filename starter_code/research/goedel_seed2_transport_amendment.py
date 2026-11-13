"""One disclosed re-entry after zero-delivery HTTP429; combined original ceilings."""
import argparse
from pathlib import Path
import yaml
from research import goedel_cohort as g

FIRST = g.BASE / 'runs/goedel_second_seed_20261108'
FREEZE_MARKER = g.BASE.parent / 'DATA_COLLECTION_FROZEN.json'


def guard():
    if FREEZE_MARKER.exists():
        raise RuntimeError('Data collection is permanently frozen.')


def config():
    first = g.read(FIRST / 'summary.json')
    assert first['delivered_decisions'] == first['completed_rounds'] == 0
    assert first['usage']['requests_made'] == 1
    records = [__import__('json').loads(line) for line in (FIRST / 'provider_transport.jsonl').read_text().splitlines()]
    assert len(records) == 1 and records[0]['error']['http_status'] == 429 and 'response' not in records[0]
    cfg = yaml.safe_load((FIRST / 'config.yaml').read_text())
    cfg['llm_limits']['max_requests'] -= first['usage']['requests_made']
    cfg['llm_limits']['max_reserved_tokens'] -= first['usage']['reserved_tokens']
    return cfg


def prepare(root):
    guard()
    old = g.validate(FIRST)
    for name, expected in g.read(FIRST / 'output_manifest.json').items():
        assert g.digest(FIRST / name) == expected, name
    root = Path(root).resolve();root.mkdir(parents=True, exist_ok=False)
    (root / 'config.yaml').write_text(yaml.safe_dump(config()), encoding='utf-8')
    protocol = {k: old[k] for k in ('requested_profile', 'design', 'primary', 'retention', 'costs', 'limitations', 'preservation', 'donor_protocol_sha256')}
    inputs = dict(old['inputs_sha256'])
    for name in ('protocol.json', 'preparation.json', 'config.yaml', 'output_manifest.json', 'summary.json', 'provider_transport.jsonl'):
        p = FIRST / name;inputs[p.relative_to(g.BASE).as_posix()] = g.digest(p)
    protocol.update(version='R056_seed2_HTTP429_zero_delivery_amendment_v1', study='R056 seed 2 transport amendment',
        status='amendment_frozen_before_reattempt', config_sha256=g.digest(root / 'config.yaml'), inputs_sha256=inputs,
        amendment='Original seed2 stopped on first HTTP429, Retry-After2 seconds, zero replies and zero cleared auctions. Its no-restart rule is explicitly superseded ONCE by this disclosed amendment before any behavioral output. This is a fresh single-use root from initial state, not a resumed/spliced path. Original failed attempt remains archived. No further re-entry if this attempt stops.',
        limits=dict(normal_calls=150, max_http_attempts=179, max_reserved_tokens=2994480, combined_with_first_attempt_max_http=180, combined_with_first_attempt_max_reservations=3000000, requests_per_minute=10, input_estimate_tokens_per_minute=60000, timeout_seconds=180),
        transport=old['transport'],
        final_collection='Permanent collection freeze after this amended attempt completes or stops. No further restart, seed, model request or new scientific simulation. Offline saved-evidence analysis and exact reproduction allowed.')
    g.freeze(root, protocol, ['research/goedel_seed2_transport_amendment.py', 'tests/test_goedel_seed2_amendment.py'])
    print(g.read(root / 'preparation.json'))


def execute(root):
    guard();root = Path(root).resolve();p = g.validate(root)
    assert p['version'] == 'R056_seed2_HTTP429_zero_delivery_amendment_v1'
    assert yaml.safe_load((root / 'config.yaml').read_text()) == config()
    assert not (root / 'execution.json').exists(), 'Single use; no restart.'
    g.execute(root)


if __name__ == '__main__':
    parser = argparse.ArgumentParser();parser.add_argument('action', choices=('prepare', 'run'));parser.add_argument('--study', required=True)
    args = parser.parse_args();{'prepare': prepare, 'run': execute}[args.action](args.study)
