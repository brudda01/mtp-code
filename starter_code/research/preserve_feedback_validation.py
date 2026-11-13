"""Seal R052's stopped attempt and missing evidence; no provider calls."""
import io
import json
from pathlib import Path
import zipfile

from research import feedback_validation as f
from research.feedback_validation_review import inspect
from sim.llm.client import dotenv_api_key


def main():
    root=f.BASE/'runs/feedback_validation_20261107';repo=f.BASE.parent
    verified=inspect(root)
    assert verified['provider_status']=='stopped' and verified['delivered']==8
    sources=f.read(repo/'thesis/sources.json')
    for n,h in sources['prior_archives'].items():assert f.digest(f.BASE/'runs'/n)==h,n
    for n,h in sources['previous_writing_archives'].items():assert f.digest(repo/n)==h,n
    folders=('feedback_validation_20261107','feedback_validation_preflight_20261107',
             'feedback_validation_review_20261107','feedback_validation_packet_20261107',
             'feedback_validation_analysis_20261107','feedback_validation_analysis_20261107_v2')
    paths=[p for name in folders for p in (f.BASE/'runs'/name).rglob('*')]
    paths+=list((repo/'thesis').rglob('*'))
    paths += [f.BASE/n for n in f.read(root/'protocol.json')['inputs_sha256']]
    paths += [f.BASE/'research'/n for n in ('feedback_validation.py','feedback_validation_review.py',
              'feedback_validation_analysis.py','preserve_feedback_validation.py')]
    paths += [f.BASE/'tests/test_feedback_validation.py',f.BASE/'requirements.txt']
    paths += [repo/n for n in ('AGENTS.md','RESEARCH_DIARY.md','WORK_PLAN.tmp.md')]
    files={p.relative_to(repo).as_posix():p.read_bytes() for p in sorted(set(paths))
           if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc'}
    keys=('API_KEY','BHARATCODE_API_KEY','GEMINI_API_KEY','NVIDIA_API_KEY','OPENAI_API_KEY','ANTHROPIC_API_KEY')
    secrets={v.encode() for key in keys if (v:=dotenv_api_key(key)) and len(v)>=8};count=0

    def scan(name,data):
        nonlocal count
        assert '.env' not in Path(name).name and '.git' not in Path(name).parts
        assert not any(s in data for s in secrets),'Configured secret guard failed;no export'
        count+=1
        if name.endswith('.zip'):
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                assert z.testzip() is None
                for member in z.namelist():scan(member,z.read(member))

    for name,data in files.items():scan(name,data)
    import hashlib
    hashes={n:hashlib.sha256(data).hexdigest() for n,data in files.items()}
    destination=f.BASE/'runs/feedback_validation_20261107_evidence.zip'
    receipt=destination.with_name(destination.stem+'_manifest.json')
    assert not destination.exists() and not receipt.exists()
    manifest=dict(scope='R052stopped8/48fixed-historyreflectioncomparison;40missing;not efficacy/equivalence evidence',
                  files=hashes,verification=verified,prior_archives=sources['prior_archives'],
                  previous_writing_archives=sources['previous_writing_archives'],recursive_configured_secret_checks=count,
                  note='Alloriginalrawattempts/frozeninputs and manualcoding retained;initialanalysis retained with finalv2missingcells. Documentation snapshot precedes finalchecksumclosure. Earlier fullcampaign archives remain separate.')
    with zipfile.ZipFile(destination,'x',zipfile.ZIP_DEFLATED) as z:
        for n,data in files.items():z.writestr(n,data)
        z.writestr('EVIDENCE_MANIFEST.json',json.dumps(manifest,indent=2))
    with zipfile.ZipFile(destination) as z:
        assert z.testzip() is None
        for n,h in hashes.items():assert hashlib.sha256(z.read(n)).hexdigest()==h,n
    result=dict(status='preserved_partial_stopped_attempt',path=destination.relative_to(repo).as_posix(),
                sha256=f.digest(destination),bytes=destination.stat().st_size,exported_file_hashes=len(files),
                recursive_configured_secret_checks=count,all_member_hashes_verified=True,
                configured_secret_scan_passed=True,prior_scientific_archives_unchanged=len(sources['prior_archives']),
                prior_writing_archives_unchanged=len(sources['previous_writing_archives']),
                delivered_reflections=8,missing_reflections=40,http_attempts=10,new_markets=0)
    f.write(receipt,result);print(json.dumps(result,indent=2))


if __name__=='__main__':main()
