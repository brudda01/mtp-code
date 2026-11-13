"""Seal completed two-seed evidence and final substantive manuscript; no live work."""
import hashlib,io,json,zipfile
from pathlib import Path
from research.order_influence import BASE,read,digest
from research.goedel_cohort import validate
from sim.llm.client import dotenv_api_key


def main():
    repo=BASE.parent;sources=read(repo/'thesis/sources.json');checks=read(repo/'thesis/checks.json')
    assert checks['writing_stage']=='R058 completed replication and final substantive draft'
    assert read(repo/'DATA_COLLECTION_AUTHORIZATION.json')['status']=='closed_after_seed31991'
    names=('dynamic_order_tape_20261108','goedel_cohort_20261108','goedel_second_seed_20261108','goedel_second_seed_retry_20261108',
        'goedel_seed2_backoff_20261109','goedel_seed2_detached_20261109','goedel_seed2_expbackoff_20261109','goedel_seed2_full25_20261109','goedel_seed2_final_20261109','goedel_seed2_finish25_20261109')
    paths=list((repo/'thesis').rglob('*'))+list((repo/'archive/early_proposals').rglob('*'))
    for name in names:
        root=BASE/'runs'/name;p=validate(root);paths+=list(root.rglob('*'))
        paths += [BASE/n for n in {*p['inputs_sha256'],*p['source_sha256']}]
        if (root/'output_manifest.json').exists():
            for n,h in read(root/'output_manifest.json').items():assert digest(root/n)==h,n
    for name in ('dynamic_order_analysis_20261108','goedel_cohort_analysis_20261108','provider_docs_20261108','final_extensions_review_20261108','final_collection_analysis_20261108','final_collection_verification_20261108','deepseek_completed_analysis_20261109','deepseek_completed_review_20261109'):
        paths+=list((BASE/'runs'/name).rglob('*'))
    for n,h in sources['local_sha256'].items():assert digest(repo/n)==h,n
    for n,h in sources['prior_archives'].items():assert digest(BASE/'runs'/n)==h,n
    for n,h in sources['previous_writing_archives'].items():assert digest(repo/n)==h,n
    for n,h in read(repo/'thesis/artifact_manifest.json')['files'].items():assert digest(repo/'thesis'/n)==h,n
    paths += [repo/n for n in ('README.md','THESIS_RESULTS.md','AGENTS.md','RESEARCH_DIARY.md','WORK_PLAN.tmp.md','DATA_COLLECTION_FROZEN.md','DATA_COLLECTION_FROZEN.json','DATA_COLLECTION_AUTHORIZATION.json','DATA_COLLECTION_STATUS.md')]
    paths += [BASE/'research'/n for n in ('analyze_final_extensions.py','analyze_final_collection.py','analyze_completed_deepseek.py','summarize_completed_deepseek.py','preserve_completed_thesis.py')]
    paths += [BASE/n for n in ('requirements.txt','research/__init__.py','tests/__init__.py') if (BASE/n).exists()]
    files={p.relative_to(repo).as_posix():p.read_bytes() for p in sorted(set(paths)) if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc'}
    secrets={v.encode() for key in ('API_KEY','BHARATCODE_API_KEY','GEMINI_API_KEY','NVIDIA_API_KEY','OPENAI_API_KEY','ANTHROPIC_API_KEY','GODEL_MACHINES_API_KEY') if (v:=dotenv_api_key(key)) and len(v)>=8};scanned=0
    def scan(name,data):
        nonlocal scanned
        assert '.env' not in Path(name).name and '.git' not in Path(name).parts
        assert not any(s in data for s in secrets),'Configured secret found; no export'
        scanned+=1
        if name.endswith('.zip'):
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                assert z.testzip() is None
                for n in z.namelist():scan(n,z.read(n))
    for n,b in files.items():scan(n,b)
    hashes={n:hashlib.sha256(b).hexdigest() for n,b in files.items()}
    dest=BASE/'runs/completed_thesis_20261109_evidence.zip';receipt=dest.with_name(dest.stem+'_manifest.json')
    assert not dest.exists() and not receipt.exists()
    manifest=dict(stage=checks['writing_stage'],files=hashes,prior_archives=sources['prior_archives'],recursive_configured_secret_checks=scanned,
        note='Two completed DeepSeek paths. Seed31991 recovered through successful-prefix-preserving continuations. All retained errors and partial stages included; no replay usage counted as fresh. Main scientific archives remain separate. Documentation snapshot precedes final checksum closure.')
    with zipfile.ZipFile(dest,'x',zipfile.ZIP_DEFLATED) as z:
        for n,b in files.items():z.writestr(n,b)
        z.writestr('EVIDENCE_MANIFEST.json',json.dumps(manifest,indent=2))
    with zipfile.ZipFile(dest) as z:
        assert z.testzip() is None
        for n,h in hashes.items():assert hashlib.sha256(z.read(n)).hexdigest()==h,n
    result=dict(status='preserved',path=dest.relative_to(repo).as_posix(),sha256=digest(dest),bytes=dest.stat().st_size,
        exported_file_hashes=len(files),recursive_configured_secret_checks=scanned,all_member_hashes_verified=True,configured_secret_scan_passed=True,
        prior_archives_unchanged=len(sources['prior_archives']),prior_writing_archives_unchanged=len(sources['previous_writing_archives']),
        completed_deepseek_scenarios=2,completed_market_decisions=300,seed31991_market_chain_actual_http=488,
        collection_status='closed',formatting='deferred')
    receipt.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8');print(json.dumps(result,indent=2))


if __name__=='__main__':main()
