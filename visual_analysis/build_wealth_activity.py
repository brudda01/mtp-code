"""Price and volume figure from the three eligible saved wealth ledgers."""
from pathlib import Path
import json
B=Path(__file__).resolve().parent
(B/"figures").mkdir(exist_ok=True)
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
plt.rcParams.update({'font.size':11,'axes.spines.top':False,'axes.spines.right':False,'pdf.fonttype':42})
fig,axs=plt.subplots(1,2,figsize=(7,2.8),layout='constrained')
for name,label,color,style in [('s42_heterogeneous','42 heterogeneous','#287c8e','-'),('s43_equal','43 equal','#64748b','--'),('s43_heterogeneous','43 heterogeneous','#b56b43','-.')]:
 p=B.parent/'sandbox_experiments/runs/wealth_live_12llm_100round_fast110'/name/'ledger.jsonl'
 data=[json.loads(l) for l in p.read_text(encoding='utf-8').splitlines()]
 rows=[r for r in data if r['kind']=='round']; assert len(rows)==100
 for ax,key in zip(axs,['price','volume']): ax.plot([r['round'] for r in rows],[r[key] for r in rows],color=color,ls=style,lw=1.4,label=label)
axs[0].axhline(100,color='black',ls=':',lw=.7)
axs[0].set_ylabel('Price'); axs[1].set_ylabel('Traded shares')
for ax in axs: ax.set_xlabel('Round'); ax.tick_params(labelsize=9)
handles,labels=axs[0].get_legend_handles_labels()
fig.legend(handles,labels,loc='outside upper center',ncol=3,fontsize=9,frameon=False)
fig.savefig(B/'figures/wealth_talk.pdf',bbox_inches='tight'); plt.close(fig)
