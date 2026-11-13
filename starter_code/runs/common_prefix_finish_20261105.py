"""Local-only R047 analysis,isolated replay,preservation and neutral diary receipt."""
import argparse
from datetime import datetime,timezone
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import zipfile
from sim.llm.client import dotenv_api_key
from sim.provenance import sha256,write_json
from runs import common_prefix_20261105 as d
from runs import common_prefix_analysis_20261105 as analysis


def replay(root,out):
    code=root/'verification_source';code.mkdir(exist_ok=False)
    with zipfile.ZipFile(root/'prepared_source.zip') as z:
        for member in z.namelist():
            target=(code/member).resolve();assert target.is_relative_to(code.resolve()) and member.endswith('.py')
            target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(z.read(member))
    command=[sys.executable,str(d.BASE/'runs/common_prefix_replay_20261105.py'),'--source',str(code),'--study',str(root),
        '--output',str(root/'verification_replays'),'--result',str(out/'replay_report.json')]
    result=subprocess.run(command,cwd=code,capture_output=True,text=True)
    (out/'replay.stdout.log').write_text(result.stdout);(out/'replay.stderr.log').write_text(result.stderr)
    assert result.returncode==0,'Isolated replay failed;raw evidence remains,inspect replay.stderr.log'
    return d.read(out/'replay_report.json')


def preserve(root,out):
    old=d.read(root/'prior_archives.json')
    for name,digest in old.items():assert sha256(d.BASE/'runs'/name)==digest
    paths=[p for folder in (root,out) for p in folder.rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    files={p.relative_to(d.BASE.parent).as_posix():p.read_bytes() for p in paths}
    secrets={v.encode() for name in ('API_KEY','BHARATCODE_API_KEY','GEMINI_API_KEY','NVIDIA_API_KEY') if (v:=dotenv_api_key(name)) and len(v)>=8}
    scanned=0
    def scan(name,data):
        nonlocal scanned
        assert '.env' not in Path(name).name and '.git' not in Path(name).parts
        assert not any(v in data for v in secrets),'Configured-secret export guard failed'
        scanned+=1
        if name.endswith('.zip'):
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                assert archive.testzip() is None
                for member in archive.namelist():scan(member,archive.read(member))
    for name,data in files.items():scan(name,data)
    manifest=dict(scope='R047 actual prefix/fresh branch data plus explicitly labelled offline verification;replay usage is not new provider usage.',
        files={name:hashlib.sha256(data).hexdigest() for name,data in files.items()},old_archives=old,recursive_configured_secret_members=scanned,
        note='Diary/checksum closure outside archive avoids circular hash. No .env or configured key exported.')
    archive=d.BASE/'runs/common_prefix_20261105_evidence.zip'
    with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as z:
        for name,data in files.items():z.writestr(name,data)
        z.writestr('EVIDENCE_MANIFEST.json',json.dumps(manifest,indent=2))
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        for name,digest in manifest['files'].items():assert hashlib.sha256(z.read(name)).hexdigest()==digest
    result=dict(path=archive.relative_to(d.BASE.parent).as_posix(),sha256=sha256(archive),bytes=archive.stat().st_size,
        exported_hashes=len(files),recursive_secret_checks=scanned,previous_archives_unchanged=len(old),all_member_hashes_verified=True)
    write_json(d.BASE/'runs/common_prefix_20261105_evidence_manifest.json',result);return result


def finish(root,out,*,append_diary=True):
    root=Path(root).resolve();out=Path(out).resolve();d.validate(root)
    report=analysis.analyze(root,out);verification=replay(root,out)
    shutil.copyfile(__file__,out/'finish_source.py')
    write_json(out/'artifact_manifest.json',{p.name:sha256(p) for p in out.iterdir() if p.is_file() and p.name!='artifact_manifest.json'})
    archive=preserve(root,out)
    status=dict(status='analyzed_replayed_and_preserved',finished_utc=datetime.now(timezone.utc).isoformat(),
        study_status=report['summary']['status'],summary=report['summary'],analysis=out.relative_to(d.BASE).as_posix(),verification=dict(verified_clean_paths=verification['verified_clean_paths'],not_replayed=verification['not_replayed'],network_attempts=verification['network_attempts']),evidence=archive,
        interpretation='Automated neutral readout,not visual/manual scientific interpretation or a claim of universal reflection/human realism.')
    write_json(root/'postprocessing_summary.json',status)
    if append_diary:
        text=['','',f"**R047 automated completion ({status['finished_utc']} UTC):**",'Study '+json.dumps(report['summary'])+'.',
            'Primary all-prefix contrasts and same-mode controls:'+str(out.relative_to(d.BASE))+'.',
            'Actual cached prefixes were not billed or counted as fresh independent observations.',
            'Replay summary:'+json.dumps(status['verification'])+'.', 'Archive:'+json.dumps(archive)+'.',
            'All raw partial/missing outcomes retained. Manual visual/scientific review remains;no model/default promotion or further study scheduled.','']
        with (d.BASE.parent/'RESEARCH_DIARY.md').open('a',encoding='utf-8') as stream:stream.write('\n'.join(text))
    return status


def watch(root,out):
    root=Path(root).resolve();out=Path(out).resolve();d.validate(root)
    with (root/'postprocessing_execution.json').open('x') as stream:json.dump(dict(pid=os.getpid(),started_utc=datetime.now(timezone.utc).isoformat()),stream)
    deadline=time.monotonic()+6*60*60
    try:
        while time.monotonic()<deadline:
            if (root/'summary.json').exists():return finish(root,out)
            time.sleep(20)
        raise TimeoutError('Original study summary missing;inspect job,never restart')
    except BaseException as exc:
        write_json(root/'postprocessing_failure.json',dict(error_type=type(exc).__name__,finished_utc=datetime.now(timezone.utc).isoformat(),action='Local completion stopped;original study not resumed or altered.'))
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--study',required=True);parser.add_argument('--output',required=True);args=parser.parse_args()
    print(json.dumps(watch(args.study,args.output)),flush=True)
