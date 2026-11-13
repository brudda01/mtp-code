"""Read-only evidence analysis for R055 and completed/partial R056."""
import argparse
from collections import defaultdict,Counter
import json
from pathlib import Path
from statistics import mean
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from research.order_influence import BASE,read,write,digest,rows
from research.goedel_cohort import validate,audit_financial,metrics

KEYS=('price_return_sd_pct','maker_boundary_fraction','mean_gap_pct','max_drawdown_pct','volume')


def verify_outputs(root):
    validate(root)
    for n,h in read(root/'output_manifest.json').items():assert digest(root/n)==h,n


def dynamic(root,dest):
    root=Path(root).resolve();dest=Path(dest).resolve();dest.mkdir(parents=True,exist_ok=False);verify_outputs(root)
    controls=read(root/'controls.json');runs=read(root/'runs.json');assert len(controls)==18 and len(runs)==36
    by={r['donor_path']:r for r in controls};contrasts=[]
    for r in controls+runs:
        path=root/r['run_path'];audit=audit_financial(path);assert audit==r['audit'];assert metrics(path)==r['metrics']
    for r in runs:
        original=by[r['donor_path']]
        contrasts.append(dict(**{k:r[k] for k in ('seed','mode','repetition','condition','run_path','donor_path')},
            original=original['metrics'],intervention=r['metrics'],delta={k:r['metrics'][k]-original['metrics'][k] for k in KEYS}))
    summaries=[]
    for seed in sorted({r['seed'] for r in runs}):
        for condition in ('cap10','remove'):
            subset=[r for r in contrasts if r['seed']==seed and r['condition']==condition]
            summaries.append(dict(seed=seed,condition=condition,comparisons=6,mean_delta={k:mean(r['delta'][k] for r in subset) for k in KEYS}))
    signs={c:{k:dict(Counter('lower' if r['delta'][k]<-1e-10 else 'higher' if r['delta'][k]>1e-10 else 'equal' for r in contrasts if r['condition']==c)) for k in KEYS} for c in ('cap10','remove')}
    # Removal ignores original tapes: within seed all six financial paths must match.
    removal_identity=[]
    for seed in sorted({r['seed'] for r in runs}):
        rr=[r for r in runs if r['seed']==seed and r['condition']=='remove']
        for name in ('prices.csv','trades.csv','agents_state.csv','cashflows.csv','liquidity.csv','initial_state.csv','orders.csv'):
            assert len({digest(root/r['run_path']/name) for r in rr})==1,(seed,name)
        removal_identity.append(dict(seed=seed,executions=6,unique_financial_paths=1,matched_files=7))
    examples=[r for r in contrasts if r['condition']=='cap10' and r['delta']['volume']>0]
    report=dict(study='R055',status='completed',protocol_sha256=digest(root/'protocol.json'),
        inputs_sha256={n:digest(root/n) for n in ('protocol.json','preparation.json','gate_summary.json','controls.json','runs.json','summary.json','output_manifest.json')},
        controls=18,dynamic_executions=36,distinct_removal_paths=3,existing_seeds=3,
        account_rounds_rechecked=9072,contrasts=contrasts,seed_summaries=summaries,signs=signs,
        removal_identity=removal_identity,cap_volume_increase_examples=examples,
        all_maker_boundary_fractions_zero=all(r['metrics']['maker_boundary_fraction']==0 for r in controls+runs),
        new_api_requests=0,new_model_samples=0,
        limitation='Rule agents adapt;the factual accepted LLM tape does not. No adaptive LLM policy effect or long-run stability claim. Three inherited scenarios;18 removal executions collapse to3unique paths.')
    write(dest/'report.json',report)
    lines=['# R055 dynamic rule response to fixed LLM order tapes','',
        'All18 uncapped factual controls reproduced before36 intervention paths. No new LLM calls. The eighteen removal executions collapse to three distinct financial paths (one per original seed).','',
        '| Seed | Intervention | Return SD change (pp) | Maker boundary change (pp) | Mean reference-gap change (pp) | Maximum drawdown change (pp) | Mean volume change (shares) |',
        '|---|---|---:|---:|---:|---:|---:|']
    for r in summaries:
        d=r['mean_delta'];lines.append(f"| {r['seed']} | {r['condition']} | {d['price_return_sd_pct']:+.6f} | {100*d['maker_boundary_fraction']:+.3f} | {d['mean_gap_pct']:+.6f} | {d['max_drawdown_pct']:+.6f} | {d['volume']:+.3f} |")
    lines+=['','All eighteen inherited paths, each compared to its own uncapped control:','',
        '| Seed | Mode | Draw | Intervention | Return SD change (pp) | Gap change (pp) | Drawdown change (pp) | Volume change |','|---|---|---|---|---:|---:|---:|---:|']
    for r in sorted(contrasts,key=lambda r:(r['seed'],r['mode'],r['repetition'],r['condition'])):
        d=r['delta'];lines.append(f"| {r['seed']} | {r['mode']} | {r['repetition']} | {r['condition']} | {d['price_return_sd_pct']:+.6f} | {d['mean_gap_pct']:+.6f} | {d['max_drawdown_pct']:+.6f} | {d['volume']:+d} |")
    lines+=['','All boundary fractions are zero: there is no observed boundary-avoidance benefit. Twelve sessions are too short for long-run stability or stylized-fact claims. Fixed future tape orders arose from factual histories, so only the rule background adapts in these sensitivity paths.']
    (dest/'READOUT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    keys=sorted({(r['seed'],r['mode'],r['repetition']) for r in contrasts})
    fig,axes=plt.subplots(1,2,figsize=(11,7),layout='constrained')
    for c,col,offset in [('cap10','#0072B2',-.13),('remove','#D55E00',.13)]:
        rr=[next(r for r in contrasts if (r['seed'],r['mode'],r['repetition'])==k and r['condition']==c) for k in keys]
        y=[i+offset for i in range(18)]
        for ax,k in zip(axes,('price_return_sd_pct','mean_gap_pct')):ax.scatter([r['delta'][k] for r in rr],y,color=col,label=c,s=30)
    axes[0].set_yticks(range(18),[f'{s} {m} draw {d}' for s,m,d in keys]);axes[1].set_yticks(range(18),[])
    for ax in axes:ax.invert_yaxis();ax.axvline(0,color='grey',linewidth=1);ax.grid(axis='x',alpha=.25)
    axes[0].set_xlabel('Change in log-price-return SD (percentage points)');axes[1].set_xlabel('Change in mean reference gap (percentage points)');axes[0].legend()
    fig.suptitle('Dynamic rule responses with fixed original LLM order tapes\n12-session sensitivity paths; LLM choices do not adapt; all maker-boundary fractions zero',fontsize=11)
    fig.savefig(dest/'dynamic_contrasts.png',dpi=170);fig.savefig(dest/'dynamic_contrasts.pdf');plt.close(fig)
    write(dest/'output_manifest.json',{p.name:digest(p) for p in dest.iterdir() if p.is_file() and p.name!='output_manifest.json'})
    print(json.dumps(dict(signs=signs,seed_summaries=summaries,volume_increase=examples,removal_identity=removal_identity),indent=2))


def check_live_inputs(path):
    path=Path(path)
    requests=[json.loads(l) for l in (path/'llm_requests.jsonl').read_text().splitlines()]
    decisions=[json.loads(l) for l in (path/'llm_calls.jsonl').read_text().splitlines()]
    outcomes=[json.loads(l) for l in (path/'agent_outcomes.jsonl').read_text().splitlines()]
    personas=read(path/'personas.json');assert len(personas)==6
    # Own-history records checked directly against each actor's recorded outcomes.
    from research.goedel_cohort import CappedAgent
    from sim.agents.base import Observation
    import numpy as np
    cfg=__import__('yaml').safe_load((path/'config.yaml').read_text());initial=rows(path/'initial_state.csv');states=rows(path/'agents_state.csv');prices=rows(path/'prices.csv')
    checked=0;input_checks=0
    for call in decisions:
        aid=call['agent_id'];rnd=int(call['round']);actor=[x for x in outcomes if x['agent_id']==aid and int(x['round'])<rnd]
        # Literal own verified outcome list in the original user message; no reconstruction from prose.
        memories=[x['outcome'] for x in actor][-5:]
        user=call.get('messages',[{},{}])[-1].get('content','')
        if not user:
            matching=[x for x in requests if x.get('agent_id')==aid and x.get('round')==rnd and x.get('call_type')=='decision']
            user=matching[0]['messages'][-1]['content']
        marker='Your recent verified outcomes: '
        assert marker in user
        raw=user.split(marker,1)[1].split('\nComputed facts',1)[0]
        assert json.loads(raw)==memories
        assert f'Round {rnd}/25.' not in user
        opening=next(x for x in (initial if rnd==1 else states) if x['agent_id']==aid and (rnd==1 or int(x['round'])==rnd-1))
        actor_agent=CappedAgent(aid,float(opening['cash']),int(opening['shares']),np.random.default_rng(0),
            params=dict(condition='B',memory_window=5,tick=cfg['market']['tick'],ticker=cfg['asset']['ticker'],round_unit=cfg['time']['round_unit']),
            persona=personas[aid],initial_cost=float(opening['avg_cost']),transaction_tax=cfg['market']['transaction_tax'],price_band=cfg['market']['price_band'])
        actor_agent.memory=memories
        past_trades=[]
        for t in rows(path/'trades.csv'):
            if int(t['round'])>=rnd:continue
            if t['buyer_id']==aid:past_trades.append(f"r{t['round']}: bought {t['quantity']} @ {float(t['price']):.2f}")
            if t['seller_id']==aid:past_trades.append(f"r{t['round']}: sold {t['quantity']} @ {float(t['price']):.2f}")
        previous=[cfg['asset']['initial_price']]+[float(p['price']) for p in prices if int(p['round'])<rnd]
        obs=Observation(rnd,25,previous[-cfg['observation']['price_history_len']:],
            0 if rnd==1 else int(prices[rnd-2]['volume']),
            cfg['asset']['dividend']['mean'] if rnd==1 else float(prices[rnd-2]['dividend']),
            cfg['asset']['risk_free'],None,[],[],actor_agent.cash,actor_agent.shares,actor_agent.avg_cost,
            actor_agent.wealth(previous[-1]),past_trades[-5:],cfg['time']['round_unit'])
        assert actor_agent.user_prompt(obs)==user,(aid,rnd,'actual input differs')
        assert actor_agent.system_prompt(cfg['asset']['ticker'])==call['system_prompt']
        input_checks+=1
        checked+=1
    return dict(own_history_messages_checked=checked,complete_actual_input_pairs_checked=input_checks)


def live(root,dest):
    root=Path(root).resolve();dest=Path(dest).resolve();dest.mkdir(parents=True,exist_ok=False);verify_outputs(root)
    summary=read(root/'summary.json');path=root/summary['run_path'];audit=audit_financial(path)
    checked_inputs=check_live_inputs(path)
    personas=read(path/'personas.json');states=rows(path/'agents_state.csv');prices=rows(path/'prices.csv')
    ev=read(root/'evaluation.json') if (root/'evaluation.json').exists() else None
    per=[]
    orders=rows(path/'orders.csv');trades=rows(path/'trades.csv')
    for aid,p in personas.items():
        rr=[o for o in orders if o['agent_id']==aid];acct=next((x for x in ev['accounts'] if x['agent_id']==aid),None) if ev else None
        per.append(dict(agent_id=aid,name=p['name'],requested_actions=dict(Counter(o['llm_requested_side'] for o in rr)),
            accepted_actions=dict(Counter(o['side'] for o in rr)),cap_adjustments=sum(int(o['llm_requested_quantity'] or 0)>10 for o in rr),
            bought=sum(int(t['quantity']) for t in trades if t['buyer_id']==aid),sold=sum(int(t['quantity']) for t in trades if t['seller_id']==aid),
            account=acct))
    report=dict(study='R056',summary=summary,metrics=metrics(path),audit=audit,**checked_inputs,per_persona=per,
        status=summary['status'],protocol_sha256=digest(root/'protocol.json'),independent_scenarios=1,
        limitations='Single six-LLM capped25-session cohort with newmodel/population/horizon. No isolated cross-model/count effect or general stability claim.')
    write(dest/'report.json',report)
    fig,axes=plt.subplots(2,1,figsize=(10,6),layout='constrained',sharex=True)
    x=[int(p['round']) for p in prices];axes[0].plot([0]+x,[100]+[float(p['price']) for p in prices],label='Auction price');axes[0].axhline(100,color='grey',linestyle='--',label='Private reference');axes[0].legend();axes[0].set_ylabel('Price')
    maker=[r for r in states if r['agent_id']=='mark_000'];axes[1].plot([0]+x,[150]+[int(r['shares']) for r in maker],label='Maker shares')
    axes[1].axhline(0,color='grey',linestyle=':');axes[1].axhline(300,color='grey',linestyle=':');axes[1].set_ylim(-10,310);axes[1].set_ylabel('Maker inventory');axes[1].set_xlabel('Uncalibrated trading session')
    fig.suptitle(f'DeepSeek six-LLM capped B cohort: {summary["status"]}\nOne seed, separate study; no causal comparison with Qwen',fontsize=11)
    fig.savefig(dest/'goedel_path.png',dpi=170);fig.savefig(dest/'goedel_path.pdf');plt.close(fig)
    write(dest/'output_manifest.json',{p.name:digest(p) for p in dest.iterdir() if p.is_file() and p.name!='output_manifest.json'})
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('study',choices=('dynamic','live'));a.add_argument('--root',required=True);a.add_argument('--output',required=True);x=a.parse_args();{'dynamic':dynamic,'live':live}[x.study](x.root,x.output)
