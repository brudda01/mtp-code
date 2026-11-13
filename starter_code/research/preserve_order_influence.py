"""Seal R054 conditional calculations, direct financial inputs and writing."""
import hashlib
import io
import json
from pathlib import Path
import zipfile
from research.order_influence import BASE,read,digest,validate
from sim.llm.client import dotenv_api_key


def main():
    repo=BASE.parent;study=BASE/'runs/order_influence_20261107'
    protocol=validate(study);sources=read(repo/'thesis/sources.json')
    assert read(repo/'thesis/checks.json')['writing_stage']=='R054 conditional LLM order influence'
    for n,h in sources['local_sha256'].items():assert digest(repo/n)==h,n
    for n,h in sources['prior_archives'].items():assert digest(BASE/'runs'/n)==h,n
    for n,h in sources['previous_writing_archives'].items():assert digest(repo/n)==h,n
    for n,h in read(repo/'thesis/artifact_manifest.json')['files'].items():assert digest(repo/'thesis'/n)==h,n
    paths=list((repo/'thesis').rglob('*'))+list(study.rglob('*'))
    for name in ('order_influence_analysis_20261107','order_influence_analysis_20261107_v2','order_influence_review_20261108'):
        paths+=list((BASE/'runs'/name).rglob('*'))
    paths += [BASE/n for n in protocol['inputs_sha256']]
    paths += [repo/n for n in ('THESIS_RESULTS.md','AGENTS.md','RESEARCH_DIARY.md','WORK_PLAN.tmp.md')]
    paths += [BASE/'research'/n for n in ('order_influence.py','analyze_order_influence.py','preserve_order_influence.py')]
    paths += [BASE/'tests'/n for n in ('test_order_influence.py','test_order_influence_analysis.py')]
    paths += [BASE/'requirements.txt']
    files={p.relative_to(repo).as_posix():p.read_bytes() for p in sorted(set(paths))
           if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc'}
    keys=('API_KEY','BHARATCODE_API_KEY','GEMINI_API_KEY','NVIDIA_API_KEY','OPENAI_API_KEY','ANTHROPIC_API_KEY')
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
    manifest=dict(stage='R054 conditional order influence',files=hashes,
        factual_auctions=216,counterfactual_clears=432,existing_exogenous_seeds=3,
        new_api_requests=0,new_endogenous_markets=0,new_model_samples=0,
        prior_archives=sources['prior_archives'],
        note='Direct R043 financial/config inputs and R054 frozen source/outputs included. Original full prompts/replies remain in separate R043 archive. Documentation snapshot precedes final checksum closure.',
        recursive_configured_secret_checks=scanned)
    dest=BASE/'runs/order_influence_20261108_evidence.zip';receipt=dest.with_name(dest.stem+'_manifest.json')
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
        new_api_requests=0,new_endogenous_markets=0,new_model_samples=0,counterfactual_clears=432)
    receipt.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8');print(json.dumps(result,indent=2))


if __name__=='__main__':main()
