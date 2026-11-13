"""Audit/plot the complete predeclared screen; supplementary inventory counts."""
import json
from pathlib import Path
import shutil
import zipfile

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from sim.background_check import CELLS, SEEDS
from sim.behaviour_check import cases
from sim.evaluation import evaluate_run, read_rows
from sim.provenance import sha256, write_json

ROOT=Path(__file__).resolve().parents[1]
TARGET=ROOT/"runs/20261102_193747_background_screen_83ae5e22"
BEHAVIOUR=ROOT/"runs/20261102_193749_behaviour_inputs_5e633670"
report=json.loads((TARGET/"report.json").read_text())
assert len(report["runs"])==12
source_hashes=[]
cash_errors=[]
boundary=[]
max_excess_error=0
for entry in report["runs"]:
    market=TARGET/entry["run_path"]
    manifest=json.loads((market/"manifest.json").read_text())
    assert sha256(market/"manifest.json")==entry["manifest_sha256"]
    assert manifest["models"]==[] and manifest["status"]=="completed"
    assert sha256(market/"source.zip")==manifest["source_archive_sha256"]
    for name,digest in manifest["output_sha256"].items():assert sha256(market/name)==digest
    for name,digest in manifest["source_sha256"].items():assert sha256(ROOT/name)==digest
    source_hashes.append(manifest["source_sha256"])
    summary=json.loads((market/"summary.json").read_text())
    cash_errors.append(summary["max_cash_conservation_error"])
    evaluation=json.loads((TARGET/entry["evaluation"]).read_text())
    assert sha256(TARGET/entry["evaluation"])==entry["evaluation_sha256"]
    assert evaluate_run(market)==evaluation
    max_excess_error=max(max_excess_error,*map(abs,evaluation["aggregate_active_minus_passive"].values()))
    mm=[int(r["shares"]) for r in read_rows(market/"agents_state.csv") if r["type"]=="MarketMakerAgent"]
    boundary.append(dict(seed=entry["seed"],cell=entry["cell"],
                         fraction_at_0_or_300=sum(x in (0,300) for x in mm)/len(mm)))
assert all(x==source_hashes[0] for x in source_hashes)
battery=json.loads((BEHAVIOUR/"battery.json").read_text())
assert battery["status"]=="prepared_not_run" and battery["cases"]==cases()
assert len(battery["schedule"])==48 and len({(r["case_id"],r["repetition"]) for r in battery["schedule"]})==48
assert sha256(BEHAVIOUR/"source.zip")==battery["source_archive_sha256"]
with zipfile.ZipFile(BEHAVIOUR/"source.zip") as archive:
    for name in archive.namelist():assert archive.read(name)==(ROOT/name).read_bytes()

metrics=(("mean_absolute_relative_gap",100,"Mean absolute price/benchmark gap (%)"),
         ("acf_returns_lag1",1,"Lag-one return autocorrelation"),
         ("turnover_per_round",100,"Turnover per round (% of shares)"),
         ("volume_weighted_mm_share",100,"Market-maker share of volume (%)"))
fig,axes=plt.subplots(2,2,figsize=(11,7),constrained_layout=True)
labels=["Original\nskew .02, window 1","Average 5\nskew .02","No skew\nwindow 1","No skew\naverage 5"]
colors=["#37669a","#659fba","#be6b32","#cfaa5a"]
aggregate=[]
for ax,(metric,scale,label) in zip(axes.flat,metrics):
    for i,cell in enumerate(CELLS):
        values=np.array([r[metric]*scale for r in report["results"] if r["cell"]==cell])
        ax.bar(i,float(values.mean()),color=colors[i],alpha=.75,width=.65)
        ax.scatter(i+np.array([-.12,0,.12]),values,color="black",s=18,zorder=3)
        aggregate.append(dict(cell=cell,metric=metric,mean_native_units=float(values.mean()/scale),
                              sample_sd_native_units=float(values.std(ddof=1)/scale)))
    ax.set_xticks(range(4),labels,fontsize=8)
    ax.set_title(label,fontsize=11)
    ax.grid(axis="y",alpha=.18)
fig.suptitle("Background sensitivity: all four settings, three matched seeds\n"
             "14 rule traders, hidden benchmark, 600 no-news rounds; bars = means, dots = individual seeds",
             fontsize=12)
fig.savefig(TARGET/"background_tradeoffs.png",dpi=180)
fig.savefig(TARGET/"background_tradeoffs.pdf")
plt.close(fig)
for source in ROOT.glob("tests/test_*.py"):
    # Snapshot all tests alongside the archived simulator code, excluding temp outputs.
    folder=TARGET/"tests_snapshot"
    folder.mkdir(exist_ok=True)
    shutil.copyfile(source,folder/source.name)
regression=json.loads((ROOT/"runs/background_baseline_regression_20261102.json").read_text())
write_json(TARGET/"analysis.json",dict(status="verified_exploratory",aggregates=aggregate,
    supplementary_mm_boundary_counts=boundary,inventory_count_note="Supplementary post-screen diagnostic, not a predeclared optimization target.",
    max_cash_error=max(cash_errors),max_aggregate_passive_excess_residual=max_excess_error,
    source_parent=manifest["parent_revision"],working_tree_status=manifest["working_tree_status"],
    source_sha256=source_hashes[0],baseline_regression=regression,
    behaviour_battery=str(BEHAVIOUR.relative_to(ROOT)),behaviour_battery_sha256=sha256(BEHAVIOUR/"battery.json"),
    analysis_source_sha256=sha256(Path(__file__)),
    decision="Keep defaults. Five-payout averaging is a sensitivity option, not a validated realism improvement. No live behavioural generation or empirical comparison here."))
hashes={p.relative_to(TARGET).as_posix():sha256(p) for p in TARGET.rglob("*") if p.is_file() and p.name!="artifact_hashes.json"}
write_json(TARGET/"artifact_hashes.json",hashes)
print(json.dumps(dict(root=str(TARGET),max_cash_error=max(cash_errors),
                     aggregate_passive_residual=max_excess_error,aggregates=aggregate,
                     supplementary_mm_boundary_counts=boundary),indent=2))
