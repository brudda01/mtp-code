"""R046: archived-source replay and post-hoc diagnostic audit, zero live calls."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

BASE=Path(__file__).resolve().parents[1]
OUT=BASE/'runs/examiner_audit_20261105_v2'
WORKER=BASE/'runs/examiner_replay_worker_20261105.py'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
STUDIES=[('R039','20261104_154730_market_validation_fff53e3b','report.json','none'),
    ('R041','20261104_161605_downside_confirmation_1be3841b','runs.json','downside'),
    ('R043','20261105_012335_quiet_components_5066abab','runs.json','quiet')]


def main(output=None):
    global OUT
    if output is not None:
        OUT=Path(output).resolve()
        assert OUT.is_relative_to((BASE/'runs').resolve())
    OUT.mkdir(exist_ok=False)
    shutil.copyfile(__file__,OUT/'audit_source.py');shutil.copyfile(WORKER,OUT/'replay_worker.py')
    records=[]
    for label,name,index,adapter in STUDIES:
        root=BASE/'runs'/name;dest=OUT/label;dest.mkdir()
        code=dest/'snapshot_code';code.mkdir()
        p=json.loads((root/'protocol.json').read_text());archive=root/'prepared_source.zip'
        assert sha(archive)==p.get('source_zip_sha256',p.get('source_archive_sha256'))
        with zipfile.ZipFile(archive) as z:
            for member in z.namelist():
                target=(code/member).resolve();assert target.is_relative_to(code.resolve()) and member.endswith(('.py','.yaml'))
                target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(z.read(member))
        def run(attempt):
            path=dest/(attempt+'.json')
            command=[sys.executable,str(WORKER),'--source',str(code),'--study',str(root),'--index',str(root/index),
                '--output',str(dest/attempt),'--result',str(path),'--adapter',adapter]
            process=subprocess.run(command,cwd=code,text=True,capture_output=True)
            (dest/(attempt+'.stdout.log')).write_text(process.stdout)
            (dest/(attempt+'.stderr.log')).write_text(process.stderr)
            return json.loads(path.read_text())
        first=run('original_bundle')
        record=dict(study=label,source_zip_sha256=sha(archive),original_bundle_result=first)
        if first['status']=='failed':
            assert label=='R043' and first['error_type']=='ModuleNotFoundError' and 'runs.sequential_next_20261103' in first['error']
            assert not first['markets'] and first['network_attempts']==0
            # Explicit linked dependency supplement from a PREVIOUS archived
            # source,not the mutable working tree; preserve the original failure.
            dependency='runs/sequential_next_20261103.py'
            previous=BASE/'runs/20261104_161605_downside_confirmation_1be3841b/prepared_source.zip'
            with zipfile.ZipFile(previous) as z:data=z.read(dependency)
            target=code/dependency;target.write_bytes(data)
            checkpoint=json.loads((BASE/'runs/thesis_synthesis_20261105/start_state.json').read_text())
            digest=hashlib.sha256(data).hexdigest()
            assert digest==checkpoint['sha256']['starter_code/'+dependency]
            record['dependency_supplement']=dict(file=dependency,sha256=digest,from_archive=str(previous),
                source_archive_sha256=sha(previous),reason='Transitive import missing from original prepared source ZIP;imports an unused continuation helper via horizon adapter.')
            record['supplemented_result']=run('with_archived_dependency')
            assert record['supplemented_result']['status']=='passed'
        else:assert first['status']=='passed'
        records.append(record)
        (OUT/'replay_report.json').write_text(json.dumps(dict(scope='Exact offline recorded-reply replay,not independent behavioural replication',studies=records),indent=2)+'\n')
        print(label, 'verified',len(record.get('supplemented_result',first)['markets']),'markets',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output');args=parser.parse_args()
    main(args.output)
