"""Final, explicitly authorized R056 replication. Original frozen sources untouched."""
import argparse
from copy import deepcopy
from pathlib import Path
import yaml
from research import goedel_cohort as g

DONOR = g.BASE / 'runs/goedel_cohort_20261108'
FREEZE_MARKER = g.BASE.parent / 'DATA_COLLECTION_FROZEN.json'
SEED = 31991


def collection_open():
    if FREEZE_MARKER.exists():
        raise RuntimeError('Data collection is permanently frozen; this launcher is disabled.')


def recipe():
    cfg = yaml.safe_load((DONOR / 'config.yaml').read_text(encoding='utf-8'))
    cfg = deepcopy(cfg)
    cfg.update(seed=SEED, name='goedel_6LLM_B_cap10_s31991')
    return cfg


def prepare(root):
    collection_open()
    old = g.validate(DONOR)
    for name, expected in g.read(DONOR / 'output_manifest.json').items():
        assert g.digest(DONOR / name) == expected, name
    assert g.read(DONOR / 'summary.json')['status'] == 'completed'
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=False)
    (root / 'config.yaml').write_text(yaml.safe_dump(recipe()), encoding='utf-8')
    protocol = {k: deepcopy(old[k]) for k in ('requested_profile', 'limits', 'transport', 'retention', 'costs', 'preservation')}
    inputs = dict(old['inputs_sha256'])
    for name in ('protocol.json', 'preparation.json', 'config.yaml', 'output_manifest.json', 'summary.json'):
        p = DONOR / name
        inputs[p.relative_to(g.BASE).as_posix()] = g.digest(p)
    protocol.update(version='R056_seed2_final_replication_v1', study='R056 seed 2',
        status='frozen_before_live_requests', config_sha256=g.digest(root / 'config.yaml'),
        inputs_sha256=inputs, donor_protocol_sha256=g.digest(DONOR / 'protocol.json'),
        design='One final 25-round, 6-LLM plus 8-rule Mode B market at seed31991. Exact R056 seed30841 configuration except seed and name; unchanged personas, adapter, cap10, model and transport. 150 normal decisions. No treatment arm, no pooling with Qwen.',
        primary=old['primary'].replace('Descriptive single unpooled cohort.', 'Show each seed separately and equal-weight descriptive means across two scenarios; no significance or equivalence claim.'),
        limitations='Two independently seeded scenarios under a matched configuration, NOT a paired treatment comparison. Provider draws are unseeded. Six agents and 25 rounds are dependent within each market. No identified model/count/cap effect, human validation or long-run calibration.',
        final_collection='User explicitly requested seed31991 then permanent data-collection freeze. Single use; retain any partial outcome. No restart, missing-slot completion, additional seed or new scientific simulation. Saved-evidence analysis and exact offline reproduction remain allowed.')
    g.freeze(root, protocol, ['research/goedel_second_seed.py', 'tests/test_goedel_second_seed.py', 'tests/test_final_extensions.py'])
    print(g.read(root / 'preparation.json'))


def execute(root):
    collection_open()
    root = Path(root).resolve()
    p = g.validate(root)
    assert p['version'] == 'R056_seed2_final_replication_v1'
    assert yaml.safe_load((root / 'config.yaml').read_text(encoding='utf-8')) == recipe()
    # The inherited worker also uses exclusive creation of execution.json.
    assert not (root / 'execution.json').exists(), 'Never restart this study.'
    g.execute(root)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('prepare', 'run'))
    parser.add_argument('--study', required=True)
    args = parser.parse_args()
    {'prepare': prepare, 'run': execute}[args.action](args.study)
