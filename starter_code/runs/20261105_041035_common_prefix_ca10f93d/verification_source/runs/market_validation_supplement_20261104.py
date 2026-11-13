"""Read-only R039 audit, aggregate descriptions and all-seed state plots."""
from collections import defaultdict
import json
from pathlib import Path
import shutil
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sim.evaluation import dependence, read_rows
from sim.provenance import sha256, write_json
from sim.sequential_markets import verify_market
from runs import market_validation_20261104 as d

ROOT=d.BASE/"runs/20261104_154730_market_validation_fff53e3b"


def main():
    p=d.validate(ROOT);report=d.read(ROOT/"report.json")
    for name,digest in d.read(ROOT/"output_manifest.json").items():assert sha256(ROOT/name)==digest
    out=ROOT/"supplement";out.mkdir(exist_ok=False);audits=[];records=[]
    for entry in report["runs"]:
        path=ROOT/entry["run_path"];verify_market(path);assert sha256(path/"manifest.json")==entry["manifest_sha256"]
        rows=read_rows(path/"prices.csv");states=read_rows(path/"agents_state.csv");initial=read_rows(path/"initial_state.csv");previous_cash=sum(float(x["cash"]) for x in initial)
        assert previous_cash==160000 and sum(int(x["shares"]) for x in initial)==1450
        grouped=defaultdict(list)
        for state in states:
            assert float(state["cash"])>=-1e-7 and int(state["shares"])>=0
            grouped[int(state["round"])].append(state)
        error=0.;boundaries=0;maker=[]
        for row in rows:
            rnd=int(row["round"]);group=grouped[rnd];assert sum(int(x["shares"]) for x in group)==1450
            expected=previous_cash*1.0002+1450*float(row["dividend"]);cash=sum(float(x["cash"]) for x in group)
            error=max(error,abs(cash-expected));previous_cash=cash
            inventory=next(int(x["shares"]) for x in group if x["type"]=="MarketMakerAgent")
            assert 0<=inventory<=300;boundaries+=inventory in (0,300);maker.append(inventory)
        assert error<1e-7
        price,total=d.returns(rows,100)
        assert abs(dependence(price)-entry["acf_price"][0])<1e-12
        assert abs(dependence(total)-entry["acf_total"][0])<1e-12
        audits.append(dict(seed=entry["seed"],cell=entry["cell"],rounds=len(rows),account_states=len(states),max_aggregate_cash_reconstruction_error=error))
        m=entry["evaluation"]["metrics"]
        records.append(dict(seed=entry["seed"],cell=entry["cell"],price_acf1=entry["acf_price"][0],total_acf1=entry["acf_total"][0],abs_total_acf1=entry["acf_abs_total"][0],
            gap=m["mean_absolute_relative_gap"],turnover=m["turnover_per_round"],mm_share=m["volume_weighted_mm_share"],boundary_fraction=boundaries/600,
            cash_growth=m["aggregate_cash_growth"],block_gaps=[x["gap"] for x in entry["blocks"]],block_price_acf1=[x["price_acf"][0] for x in entry["blocks"]],
            prices=[float(x["price"]) for x in rows],maker_inventory=maker))
    means={}
    for cell in ("original","no_skew"):
        selected=[x for x in records if x["cell"]==cell]
        means[cell]={k:float(np.mean([x[k] for x in selected])) for k in ("price_acf1","total_acf1","abs_total_acf1","gap","turnover","mm_share","boundary_fraction","cash_growth")}
    evidence=dict(audits=audits,means=means,records=records,protocol_sha256=sha256(ROOT/"protocol.json"),report_sha256=sha256(ROOT/"report.json"),
        scope="Secondary audit and descriptions; all4 fresh seeds/all8 paths. Four original/no-skew seed pairs,not8 independent repetitions. Three blocks nest within paths; do not treat as independent samples. No additional experiment or default selection.")
    write_json(out/"audit.json",evidence);shutil.copyfile(__file__,out/"supplement_source.py")
    fig,axes=plt.subplots(4,2,figsize=(12,11),layout="constrained")
    for row,seed in enumerate(d.SEEDS):
        for a in [r for r in records if r["seed"]==seed]:
            color="C0" if a["cell"]=="original" else "C1";style="-" if a["cell"]=="original" else "--"
            axes[row,0].plot(range(601),[100]+a["prices"],color=color,ls=style,lw=1,label=a["cell"])
            axes[row,1].plot(range(601),[150]+a["maker_inventory"],color=color,ls=style,lw=.8,label=a["cell"])
        axes[row,0].axhline(100,color="black",lw=.6,ls=":")
        axes[row,1].set_ylim(-8,308)
        for ax in axes[row]:
            for boundary in (200,400):ax.axvline(boundary,color="gray",lw=.6,ls=":")
            ax.set_xlabel("Trading session");ax.grid(alpha=.2);ax.legend(fontsize=7)
        axes[row,0].set_ylabel("Closing price");axes[row,1].set_ylabel("MM shares")
        axes[row,0].set_title(f"Seed {seed}: price (private benchmark100)");axes[row,1].set_title(f"Seed {seed}: finite MM inventory0..300")
    fig.suptitle("All four fresh seed pairs: full paths and inventory; three predeclared200-session blocks")
    fig.savefig(out/"price_inventory_paths.png",dpi=160);fig.savefig(out/"price_inventory_paths.pdf");plt.close(fig)
    write_json(out/"artifact_manifest.json",{x.name:sha256(x) for x in out.iterdir() if x.is_file()})
    print(json.dumps(dict(output=str(out),means=means,financial_rounds=sum(x['rounds'] for x in audits),account_states=sum(x['account_states'] for x in audits),max_cash_error=max(x['max_aggregate_cash_reconstruction_error'] for x in audits)),indent=2))


if __name__=="__main__":main()
