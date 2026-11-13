"""R051: frozen, zero-provider 2x2 background/skew sensitivity.

Separate commands freeze the design before any outcomes:
python -B -m research.background_diversity prepare --study runs/background_diversity_20261106
python -B -m research.background_diversity run --study runs/background_diversity_20261106
"""
import argparse
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import io
import json
from pathlib import Path
import platform
import socket
import subprocess
from unittest.mock import patch
import zipfile

import numpy as np
import yaml
from sim import engine
from sim.background_check import slot_recipe
from sim.config import parse_config
from sim.evaluation import evaluate_run,read_rows

BASE=Path(__file__).resolve().parents[1]
SEEDS=(26183,27329,28513,29671)
VERSION='R051_background_diversity_v1'


def read(p):return json.loads(p.read_text(encoding='utf-8'))
def digest(p):return sha256(p.read_bytes()).hexdigest()
def write(p,x):p.write_text(json.dumps(x,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def recipe(seed,heterogeneous,skew,rounds=600):
    cfg=slot_recipe(seed,skew=skew,rounds=rounds).to_dict()
    cfg['name']=f'diversity_{int(heterogeneous)}_skew_{int(skew*1000)}_s{seed}'
    if heterogeneous:
        groups=[]
        for i,g in enumerate(cfg['agents']):
            values=(.02,.03,.04) if i==2 else (3,4,6,7) if i==3 else None
            if values is None:groups.append(g);continue
            assert len(values)==g['count']
            for value in values:
                new=deepcopy(g);new['count']=1
                new['params']['delta' if i==2 else 'window']=value;groups.append(new)
        cfg['agents']=groups
    return parse_config(cfg)


def prepare(root):
    root=Path(root);root.mkdir(parents=True,exist_ok=False);(root/'configs').mkdir()
    arms=[]
    for seed in SEEDS:
        for heterogeneous in (False,True):
            for skew in (.02,0.):
                cfg=recipe(seed,heterogeneous,skew)
                p=root/'configs'/(cfg.name+'.yaml');p.write_text(yaml.safe_dump(cfg.to_dict()),encoding='utf-8')
                arms.append(dict(seed=seed,heterogeneous=heterogeneous,skew=skew,config=p.relative_to(root).as_posix(),sha256=digest(p)))
    files=sorted((BASE/'sim').rglob('*.py'))+sorted((BASE/'research').glob('*.py'))+[
        BASE/'configs/pilot_a_mock.yaml',BASE/'tests/test_background_diversity.py']
    hashes={p.relative_to(BASE).as_posix():digest(p) for p in files}
    with zipfile.ZipFile(root/'source.zip','x',zipfile.ZIP_DEFLATED) as z:
        for p in files:z.write(p,p.relative_to(BASE).as_posix())
    protocol=dict(version=VERSION,status='frozen_before_any_study_outcomes',created_utc=datetime.now(timezone.utc).isoformat(),
        parent_revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=BASE,text=True).strip(),
        working_tree_status=subprocess.check_output(['git','status','--short'],cwd=BASE,text=True).splitlines(),
        question='Does the inventory-skew/return-dependence trade-off survive one less synchronized background-policy bundle?',
        seeds=list(SEEDS),arms=arms,rounds=600,source_sha256=hashes,source_zip_sha256=digest(root/'source.zip'),
        primary='Per seed, no-skew minus skew.02 PRICE-return ACF1 under each background; heterogeneous minus homogeneous of these paired contrasts. Four independent exogenous scenarios; preserve every sign. No p-value, pass score or default selection.',
        secondary='MM0/300 boundary fraction,absolute-price-return ACF1,mean absolute benchmark gap,turnover,MMvolume share,cash growth,zero volume,actual order synchrony,200-session nested blocks and both-mark passive excess for all accounts.',
        intervention='Background F3 thresholds .02/.03/.04 instead of .03 each; M4 lookbacks3/4/6/7 instead of5 each. Mean thresholds/lookbacks retained but realized intensity need not be equal. This is a joint policy heterogeneity bundle,not isolated variance or a calibrated human population. F dividend_window stays1. Target F/M replacement slots unchanged.',
        controls='Same14account IDs/order/endowments,agent RNG positions,1450shares/160000cash,dividend path,auction/asset/rates and no news per seed. Rule-only. No LLM/provider/persona/prompt treatment. No live inference.',
        failure_policy='No restart into an existing execution; stop on first failed invariant and preserve partial outputs. No outcome-dependent extension,selected replacement seeds or tuning.',
        environment=dict(python=platform.python_version(),numpy=np.__version__,pyyaml=yaml.__version__),
        limitations='Four seed pairs per background;600 artificial sessions,rule-only. Dependence on this bundle cannot identify which component caused a difference. Longer-run stationarity,empirical realism and LLM effects remain unvalidated.')
    write(root/'protocol.json',protocol);write(root/'preparation.json',dict(protocol_sha256=digest(root/'protocol.json')))
    print(json.dumps(dict(status='prepared',study=str(root),markets=16,api_requests=0,protocol_sha256=digest(root/'protocol.json'))))


def describe(path):
    ev=evaluate_run(path);states=read_rows(path/'agents_state.csv');orders=read_rows(path/'orders.csv');prices=read_rows(path/'prices.csv')
    boundary=sum(r['type']=='MarketMakerAgent' and int(r['shares']) in (0,300) for r in states)/len(prices)
    sync={}
    for name,ids in [('fundamentalists',('fund_005','fund_006','fund_007')),('momentum',('mome_008','mome_009','mome_010','mome_011'))]:
        equal=active=active_equal=0
        for rnd in range(1,len(prices)+1):
            book=[r for r in orders if int(r['round'])==rnd and r['agent_id'] in ids]
            assert len(book)==len(ids)
            same=len({(r['side'],r['quantity'],r['limit_price']) for r in book})==1
            moving=any(r['side']!='hold' for r in book)
            equal+=same;active+=moving;active_equal+=same and moving
        sync[name]=dict(identical_fraction=equal/len(prices),active_sessions=active,identical_active_sessions=active_equal)
    from sim.evaluation import dependence
    returns=np.diff(np.log(np.r_[100.,[float(r['price']) for r in prices]]))
    blocks=[]
    for start in (0,200,400):
        selected=prices[start:start+200]
        blocks.append(dict(start=start+1,end=start+200,acf1=dependence(returns[start:start+200]),
            gap=float(np.mean([abs(float(r['price'])/float(r['fundamental'])-1) for r in selected])),
            mm_boundary_fraction=sum(r['type']=='MarketMakerAgent' and start<int(r['round'])<=start+200 and int(r['shares']) in (0,300) for r in states)/200))
    return dict(**ev['metrics'],mm_boundary_fraction=boundary,synchrony=sync,blocks=blocks,
                accounts=ev['accounts'],aggregate_active_minus_passive=ev['aggregate_active_minus_passive'])


def execute(root):
    root=Path(root);p=read(root/'protocol.json')
    assert digest(root/'protocol.json')==read(root/'preparation.json')['protocol_sha256']
    assert digest(root/'source.zip')==p['source_zip_sha256']
    assert all(digest(BASE/n)==h for n,h in p['source_sha256'].items())
    assert all(digest(root/a['config'])==a['sha256'] for a in p['arms'])
    with (root/'execution.json').open('x') as f:json.dump(dict(started_utc=datetime.now(timezone.utc).isoformat()),f)
    records=[];status='running';failure=None;network_attempts=[];controls={}
    def forbidden(*args,**kwargs):
        network_attempts.append('blocked');raise RuntimeError('R051 forbids network and model access')
    try:
        with patch.object(engine,'LLMClient',forbidden),patch.object(socket.socket,'connect',forbidden),patch.object(socket,'create_connection',forbidden):
            for arm in p['arms']:
                with redirect_stdout(io.StringIO()):path=Path(engine.run(root/arm['config'],output_root=root/'markets'))
                summary=read(path/'summary.json')
                assert summary['status']=='completed' and summary['rounds']==600 and summary['llm_usage']['requests_made']==0
                assert summary['max_cash_conservation_error']<1e-7 and summary['total_shares']==1450 and summary['initial_cash']==160000
                control=((path/'initial_state.csv').read_bytes(),[r['dividend'] for r in read_rows(path/'prices.csv')])
                if arm['seed'] in controls:assert controls[arm['seed']]==control
                else:controls[arm['seed']]=control
                result=describe(path)
                assert all(abs(v)<1e-7 for v in result['aggregate_active_minus_passive'].values())
                assert 0<=result['mm_inventory_min']<=result['mm_inventory_max']<=300
                records.append(dict(**arm,path=path.relative_to(root).as_posix(),manifest_sha256=digest(path/'manifest.json'),result=result))
                write(root/'runs.json',records);print(f"completed seed{arm['seed']} heterogeneous={arm['heterogeneous']} skew={arm['skew']}",flush=True)
        status='completed'
    except BaseException as exc:
        status='failed';failure=type(exc).__name__;raise
    finally:
        write(root/'summary.json',dict(status=status,completed=len(records),planned=16,failure=failure,api_requests=0,
              network_attempts=len(network_attempts),finished_utc=datetime.now(timezone.utc).isoformat()))
    contrasts=[]
    metrics=('acf_returns_lag1','acf_absolute_returns_lag1','mm_boundary_fraction','mean_absolute_relative_gap','turnover_per_round','volume_weighted_mm_share','aggregate_cash_growth','zero_volume_fraction')
    for seed in SEEDS:
        by={(a['heterogeneous'],a['skew']):a['result'] for a in records if a['seed']==seed}
        delta={str(h):{k:by[h,0.][k]-by[h,.02][k] for k in metrics} for h in (False,True)}
        contrasts.append(dict(seed=seed,no_skew_minus_skew=delta,interaction={k:delta['True'][k]-delta['False'][k] for k in metrics}))
    write(root/'report.json',dict(version=VERSION,protocol_sha256=digest(root/'protocol.json'),summary=read(root/'summary.json'),contrasts=contrasts,arms=records))
    lines=['# R051: background diversity sensitivity','',p['primary'],'',
           '|Seed|Homogeneous skew-removal ACF1 delta|Heterogeneous delta|Interaction|Homogeneous boundary delta pp|Heterogeneous boundary delta pp|',
           '|---|---:|---:|---:|---:|---:|']
    for c in contrasts:
        a,b=c['no_skew_minus_skew']['False'],c['no_skew_minus_skew']['True']
        lines.append(f"|{c['seed']}|{a['acf_returns_lag1']:+.6f}|{b['acf_returns_lag1']:+.6f}|{c['interaction']['acf_returns_lag1']:+.6f}|{100*a['mm_boundary_fraction']:+.3f}|{100*b['mm_boundary_fraction']:+.3f}|")
    lines+=['',p['intervention'],'',p['limitations'],'','All16 markets completed; no provider or network requests. Protocol/source/configs were frozen before these outcomes. All initial accounts and dividend paths match within seed. Full both-mark account outcomes and block diagnostics are in report.json.']
    (root/'READOUT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    write(root/'output_manifest.json',{x.relative_to(root).as_posix():digest(x) for x in root.rglob('*') if x.is_file() and x.name!='output_manifest.json'})


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=('prepare','run'));p.add_argument('--study',required=True);a=p.parse_args()
    (prepare if a.action=='prepare' else execute)(a.study)
