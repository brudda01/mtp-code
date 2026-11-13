"""Seal R058 completed two-seed cohort and retry policy; no collection or replay."""
import hashlib
import io
import json
from pathlib import Path
import zipfile
from research.order_influence import BASE, read, digest
from research.goedel_cohort import validate
from sim.llm.client import dotenv_api_key


def main():
    repo = BASE.parent;sources = read(repo / 'thesis/sources.json')
    assert read(repo / 'thesis/checks.json')['writing_stage'] == 'R058 two-seed DeepSeek replication'
    assert read(repo / 'DATA_COLLECTION_AUTHORIZATION.json')['status'] == 'closed_after_seed31991'
    names = ('dynamic_order_tape_20261108', 'goedel_cohort_20261108', 'goedel_second_seed_20261108', 'goedel_second_seed_retry_20261108', 'goedel_seed2_backoff_20261109')
    roots = [BASE / 'runs' / name for name in names];inputs = {};runtime_sources = {}
    for root in roots:
        protocol = validate(root);inputs.update(protocol['inputs_sha256']);runtime_sources.update(protocol['source_sha256'])
        for n,h in read(root / 'output_manifest.json').items():assert digest(root / n) == h, n
    for n,h in sources['local_sha256'].items():assert digest(repo / n) == h, n
    for n,h in sources['prior_archives'].items():assert digest(BASE / 'runs' / n) == h, n
    for n,h in sources['previous_writing_archives'].items():assert digest(repo / n) == h, n
    for n,h in read(repo / 'thesis/artifact_manifest.json')['files'].items():assert digest(repo / 'thesis' / n) == h, n
    paths = list((repo / 'thesis').rglob('*')) + list((repo / 'archive/early_proposals').rglob('*'))
    for root in roots:paths += list(root.rglob('*'))
    for name in ('dynamic_order_analysis_20261108', 'goedel_cohort_analysis_20261108', 'provider_docs_20261108', 'final_extensions_review_20261108', 'final_collection_analysis_20261108', 'final_collection_verification_20261108', 'deepseek_replication_analysis_20261109'):
        paths += list((BASE / 'runs' / name).rglob('*'))
    paths += [BASE / n for n in {*inputs, *runtime_sources}]
    paths += [BASE / n for n in ('requirements.txt', 'tests/__init__.py', 'research/__init__.py') if (BASE / n).exists()]
    paths += [repo / n for n in ('README.md', 'THESIS_RESULTS.md', 'AGENTS.md', 'RESEARCH_DIARY.md', 'WORK_PLAN.tmp.md', 'DATA_COLLECTION_FROZEN.md', 'DATA_COLLECTION_FROZEN.json', 'DATA_COLLECTION_AUTHORIZATION.json', 'DATA_COLLECTION_STATUS.md')]
    paths += [BASE / 'research' / n for n in ('goedel_cohort.py', 'dynamic_order_tape.py', 'analyze_final_extensions.py', 'render_dynamic_paths.py', 'preserve_final_extensions.py', 'goedel_second_seed.py', 'goedel_seed2_transport_amendment.py', 'analyze_final_collection.py', 'preserve_final_collection.py', 'goedel_backoff.py', 'goedel_seed2_backoff.py', 'analyze_deepseek_replication.py', 'preserve_deepseek_replication.py')]
    paths += [BASE / 'tests' / n for n in ('test_final_extensions.py', 'test_dynamic_order_tape.py', 'test_goedel_second_seed.py', 'test_goedel_seed2_amendment.py', 'test_goedel_backoff.py')]
    paths += [BASE / 'runs/final_extensions_20261108_evidence_manifest.json']
    files = {p.relative_to(repo).as_posix():p.read_bytes() for p in sorted(set(paths))
             if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'}
    keys = ('API_KEY', 'BHARATCODE_API_KEY', 'GEMINI_API_KEY', 'NVIDIA_API_KEY', 'OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'GODEL_MACHINES_API_KEY')
    secrets = {v.encode() for key in keys if (v := dotenv_api_key(key)) and len(v) >= 8};scanned = 0
    def scan(name, data):
        nonlocal scanned
        assert '.env' not in Path(name).name and '.git' not in Path(name).parts
        assert not any(s in data for s in secrets), 'Configured secret guard failed; no export'
        scanned += 1
        if name.endswith('.zip'):
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                assert z.testzip() is None
                for n in z.namelist():scan(n, z.read(n))
    for n,b in files.items():scan(n,b)
    hashes = {n:hashlib.sha256(b).hexdigest() for n,b in files.items()}
    result = read(BASE / 'runs/deepseek_replication_analysis_20261109/report.json')
    manifest = dict(stage='R058 two-seed DeepSeek replication', files=hashes, final_collection_report=result,
        prior_archives=sources['prior_archives'], recursive_configured_secret_checks=scanned,
        note='R058 user-authorized fresh seed31991 with budgeted Retry-After+1 handling. Two completed market scenarios; old two aborted attempts and lone unexecuted reply preserved separately. No cross-model/count/cap causal claim. Collection exception closed. Historical archives unchanged; docs precede final checksum closure.')
    dest = BASE / 'runs/deepseek_replication_20261109_evidence.zip';receipt = dest.with_name(dest.stem + '_manifest.json')
    assert not dest.exists() and not receipt.exists()
    with zipfile.ZipFile(dest, 'x', zipfile.ZIP_DEFLATED) as z:
        for n,b in files.items():z.writestr(n,b)
        z.writestr('EVIDENCE_MANIFEST.json', json.dumps(manifest, indent=2))
    with zipfile.ZipFile(dest) as z:
        assert z.testzip() is None
        for n,h in hashes.items():assert hashlib.sha256(z.read(n)).hexdigest() == h, n
    output = dict(status='preserved', collection_status='permanently_frozen', path=dest.relative_to(repo).as_posix(),
        sha256=digest(dest), bytes=dest.stat().st_size, exported_file_hashes=len(files), recursive_configured_secret_checks=scanned,
        all_member_hashes_verified=True, configured_secret_scan_passed=True,
        prior_archives_unchanged=len(sources['prior_archives']), prior_writing_archives_unchanged=len(sources['previous_writing_archives']),
        seed31991_status=result['reports'][1]['summary']['status'], seed31991_decisions=result['reports'][1]['summary']['delivered_decisions'], seed31991_missing_decisions=0,
        seed31991_http_attempts=result['seed31991_new_delivery']['http_attempts'], seed31991_unknown_usage_errors=result['seed31991_new_delivery']['unknown_usage_errors'], completed_deepseek_scenarios=2)
    receipt.write_text(json.dumps(output, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(output, indent=2))


if __name__ == '__main__':main()
