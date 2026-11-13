"""Replay R051 from its frozen source ZIP and compare all seven financial files.

Only creates a new output directory; worker network and provider access blocked.
"""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

BASE=Path(__file__).resolve().parents[1]
STUDY=BASE/'runs/background_diversity_20261106'
FINANCIAL=('initial_state.csv','prices.csv','orders.csv','trades.csv','agents_state.csv','cashflows.csv','liquidity.csv')


def worker(study,source,output):
    sys.path.insert(0,str(source))
    import contextlib
    import io
    import socket
    from unittest.mock import patch
    from sim import engine
    assert Path(engine.__file__).resolve().is_relative_to(source.resolve())
    report=json.loads((study/'report.json').read_text());records=[];attempts=[]
    def forbid(*args,**kwargs):
        attempts.append('blocked');raise RuntimeError('Replay forbids network/provider calls')
    with patch.object(socket.socket,'connect',forbid),patch.object(socket,'create_connection',forbid),patch.object(engine,'LLMClient',forbid):
        for arm in report['arms']:
            with contextlib.redirect_stdout(io.StringIO()):p=Path(engine.run(study/arm['config'],output_root=output/'markets'))
            matches={n:(p/n).read_bytes()==(study/arm['path']/n).read_bytes() for n in FINANCIAL}
            assert all(matches.values()),(arm['seed'],matches)
            records.append(dict(seed=arm['seed'],heterogeneous=arm['heterogeneous'],skew=arm['skew'],path=p.relative_to(output).as_posix(),files=matches))
            print(f"verified {len(records)}/16",flush=True)
    result=dict(status='passed',verified_paths=len(records),byte_identical_financial_files=sum(len(r['files']) for r in records),
                network_attempts=len(attempts),new_api_requests=0,new_scientific_markets=0,records=records,
                scope='New local deterministic reproduction from frozen sources,not independent-machine reproduction or fresh scientific scenarios.')
    (output/'receipt.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')


def launch(output):
    output=Path(output).resolve()
    if not output.is_relative_to((BASE/'runs').resolve()):raise ValueError('output must be within starter_code/runs')
    output.mkdir(parents=True,exist_ok=False);source=output/'frozen_source';source.mkdir()
    protocol=json.loads((STUDY/'protocol.json').read_text())
    data=(STUDY/'source.zip').read_bytes()
    assert sha256(data).hexdigest()==protocol['source_zip_sha256']
    with zipfile.ZipFile(STUDY/'source.zip') as z:
        assert set(z.namelist())==set(protocol['source_sha256'])
        for name,h in protocol['source_sha256'].items():
            target=(source/name).resolve()
            if not target.is_relative_to(source):raise ValueError('archive path escapes extraction root')
            b=z.read(name);assert sha256(b).hexdigest()==h
            target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(b)
    env={k:v for k,v in os.environ.items() if not any(s in k.upper() for s in ('API_KEY','TOKEN','SECRET','PASSWORD'))}
    env['PYTHONDONTWRITEBYTECODE']='1'
    args=[sys.executable,'-B',str(Path(__file__).resolve()),'--worker','--output',str(output)]
    with (output/'stdout.log').open('w',encoding='utf-8') as stdout,(output/'stderr.log').open('w',encoding='utf-8') as stderr:
        result=subprocess.run(args,cwd=source,env=env,stdout=stdout,stderr=stderr)
    if result.returncode:
        (output/'failure.json').write_text(json.dumps(dict(returncode=result.returncode)))
        raise RuntimeError('Frozen replay failed;logs preserved')
    receipt=json.loads((output/'receipt.json').read_text());print(json.dumps({k:v for k,v in receipt.items() if k!='records'}))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--worker',action='store_true');a=p.parse_args()
    out=Path(a.output).resolve()
    if a.worker:worker(STUDY,out/'frozen_source',out)
    else:launch(out)
