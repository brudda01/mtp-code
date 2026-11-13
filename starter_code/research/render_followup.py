"""Render all-case R051 diagnostics from saved data; never runs markets."""
import csv
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

BASE=Path(__file__).resolve().parents[1]


def main():
    root=BASE/'runs/background_diversity_20261106';r=json.loads((root/'report.json').read_text())
    output=root/'review';output.mkdir(exist_ok=False)
    seeds=[c['seed'] for c in r['contrasts']];x=np.arange(4)
    fig,axes=plt.subplots(1,3,figsize=(15,4.7))
    for h,label,offset,color in [('False','Homogeneous',-.08,'#326ba8'),('True','Heterogeneous',.08,'#d16b2b')]:
        for ax,metric,scale in [(axes[0],'acf_returns_lag1',1),(axes[1],'mm_boundary_fraction',100)]:
            ax.scatter(x+offset,[scale*c['no_skew_minus_skew'][h][metric] for c in r['contrasts']],label=label,color=color,s=55)
    for skew,label,offset,color in [(.02,'Original skew',-.08,'#326ba8'),(0.,'No skew',.08,'#d16b2b')]:
        d=[]
        for seed in seeds:
            by={a['heterogeneous']:a['result'] for a in r['arms'] if a['seed']==seed and a['skew']==skew}
            d.append(100*(by[True]['mean_absolute_relative_gap']-by[False]['mean_absolute_relative_gap']))
        axes[2].scatter(x+offset,d,label=label,color=color,s=55)
    for ax,title,ylabel in zip(axes,['Removing skew: return dependence','Removing skew: inventory boundaries','Adding heterogeneity: valuation gap'],
                                ['No-skew minus skew ACF1','No-skew minus skew boundary time (pp)','Heterogeneous minus homogeneous gap (pp)']):
        ax.axhline(0,color='black',linewidth=.7);ax.set_xticks(x,seeds);ax.set_title(title);ax.set_ylabel(ylabel);ax.set_xlabel('Exogenous seed');ax.legend();ax.grid(axis='y',alpha=.2)
    fig.suptitle('Four fresh scenarios; all outcomes retained; no realism/default-selection criterion')
    fig.tight_layout()
    for ext in ('png','pdf'):fig.savefig(output/f'background_diversity.{ext}',dpi=160)
    plt.close(fig)
    fig,axes=plt.subplots(4,2,figsize=(13,13),sharex=True)
    for j,seed in enumerate(seeds):
        for h,skew,color,style,label in [(False,.02,'#326ba8','-','Homogeneous / skew'),(False,0.,'#326ba8','--','Homogeneous / no skew'),
                                       (True,.02,'#d16b2b','-','Heterogeneous / skew'),(True,0.,'#d16b2b','--','Heterogeneous / no skew')]:
            arm=next(a for a in r['arms'] if a['seed']==seed and a['heterogeneous']==h and a['skew']==skew)
            with (root/arm['path']/'prices.csv').open() as f:prices=list(csv.DictReader(f))
            with (root/arm['path']/'agents_state.csv').open() as f:states=[v for v in csv.DictReader(f) if v['agent_id']=='mark_000']
            axes[j,0].plot([int(v['round']) for v in prices],[float(v['price']) for v in prices],color=color,linestyle=style,linewidth=.8,label=label)
            axes[j,1].plot([int(v['round']) for v in states],[int(v['shares']) for v in states],color=color,linestyle=style,linewidth=.8)
        axes[j,0].axhline(100,color='gray',linestyle=':',linewidth=.8)
        axes[j,0].set_ylabel(f'Seed {seed}\nAuction price');axes[j,1].set_ylabel('Maker shares');axes[j,1].set_ylim(-5,305)
    axes[0,0].legend(fontsize=8);axes[-1,0].set_xlabel('Simulation session');axes[-1,1].set_xlabel('Simulation session')
    fig.suptitle('All 16 price/inventory paths: heterogeneous policies do not ensure smaller valuation gaps')
    fig.tight_layout()
    for ext in ('png','pdf'):fig.savefig(output/f'all_paths.{ext}',dpi=150)
    plt.close(fig)
    print(output)


if __name__=='__main__':main()
