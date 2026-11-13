"""R053 saved-evidence synthesis and terminal-mark identities; no simulation/API."""
import argparse
import csv
from hashlib import sha256
import json
from pathlib import Path
import yaml

BASE=Path(__file__).resolve().parents[1]


def read(path):return json.loads(path.read_text(encoding='utf-8'))
def rows(path):
    with path.open(newline='',encoding='utf-8') as f:return list(csv.DictReader(f))
def digest(path):return sha256(path.read_bytes()).hexdigest()


def analyze(output):
    inputs={};account_checks=[];aggregate_checks=[]
    def pin(path):inputs[path.relative_to(BASE).as_posix()]=digest(path);return path
    pin(Path(__file__))
    r39=read(pin(BASE/'runs/20261104_154730_market_validation_fff53e3b/report.json'))
    r41=read(pin(BASE/'runs/downside_confirmation_analysis_20261104/report.json'))
    r47=read(pin(BASE/'runs/common_prefix_analysis_20261105/report.json'))
    r50=read(pin(BASE/'runs/feedback_audit_20261106/report.json'))
    r51=read(pin(BASE/'runs/background_diversity_20261106/report.json'))
    r52=read(pin(BASE/'runs/feedback_validation_20261107/summary.json'))
    r52review=read(pin(BASE/'runs/feedback_validation_analysis_20261107_v2/report.json'))
    studies=[('R041',BASE/'runs/20261104_161605_downside_confirmation_1be3841b',r41,0,'full_horizon_evaluation'),
             ('R047',BASE/'runs/20261105_041035_common_prefix_ca10f93d',r47,5,'observed_postprefix')]
    for study,root,report,start,field in studies:
        for arm in report['arms']:
            path=root/arm['run_path'];prices=rows(pin(path/'prices.csv'));states=rows(pin(path/'agents_state.csv'))
            cfg=yaml.safe_load(pin(path/'config.yaml').read_text(encoding='utf-8'))
            assert cfg['market']['transaction_tax']==0
            initial=rows(pin(path/'initial_state.csv')) if not start else [r for r in states if int(r['round'])==start]
            opening={r['agent_id']:r for r in initial};end={r['agent_id']:r for r in states if int(r['round'])==len(prices)}
            assert len(opening)==len(end)==14
            accounts={a['agent_id']:a for a in arm[field]['accounts']}
            p=float(prices[-1]['price']);v=float(prices[-1]['fundamental']);rate=cfg['asset']['risk_free']
            aggregate={'auction':0.,'regime_benchmark':0.}
            for aid,a in sorted(opening.items()):
                cash=float(a['cash']);q0=int(a['shares']);w0=float(a['wealth'])
                for t in prices[start:]:cash=cash*(1+rate)+q0*float(t['dividend'])
                final=end[aid];q=int(final['shares']);active_cash=float(final['cash']);marks={}
                for mark,value in [('auction',p),('regime_benchmark',v)]:
                    excess=active_cash-cash+(q-q0)*value
                    assert abs(excess-accounts[aid]['marks'][mark]['active_minus_passive'])<1e-7
                    assert abs(excess/w0-accounts[aid]['marks'][mark]['excess_return'])<1e-10
                    marks[mark]=dict(excess_wealth=excess,excess_return=excess/w0)
                    aggregate[mark]+=excess
                lhs=marks['auction']['excess_return']-marks['regime_benchmark']['excess_return']
                rhs=(q-q0)*(p-v)/w0
                assert abs(lhs-rhs)<1e-10
                account_checks.append(dict(study=study,run_path=path.relative_to(BASE).as_posix(),agent_id=aid,start_session=start,
                    opening_auction_wealth=w0,opening_shares=q0,terminal_shares=q,terminal_price=p,terminal_reference=v,
                    marks=marks,mark_difference_pp=100*lhs,exposure_identity_pp=100*rhs,identity_residual=lhs-rhs,
                    signs_differ=marks['auction']['excess_return']*marks['regime_benchmark']['excess_return'] < -1e-16))
            assert all(abs(x)<1e-7 for x in aggregate.values())
            aggregate_checks.append(dict(study=study,run_path=path.relative_to(BASE).as_posix(),aggregate_excess_wealth=aggregate))
    assert len(account_checks)==560 and len(aggregate_checks)==40
    target_signs=sorted([a for a in account_checks if a['agent_id'] in ('llm_012','llm_013') and a['signs_differ']],
                        key=lambda a:(a['study'],a['run_path'],a['agent_id']))
    pairs=[]
    for c in r39['paired_contrasts']:
        pair={a['cell']:a for a in r39['runs'] if a['seed']==c['seed']}
        boundary={}
        for cell,a in pair.items():
            root=BASE/'runs/20261104_154730_market_validation_fff53e3b'/a['run_path']
            state=rows(pin(root/'agents_state.csv'))
            boundary[cell]=sum(r['type']=='MarketMakerAgent' and int(r['shares']) in (0,300) for r in state)/600
        pairs.append(dict(study='R039',seed=c['seed'],background='homogeneous',delta_acf1=c['delta_acf1'],
                          delta_boundary_pp=100*(boundary['no_skew']-boundary['original'])))
    for c in r51['contrasts']:
        for key,name in [('False','homogeneous'),('True','heterogeneous')]:
            d=c['no_skew_minus_skew'][key]
            pairs.append(dict(study='R051',seed=c['seed'],background=name,delta_acf1=d['acf_returns_lag1'],
                              delta_boundary_pp=100*d['mm_boundary_fraction']))
    assert len(pairs)==12 and len({p['seed'] for p in pairs})==8
    collapse={kind:dict(pairs=len(selected),account_difference=sum(bool(p['differing_rounds']['accounts']) for p in selected),
                       price_difference=sum(bool(p['differing_rounds']['price']) for p in selected),
                       account_difference_with_identical_prices=sum(bool(p['differing_rounds']['accounts']) and not p['differing_rounds']['price'] for p in selected))
              for kind in ('same_mode','cross_mode') if (selected:=[p for p in r50['pairs'] if p['kind']==kind])}
    gaps=[dict(prefix=c['prefix_id'],gap_difference_pp=100*c['Cmean_minus_Bmean_gap']) for c in r47['prefix_contrasts']]
    results=dict(scope='Post-hoc synthesis and accounting interpretation of saved completed studies;no new samples,markets or inferential test.',
        new_api_requests=0,new_markets=0,new_replay_executions=0,inputs_sha256=inputs,
        background_pairs=pairs,background_unit_note='R039four seeds;R051four different seeds crossed withtwo backgrounds. Separate protocols;12pairs are not12independent scenarios. No pooled effect estimate.',
        price_account_collapse=collapse,collapse_unit_note='36pairs reuse24R047branches in6contexts/3originalseeds;not36independent observations or causal mediation.',
        reflection_contexts=gaps,reflection_range_pp=[min(c['gap_difference_pp'] for c in gaps),max(c['gap_difference_pp'] for c in gaps)],
        account_identity_checks=account_checks,aggregate_identity_checks=aggregate_checks,
        max_identity_residual=max(abs(a['identity_residual']) for a in account_checks),
        max_aggregate_excess_residual=max(abs(x) for a in aggregate_checks for x in a['aggregate_excess_wealth'].values()),
        illustration_selection='First sorted(study,run_path,agent_id)target-account case with mark-dependent sign;illustration,not a new experiment or representative effect size.',
        illustration=target_signs[0] if target_signs else None,
        r052=dict(status=r52['status'],delivered=r52['delivered'],missing=len(r52['missing_slots']),totals=r52review['totals']))
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    (output/'report.json').write_text(json.dumps(results,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    lines=['# R053 saved-evidence ledger','',results['scope'],'',
           '|Study|Seed|Background|No-skew minus skew ACF1|Boundary-time change (pp)|',
           '|---|---:|---|---:|---:|']
    for p in pairs:lines.append(f"|{p['study']}|{p['seed']}|{p['background']}|{p['delta_acf1']:+.6f}|{p['delta_boundary_pp']:+.3f}|")
    lines+=['',results['background_unit_note'],'',
            'The terminal-mark identity matches all560account endpoints across40saved paths;aggregate passive excess cancels in each path. This is internal accounting verification,not an empirical discovery or realism validation.',
            '',results['collapse_unit_note']]
    (output/'READOUT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps(dict(account_endpoints=560,paths=40,illustration=results['illustration'],reflection_range_pp=results['reflection_range_pp'],collapse=collapse),indent=2))
    return results


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args();analyze(a.output)
