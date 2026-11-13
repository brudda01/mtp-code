"""R046 post-hoc all-case window/sizing audit; no model calls or new samples."""
import csv
import hashlib
import json
from pathlib import Path
import statistics
import zipfile

BASE=Path(__file__).resolve().parents[1]
OUT=BASE/'runs/examiner_audit_20261105_v2'
ROOT=BASE/'runs/20261105_012335_quiet_components_5066abab'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()


def rows(path):
    with path.open(newline='') as stream:return list(csv.DictReader(stream))


def main():
    source=BASE/'runs/quiet_components_analysis_20261105/report.json'
    report=json.loads(source.read_text());by={(a['seed'],a['repetition'],a['mode']):a for a in report['arms']}
    paths={key:rows(ROOT/a['run_path']/'prices.csv') for key,a in by.items()}
    def gap(key,start,end):
        return statistics.mean(abs(float(x['price'])/float(x['fundamental'])-1) for x in paths[key] if start<=int(x['round'])<=end)
    windows=[]
    for seed in (22853,23971,25087):
        for rep in (1,2):
            key=lambda mode:(seed,rep,mode)
            pre=100*(gap(key('C'),1,5)-gap(key('B'),1,5))
            post=100*(gap(key('C'),6,12)-gap(key('B'),6,12))
            full=100*(gap(key('C'),1,12)-gap(key('B'),1,12))
            assert abs(full-(5*pre+7*post)/12)<1e-10
            expected=next(c['mean_gap_difference']*100 for c in report['contrasts'] if c['seed']==seed and c['repetition']==rep and c['contrast']=='C-B')
            assert abs(expected-full)<1e-10
            windows.append(dict(seed=seed,repetition=rep,C_B_pre_reflection_gap_pp=pre,C_B_later_gap_pp=post,C_B_full_gap_pp=full))
    averages=[dict(seed=seed,pre_reflection_gap_pp=statistics.mean(w['C_B_pre_reflection_gap_pp'] for w in windows if w['seed']==seed),
        later_gap_pp=statistics.mean(w['C_B_later_gap_pp'] for w in windows if w['seed']==seed)) for seed in (22853,23971,25087)]
    sizing=[]
    for arm in report['arms']:
        path=ROOT/arm['run_path'];trades=rows(path/'trades.csv');orders=rows(path/'orders.csv')
        volume=sum(int(t['quantity']) for t in trades)
        involved=sum(int(t['quantity']) for t in trades if t['buyer_id'].startswith('llm_') or t['seller_id'].startswith('llm_'))
        legs=sum(int(t['quantity'])*(int(t['buyer_id'].startswith('llm_'))+int(t['seller_id'].startswith('llm_'))) for t in trades)
        quantities=lambda llm:[int(o['quantity']) for o in orders if o['side']!='hold' and int(o['quantity'])>0 and o['agent_id'].startswith('llm_')==llm]
        sizing.append(dict(seed=arm['seed'],repetition=arm['repetition'],mode=arm['mode'],target_union_fraction=involved/volume,
            target_trade_leg_fraction=legs/(2*volume),median_target_nonhold_accepted_quantity=statistics.median(quantities(True)) if quantities(True) else None,
            median_background_nonhold_accepted_quantity=statistics.median(quantities(False))))
    replay=json.loads((OUT/'replay_report.json').read_text())
    final=[s.get('supplemented_result',s['original_bundle_result']) for s in replay['studies']]
    result=dict(scope='Post-hoc all-case diagnostics and reproducibility audit;no causal difference-in-differences or new independent replication.',
        source_report_sha256=sha(source),windows=windows,within_seed_window_averages=averages,
        pre_reflection_gap_negative_pairs=sum(w['C_B_pre_reflection_gap_pp']<0 for w in windows),target_order_sizing_and_participation=sizing,
        replay=dict(verification_markets=sum(len(s['markets']) for s in final),financial_rounds=sum(m['rounds'] for s in final for m in s['markets']),
            financial_file_matches=sum(len(m['exact_financial_files']) for s in final for m in s['markets']),
            recorded_calls_consumed=sum(m['recorded_calls_consumed'] for s in final for m in s['markets']),network_attempts=sum(s['network_attempts'] for s in final)),
        realism_design_arithmetic=dict(fundamentalist_window1_baseline_proxy_range=[.02*.8/.0002,.02*1.2/.0002],
            expected_dividend_one_session_downside_difference=.02-.016,permanent_risk_neutral_value_difference=100-80,
            label='Arithmetic from the configured model,not estimated human expectations.'),new_live_calls=0)
    (OUT/'diagnostics.json').write_text(json.dumps(result,indent=2)+'\n')
    # Link the omitted import explicitly without changing old sealed bundles.
    record=next(s for s in replay['studies'] if s['study']=='R043')['dependency_supplement']
    with zipfile.ZipFile(OUT/'R043/dependency_supplement.zip','x',zipfile.ZIP_DEFLATED) as archive:
        archive.write(OUT/'R043/snapshot_code'/record['file'],record['file'])
        archive.writestr('SUPPLEMENT.json',json.dumps(record,indent=2))
    print(json.dumps(dict(replay=result['replay'],pre_reflection_negative_pairs=result['pre_reflection_gap_negative_pairs'],seed_means=averages),indent=2))


if __name__=='__main__':main()
