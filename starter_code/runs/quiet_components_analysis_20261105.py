"""R043 read-only analysis: retain every arm, both marks, costs and missing slots."""
import argparse
from collections import defaultdict
from pathlib import Path
import shutil
import statistics
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from sim.config import load_config
from sim.evaluation import evaluate_run, read_rows
from sim.provenance import sha256, write_json
from runs import initial_news_analysis_20261104 as helper
from runs import quiet_components_20261105 as d


def analyze(root, output):
    root=Path(root);out=Path(output);p=d.validate(root);summary=d.read(root/'summary.json')
    assert summary['status']!='running'
    out.mkdir(parents=True,exist_ok=False)
    refs=d.baselines(root);index=d.read(root/'runs.json') if (root/'runs.json').exists() else []
    assert {(root/e['run_path']).resolve() for e in index}=={x.resolve() for x in (root/'market_runs').glob('*') if x.is_dir()}
    baselines=[];arms=[];all_calls=[];account_rounds=0;max_cash_error=0.
    for entries,live in ((refs,False),(index,True)):
        for entry in entries:
            path=root/entry['run_path'];d.base.verify_market(path)
            assert sha256(path/'manifest.json')==entry['manifest_sha256']
            cfg=load_config(path/'config.yaml');ss=d.read(path/'summary.json');prices=read_rows(path/'prices.csv')
            ev=evaluate_run(path) if prices else None
            recon=helper.account_reconstruction(path,cfg)
            account_rounds+=recon['account_rounds'];max_cash_error=max(max_cash_error,recon['max_cash_error'])
            groups=helper.grouped_accounts(ev) if ev else None
            rr,_,_,uncleared=helper.trading(path,cfg,live=live)
            calls=[c for c in d.base.lines(path/'llm_requests.jsonl') if c['record_type']=='model_call']
            if live:
                all_calls+=calls
                audit=d.history_audit(path,entry['mode'])
                clean=ss['status']=='completed' and ss['rounds']==12 and not any(entry['operational_failures'].values())
                if clean:assert audit['reflections_recorded']==(4 if entry['mode']=='C' else 0)
            else:clean=True;audit=None
            windows={}
            target_ids=sorted({r['agent_id'] for r in rr})
            for label,start,end in (('pre_reflection_1_5',1,5),('later_6_12',6,12),('all_1_12',1,12)):
                windows[label]={aid:{k:sum(r[k] for r in rr if r['agent_id']==aid and start<=r['round']<=end and r[k] is not None)
                    for k in ('accepted_signed','executed_net','executed_gross')} for aid in target_ids}
            record={**entry,'full_clean':clean,'prices':prices,'trading':rr,'execution_windows':windows,
                'full_horizon_evaluation':ev if clean else None,'observed_prefix_evaluation':ev,
                'counterpart_groups':groups,'account_reconstruction':recon,'actual_history_audit':audit,
                'delivered_but_uncleared':uncleared}
            (arms if live else baselines).append(record)
    assert len(all_calls)==summary['usage']['requests_made']
    assert sum(c.get('usage',{}).get('total_tokens',0) for c in all_calls if c.get('usage') and c['usage'].get('source')=='provider')==summary['usage']['provider_reported_tokens']
    by={(a['seed'],a['repetition'],a['mode']):a for a in arms};contrasts=[]
    for seed in p['seeds']:
        complete_entries=[a for a in index if a['seed']==seed]
        if len(complete_entries)==6 and all(a['full_clean'] for a in arms if a['seed']==seed):d.initial_gates(root,complete_entries)
        for rep in (1,2):
            for high,low in (('B','A'),('C','B')):
                hi=by.get((seed,rep,high));lo=by.get((seed,rep,low))
                record=dict(seed=seed,repetition=rep,contrast=high+'-'+low,available=bool(hi and lo and hi['full_clean'] and lo['full_clean']))
                if not record['available']:
                    record['reason']='At least one arm unattempted, partial or operationally affected; full-horizon contrast missing.'
                    contrasts.append(record);continue
                hev,lev=hi['full_horizon_evaluation'],lo['full_horizon_evaluation']
                accounts=[{a['agent_id']:a for a in ev['accounts']} for ev in (hev,lev)]
                record.update(mean_gap_difference=hev['metrics']['mean_absolute_relative_gap']-lev['metrics']['mean_absolute_relative_gap'],
                    reported_token_difference=hi['usage']['provider_reported_tokens']-lo['usage']['provider_reported_tokens'],
                    reserved_token_difference=hi['usage']['reserved_tokens']-lo['usage']['reserved_tokens'],
                    passive_excess_differences={aid:{mark:accounts[0][aid]['marks'][mark]['excess_return']-accounts[1][aid]['marks'][mark]['excess_return']
                        for mark in ('auction','regime_benchmark')} for aid in d.TARGETS},
                    execution_window_differences={window:{aid:{k:hi['execution_windows'][window][aid][k]-lo['execution_windows'][window][aid][k]
                        for k in ('accepted_signed','executed_net','executed_gross')} for aid in d.TARGETS} for window in hi['execution_windows']})
                contrasts.append(record)
    averaged=[]
    for seed in p['seeds']:
        for label in ('B-A','C-B'):
            values=[c for c in contrasts if c['seed']==seed and c['contrast']==label and c['available']]
            record=dict(seed=seed,contrast=label,complete_paired_draws=len(values),two_draw_average_available=len(values)==2)
            if len(values)==2:
                record.update(mean_gap_difference=statistics.mean(c['mean_gap_difference'] for c in values),
                    reported_token_difference=statistics.mean(c['reported_token_difference'] for c in values),
                    passive_excess_differences={aid:{mark:statistics.mean(c['passive_excess_differences'][aid][mark] for c in values)
                        for mark in ('auction','regime_benchmark')} for aid in d.TARGETS})
            averaged.append(record)
    costs={mode:{k:sum(a['usage'][k] for a in arms if a['mode']==mode) for k in d.USAGE} for mode in 'ABC'}
    reflections=[c for c in all_calls if c['call_type']=='reflection']
    report=dict(version='quiet_components_analysis_v1',protocol_sha256=sha256(root/'protocol.json'),summary=summary,
        baselines=baselines,arms=arms,contrasts=contrasts,within_seed_two_draw_averages=averaged,
        not_attempted=[a for b in p['blocks'] for a in b['arms'] if (a['seed'],a['repetition'],a['mode']) not in by],
        costs_by_mode=costs,reflection_cost=dict(http_attempts=len(reflections),provider_reported_tokens=sum(c['usage'].get('total_tokens',0) for c in reflections if c.get('usage') and c['usage'].get('source')=='provider')),
        delivered_but_uncleared=sum(len(a['delivered_but_uncleared']) for a in arms),
        audit=dict(account_rounds=account_rounds,max_cash_error=max_cash_error,history_request_checks=sum(a['actual_history_audit']['actual_history_requests_checked'] for a in arms),
            genuine_completed_reflections=sum(a['actual_history_audit']['reflections_recorded']-a['operational_failures']['reflection_failures'] for a in arms),
            source_and_config_hashes_verified=True,raw_calls_match_summary_attempt_and_reported_usage=True),
        limitations=p['limitations'],analysis_source_sha256=sha256(__file__))
    write_json(out/'report.json',report);shutil.copyfile(__file__,out/'analysis_source.py')
    readout(out,report);figure(out,report)
    write_json(out/'artifact_manifest.json',{f.name:sha256(f) for f in out.iterdir() if f.is_file()})
    print(f'analysis -> {out}',flush=True)
    return report


def readout(out,r):
    s=r['summary'];lines=['# R043: fresh quiet A/B/C replication','',
        f"Status: {s['status']}; {s['completed_markets']}/{s['planned_markets']} clean complete markets, {s['recorded_markets']} attempted. Three exogenous seeds, two model draws per mode. Missing/affected outcomes remain missing.",'',
        'No news;12sessions; common hidden length/honest prior. C reflects on own outcomes after5/10, used from6/11. Same original economic rules/resources/personas; unseeded Qwen draws.','',
        '## Every eligible primary contrast','',
        'Differences are higher-mode minus lower-mode; return/gap units below are percentage points, not percent changes. Lower gap is not itself realism; passive excess is not risk-adjusted alpha.','',
        '| Seed | Draw | Contrast | Mean gap pp | Meera auction/private pp | Arjun auction/private pp | Reported tokens |',
        '|---|---:|---|---:|---:|---:|---:|']
    for c in r['contrasts']:
        if not c['available']:
            lines.append(f"| {c['seed']} | {c['repetition']} | {c['contrast']} | missing | missing | missing | missing |");continue
        values=c['passive_excess_differences'];fmt=lambda aid:'/'.join(f'{values[aid][m]*100:+.3f}' for m in ('auction','regime_benchmark'))
        lines.append(f"| {c['seed']} | {c['repetition']} | {c['contrast']} | {c['mean_gap_difference']*100:+.3f} | {fmt('llm_012')} | {fmt('llm_013')} | {c['reported_token_difference']:+d} |")
    lines+=['','## Scope, execution and cost','',str(s['usage']),'',f"Reflection HTTP attempts/reported tokens: {r['reflection_cost']}. Delivered but uncleared choices: {r['delivered_but_uncleared']}.",'',
        'report.json retains all per-arm requested/accepted/fill/exposure records, 1-5 and6-12 execution windows, both wealth marks and counterpart accounts, all per-seed repeat averages, partial prefixes and unattempted slots. Full-horizon contrasts require both arms clean and complete.','',
        'Cost by mode includes known retry/repair usage; unknown usage remains explicitly incomplete. Never divide these campaign totals into a universal per-decision price.','',
        'B/C have identical first inputs but can differ before their first reflection through model draws; subsequent histories are endogenous. These are comparisons of specified policies, not same-history isolated reflection effects. No hypothesis test or winner-selection rule is applied.','',r['limitations'],'',
        f"Audit: {r['audit']}", '', 'Older ambiguous-news/disclosed-horizon experiments remain distinct; this is not a causal before/after prompt improvement. No simulator default or mode selection follows automatically.','']
    (out/'READOUT.md').write_text('\n'.join(lines),encoding='utf-8')


def figure(out,r):
    fig,axes=plt.subplots(1,2,figsize=(11,4.8));colors={'B-A':'#0072B2','C-B':'#D55E00'}
    for label,color in colors.items():
        points=[c for c in r['contrasts'] if c['contrast']==label and c['available']]
        for ax,key,scale in ((axes[0],'mean_gap_difference',100),(axes[1],'reported_token_difference',1)):
            positions=[[22853,23971,25087].index(c['seed'])+(-.16 if label=='B-A' else .16) for c in points]
            ax.scatter(positions,[c[key]*scale for c in points],color=color,label=label,alpha=.8,marker='o' if label=='B-A' else 's')
            means=[a for a in r['within_seed_two_draw_averages'] if a['contrast']==label and a['two_draw_average_available']]
            for a in means:
                x=[22853,23971,25087].index(a['seed'])+(-.16 if label=='B-A' else .16)
                ax.plot([x-.09,x+.09],[a[key]*scale]*2,color=color,lw=3)
    for ax in axes:
        ax.axhline(0,color='black',lw=.8);ax.set_xticks(range(3),['22853','23971','25087']);ax.set_xlabel('Exogenous scenario seed')
        ax.grid(axis='y',alpha=.2);ax.spines[['top','right']].set_visible(False)
    axes[0].set_ylabel('Full-path mean valuation-gap difference (pp)')
    axes[1].set_ylabel('Provider-reported token difference')
    axes[0].legend(frameon=False)
    fig.suptitle('R043 quiet components: all available draws and within-seed means')
    fig.text(.5,.015,'Points: model draws nested in three scenarios. Bars: two-draw mean only when both pairs complete. No realism ranking.',ha='center',fontsize=9)
    fig.tight_layout(rect=(0,.045,1,.93))
    for suffix in ('png','pdf'):fig.savefig(out/f'component_contrasts.{suffix}',dpi=180,bbox_inches='tight')
    plt.close(fig)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--study',required=True);parser.add_argument('--output',required=True);args=parser.parse_args()
    analyze(args.study,args.output)
