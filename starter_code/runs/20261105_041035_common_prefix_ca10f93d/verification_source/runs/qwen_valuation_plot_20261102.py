"""Illustrate valuation sensitivity for all 12 pilot agent outcomes, no ranking."""
from pathlib import Path
import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent
report = json.loads((ROOT/"qwen_pilot_diagnostic_20261102.json").read_text())
labels, market, benchmark = [], [], []
for run in sorted(report["market_runs"], key=lambda r:(r["seed"],r["condition"])):
    for item in run["exploratory_valuation_diagnostic"]:
        persona = "Meera" if item["agent_id"] == "llm_012" else "Arjun"
        labels.append(f"{run['seed']} / {run['condition']} / {persona}")
        market.append(item["market_return_pct"])
        benchmark.append(item["benchmark_valued_return_pct"])

fig, ax = plt.subplots(figsize=(10,7))
for i,(a,b) in enumerate(zip(market,benchmark)):
    ax.plot([a,b],[i,i],color="#b8b8b8",lw=1.7,zorder=1)
ax.scatter(market,range(len(labels)),label="Marked at final market price",color="#2563a5",s=40,zorder=3)
ax.scatter(benchmark,range(len(labels)),label="Marked at regime benchmark (100)",color="#c65b13",marker="s",s=32,zorder=3)
ax.axvline(0,color="#666666",lw=0.8,ls="--")
ax.axhline(5.5,color="#dddddd",lw=1)
ax.set_yticks(range(len(labels)),labels)
ax.invert_yaxis()
ax.set_xlabel("Change from initial endowment (%)")
ax.set_ylabel("Scenario seed / condition / persona")
ax.grid(axis="x",alpha=.2)
ax.legend(loc="lower right",fontsize=9)
fig.suptitle("Closing valuation can change apparent performance",x=.24,y=.975,ha="left",fontsize=15)
fig.text(.24,.93,"Qwen student pilot: all 12 agent outcomes, two scenarios, four rounds each",fontsize=10,color="#555555")
fig.text(.13,.025,"Descriptive diagnostic; no performance ranking. Benchmark marking uses the model's stationary-regime\nrisk-neutral reference. Neither mark is a realized liquidation return or a human-welfare measure.",fontsize=9,color="#555555")
fig.subplots_adjust(left=.24,right=.97,top=.86,bottom=.14)
for suffix in ("png","pdf"):
    fig.savefig(ROOT/f"qwen_valuation_diagnostic_20261102.{suffix}",dpi=180)
plt.close(fig)
