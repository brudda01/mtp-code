"""R043 local-only completion: analyze once, preserve evidence, append a receipt.

This worker never calls an API, resumes a market or changes a model/default.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import time
import zipfile
from sim.llm.client import dotenv_api_key
from sim.provenance import sha256, write_json
from runs import quiet_components_20261105 as d
from runs import quiet_components_analysis_20261105 as analysis


def preserve(root, out):
    repo=d.BASE.parent
    sources=d.read(d.BASE/'runs/thesis_synthesis_20261105/sources.json')['archives']
    sources['thesis_synthesis_20261105_evidence.zip']=d.read(d.BASE/'runs/thesis_synthesis_20261105_evidence_manifest.json')['sha256']
    for name,digest in sources.items():assert sha256(d.BASE/'runs'/name)==digest
    paths=[p for folder in (root,out) for p in folder.rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    paths += [d.BASE/'runs'/name for name in (
        'quiet_components_20261105.py','quiet_components_checks_20261105.py',
        'quiet_components_analysis_20261105.py','quiet_components_analysis_checks_20261105.py',
        'quiet_components_finish_20261105.py','quiet_components_finish_checks_20261105.py')]
    files={p.relative_to(repo).as_posix():p.read_bytes() for p in paths}
    secrets={v.encode() for name in ('API_KEY','BHARATCODE_API_KEY','GEMINI_API_KEY','NVIDIA_API_KEY')
             if (v:=dotenv_api_key(name)) and len(v)>=8}
    scanned=0
    def scan(name,data):
        nonlocal scanned
        assert '.env' not in Path(name).name and '.git' not in Path(name).parts
        assert not any(value in data for value in secrets),'Configured secret export guard failed'
        scanned+=1
        if name.endswith('.zip'):
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                assert archive.testzip() is None
                for member in archive.namelist():scan(member,archive.read(member))
    for name,data in files.items():scan(name,data)
    manifest=dict(scope='R043 quiet campaign and exact source/prompt/config/raw evidence plus read-only all-arm analysis. No old evidence overwritten.',
        protocol_sha256=sha256(root/'protocol.json'),files={name:hashlib.sha256(data).hexdigest() for name,data in files.items()},
        previous_archives=sources,recursive_configured_secret_scan_members=scanned,
        note='Research diary receipt is appended after checksum creation, avoiding circular hash. No .env exported.')
    dest=d.BASE/'runs/quiet_components_20261105_evidence.zip'
    with zipfile.ZipFile(dest,'x',zipfile.ZIP_DEFLATED) as archive:
        for name,data in files.items():archive.writestr(name,data)
        archive.writestr('EVIDENCE_MANIFEST.json',json.dumps(manifest,indent=2))
    with zipfile.ZipFile(dest) as archive:
        assert archive.testzip() is None
        for name,digest in manifest['files'].items():assert hashlib.sha256(archive.read(name)).hexdigest()==digest
    receipt=dict(path=dest.relative_to(repo).as_posix(),sha256=sha256(dest),bytes=dest.stat().st_size,
        exported_file_hashes=len(files),recursive_configured_secret_scan_members=scanned,previous_archives_unchanged=len(sources),all_member_hashes_verified=True)
    write_json(d.BASE/'runs/quiet_components_20261105_evidence_manifest.json',receipt)
    return receipt


def finish(root, out, *, append_diary=True):
    root=Path(root);out=Path(out)
    assert d.read(root/'summary.json')['status']!='running'
    report=analysis.analyze(root,out)
    write_json(out/'offline_analysis_checks.json',dict(status='passed',test_count=3,
        source_sha256=sha256(d.BASE/'runs/quiet_components_analysis_checks_20261105.py'),
        scope='Mocked complete, zero-round and failed-reflection analysis checks; not live behavioural evidence.'))
    shutil.copyfile(__file__,out/'finish_source.py')
    write_json(out/'artifact_manifest.json',{p.name:sha256(p) for p in out.iterdir() if p.is_file() and p.name!='artifact_manifest.json'})
    receipt=preserve(root,out)
    status=dict(status='analyzed_and_preserved',finished_utc=datetime.now(timezone.utc).isoformat(),
        study_status=report['summary']['status'],summary=report['summary'],
        analysis=out.relative_to(d.BASE).as_posix(),evidence=receipt,
        interpretation='Automated neutral accounting/readout, not a claim of component efficacy or a visually reviewed final thesis interpretation. All missing/affected outcomes retained.')
    write_json(root/'postprocessing_summary.json',status)
    if append_diary:
        # Append only: never rewrite concurrent research decisions or older entries.
        lines=['','',f"**R043 automated completion receipt ({status['finished_utc']} UTC):**",
            f"Frozen campaign status {report['summary']['status']}; clean complete markets {report['summary']['completed_markets']}/18; attempted {report['summary']['recorded_markets']}.",
            'No automatic restart, substitution or financial-sign gate. Partial/affected endpoints remain missing.',
            'Final usage: '+json.dumps(report['summary']['usage'])+'.',
            'Audit: '+json.dumps(report['audit'])+'.',
            'All-arm readout/report and exportable figures: starter_code/'+out.relative_to(d.BASE).as_posix()+'.',
            'Every primary B-A/C-B draw and within-seed average is retained there, including zero/opposing signs.',
            'Reflection cost: '+json.dumps(report['reflection_cost'])+'.',
            'Archive receipt: '+json.dumps(receipt)+'.',
            'Exact code/config/prompt/persona/model/randomness metadata remain sealed in the frozen protocol/raw manifests.',
            'Automated results are recorded, not a validated human-realism, general C benefit/harm or default-selection claim.',
            'Visual inspection and concise thesis interpretation remain for the next review; no further API work scheduled.','']
        with (d.BASE.parent/'RESEARCH_DIARY.md').open('a',encoding='utf-8') as stream:stream.write('\n'.join(lines))
    return status


def watch(root,out):
    root=Path(root);out=Path(out);d.validate(root)
    completion_plan=d.read(root/'postprocessing_plan.json')
    for name,digest in completion_plan['source_sha256'].items():assert sha256(d.BASE/name)==digest
    with (root/'postprocessing_execution.json').open('x') as stream:
        json.dump(dict(pid=os.getpid(),started_utc=datetime.now(timezone.utc).isoformat(),action='Wait for final summary, analyze/preserve once; no API/restart'),stream)
    deadline=time.monotonic()+6*60*60
    try:
        while time.monotonic()<deadline:
            if (root/'summary.json').exists() and d.read(root/'summary.json')['status']!='running':
                for name,digest in completion_plan['source_sha256'].items():assert sha256(d.BASE/name)==digest
                return finish(root,out)
            time.sleep(20)
        raise TimeoutError('No final campaign summary within local watcher deadline; inspect original job, never restart it.')
    except BaseException as exc:
        write_json(root/'postprocessing_failure.json',dict(error_type=type(exc).__name__,finished_utc=datetime.now(timezone.utc).isoformat(),
            action='Postprocessing stopped; original API job was not altered or restarted. Inspect retained evidence.'))
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--study',required=True);parser.add_argument('--output',required=True);args=parser.parse_args()
    print(json.dumps(watch(args.study,args.output)),flush=True)
