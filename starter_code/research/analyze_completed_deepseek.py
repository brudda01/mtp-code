"""Offline two-seed comparison and complete retry accounting; no inference requests."""
import argparse
from collections import defaultdict,Counter
from datetime import datetime
import json
from pathlib import Path
from statistics import mean
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import yaml
from research.order_influence import BASE,read,write,digest,rows
from research.analyze_final_extensions import verify_outputs,check_live_inputs
from research.goedel_cohort import audit_financial,metrics


def analyze(dest):
    dest=Path(dest).resolve();dest.mkdir(parents=True,exist_ok=False)
    roots=[BASE/'runs/goedel_cohort_20261108',BASE/'runs/goedel_seed2_finish25_20261109']
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
        close=rows(path/'agents_state.csv')
        for actor in per:
            actor['terminal_state']=next(a for a in close if int(a['round'])==25 and a['agent_id']==actor['agent_id'])
        pr=np.array([float(a['price']) for a in rows(path/'prices.csv')]);mm=metrics(path)
        mm.update(mean_price=float(np.mean(pr)),mean_log_return_pct=float(np.mean(np.diff(np.log(np.r_[100,pr])))*100),volume_per_round=mm['volume']/25)
        for actor in per:
            oo=[o for o in orders if o['agent_id']==actor['agent_id']]
            seq=[o['llm_requested_side'] for o in oo]
            actor['same_action_transitions']=sum(a==b for a,b in zip(seq,seq[1:]))
            actor['dominant_action_fraction']=max(Counter(seq).values())/len(seq)
        assert audit['account_rounds']==350 and inputcheck['complete_actual_input_pairs_checked']==150
        reports.append(dict(seed=cfg['seed'],root=root.relative_to(BASE).as_posix(),summary=s,metrics=mm,
            audit=audit,**inputcheck,per_persona=per,protocol_sha256=digest(root/'protocol.json')))
    assert personas[0]==personas[1]
    for a,b in zip(initials[0],initials[1]):
        assert {k:v for k,v in a.items() if k!='type'}=={k:v for k,v in b.items() if k!='type'}
        assert a['type']==b['type'] or (a['type']=='CappedAgent' and b['type']=='PersistentBackoffAgent' and a['agent_id'].startswith('llm_'))
    assert {k for k in configs[0] if configs[0][k]!=configs[1][k]}=={'seed','name','llm_limits'}
    assert {k for k in configs[0]['llm_limits'] if configs[0]['llm_limits'][k]!=configs[1]['llm_limits'][k]}=={'max_requests','max_reserved_tokens'}
    chain_names=('goedel_seed2_backoff_20261109','goedel_seed2_detached_20261109','goedel_seed2_expbackoff_20261109','goedel_seed2_full25_20261109','goedel_seed2_final_20261109','goedel_seed2_finish25_20261109')
    chain=[];all_wire=[];all_success=[];source_records={};prefix_checks=[]
    def jl(p):return [json.loads(l) for l in p.read_text().splitlines()]
    def canonical(x):return json.dumps(x,sort_keys=True,separators=(',',':'))
    for name in chain_names:
        root=BASE/'runs'/name
        from research.goedel_cohort import validate
        validate(root)
        if (root/'output_manifest.json').exists():verify_outputs(root)
        if (root/'prefix_transport.jsonl').exists():
            prefix=jl(root/'prefix_transport.jsonl')
            assert all(canonical(x) in source_records for x in prefix)
            assert [canonical(x) for x in prefix if 'response' in x]==[canonical(x) for x in all_success]
            checks=jl(root/'replayed_prefix.jsonl')
            assert len(checks)==len(prefix) and all(x['request_matches'] for x in checks)
            prefix_checks.append(dict(root=name,records=len(prefix),decisions=len(all_success),success_sequence_preserved=True))
        wire=jl(root/'provider_transport.jsonl');all_wire+=wire
        for x in wire:
            assert canonical(x) not in source_records,'Duplicate fresh wire record'
            source_records[canonical(x)]=name
        success=[x for x in wire if 'response' in x];all_success+=success
        chain.append(dict(root=name,fresh_http_attempts=len(wire),fresh_decisions=len(success),known_tokens=sum(x['response']['usage']['total_tokens'] for x in success),
            errors=dict(Counter(str(x.get('error',{}).get('http_status',x.get('error_type','unknown'))) for x in wire if 'response' not in x))))
    assert len(all_success)==150
    final_tape=jl(roots[1]/'prefix_transport.jsonl')+jl(roots[1]/'provider_transport.jsonl')
    assert [canonical(x) for x in final_tape if 'response' in x]==[canonical(x) for x in all_success]
    discarded=[x for x in all_wire if canonical(x) not in {canonical(y) for y in final_tape}]
    assert all('response' not in x for x in discarded)
    requests=jl(paths[1]/'llm_requests.jsonl');calls=[x for x in requests if x['record_type']=='model_call']
    usage=reports[1]['summary']['usage']
    assert len(calls)==len(final_tape)==usage['requests_made']
    assert sum(x['status']=='returned' for x in calls)==150
    assert sum((x.get('usage') or {}).get('total_tokens',0) for x in calls)==sum(x['response']['usage']['total_tokens'] for x in all_success)==usage['provider_reported_tokens']
    groups=defaultdict(list)
    for meta,wire in zip(calls,final_tape):
        assert meta['messages']==wire['request']['messages']
        groups[meta['request_group_id']].append(wire['request'])
    assert all(all(w==group[0] for w in group) for group in groups.values())
    delivery=dict(chain=chain,prefix_checks=prefix_checks,actual_archived_http_attempts=len(all_wire),actual_successful_decisions=len(all_success),
        known_tokens=sum(x['response']['usage']['total_tokens'] for x in all_success),unknown_usage_attempts=len(all_wire)-len(all_success),
        final_summary_record_count=len(final_tape),terminal_error_records_excluded_from_replay=len(discarded),exact_retry_groups=len(groups),
        limitation='Market-wire logs only; external availability probes and any unlogged in-flight request at initial interruption are outside this subtotal. Never sum continuation summary usage.')
    qroot=BASE/'runs/20261105_012335_quiet_components_5066abab';qwen=[]
    for x in read(qroot/'runs.json'):
        if x['mode']!='B':continue
        qp=qroot/x['run_path'];qm=metrics(qp);qr=rows(qp/'orders.csv');persistence={}
        for aid in ('llm_012','llm_013'):
            seq=[o['llm_requested_side'] for o in qr if o['agent_id']==aid]
            assert len(seq)==12
            persistence[aid]=dict(actions=dict(Counter(seq)),dominant_action_fraction=max(Counter(seq).values())/12,same_action_transitions=sum(a==b for a,b in zip(seq,seq[1:])))
        qm['volume_per_round']=qm['volume']/12
        qwen.append(dict(seed=x['seed'],repetition=x['repetition'],metrics=qm,persistence=persistence,run_path=str(qp.relative_to(BASE))))
    assert len(qwen)==6
    qsummary={key:dict(mean=mean(x['metrics'][key] for x in qwen),minimum=min(x['metrics'][key] for x in qwen),maximum=max(x['metrics'][key] for x in qwen)) for key in ('price_return_sd_pct','mean_gap_pct','max_drawdown_pct','volume_per_round')}
    table='| Metric | Seed 30841 | Seed 31991 | Two-seed mean |\n|---|---:|---:|---:|\n'
    fields=[('mean_price','Mean closing price',3),('mean_log_return_pct','Mean log-price return (%)',6),('price_return_sd_pct','Log-price-return SD (%)',6),('mean_gap_pct','Mean reference gap (%)',3),
        ('max_drawdown_pct','Maximum drawdown (%)',6),('terminal_price','Final auction price',1),
        ('volume','Total traded shares',0),('volume_per_round','Shares traded per round',2),('target_union_volume','Shares involving an LLM',0),
        ('maker_min','Minimum closing maker inventory',0),('maker_max','Maximum closing maker inventory',0),
        ('zero_volume_rounds','Zero-trade rounds',0)]
    for key,label,decimals in fields:table+=f"| {label} | {reports[0]['metrics'][key]:.{decimals}f} | {reports[1]['metrics'][key]:.{decimals}f} | {mean(r['metrics'][key] for r in reports):.{max(1,decimals)}f} |\n"
    both='| Trader | Seed | Executed buys | Executed sells | Passive excess, auction (pp) | Passive excess, reference (pp) |\n|---|---:|---:|---:|---:|---:|\n'
    for report in reports:
        for p in report['per_persona']:
            marks=p['account']['marks'];both+=f"| {p['name']} | {report['seed']} | {p['bought']} | {p['sold']} | {100*marks['auction']['excess_return']:+.3f} | {100*marks['regime_benchmark']['excess_return']:+.3f} |\n"
    averages={k:mean(r['metrics'][k] for r in reports) for k in ('price_return_sd_pct','mean_gap_pct','max_drawdown_pct','volume')}
    result=dict(stage='R058 completed DeepSeek two-seed cohort',completed_market_scenarios=2,reports=reports,means_descriptive_only=averages,
        delivery=delivery,qwen_B_context=dict(paths=qwen,summary=qsummary,distinct_seeds=3,repeats_per_seed=2,comparison='Post-hoc cross-study descriptive context, not a treatment contrast.'),
        initial_type_metadata_change='Only LLM type labels CappedAgent to PersistentBackoffAgent; initial financial fields and personas equal.',
        limitations='Two scenario seeds,one provider realization per scenario. Seed31991 is an exact-success-prefix continuation across amended retry policies and a user-reported credential change,not an uninterrupted API session. No isolated model/count/cap or long-run stability inference.')
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
    print(json.dumps(dict(means=averages,delivery=delivery,qwen_B=qsummary),indent=2))


if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('--output',required=True);x=a.parse_args();analyze(x.output)
