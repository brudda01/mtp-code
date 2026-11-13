"""Independent arithmetic checks of R050/R051 saved evidence; no simulation/API.

Writes a new receipt only when --output is supplied (refuses an existing file).
"""
import argparse
import csv
from hashlib import sha256
import json
import math
from pathlib import Path

BASE=Path(__file__).resolve().parents[1]


def read(p):return json.loads(p.read_text(encoding='utf-8'))
def rows(p):
    with p.open(newline='',encoding='utf-8') as f:return list(csv.DictReader(f))
def digest(p):return sha256(p.read_bytes()).hexdigest()
def correlation(values):
    mean=sum(values)/len(values);x=[v-mean for v in values]
    return sum(a*b for a,b in zip(x,x[1:]))/sum(a*a for a in x)


def check():
    root=BASE/'runs/background_diversity_20261106';report=read(root/'report.json');protocol=read(root/'protocol.json')
    assert digest(root/'protocol.json')==report['protocol_sha256']==read(root/'preparation.json')['protocol_sha256']
    assert all(digest(BASE/n)==h for n,h in protocol['source_sha256'].items())
    assert digest(root/'source.zip')==protocol['source_zip_sha256']
    for name,h in read(root/'output_manifest.json').items():assert digest(root/name)==h,name
    assert report['summary']['completed']==16 and report['summary']['network_attempts']==0
    checks=0;max_error=0.;computed={}
    for arm in report['arms']:
        p=root/arm['path'];assert digest(root/arm['config'])==arm['sha256']
        prices=rows(p/'prices.csv');states=rows(p/'agents_state.csv');trades=rows(p/'trades.csv')
        initial=rows(p/'initial_state.csv');accounts={r['agent_id']:(float(r['cash']),int(r['shares'])) for r in initial}
        assert len(accounts)==14 and len(prices)==600
        state_lookup={(int(r['round']),r['agent_id']):r for r in states}
        trades_by_round={}
        for t in trades:trades_by_round.setdefault(int(t['round']),[]).append(t)
        for pr in prices:
            rnd=int(pr['round']);tt=trades_by_round.get(rnd,[]);d=float(pr['dividend'])
            assert sum(int(t['quantity']) for t in tt)==int(pr['volume'])
            for aid,(cash,shares) in list(accounts.items()):
                for t in tt:
                    q=int(t['quantity']);value=q*float(t['price'])
                    if t['buyer_id']==aid:cash-=value;shares+=q
                    if t['seller_id']==aid:cash+=value;shares-=q
                expected_cash=cash*(1+.0002)+shares*d
                row=state_lookup[rnd,aid]
                error=abs(expected_cash-float(row['cash']));max_error=max(error,max_error)
                assert error<1e-7 and shares==int(row['shares']) and cash>=-1e-7 and shares>=0
                assert abs(float(row['wealth'])-(expected_cash+shares*float(pr['price'])))<1e-7
                accounts[aid]=(expected_cash,shares);checks+=1
            assert sum(s for c,s in accounts.values())==1450
        pp=[100.]+[float(r['price']) for r in prices]
        ret=[math.log(b/a) for a,b in zip(pp,pp[1:])]
        value=correlation(ret);assert abs(value-arm['result']['acf_returns_lag1'])<1e-12
        bounds=sum(r['type']=='MarketMakerAgent' and int(r['shares']) in (0,300) for r in states)/600
        assert bounds==arm['result']['mm_boundary_fraction']
        computed[arm['seed'],arm['heterogeneous'],arm['skew']]=(value,bounds)
    for c in report['contrasts']:
        seed=c['seed'];delta=[]
        for h in (False,True):
            v=computed[seed,h,0.][0]-computed[seed,h,.02][0]
            assert abs(v-c['no_skew_minus_skew'][str(h)]['acf_returns_lag1'])<1e-12;delta.append(v)
        assert abs(delta[1]-delta[0]-c['interaction']['acf_returns_lag1'])<1e-12
    audit=BASE/'runs/feedback_audit_20261106';saved=read(audit/'report.json');ledger=read(audit/'reflection_ledger.json')
    for n,h in saved['inputs_sha256'].items():assert digest(BASE/n)==h,n
    for r in ledger:
        c=json.loads((BASE/r['source']).read_text(encoding='utf-8').splitlines()[r['line']-1])
        assert r['messages']==c['messages'] and r['reflection_raw']==c['raw']
    assert len(ledger)==48 and len(saved['pairs'])==36
    # Confirm account-trajectory distinctness is not just floating-point noise.
    original=BASE/'runs/20261105_041035_common_prefix_ca10f93d';arms=read(original/'runs.json')
    for item in saved['distinct_paths']:
        for field in ('price','accounts'):
            signatures=[]
            for a in arms:
                if a['prefix_id']!=item['prefix']:continue
                p=original/a['run_path']
                if field=='price':s=tuple(float(r['price']) for r in rows(p/'prices.csv') if int(r['round'])>5)
                else:s=tuple((r['agent_id'],int(r['shares']),round(float(r['cash']),5)) for r in rows(p/'agents_state.csv') if int(r['round'])>5 and r['agent_id'] in ('llm_012','llm_013'))
                signatures.append(s)
            assert len(set(signatures))==item[field],(item,field)
    review=read(audit/'reflection_review.json')
    assert len(review['annotations'])==48
    for a in review['annotations']:
        r=ledger[a['ledger_index']]
        assert a['source_sha256']==digest(BASE/r['source'])
        for q in a['evidence_quotes']:assert q in r['reflection_raw']
    return dict(status='passed',account_rounds_independently_reconstructed=checks,max_cash_error=max_error,
                new_rule_markets=16,rule_sessions=9600,reflection_records_source_checked=48,
                dependent_pair_records=36,account_distinctness_survives_cash_rounding_to_5_decimals=True,
                all_source_config_output_hashes_match=True,new_api_requests=0,new_replay_executions=0)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output');a=p.parse_args();result=check()
    if a.output:
        with Path(a.output).open('x',encoding='utf-8') as f:json.dump(result,f,indent=2)
    print(json.dumps(result,indent=2))
