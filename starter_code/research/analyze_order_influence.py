"""Read sealed R054 outputs; aggregate nested observations and audit settlement."""
import argparse
from collections import defaultdict
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_EVEN
import math
from pathlib import Path
from statistics import mean
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from research.order_influence import BASE, read, write, digest, validate, TARGETS


def aggregate(records):
    changed=[r for r in records if r['price_changed']]
    affected=[r for r in records if r['cap_affected']]
    av=sum(r['factual']['volume'] for r in records)
    cv=sum(r['result']['volume'] for r in records)
    return dict(frames=len(records),cap_affected=len(affected),price_changes=len(changed),
        price_change_pct=100*len(changed)/len(records),
        mean_absolute_impact_pct=mean(r['absolute_price_impact_pct'] for r in records),
        affected_price_changes=sum(r['price_changed'] for r in affected),
        affected_price_change_pct=100*sum(r['price_changed'] for r in affected)/len(affected) if affected else None,
        affected_mean_absolute_impact_pct=mean(r['absolute_price_impact_pct'] for r in affected) if affected else None,
        max_absolute_impact_pct=max(r['absolute_price_impact_pct'] for r in records),
        factual_volume=av,counterfactual_volume=cv,volume_reduction_pct=100*(av-cv)/av if av else None,
        factual_target_volume_share_pct=100*sum(r['factual']['target_involved_volume'] for r in records)/av if av else None,
        changed_fills_same_price=sum(r['target_fills_changed'] and not r['price_changed'] for r in records),
        price_up=sum(r['signed_price_difference']>0 for r in records),
        price_down=sum(r['signed_price_difference']<0 for r in records),
        gap_improves=sum(r['gap_difference_pp'] < -1e-12 for r in records),
        gap_worsens=sum(r['gap_difference_pp'] > 1e-12 for r in records),
        gap_equal=sum(abs(r['gap_difference_pp'])<=1e-12 for r in records),
        mean_gap_difference_pp=mean(r['gap_difference_pp'] for r in records),
        maker_inventory_changes=sum(r['result']['maker_closing_shares']!=r['factual']['maker_closing_shares'] for r in records))


def independent_audit(frames,records):
    """Do not call market.clear/settle: check quantities, candidate price and cash."""
    max_error=0.;account_count=0
    for r in records:
        f=frames[r['frame_index']];out=r['result'];prev=f['previous_price'];cfg=f['config']['market']
        assert cfg['transaction_tax']==0
        tick=Decimal(str(cfg['tick']))
        def snap(x,rule):return float((Decimal(str(x))/tick).to_integral_value(rounding=rule)*tick)
        lo=snap(Decimal(str(prev))*(1-Decimal(str(cfg['price_band']))),ROUND_CEILING)
        hi=snap(Decimal(str(prev))*(1+Decimal(str(cfg['price_band']))),ROUND_FLOOR)
        book=[]
        for o in f['orders']:
            q=int(o['quantity'])
            if o['agent_id'] in TARGETS:q=min(10,q) if r['condition']=='cap10' else 0
            if q and o['side']!='hold':
                limit=snap(o['limit_price'],ROUND_FLOOR if o['side']=='buy' else ROUND_CEILING) if o['limit_price'] else None
                book.append(dict(agent=o['agent_id'],side=o['side'],q=q,limit=limit))
        def eligible(o,p):return o['limit'] is None or (o['limit']>=p if o['side']=='buy' else o['limit']<=p)
        candidates={lo,hi,min(max(snap(prev,ROUND_HALF_EVEN),lo),hi)}
        candidates.update(o['limit'] for o in book if o['limit'] is not None and lo<=o['limit']<=hi)
        capacities={p:min(sum(o['q'] for o in book if o['side']=='buy' and eligible(o,p)),
                          sum(o['q'] for o in book if o['side']=='sell' and eligible(o,p))) for p in candidates}
        cp=min(capacities,key=lambda p:(-capacities[p],abs(p-prev),p));vol=capacities[cp]
        assert out['price']==(cp if vol else prev) and out['volume']==vol
        assert out['unmatched']==sum(o['q'] for o in book)-2*vol
        flows=defaultdict(list);bought=defaultdict(int);sold=defaultdict(int)
        for t in out['trades']:
            assert t['quantity']>0 and t['price']==out['price'] and t['buyer_id']!=t['seller_id']
            q=t['quantity'];gross=q*t['price'];bought[t['buyer_id']]+=q;sold[t['seller_id']]+=q
            flows[t['buyer_id']].append(-gross);flows[t['seller_id']].append(gross)
        for o in book:
            # Maker has one order on each side; other accounts one accepted order.
            filled=bought[o['agent']] if o['side']=='buy' else sold[o['agent']]
            assert filled<=o['q'] and (not filled or eligible(o,out['price']))
        assert sum(bought.values())==sum(sold.values())==vol
        for opening in f['opening']:
            aid=opening['agent_id'];a=out['posttrade_accounts'][aid]
            expected_cash=float(opening['cash'])+math.fsum(flows[aid])
            max_error=max(max_error,abs(expected_cash-a['cash']));assert abs(expected_cash-a['cash'])<1e-8
            assert a['shares']==int(opening['shares'])+bought[aid]-sold[aid]
            assert sold[aid]<=int(opening['shares']) and a['cash']>=-1e-8
            if aid in TARGETS and r['condition']=='remove':assert bought[aid]==sold[aid]==0
            account_count+=1
        assert sum(a['shares'] for a in out['posttrade_accounts'].values())==sum(int(a['shares']) for a in f['opening'])
        assert abs(math.fsum(a['cash'] for a in out['posttrade_accounts'].values())-math.fsum(float(a['cash']) for a in f['opening']))<1e-7
    return dict(status='passed',candidate_price_volume_checks=len(records),account_settlements=account_count,max_cash_error=max_error,
                note='Independent calculation of documented candidate/price rule and cash/share flows;not external market validation.')


def analyze(study,dest):
    study=Path(study).resolve();dest=Path(dest).resolve();dest.mkdir(parents=True,exist_ok=False)
    protocol=validate(study)
    for n,h in read(study/'output_manifest.json').items():assert digest(study/n)==h,n
    assert read(study/'summary.json')['status']=='completed'
    records=read(study/'results.json');frames=read(study/'frames.json')
    assert len(records)==432 and len(frames)==216
    assert {(r['frame_index'],r['condition']) for r in records}=={(i,c) for i in range(216) for c in ('cap10','remove')}
    for r in records:assert r['factual']==frames[r['frame_index']]['factual']
    audit=independent_audit(frames,records)
    grouped={}
    for fields in (('condition',),('seed','condition'),('mode','condition'),('seed','mode','repetition','condition')):
        groups=defaultdict(list)
        for r in records:groups[tuple(r[f] for f in fields)].append(r)
        grouped['_'.join(fields)]=[dict(zip(fields,key),**aggregate(value)) for key,value in sorted(groups.items())]
    examples=[]
    for condition in ('cap10','remove'):
        subset=[r for r in records if r['condition']==condition]
        for rule,key,eligible in (
            ('largest_absolute_price_change',lambda r:r['absolute_price_impact_pct'],subset),
            ('largest_volume_reduction_without_price_change',lambda r:-r['volume_difference'],[r for r in subset if not r['price_changed']])):
            selected=max(eligible,key=key) # stable saved frame order breaks ties
            examples.append(dict(selection_rule=rule,record=selected,accepted_orders=frames[selected['frame_index']]['orders']))
    report=dict(stage='R054 conditional auction influence',protocol_sha256=digest(study/'protocol.json'),
        inputs_sha256={p.relative_to(BASE).as_posix():digest(p) for p in study.iterdir() if p.is_file()},
        aggregates=grouped,audit=audit,examples=examples,
        independent_exogenous_seeds=3,new_model_samples=0,new_endogenous_markets=0,new_api_requests=0,
        note='All 216 nested observed auctions;432 isolated interventions. Descriptive aggregation,not independent sample inference. Examples selected after results by stated extreme rules;not representative.')
    write(dest/'report.json',report);write(dest/'verification.json',audit)
    lines=['# Conditional LLM order influence (R054)','',
        'All 216 R043 auctions reconstructed exactly; 432 isolated counterfactual clears. Three existing seeds, eighteen existing paths; no new model calls or adaptive trajectories. Cap10 retains accepted side/limit and caps each target quantity at ten; remove suppresses both target orders while retaining accounts. Other orders, opening state and allocation RNG are fixed.','',
        '| Seed | Intervention | Changed prices / 72 | Mean absolute price impact (% previous close) | Volume reduction (%) | Changed target fills at same price |',
        '|---|---|---:|---:|---:|---:|']
    for r in grouped['seed_condition']:
        lines.append(f"| {r['seed']} | {r['condition']} | {r['price_changes']}/72 | {r['mean_absolute_impact_pct']:.6f} | {r['volume_reduction_pct']:.3f} | {r['changed_fills_same_price']} |")
    lines += ['', 'All individual markets (twelve nested auctions each):','',
        '| Seed | Mode | Draw | Intervention | Cap-affected frames | Price changes | Mean absolute impact (%) | Volume reduction (%) |',
        '|---|---|---|---|---:|---:|---:|---:|']
    for r in grouped['seed_mode_repetition_condition']:
        lines.append(f"| {r['seed']} | {r['mode']} | {r['repetition']} | {r['condition']} | {r['cap_affected']} | {r['price_changes']} | {r['mean_absolute_impact_pct']:.6f} | {r['volume_reduction_pct']:.3f} |")
    lines += ['', 'The JSON report retains all/affected denominators, signed and benchmark-gap changes, maker inventory and full examples. Lower volume follows mechanically from reducing orders in this maximum-volume auction; the magnitude and price response are the observations. No estimate of persistent caps, agent-count scaling, human behavior or welfare follows.']
    (dest/'READOUT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    fig,axes=plt.subplots(1,2,figsize=(11,6),layout='constrained')
    per=grouped['seed_mode_repetition_condition'];keys=sorted({(r['seed'],r['mode'],r['repetition']) for r in per})
    for condition,color,offset,label in [('cap10','#0072B2',-.13,'Cap each LLM order at 10'),('remove','#D55E00',.13,'Suppress both LLM orders')]:
        rr=[next(r for r in per if (r['seed'],r['mode'],r['repetition'])==key and r['condition']==condition) for key in keys]
        ys=[i+offset for i in range(len(keys))]
        axes[0].scatter([r['price_changes'] for r in rr],ys,c=color,s=30,label=label)
        axes[1].scatter([r['volume_reduction_pct'] for r in rr],ys,c=color,s=30)
    axes[0].set_yticks(range(len(keys)),[f'{s}  {m}  draw {d}' for s,m,d in keys]);axes[1].set_yticks(range(len(keys)),[])
    for ax in axes:ax.invert_yaxis();ax.grid(axis='x',alpha=.25)
    axes[0].set_xlabel('Auctions with a different clearing price / 12');axes[0].set_xticks(range(0,13,2));axes[0].set_xlim(-.5,12.5)
    axes[1].set_xlabel('Reduction in total executed volume (%)')
    axes[0].legend(loc='upper right',fontsize=8)
    fig.suptitle('Immediate auction effects, conditional on actual books\n18 existing paths; each hypothetical auction starts from its factual state',fontsize=12)
    fig.savefig(dest/'order_influence.png',dpi=180);fig.savefig(dest/'order_influence.pdf');plt.close(fig)
    write(dest/'output_manifest.json',{p.name:digest(p) for p in dest.iterdir() if p.is_file() and p.name!='output_manifest.json'})
    print(__import__('json').dumps(dict(overall=grouped['condition'],seeds=grouped['seed_condition'],audit=audit),indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--study',required=True);p.add_argument('--output',required=True);a=p.parse_args();analyze(a.study,a.output)
