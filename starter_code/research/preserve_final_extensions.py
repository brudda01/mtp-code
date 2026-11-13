"""Seal R055/R056 and housekeeping, without changing older archives."""
import hashlib
import io
import json
from pathlib import Path
import zipfile
from research.order_influence import BASE,read,digest
from research.goedel_cohort import validate
from sim.llm.client import dotenv_api_key


def main():
    repo=BASE.parent;sources=read(repo/'thesis/sources.json')
    assert read(repo/'thesis/checks.json')['writing_stage']=='R055/R056 final extensions'
    roots=[BASE/'runs'/n for n in ('dynamic_order_tape_20261108','goedel_cohort_20261108')]
    inputs={};runtime_sources={}
    for root in roots:
        p=validate(root);inputs.update(p['inputs_sha256']);runtime_sources.update(p['source_sha256'])
        for n,h in read(root/'output_manifest.json').items():assert digest(root/n)==h,n
    for n,h in sources['local_sha256'].items():assert digest(repo/n)==h,n
    for n,h in sources['prior_archives'].items():assert digest(BASE/'runs'/n)==h,n
    for n,h in sources['previous_writing_archives'].items():assert digest(repo/n)==h,n
    for n,h in read(repo/'thesis/artifact_manifest.json')['files'].items():assert digest(repo/'thesis'/n)==h,n
    paths=list((repo/'thesis').rglob('*'))+list((repo/'archive/early_proposals').rglob('*'))
    for root in roots:paths+=list(root.rglob('*'))
    for name in ('dynamic_order_analysis_20261108','goedel_cohort_analysis_20261108','provider_docs_20261108','final_extensions_review_20261108'):
        paths+=list((BASE/'runs'/name).rglob('*'))
    paths += [BASE/n for n in inputs]
    paths += [BASE/n for n in runtime_sources]
    paths += [p for p in (BASE/'tests/__init__.py',BASE/'research/__init__.py') if p.exists()]
    paths += [repo/n for n in ('README.md','THESIS_RESULTS.md','AGENTS.md','RESEARCH_DIARY.md','WORK_PLAN.tmp.md')]
    paths += [BASE/'research'/n for n in ('goedel_cohort.py','dynamic_order_tape.py','analyze_final_extensions.py','render_dynamic_paths.py','preserve_final_extensions.py')]
    paths += [BASE/'tests'/n for n in ('test_final_extensions.py','test_dynamic_order_tape.py')]
    paths += [BASE/'requirements.txt']
    files={p.relative_to(repo).as_posix():p.read_bytes() for p in sorted(set(paths))
           if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc'}
    keys=('API_KEY','BHARATCODE_API_KEY','GEMINI_API_KEY','NVIDIA_API_KEY','OPENAI_API_KEY','ANTHROPIC_API_KEY','GODEL_MACHINES_API_KEY')
    secrets={v.encode() for key in keys if (v:=dotenv_api_key(key)) and len(v)>=8};scanned=0
    def scan(n,b):
        nonlocal scanned
        assert '.env' not in Path(n).name and '.git' not in Path(n).parts
        assert not any(s in b for s in secrets),'Configured secret guard failed;no export'
        scanned+=1
        if n.endswith('.zip'):
            with zipfile.ZipFile(io.BytesIO(b)) as z:
                assert z.testzip() is None
                for name in z.namelist():scan(name,z.read(name))
    for n,b in files.items():scan(n,b)
    hashes={n:hashlib.sha256(b).hexdigest() for n,b in files.items()}
    live=read(roots[1]/'summary.json');dynamic=read(roots[0]/'summary.json')
    manifest=dict(stage='R055/R056 final extensions',files=hashes,dynamic_summary=dynamic,live_summary=live,
        prior_archives=sources['prior_archives'],
        note='Original Qwen studies remain separate archives. R055 partly endogenous fixed-tape sensitivities;R056 independent single cohort,not identified cross-model/count effect. Mock-only temporary test directories excluded. Documentation snapshot precedes final checksum closure.',
        recursive_configured_secret_checks=scanned)
    dest=BASE/'runs/final_extensions_20261108_evidence.zip';receipt=dest.with_name(dest.stem+'_manifest.json')
    assert not dest.exists() and not receipt.exists()
    with zipfile.ZipFile(dest,'x',zipfile.ZIP_DEFLATED) as z:
        for n,b in files.items():z.writestr(n,b)
        z.writestr('EVIDENCE_MANIFEST.json',json.dumps(manifest,indent=2))
    with zipfile.ZipFile(dest) as z:
        assert z.testzip() is None
        for n,h in hashes.items():assert hashlib.sha256(z.read(n)).hexdigest()==h,n
    result=dict(status='preserved',path=dest.relative_to(repo).as_posix(),sha256=digest(dest),bytes=dest.stat().st_size,
        exported_file_hashes=len(files),recursive_configured_secret_checks=scanned,all_member_hashes_verified=True,
        configured_secret_scan_passed=True,prior_archives_unchanged=len(sources['prior_archives']),
        prior_writing_archives_unchanged=len(sources['previous_writing_archives']),
        dynamic_paths=36,distinct_removal_paths=3,live_status=live['status'],fresh_decisions=live['delivered_decisions'],
        live_http_attempts=live['usage']['requests_made'])
    receipt.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8');print(json.dumps(result,indent=2))


if __name__=='__main__':main()
