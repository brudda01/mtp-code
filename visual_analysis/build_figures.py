"""Presentation-only figures from preserved reports and ledgers. No simulation."""
from pathlib import Path
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
ROOT=Path(__file__).resolve().parents[1]; OUT=Path(__file__).parent/'figures'
OUT.mkdir(exist_ok=True)
plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False,'pdf.fonttype':42})
def save(fig,name):
    fig.savefig(OUT/(name+'.pdf'),bbox_inches='tight',pad_inches=.08)
    fig.savefig(OUT/(name+'.png'),dpi=130,bbox_inches='tight',pad_inches=.08)
    plt.close(fig)
def box(ax,x,y,w,h,text):
    ax.add_patch(FancyBboxPatch((x,y),w,h,boxstyle='round,pad=.015',facecolor='#edf2f7',edgecolor='#475569'))
    ax.text(x+w/2,y+h/2,text,ha='center',va='center',fontsize=9)
def arrow(ax,a,b): ax.annotate('',xy=b,xytext=a,arrowprops=dict(arrowstyle='->',color='#475569'))
fig,ax=plt.subplots(figsize=(7,3.2)); ax.set(xlim=(0,1),ylim=(0,1)); ax.axis('off')
box(ax,.02,.65,.26,.24,'Public history and\nown account state')
box(ax,.37,.65,.26,.24,'Alternative inputs:\nA raw; B factual; C diary')
box(ax,.72,.65,.26,.24,'Requested order\nand explanation')
box(ax,.72,.15,.26,.24,'Feasibility checks\nand accepted orders')
box(ax,.37,.15,.26,.24,'Uniform-price auction\nwith parallel rule orders')
box(ax,.02,.15,.26,.24,'Fills, settlement\nand income')
for a,b in [((.28,.77),(.37,.77)),((.63,.77),(.72,.77)),((.85,.65),(.85,.39)),((.72,.27),(.63,.27)),((.37,.27),(.28,.27)),((.15,.39),(.15,.65))]: arrow(ax,a,b)
ax.text(.50,.51,'Verified outcomes feed later decisions',fontsize=9,ha='center'); save(fig,'pipeline')
fig,axs=plt.subplots(1,2,figsize=(7,3.2),layout='constrained')
labels=['16253','17341','18433','19531','26183 H','26183 D','27329 H','27329 D','28513 H','28513 D','29671 H','29671 D']
acf=[-.0499,-.0955,-.0496,-.0390,-.006428,-.102209,-.074986,-.097649,-.159922,-.255097,-.084808,-.092784]
axs[0].barh(range(12),acf,color=['#64748b']*4+['#287c8e']*8); axs[0].set_yticks(range(12),labels,fontsize=8); axs[0].invert_yaxis(); axs[0].set_xlabel('No-skew minus skew: return ACF(1)'); axs[0].axvline(0,color='black',lw=.7)
axs[1].barh(range(8),[1.167,1.667,5.333,5.667,.5,2.833,9.167,1.833],color='#b56b43'); axs[1].set_yticks(range(8),labels[4:],fontsize=8); axs[1].invert_yaxis(); axs[1].set_xlabel('Boundary-time difference (pp)')
save(fig,'inventory')
fig,axs=plt.subplots(1,2,figsize=(7,2.8),layout='constrained')
axs[0].bar(['Visible','Silent'],[22,72],color=['#287c8e','#b56b43']); axs[0].set_ylabel('Session-5 traded shares'); axs[0].set_title('Same execution price: 92.8')
axs[1].bar(['Meera','Arjun'],[50,-50],color=['#287c8e','#b56b43']); axs[1].axhline(0,color='black',lw=.8); axs[1].set_ylabel('Extra shares in silent condition'); axs[1].set_title('Selected transfer at unchanged price')
save(fig,'transfer')
fig,axs=plt.subplots(1,2,figsize=(7,2.9),layout='constrained')
axs[0].bar(['Cap ten','Suppress'],[49,74],color=['#287c8e','#b56b43']); axs[0].set_ylim(0,216); axs[0].set_ylabel('Price-changing auctions / 216')
axs[1].bar(['Factual','Cap ten','Suppress'],[5118,4339,3801],color=['#64748b','#287c8e','#b56b43']); axs[1].set_ylabel('Total shares in isolated auctions'); save(fig,'influence')
fig,axs=plt.subplots(3,1,figsize=(7,4.8),sharex=True,layout='constrained')
for name,label,col in [('s42_heterogeneous','42 heterogeneous','#287c8e'),('s43_equal','43 equal','#64748b'),('s43_heterogeneous','43 heterogeneous','#b56b43')]:
    data=[json.loads(l) for l in (ROOT/'sandbox_experiments/runs/wealth_live_12llm_100round_fast110'/name/'ledger.jsonl').read_text(encoding='utf-8').splitlines()]
    rows=[x for x in data if x['kind']=='round']; x=[r['round'] for r in rows]
    style={'s42_heterogeneous':'-','s43_equal':'--','s43_heterogeneous':'-.'}[name]
    for ax,y in zip(axs,[[r['price'] for r in rows],[r['volume'] for r in rows],[r['closing']['maker']['shares'] for r in rows]]): ax.plot(x,y,label=label,color=col,lw=1,ls=style)
axs[0].axhline(100,color='black',ls=':',lw=.7); axs[0].legend(fontsize=8,ncol=3); axs[0].set_ylabel('Price'); axs[1].set_ylabel('Volume'); axs[2].set_ylabel('Maker shares'); axs[2].set_xlabel('Session'); save(fig,'wealth')
series=json.loads((ROOT/'thesis/content_strategy_audit/forum_completed_20261110/series.json').read_text(encoding='utf-8'))
fig,axs=plt.subplots(2,2,figsize=(7,5.3),sharex=True,sharey='row',layout='constrained')
for col,seed in enumerate([42,43]):
    for condition,label,color,style in [('silent','Historical control','#64748b','--'),('posts','Opinion feed','#b56b43','-')]:
        rows=sorted([r for r in series if r['seed']==seed and r['condition']==condition],key=lambda r:r['round'])
        assert len(rows)==100,(seed,condition,len(rows))
        for row,key in [(0,'price'),(1,'volume')]:
            axs[row,col].plot([r['round'] for r in rows],[r[key] for r in rows],label=label,color=color,ls=style,lw=1.2)
    for row in [0,1]:
        axs[row,col].axvspan(20.5,40.5,color='#bcd8c5',alpha=.35)
        axs[row,col].axvspan(40.5,60.5,color='#e8c6c6',alpha=.35)
        axs[row,col].set_xlim(1,100)
    axs[0,col].axhline(100,color='black',ls=':',lw=.7)
    axs[0,col].set_title(f'Seed {seed}: heterogeneous endowments',fontsize=10)
    axs[0,col].legend(fontsize=8,loc='lower right')
    axs[0,col].text(30.5,157,'Bullish',rotation=90,fontsize=8,ha='center',va='top')
    axs[0,col].text(50.5,157,'Bearish',rotation=90,fontsize=8,ha='center',va='top')
    axs[0,col].set_ylim(97,160)
    axs[1,col].set_xlabel('Session')
axs[0,0].set_ylabel('Price'); axs[1,0].set_ylabel('Traded shares per session')
save(fig,'forum')
fig,ax=plt.subplots(figsize=(7,3.2)); ax.set(xlim=(0,1),ylim=(0,1)); ax.axis('off')
box(ax,.02,.38,.3,.3,'Actual B history\nsessions 1 to 5\nSame accounts at fork')
for y,label in [(.84,'B1: factual summaries'),(.63,'B2: factual summaries'),(.42,'C1: diary after 5 and 10'),(.21,'C2: diary after 5 and 10')]:
    box(ax,.56,y-.075,.4,.15,label); arrow(ax,(.32,.53),(.56,y))
ax.text(.49,.04,'Evaluate sessions 6 to 12; repeat for six histories in three seeds',ha='center',fontsize=9); save(fig,'fork')
fig,ax=plt.subplots(figsize=(7,3.3),layout='constrained'); labels=['22853 / 1','22853 / 2','23971 / 1','23971 / 2','25087 / 1','25087 / 2']; x=list(range(6))
for offset,vals,label,col in [(-.2,[-1.3571,0,0,.3286,0,-.2286],'C mean - B mean','#287c8e'),(0,[-5.9429,1.2714,-1.1286,-.6571,0,0],'B1 - B2','#64748b'),(.2,[-3.2286,1.2714,-1.1286,0,0,.4571],'C1 - C2','#b56b43')]: ax.bar([i+offset for i in x],vals,width=.19,label=label,color=col)
ax.set_xticks(x,labels,fontsize=8); ax.set_ylabel('Reference-gap difference (pp)'); ax.axhline(0,color='black',lw=.7); ax.legend(fontsize=8,loc='lower left',bbox_to_anchor=(0,1.01),ncol=3); save(fig,'reflection')
