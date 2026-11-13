"""Seal R050/R051 evidence once; no model or simulation execution.

The writing snapshot precedes the final archive-checksum diary receipt.
Historical campaigns remain separate; their input files used by R050 are included.
"""
import hashlib
import io
import json
from pathlib import Path
import zipfile

from sim.llm.client import dotenv_api_key

BASE = Path(__file__).resolve().parents[1]
REPO = BASE.parent


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    destination = BASE / 'runs/feedback_background_20261107_evidence.zip'
    receipt = destination.with_name(destination.stem + '_manifest.json')
    assert not destination.exists() and not receipt.exists()
    sources = read(REPO / 'thesis/sources.json')
    for name, expected in sources['prior_archives'].items():
        assert digest((BASE / 'runs' / name).read_bytes()) == expected, name
    for name, expected in sources['previous_writing_archives'].items():
        assert digest((REPO / name).read_bytes()) == expected, name
    paths = []
    for root in (REPO / 'thesis', BASE / 'research', BASE / 'tests',
                 BASE / 'runs/feedback_audit_20261106',
                 BASE / 'runs/background_diversity_20261106',
                 BASE / 'runs/diversity_replay_20261107'):
        paths.extend(root.rglob('*'))
    audit = read(BASE / 'runs/feedback_audit_20261106/report.json')
    for name, expected in audit['inputs_sha256'].items():
        path = BASE / name
        assert digest(path.read_bytes()) == expected, name
        paths.append(path)
    paths.extend(REPO / n for n in ('AGENTS.md', 'RESEARCH_DIARY.md', 'WORK_PLAN.tmp.md'))
    paths.extend(BASE / n for n in ('sim/timed_feedback.py', 'requirements.txt',
                                  'ECONOMIC_MODEL.md', 'AGENT_EXPERIMENTS.md'))
    files = {p.relative_to(REPO).as_posix(): p.read_bytes() for p in sorted(set(paths))
             if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'}
    keys = ('API_KEY', 'BHARATCODE_API_KEY', 'GEMINI_API_KEY', 'NVIDIA_API_KEY',
            'OPENAI_API_KEY', 'ANTHROPIC_API_KEY')
    secrets = {v.encode() for key in keys if (v := dotenv_api_key(key)) and len(v) >= 8}
    count = 0

    def scan(name, data):
        nonlocal count
        assert '.env' not in Path(name).name and '.git' not in Path(name).parts
        assert not any(value in data for value in secrets), 'Configured secret detected; export stopped'
        count += 1
        if name.endswith('.zip'):
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                assert archive.testzip() is None
                for member in archive.namelist():
                    scan(member, archive.read(member))

    for name, data in files.items():
        scan(name, data)
    manifest = dict(
        stage='R050/R051',
        scope='All-case retrospective feedback/path audit; opt-in offline-tested feedback adapter; '
              '16 fresh rule-only markets across four scenarios;16 deterministic local replays; '
              'manuscript and focused primary-literature update. No fresh LLM samples.',
        files={name: digest(data) for name, data in files.items()},
        prior_archives=sources['prior_archives'],
        previous_writing_archives=sources['previous_writing_archives'],
        recursive_configured_secret_checks=count,
        limitations='Original full campaigns and older independent verification dependencies remain '
                    'in their separate archives. No independent-machine or human validation. '
                    'Documentation snapshot precedes the final checksum receipt to avoid circular hashes.')
    with zipfile.ZipFile(destination, 'x', zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
        archive.writestr('EVIDENCE_MANIFEST.json', json.dumps(manifest, indent=2))
    with zipfile.ZipFile(destination) as archive:
        assert archive.testzip() is None
        for name, expected in manifest['files'].items():
            assert digest(archive.read(name)) == expected, name
    result = dict(status='preserved', path=destination.relative_to(REPO).as_posix(),
                  sha256=digest(destination.read_bytes()), bytes=destination.stat().st_size,
                  exported_file_hashes=len(files), recursive_configured_secret_checks=count,
                  configured_secret_scan_passed=True, all_member_hashes_verified=True,
                  prior_scientific_archives_unchanged=len(sources['prior_archives']),
                  prior_writing_archives_unchanged=len(sources['previous_writing_archives']),
                  new_scientific_rule_markets=16, new_api_requests=0,
                  local_frozen_rule_replay_paths=16, byte_identical_replay_csvs=112)
    with receipt.open('x', encoding='utf-8') as f:
        json.dump(result, f, indent=2)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
