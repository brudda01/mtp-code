"""All-path secondary price/inventory display; no additional simulation."""
from statistics import mean
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from research.order_influence import BASE,read,write,rows,digest


def main():
    root=BASE/'runs/dynamic_order_tape_20261108';dest=BASE/'runs/final_extensions_review_20261108';dest.mkdir(exist_ok=True)
    records=read(root/'controls.json')+read(root/'runs.json');keys=sorted({(r['seed'],r['mode'],r['repetition']) for r in records})
    groups={k:{r['condition']:r for r in records if (r['seed'],r['mode'],r['repetition'])==k} for k in keys}
    contrasts=[]
    for k,g in groups.items():
        base=g['uncapped']['metrics'];width=base['maker_max']-base['maker_min']
        for condition in ('cap10','remove'):
            m=g[condition]['metrics'];contrasts.append(dict(seed=k[0],mode=k[1],repetition=k[2],condition=condition,
                factual_closing_range=width,intervention_closing_range=m['maker_max']-m['maker_min'],
                range_delta=m['maker_max']-m['maker_min']-width))
    summary=[dict(seed=s,condition=c,mean_closing_inventory_range_change=mean(r['range_delta'] for r in contrasts if r['seed']==s and r['condition']==c)) for s in sorted({k[0] for k in keys}) for c in ('cap10','remove')]
    write(dest/'inventory_sensitivity.json',dict(note='Prespecified secondary inventory range,computed over closing sessions;initial150 excluded from this range as in frozen metrics. All-path figures include initial150. Not a new primary endpoint or evidence of boundary avoidance.',contrasts=contrasts,seed_summary=summary))
    for outcome in ('price','inventory'):
        fig,axes=plt.subplots(6,3,figsize=(13,17),layout='constrained',sharex=True,sharey=outcome=='inventory')
        for ax,key in zip(axes.flat,keys):
            for c,color,style in [('uncapped','#333333','-'),('cap10','#0072B2','-'),('remove','#D55E00','--')]:
                path=root/groups[key][c]['run_path']
                if outcome=='price':data=[100]+[float(r['price']) for r in rows(path/'prices.csv')]
                else:data=[150]+[int(r['shares']) for r in rows(path/'agents_state.csv') if r['agent_id']=='mark_000']
                ax.plot(range(13),data,label=c,color=color,linestyle=style,linewidth=1.4)
            ax.set_title(f'{key[0]} / {key[1]} / draw {key[2]}',fontsize=10);ax.grid(alpha=.2)
            if outcome=='inventory':ax.set_ylim(0,300);ax.axhline(150,linestyle=':',color='grey',linewidth=.7)
            else:ax.axhline(100,linestyle=':',color='grey',linewidth=.7)
        axes[0,0].legend(fontsize=8)
        fig.supxlabel('Uncalibrated session');fig.supylabel('Auction price' if outcome=='price' else 'Maker shares')
        fig.suptitle('R055: all dynamic '+outcome+' paths\nFixed original LLM tapes;rule agents adapt;removal paths repeat within seed',fontsize=13)
        fig.savefig(dest/f'dynamic_{outcome}_paths.pdf');fig.savefig(dest/f'dynamic_{outcome}_paths.png',dpi=140);plt.close(fig)
    write(dest/'render_manifest.json',{p.name:digest(p) for p in dest.iterdir() if p.is_file() and p.name!='render_manifest.json'})
    print(__import__('json').dumps(summary,indent=2))


if __name__=='__main__':main()
