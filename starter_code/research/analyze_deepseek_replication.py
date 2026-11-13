"""Offline two-seed comparison and complete retry accounting; no inference requests."""
import argparse
from collections import defaultdict,Counter
from datetime import datetime
import json
from pathlib import Path
from statistics import mean
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import yaml
from research.order_influence import BASE,read,write,digest,rows
from research.analyze_final_extensions import verify_outputs,check_live_inputs
from research.goedel_cohort import audit_financial,metrics


def analyze(dest):
    dest=Path(dest).resolve();dest.mkdir(parents=True,exist_ok=False)
    roots=[BASE/'runs/goedel_cohort_20261108',BASE/'runs/goedel_seed2_backoff_20261109']
    reports=[];configs=[];initials=[];personas=[];paths=[]
    for root in roots:
        verify_outputs(root);s=read(root/'summary.json');path=root/s['run_path'];paths.append(path)
        assert s['status']=='completed' and s['completed_rounds']==25 and s['delivered_decisions']==150
        cfg=yaml.safe_load((root/'config.yaml').read_text());configs.append(cfg)
        initials.append(rows(path/'initial_state.csv'));personas.append(read(path/'personas.json'))
        ev=read(root/'evaluation.json');per=[]
        orders=rows(path/'orders.csv');trades=rows(path/'trades.csv')
        for aid,p in personas[-1].items():
            oo=[o for o in orders if o['agent_id']==aid]
            per.append(dict(agent_id=aid,name=p['name'],requested_actions=dict(Counter(o['llm_requested_side'] for o in oo)),
                accepted_actions=dict(Counter(o['side'] for o in oo)),
                bought=sum(int(t['quantity']) for t in trades if t['buyer_id']==aid),
                sold=sum(int(t['quantity']) for t in trades if t['seller_id']==aid),
                cap_adjustments=sum(int(o['llm_requested_quantity'] or 0)>10 for o in oo),
                account=next(a for a in ev['accounts'] if a['agent_id']==aid)))
        audit=audit_financial(path);inputcheck=check_live_inputs(path)
        assert audit['account_rounds']==350 and inputcheck['complete_actual_input_pairs_checked']==150
        reports.append(dict(seed=cfg['seed'],root=root.relative_to(BASE).as_posix(),summary=s,metrics=metrics(path),
            audit=audit,**inputcheck,per_persona=per,protocol_sha256=digest(root/'protocol.json')))
    assert initials[0]==initials[1] and personas[0]==personas[1]
    assert {k for k in configs[0] if configs[0][k]!=configs[1][k]}=={'seed','name','llm_limits'}
    assert {k for k in configs[0]['llm_limits'] if configs[0]['llm_limits'][k]!=configs[1]['llm_limits'][k]}=={'max_requests','max_reserved_tokens'}
    requests=[json.loads(l) for l in (paths[1]/'llm_requests.jsonl').read_text().splitlines()]
    calls=[x for x in requests if x['record_type']=='model_call']
    transport=[json.loads(l) for l in (roots[1]/'provider_transport.jsonl').read_text().splitlines()]
    usage=reports[1]['summary']['usage']
    assert len(calls)==len(transport)==usage['requests_made']
    assert sum(x['status']=='returned' for x in calls)==150
    assert sum('response' in x for x in transport)==150
    assert sum(x['status']=='error' for x in calls)==usage['failed_requests']
    assert sum(x.get('usage') is None for x in calls)==usage['unknown_usage_requests']
    assert sum((x.get('usage') or {}).get('total_tokens',0) for x in calls)==usage['provider_reported_tokens']
    assert len({x['reservation']['reservation_id'] for x in calls})==len(calls)
    groups=defaultdict(list)
    for x in calls:groups[x['request_group_id']].append(x)
    paired=0;errors429=[]
    for group in groups.values():
        for previous,current in zip(group,group[1:]):
            for key in ('messages','temperature','max_tokens','json_mode'):
                assert previous[key]==current[key],key
            assert previous['transport_retry_planned']
            paired+=1
        for x in group:
            if x.get('http_status')==429:
                assert x['retry_category']=='rate_limit_429'
                h=x['retry_after']
                if h['retry_after_valid']:assert x['retry_wait_seconds']==h['retry_after_seconds']+1
                errors429.append({k:x[k] for k in ('call_id','retry_after','retry_wait_seconds')})
    # Raw wire bodies also match within each retry group, independent of the agent's metadata.
    wires=defaultdict(list)
    for meta,wire in zip(calls,transport):wires[meta['request_group_id']].append(wire['request'])
    assert all(all(w==ww[0] for w in ww) for ww in wires.values())
    table='| Metric | Seed 30841 | Seed 31991 |\n|---|---:|---:|\n'
    fields=[('price_return_sd_pct','Log-price-return SD (%)',6),('mean_gap_pct','Mean reference gap (%)',3),
        ('max_drawdown_pct','Maximum drawdown (%)',6),('terminal_price','Final auction price',1),
        ('volume','Total traded shares',0),('target_union_volume','Shares involving an LLM',0),
        ('maker_min','Minimum closing maker inventory',0),('maker_max','Maximum closing maker inventory',0),
        ('zero_volume_rounds','Zero-trade rounds',0)]
    for key,label,decimals in fields:table+=f"| {label} | {reports[0]['metrics'][key]:.{decimals}f} | {reports[1]['metrics'][key]:.{decimals}f} |\n"
    both='| Trader | Seed | Executed buys | Executed sells | Passive excess, auction (pp) | Passive excess, reference (pp) |\n|---|---:|---:|---:|---:|---:|\n'
    for report in reports:
        for p in report['per_persona']:
            marks=p['account']['marks'];both+=f"| {p['name']} | {report['seed']} | {p['bought']} | {p['sold']} | {100*marks['auction']['excess_return']:+.3f} | {100*marks['regime_benchmark']['excess_return']:+.3f} |\n"
    averages={k:mean(r['metrics'][k] for r in reports) for k in ('price_return_sd_pct','mean_gap_pct','max_drawdown_pct','volume')}
    old=[read(BASE/'runs'/n/'summary.json') for n in ('goedel_second_seed_20261108','goedel_second_seed_retry_20261108')]
    totals={k:sum(s['usage'][k] for s in [r['summary'] for r in reports]+old) for k in ('requests_made','provider_reported_tokens','reserved_tokens','unknown_usage_requests')}
    result=dict(stage='R058 completed DeepSeek two-seed cohort',completed_market_scenarios=2,
        reports=reports,means_descriptive_only=averages,all_attempt_lifecycle_usage=totals,
        seed31991_new_delivery=dict(http_attempts=len(calls),retry_pairs_verified=paired,rate_limit_errors=len(errors429),
            rate_limit_retries=sum(x.get('attempt_kind')=='rate_limit_retry' for x in calls),errors429=errors429,
            exact_wire_retry_groups_verified=len(wires),provider_reported_tokens=usage['provider_reported_tokens'],unknown_usage_errors=usage['unknown_usage_requests']),
        previous_aborted_attempts_retained=2,previous_unexecuted_reply_excluded=True,
        limitations='Two independently seeded scenarios with one provider realization each,not a paired treatment experiment. No isolated model/count/cap effect or broad repeatability/realism claim. Transport retry policy differs and providerbackend/time is not pinned. All old attempts retained;only complete market paths compared.')
    write(dest/'report.json',result);(dest/'market_table.md').write_text(table,encoding='utf-8');(dest/'persona_table.md').write_text(both,encoding='utf-8')
    fig,axes=plt.subplots(2,2,figsize=(11,6.5),sharex=True,layout='constrained')
    for col,(path,report) in enumerate(zip(paths,reports)):
        pr=rows(path/'prices.csv');states=rows(path/'agents_state.csv');x=[0]+[int(p['round']) for p in pr]
        axes[0,col].plot(x,[100]+[float(p['price']) for p in pr],label='Auction price')
        axes[0,col].axhline(100,color='grey',linestyle='--',label='Private reference')
        axes[0,col].set_title(f"Seed {report['seed']}");axes[0,col].set_ylabel('Price');axes[0,col].legend()
        maker=[int(a['shares']) for a in states if a['agent_id']=='mark_000']
        axes[1,col].plot(x,[150]+maker);axes[1,col].axhline(0,color='grey',linestyle=':');axes[1,col].axhline(300,color='grey',linestyle=':')
        axes[1,col].set_ylim(-10,310);axes[1,col].set_ylabel('Maker shares');axes[1,col].set_xlabel('Uncalibrated trading session')
    limits=[axes[0,i].get_ylim() for i in range(2)];lo=min(x[0] for x in limits);hi=max(x[1] for x in limits)
    for i in range(2):axes[0,i].set_ylim(lo,hi)
    fig.suptitle('Six DeepSeek agents, Mode B, order cap 10: two separate scenarios\nMatched economic settings; no treatment comparison; old aborted attempts retained',fontsize=11)
    for suffix in ('png','pdf'):fig.savefig(dest/('two_seed_paths.'+suffix),dpi=170)
    plt.close(fig)
    write(dest/'output_manifest.json',{p.name:digest(p) for p in dest.iterdir() if p.is_file() and p.name!='output_manifest.json'})
    print(json.dumps(dict(means=averages,delivery=result['seed31991_new_delivery'],lifecycle=totals),indent=2))


if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('--output',required=True);x=a.parse_args();analyze(x.output)
