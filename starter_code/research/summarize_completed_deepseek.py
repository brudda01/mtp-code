"""Saved-evidence tables and continuation-state consistency; no new market paths."""
from pathlib import Path
from statistics import mean
from research.order_influence import BASE,read,write,digest,rows


def main():
    source=BASE/'runs/deepseek_completed_analysis_20261109';r=read(source/'report.json')
    dest=BASE/'runs/deepseek_completed_review_20261109';dest.mkdir(exist_ok=False)
    endpoint='| Trader | Seed | Final cash | Final shares | Auction wealth | Reference wealth | Same-action transitions |\n|---|---:|---:|---:|---:|---:|---:|\n'
    for run in r['reports']:
        for p in run['per_persona']:
            a=p['terminal_state'];m=p['account']['marks']
            endpoint+=f"| {p['name']} | {run['seed']} | {float(a['cash']):.2f} | {a['shares']} | {m['auction']['active_wealth']:.2f} | {m['regime_benchmark']['active_wealth']:.2f} | {p['same_action_transitions']}/24 |\n"
    table='| Descriptive metric | DeepSeek B: two 25-round paths | Qwen B: six 12-round paths |\n|---|---:|---:|\n'
    for k,label in [('price_return_sd_pct','Mean within-path return SD (%)'),('mean_gap_pct','Mean reference gap (%)'),('max_drawdown_pct','Mean maximum drawdown (%)'),('volume_per_round','Mean traded shares per round')]:
        table+=f"| {label} | {mean(x['metrics'][k] for x in r['reports']):.3f} | {r['qwen_B_context']['summary'][k]['mean']:.3f} |\n"
    finalroot=BASE/'runs/goedel_seed2_finish25_20261109';finalpath=finalroot/read(finalroot/'summary.json')['run_path'];checks=[]
    for name in ('goedel_seed2_detached_20261109','goedel_seed2_expbackoff_20261109','goedel_seed2_full25_20261109','goedel_seed2_final_20261109'):
        root=BASE/'runs'/name;s=read(root/'summary.json');path=root/s['run_path'];n=s['completed_rounds'];counts={}
        for file in ('prices.csv','trades.csv','orders.csv','agents_state.csv','cashflows.csv','liquidity.csv'):
            def normalize(record):return {k:v for k,v in record.items() if k!='type'}
            old=[normalize(x) for x in rows(path/file) if int(x['round'])<=n]
            new=[normalize(x) for x in rows(finalpath/file) if int(x['round'])<=n]
            assert old==new,(name,file)
            counts[file]=len(old)
        checks.append(dict(root=name,completed_rounds_preserved=n,rows_checked=counts))
    (dest/'endpoint_table.md').write_text(endpoint,encoding='utf-8');(dest/'cross_study_table.md').write_text(table,encoding='utf-8')
    write(dest/'continuation_state_checks.json',dict(status='passed',checks=checks,normalization='Only Python agent type label excluded; every other financial CSV field exact. Overlapping prefixes,not new independent data.'))
    write(dest/'output_manifest.json',{p.name:digest(p) for p in dest.iterdir() if p.is_file() and p.name!='output_manifest.json'})
    print(table);print('All four completed partial-market prefixes exactly preserved.')


if __name__=='__main__':main()
