"""Post-hoc descriptive checks for the R043 manual interpretation, no API."""
import hashlib
import json
from pathlib import Path

OUT=Path(__file__).resolve().parent
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    for name,digest in json.loads((OUT/'artifact_manifest.json').read_text()).items():
        assert sha(OUT/name)==digest
    r=json.loads((OUT/'report.json').read_text())
    means=r['within_seed_two_draw_averages']
    table=[]
    for seed in (22853,23971,25087):
        pair={c['contrast']:c for c in means if c['seed']==seed}
        assert all(c['two_draw_average_available'] for c in pair.values())
        table.append(dict(seed=seed,B_minus_A_gap_pp=100*pair['B-A']['mean_gap_difference'],
            C_minus_B_gap_pp=100*pair['C-B']['mean_gap_difference'],
            C_minus_A_gap_pp=100*(pair['B-A']['mean_gap_difference']+pair['C-B']['mean_gap_difference']),
            C_minus_B_passive_excess_pp={aid:{mark:value*100 for mark,value in marks.items()}
                for aid,marks in pair['C-B']['passive_excess_differences'].items()}))
    by={(a['seed'],a['repetition'],a['mode']):a for a in r['arms']}
    first=[]
    for seed in (22853,23971,25087):
        for rep in (1,2):
            for aid in ('llm_012','llm_013'):
                orders={}
                for mode in 'BC':
                    intent=next(x for x in by[seed,rep,mode]['trading'] if x['round']==1 and x['agent_id']==aid)['requested']
                    orders[mode]={key:intent[key] for key in ('side','quantity','limit_price')}
                first.append(dict(seed=seed,repetition=rep,agent_id=aid,orders=orders,equal=orders['B']==orders['C']))
    b=r['costs_by_mode']['B']['provider_reported_tokens'];c=r['costs_by_mode']['C']['provider_reported_tokens']
    result=dict(scope='Post-hoc summary of ALL prespecified seed averages plus ALL12 first-order B/C pairs. No new independent data or component-causality test.',
        report_sha256=sha(OUT/'report.json'),source_sha256=sha(Path(__file__)),
        seed_means=table,first_BC_orders=first,first_order_pairs_different=sum(not x['equal'] for x in first),
        C_minus_B_reported_tokens=c-b,C_extra_reported_tokens_pct=100*(c/b-1),
        C_reflection_reported_tokens=r['reflection_cost']['provider_reported_tokens'],
        C_minus_B_decision_only_reported_tokens=c-b-r['reflection_cost']['provider_reported_tokens'],
        C_B_gap_negative_draws=sum(x['contrast']=='C-B' and x['mean_gap_difference']<0 for x in r['contrasts']),
        figure_visually_inspected=True,new_api_requests=0)
    with (OUT/'interpretation_checks.json').open('x',encoding='utf-8') as stream:
        json.dump(result,stream,indent=2);stream.write('\n')
    print(json.dumps({k:v for k,v in result.items() if k!='first_BC_orders'},indent=2))


if __name__=='__main__':main()
