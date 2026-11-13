"""R047 all-branch analysis,common-round5 passive accounts and same-mode controls."""
import argparse
import json
from pathlib import Path
import shutil
import statistics
from unittest.mock import patch
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from sim.config import load_config
from sim.evaluation import read_rows
from sim.provenance import sha256,write_json
from runs import common_prefix_20261105 as d
from runs import initial_news_analysis_20261104 as helper


def postprefix(path):
    cfg=load_config(path/'config.yaml');prices=read_rows(path/'prices.csv');states=read_rows(path/'agents_state.csv')
    if len(prices)<=5:return None
    start={r['agent_id']:r for r in states if r['round']=='5'}
    end={r['agent_id']:r for r in states if int(r['round'])==len(prices)}
    accounts=[]
    for aid,initial in start.items():
        cash=float(initial['cash']);shares=int(initial['shares']);wealth=float(initial['wealth'])
        passive=cash
        for p in prices[5:]:passive=passive*(1+cfg.asset.risk_free)+shares*float(p['dividend'])
        marks={}
        for mark,value in [('auction',float(prices[-1]['price'])),('regime_benchmark',float(prices[-1]['fundamental']))]:
            active=float(end[aid]['cash'])+int(end[aid]['shares'])*value
            held=passive+shares*value
            marks[mark]=dict(active_wealth=active,passive_wealth=held,active_minus_passive=active-held,excess_return=(active-held)/wealth)
        accounts.append(dict(agent_id=aid,type=initial['type'],opening5_cash=cash,opening5_shares=shares,opening5_auction_wealth=wealth,marks=marks))
    totals={mark:sum(a['marks'][mark]['active_minus_passive'] for a in accounts) for mark in ('auction','regime_benchmark')}
    assert all(abs(x)<1e-7 for x in totals.values())
    return dict(continuation_rounds=len(prices)-5,mean_gap=statistics.mean(abs(float(p['price'])/float(p['fundamental'])-1) for p in prices[5:]),
        accounts=accounts,aggregate_active_minus_passive=totals,interpretation='Conditional passive holding COMMON closing5 shares;normalize by COMMON closing5 auction wealth. Not risk-adjusted alpha or human-realism metric.')


def analyze(root,output):
    root=Path(root).resolve();out=Path(output).resolve();p=d.validate(root);summary=d.read(root/'summary.json')
    assert summary['status']!='running';out.mkdir(parents=True,exist_ok=False)
    index=d.read(root/'runs.json') if (root/'runs.json').exists() else []
    assert {(root/a['run_path']).resolve() for a in index}=={x.resolve() for x in (root/'branch_runs').glob('*') if x.is_dir()}
    arms=[];http=[];account_rounds=0
    for arm in index:
        path=root/arm['run_path'];d.prior.base.verify_market(path);assert sha256(path/'manifest.json')==arm['manifest_sha256']
        prefix=root/'prefixes'/arm['prefix_id'];d.prefix_check(prefix,path)
        cfg=load_config(path/'config.yaml');reconstruction=helper.account_reconstruction(path,cfg);account_rounds+=reconstruction['account_rounds']
        fresh=[c for c in d.lines(path/'llm_requests.jsonl') if c['record_type']=='model_call'];http+=fresh
        cached=[c for c in d.lines(path/'llm_calls.jsonl') if c['record_type']=='prefix_replay_call']
        assert len(cached)==10 and all(c['prefix_replay'] and not c['new_http_request'] and c['usage'] is None for c in cached)
        with patch.object(d.prior,'VERSION',d.VERSION):history=d.prior.history_audit(path,arm['mode'])
        clean=arm['status']=='completed' and arm['rounds']==12 and not any(arm['operational_failures'].values())
        observed=postprefix(path);trading,_,_,uncleared=helper.trading(path,cfg,live=True)
        if clean:assert history['reflections_recorded']==(4 if arm['mode']=='C' else 0) and arm['first_live_state_gate']
        arms.append({**arm,'full_clean':clean,'postprefix_primary':observed if clean else None,'observed_postprefix':observed,
            'history_audit':history,'account_reconstruction':reconstruction,'continuation_trading':[t for t in trading if t['round']>=6],
            'delivered_but_uncleared':uncleared})
    assert len(http)==summary['usage']['requests_made']
    assert sum((c.get('usage') or {}).get('total_tokens',0) for c in http if (c.get('usage') or {}).get('source')=='provider')==summary['usage']['provider_reported_tokens']
    by={(a['prefix_id'],a['mode'],a['branch_repetition']):a for a in arms};contrasts=[];book_checks=0
    def value(arm,aid,mark):return next(a for a in arm['postprefix_primary']['accounts'] if a['agent_id']==aid)['marks'][mark]['excess_return']
    for prefix in p['prefixes']:
        pid=prefix['prefix_id'];group=[a for a in arms if a['prefix_id']==pid]
        books=[]
        for a in group:
            if a['rounds']>=6:books.append([r for r in read_rows(root/a['run_path']/'orders.csv') if r['round']=='6' and r['agent_id'] not in d.TARGETS])
        if len(books)>1:assert all(b==books[0] for b in books);book_checks+=len(books)-1
        result=dict(prefix_id=pid,seed=prefix['seed'],source_repetition=prefix['source_repetition'],available=all((pid,m,n) in by and by[pid,m,n]['full_clean'] for m in 'BC' for n in (1,2)))
        # Same-mode controls stay available even if the other mode is partial.
        result['same_mode']={}
        for mode in 'BC':
            pair=[by.get((pid,mode,n)) for n in (1,2)]
            result['same_mode'][mode]=None if not all(a and a['full_clean'] for a in pair) else dict(
                gap_branch1_minus_branch2=pair[0]['postprefix_primary']['mean_gap']-pair[1]['postprefix_primary']['mean_gap'],
                target_excess_difference={aid:{mark:value(pair[0],aid,mark)-value(pair[1],aid,mark) for mark in ('auction','regime_benchmark')} for aid in d.TARGETS})
        if result['available']:
            mean=lambda mode,fn:statistics.mean(fn(by[pid,mode,n]) for n in (1,2))
            result.update(Cmean_minus_Bmean_gap=mean('C',lambda a:a['postprefix_primary']['mean_gap'])-mean('B',lambda a:a['postprefix_primary']['mean_gap']),
                Cmean_minus_Bmean_reported_tokens=mean('C',lambda a:a['usage']['provider_reported_tokens'])-mean('B',lambda a:a['usage']['provider_reported_tokens']),
                Cmean_minus_Bmean_target_excess={aid:{mark:mean('C',lambda a:value(a,aid,mark))-mean('B',lambda a:value(a,aid,mark)) for mark in ('auction','regime_benchmark')} for aid in d.TARGETS})
        else:result['reason']='At least one of four branches missing/partial/affected;no complete primary contrast.'
        contrasts.append(result)
    means=[]
    for seed in sorted({pfx['seed'] for pfx in p['prefixes']}):
        selected=[c for c in contrasts if c['seed']==seed]
        record=dict(seed=seed,two_prefix_average_available=all(c['available'] for c in selected),prefix_count=2)
        if record['two_prefix_average_available']:
            record.update(Cmean_minus_Bmean_gap=statistics.mean(c['Cmean_minus_Bmean_gap'] for c in selected),
                Cmean_minus_Bmean_target_excess={aid:{mark:statistics.mean(c['Cmean_minus_Bmean_target_excess'][aid][mark] for c in selected) for mark in ('auction','regime_benchmark')} for aid in d.TARGETS})
        means.append(record)
    report=dict(version='common_prefix_analysis_v1',protocol_sha256=sha256(root/'protocol.json'),summary=summary,arms=arms,prefix_contrasts=contrasts,within_seed_two_prefix_means=means,
        not_attempted=[a for a in p['schedule'] if (a['prefix_id'],a['mode'],a['branch_repetition']) not in by],
        audit=dict(account_rounds_reconstructed=account_rounds,fresh_request_history_checks=sum(a['history_audit']['actual_history_requests_checked'] for a in arms),
            cached_prefix_requests=summary['cached_prefix_requests'],same_first6_background_book_checks=book_checks,recorded_prefix_provider_usage_added=0),
        limitations=p['limitations'],analysis_source_sha256=sha256(__file__))
    write_json(out/'report.json',report);shutil.copyfile(__file__,out/'analysis_source.py');readout(out,report);figure(out,report)
    write_json(out/'artifact_manifest.json',{f.name:sha256(f) for f in out.iterdir() if f.is_file()})
    print(f'analysis -> {out}',flush=True);return report


def readout(out,r):
    s=r['summary'];text=['# R047 common-prefix continuation study','',
        f"Status:{s['status']};clean completed branches{s['completed_branches']}/24,attempted{s['recorded_branches']}.",'',
        'Six existing B first5-session histories nested in THREE exogenous scenarios;two fresh B/two fresh C continuations per prefix. Prefix replay is not new model data. C first reflects after5,then10;only sessions6-12 enter primary outcomes. All14 account states match before first fresh call.','',
        '| Prefix | Cmean-Bmean gap pp | B1-B2 gap pp | C1-C2 gap pp | Meera auction/private pp | Arjun auction/private pp | Extra reported tokens |',
        '|---|---:|---:|---:|---:|---:|---:|']
    for c in r['prefix_contrasts']:
        control=lambda mode:'missing' if c['same_mode'][mode] is None else f"{100*c['same_mode'][mode]['gap_branch1_minus_branch2']:+.4f}"
        if not c['available']:text.append(f"| {c['prefix_id']} | missing | {control('B')} | {control('C')} | missing | missing | missing |");continue
        fmt=lambda aid:'/'.join(f"{100*c['Cmean_minus_Bmean_target_excess'][aid][m]:+.4f}" for m in ('auction','regime_benchmark'))
        text.append(f"| {c['prefix_id']} | {100*c['Cmean_minus_Bmean_gap']:+.4f} | {control('B')} | {control('C')} | {fmt('llm_012')} | {fmt('llm_013')} | {c['Cmean_minus_Bmean_reported_tokens']:+.1f} |")
    text+=['','Fresh usage:'+json.dumps(s['usage']),'',
        'Prefix requests:'+str(s['cached_prefix_requests'])+' cached,zero provider usage/pacing/budget. First5 source replies are deliberately reused,never counted as independent draws.','',
        'Return differences use passive portfolios fixed at COMMON closing5 accounts;normalize by closing5 auction wealth under BOTH terminal marks. Complete primary contrast requires allfour branches clean. Partial postprefix data and cancellations remain in report.json.','',
        'Same-mode B1-B2/C1-C2 differences are descriptive stochastic controls,not a significance test or noise-adjusted causal estimate. All branch outcomes and within-seed prefix means are retained. Smaller private-value gaps are not human realism or a universal ranking.','',r['limitations'],'',
        'Audit:'+json.dumps(r['audit']),'']
    (out/'READOUT.md').write_text('\n'.join(text),encoding='utf-8')


def figure(out,r):
    fig,ax=plt.subplots(figsize=(10,4.8));labels=[c['prefix_id'].replace('_source','/') for c in r['prefix_contrasts']]
    for j,c in enumerate(r['prefix_contrasts']):
        if c['available']:ax.scatter(j,100*c['Cmean_minus_Bmean_gap'],color='#0072B2',marker='o',label='Cmean - Bmean' if j==0 else None)
        for mode,shift,color,marker in [('B',-.16,'#999999','x'),('C',.16,'#D55E00','+')]:
            if c['same_mode'][mode] is not None:ax.scatter(j+shift,100*c['same_mode'][mode]['gap_branch1_minus_branch2'],color=color,marker=marker,label=mode+'1 - '+mode+'2' if j==0 else None)
    ax.axhline(0,color='black',lw=.8);ax.set_xticks(range(len(labels)),labels);ax.set_ylabel('Post6-12 mean valuation-gap difference (pp)');ax.set_xlabel('Source scenario / existing B-history draw')
    ax.set_title('Common-prefix reflection contrast and same-mode variation');ax.grid(axis='y',alpha=.2)
    ax.spines[['top','right']].set_visible(False)
    handles,_=ax.get_legend_handles_labels()
    if handles:ax.legend(frameon=False)
    fig.text(.5,.01,'Six reused prefix contexts nest in three exogenous scenarios. No scalar winner or significance threshold.',ha='center',fontsize=9)
    fig.tight_layout(rect=(0,.04,1,1))
    for suffix in ('png','pdf'):fig.savefig(out/f'common_prefix_contrasts.{suffix}',dpi=180,bbox_inches='tight')
    plt.close(fig)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--study',required=True);parser.add_argument('--output',required=True);args=parser.parse_args()
    analyze(args.study,args.output)
