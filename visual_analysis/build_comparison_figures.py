"""Presentation-only assets from finalized findings; no simulation or API calls."""
from pathlib import Path
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

B = Path(__file__).resolve().parent
(B/'figures').mkdir(exist_ok=True)
# Complete six-context contrasts, rounded as in the preserved R047 readout.
labels = ['22853 / 1', '22853 / 2', '23971 / 1', '23971 / 2', '25087 / 1', '25087 / 2']
values = [-1.3571, 0, 0, 0.3286, 0, -0.2286]
plt.rcParams.update({'font.family':'DejaVu Sans', 'font.size':10,
                     'pdf.fonttype':42, 'axes.spines.top':False,
                     'axes.spines.right':False, 'axes.spines.left':False})
fig,ax=plt.subplots(figsize=(4.3,2.4),layout='constrained')
for index,value in enumerate(values):
    if value:
        ax.barh(index,value,height=.47,color='#287c8e' if value<0 else '#d47c28')
    else:
        ax.plot(0,index,'o',color='#65727a',ms=5)
    ax.text(value-.055 if value<0 else value+.055,index,
            f'{value:+.3f}' if value else '0.000',va='center',
            ha='right' if value<0 else 'left',fontsize=10)
ax.set_yticks(range(6),labels)
ax.invert_yaxis(); ax.axvline(0,color='#8f999e',lw=.8,zorder=0)
ax.set_xlim(-1.9,.85); ax.set_xticks([-1.5,-1,-.5,0,.5])
ax.set_xlabel('C minus B mean reference gap (pp)',fontsize=10)
ax.tick_params(axis='y',length=0)
ax.grid(axis='x',alpha=.12); ax.set_axisbelow(True)
fig.savefig(B/'figures/shared_history.pdf',bbox_inches='tight'); plt.close(fig)

# Read only recorded closing-round observations for presentation figures.
root=B.parent
wealth_root=root/'sandbox_experiments/runs/wealth_live_12llm_100round_fast110'
forum_root=root/'sandbox_experiments/runs/forum_heterogeneous_s42_s43_110rpm'
def rounds(path):
    result=[]
    with path.open(encoding='utf-8') as stream:
        for line in stream:
            record=json.loads(line)
            if record.get('kind')=='round':
                result.append({k:record[k] for k in ['round','price','volume']})
    assert [r['round'] for r in result]==list(range(1,101)),path
    return result
series=[('s42_heterogeneous','42 heterogeneous','#287c8e','-'),
        ('s43_equal','43 equal','#64748b','--'),
        ('s43_heterogeneous','43 heterogeneous','#d47c28','-')]
wealth={name:rounds(wealth_root/name/'ledger.jsonl') for name,*_ in series}
plt.rcParams.update({'font.size':11,'axes.spines.left':True})
fig,ax=plt.subplots(figsize=(6.2,2.5),layout='constrained')
for name,label,color,style in series:
    data=wealth[name]
    ax.plot([0]+[r['round'] for r in data],[100]+[r['price'] for r in data],
            color=color,ls=style,lw=1.7,label=label)
ax.axhline(100,color='black',ls=':',lw=.8)
ax.set(xlabel='Round',ylabel='Clearing price',xlim=(0,100))
ax.legend(loc='upper left',ncol=1,frameon=False,fontsize=10)
ax.grid(alpha=.12); fig.savefig(B/'figures/wealth_prices.pdf');plt.close(fig)

first=[sum(r['volume'] for r in wealth[name][:25]) for name,*_ in series]
last=[sum(r['volume'] for r in wealth[name][-25:]) for name,*_ in series]
zeros=[sum(r['volume']==0 for r in wealth[name][-25:]) for name,*_ in series]
assert first==[314,484,343] and last==[65,72,62] and zeros==[14,12,12]
fig,ax=plt.subplots(figsize=(6.2,2.5),layout='constrained')
x=range(3)
for shift,values,color,label in [(-.19,first,'#287c8e','Rounds 1–25'),(.19,last,'#d47c28','Rounds 76–100')]:
    bars=ax.bar([i+shift for i in x],values,width=.34,color=color,label=label)
    ax.bar_label(bars,padding=3,fontsize=11)
ax.set_xticks(list(x),['42 heterogeneous','43 equal','43 heterogeneous'])
ax.set(ylabel='Shares traded in 25 rounds',ylim=(0,650))
ax.legend(ncol=2,frameon=False,fontsize=10,loc='upper left')
ax.grid(axis='y',alpha=.12);ax.set_axisbelow(True)
fig.savefig(B/'figures/wealth_activity.pdf');plt.close(fig)

fig,axes=plt.subplots(1,2,figsize=(7,2.65),layout='constrained',sharey=True)
forum={}
for ax,seed in zip(axes,[42,43]):
    control=wealth[f's{seed}_heterogeneous']
    posted=rounds(forum_root/f's{seed}_heterogeneous_posts'/'ledger.jsonl')
    forum[seed]=posted
    ax.axvspan(20.5,40.5,color='#287c8e',alpha=.13)
    ax.axvspan(40.5,60.5,color='#d47c28',alpha=.15)
    for data,color,style,label in [(control,'#64748b','--','Historical control'),(posted,'#287c8e','-','Opinion feed')]:
        ax.plot([0]+[r['round'] for r in data],[100]+[r['price'] for r in data],
                color=color,ls=style,lw=1.65,label=label)
    ax.set(title=f'Seed {seed}',xlabel='Round',xlim=(0,100))
    ax.grid(alpha=.12)
axes[0].set_ylabel('Clearing price')
handles,labels=axes[0].get_legend_handles_labels()
fig.legend(handles,labels,loc='outside upper center',ncol=2,frameon=False,fontsize=10)
assert [sum(r['volume'] for r in forum[s]) for s in [42,43]]==[674,844]
fig.savefig(B/'figures/forum_prices.pdf');plt.close(fig)
print('Generated reflection, wealth-price, wealth-activity and forum-price figures from saved findings.')
