"""Read-only R032 synthesis of existing R020/R030 600-session rule paths."""
import json
from pathlib import Path
import shutil
import numpy as np
import yaml
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sim.evaluation import evaluate_run,read_rows
from sim.provenance import sha256,write_json
from sim.sequential_markets import verify_market

BASE=Path(__file__).resolve().parents[1]
OLD=BASE/"runs/20261102_193747_background_screen_83ae5e22"
FRESH=BASE/"runs/20261103_183126_sequential_markets_bb927356"
OUT=BASE/"runs/realism_review_20261104"
GROUPS=("original","average5","no_skew","no_skew_average5","fresh_original")
LABELS=("Original (R020)","Average 5","No skew","No skew + average 5","Original (R030)")


def read(p):return json.loads(Path(p).read_text(encoding="utf-8"))


def acf(x):
    y=np.asarray(x,dtype=float);y=y-y.mean();den=float(y@y)
    return [None if den==0 else float(y[:-k]@y[k:]/den) for k in range(1,11)]


def main():
    OUT.mkdir(exist_ok=False);records=[]
    sources=[(OLD,e,e["cell"]) for e in read(OLD/"report.json")["runs"]]
    sources += [(FRESH,e,"fresh_original") for e in read(FRESH/"baseline_runs.json") if e["cell"]=="long_quiet"]
    for parent,e,group in sources:
        root=parent/e["run_path"];m=verify_market(root)
        assert sha256(root/"manifest.json")==e["manifest_sha256"]
        ev=evaluate_run(root);metrics=ev["metrics"]
        assert metrics["rounds"]==600 and m["usage"]["requests_made"]==0
        cfg=yaml.safe_load((root/"config.yaml").read_text());prices=read_rows(root/"prices.csv")
        assert not cfg["news"]
        returns=np.diff(np.log([cfg["asset"]["initial_price"]]+[float(r["price"]) for r in prices]))
        states=read_rows(root/"agents_state.csv");mm=[int(r["shares"]) for r in states if r["type"]=="MarketMakerAgent"]
        extra=dict(acf_returns_lags1_10=acf(returns),acf_absolute_returns_lags1_10=acf(abs(returns)),
            mm_boundary_fraction=sum(s in (0,300) for s in mm)/len(mm))
        assert np.isclose(extra["acf_returns_lags1_10"][0],metrics["acf_returns_lag1"])
        records.append(dict(group=group,seed=e["seed"],run_path=root.relative_to(BASE).as_posix(),manifest_sha256=e["manifest_sha256"],
            config_sha256=sha256(root/"config.yaml"),source_archive_sha256=m["source_archive_sha256"],
            parent_revision=m["parent_revision"],working_tree_status=m["working_tree_status"],
            prompt_suite=m["prompt_suite_version"],model=None,repetitions=1,randomness="Saved simulator seed; zero API, no new simulations or repetitions.",metrics={**metrics,**extra}))
    numeric=list(records[0]["metrics"])
    means={g:{k:(np.mean([r["metrics"][k] for r in records if r["group"]==g],axis=0).tolist()) for k in numeric} for g in GROUPS}
    factors=[]
    for seed in (317,628,939):
        by={r["group"]:r["metrics"] for r in records if r["seed"]==seed}
        for a,b in (("original","average5"),("no_skew","no_skew_average5")):
            factors.append(dict(seed=seed,before=a,after=b,delta={k:by[b][k]-by[a][k] for k in ("mean_absolute_relative_gap","acf_returns_lag1","acf_absolute_returns_lag1","turnover_per_round","volume_weighted_mm_share")}))
    report=dict(version="reference_environment_review_v1",status="completed_saved_evidence_synthesis",analysis_kind="Exploratory secondary analysis; no new independent runs, significance tests or calibrated thresholds.",
        method="600 regular-session log returns per saved quiet path, including initial-price-to-first-auction change; zero returns retained. ACF uses full-series mean and sum-of-squares denominator for every lag. Group means of3 different seeds; R020/R030 cohorts separate. MM boundary is post-auction inventory equal0 or300; MM participation counts union trades. No equity risk-adjusted alpha or causal real-market/human claim.",
        references=[dict(title="The role of the end time in experimental asset markets",authors="Kopanyi-Peuker & Weber",year=2024,doi="10.1016/j.jcorpfin.2024.102647",url="https://alexandria.unisg.ch/entities/publication/db4aabe2-939b-4008-b6d1-04cb0f16381e",access="Primary repository abstract/metadata only; full methods not retrieved. Design motivation, not numerical replication."),
            dict(title="Revisiting Cont's Stylized Facts for Modern Stock Markets",authors="Ratliff-Crain et al.",version="arXiv2311.07738v2,20May2024",url="https://arxiv.org/html/2311.07738v2",access="Full primary HTML reviewed. Diagnostic framework; no dataset acquired/calibration. Intraday clock/event time differs from our session batch market.")],
        source_indexes={str(p.relative_to(BASE)):sha256(p) for p in (OLD/"report.json",FRESH/"baseline_runs.json")},
        records=records,group_means=means,paired_averaging_contrasts=factors,
        limitations="Only3 seeds per setting/cohort; six averaging pairs share3 seeds and are not6 independent repetitions. Rule-only quiet markets, not LLM stylized-fact evidence.600 sessions cannot validate long memory/tail exponents. Cash grows with dividends/interest and holdings change: stationarity not established. No default changed; isolated low benchmark gap is not human/real-market realism.")
    write_json(OUT/"report.json",report);shutil.copyfile(__file__,OUT/"analysis_source.py")
    fig,axes=plt.subplots(2,2,figsize=(11,8),layout="constrained")
    for n,(group,label) in enumerate(zip(GROUPS,LABELS)):
        m=means[group];color=f"C{n}"
        for ax,key in ((axes[0,0],"acf_returns_lags1_10"),(axes[0,1],"acf_absolute_returns_lags1_10")):
            ax.plot(range(1,11),m[key],marker=".",label=label,color=color)
        axes[1,0].scatter(100*m["mean_absolute_relative_gap"],m["acf_returns_lag1"],label=label,color=color,s=65)
        axes[1,1].scatter(100*m["volume_weighted_mm_share"],100*m["turnover_per_round"],label=label,color=color,s=65)
    for ax in axes.flat:ax.grid(alpha=.2)
    for ax in axes[0]:ax.axhline(0,color="black",lw=.5);ax.set_xlabel("Lag (auction sessions)");ax.set_ylabel("Mean ACF across 3 seeds")
    axes[0,0].set_title("Price-change dependence");axes[0,1].set_title("Magnitude dependence")
    axes[1,0].set(xlabel="Mean absolute regime-benchmark gap (%)",ylabel="Return ACF, lag 1",title="Closer valuation can retain dependence")
    axes[1,1].set(xlabel="Market-maker union volume (%)",ylabel="Turnover per session (%)",title="Liquidity and participation trade-offs")
    axes[0,0].legend(fontsize=8);fig.suptitle("Existing quiet rule markets: descriptive environment checkpoint")
    fig.savefig(OUT/"background_diagnostics.png",dpi=180);fig.savefig(OUT/"background_diagnostics.pdf");plt.close(fig)
    lines=["# Reference and environment checkpoint (R032)","", "Completed secondary analysis of 15 EXISTING 600-session rule paths. No new simulation/API call, changed default or empirical dataset. All original outputs/manifests verified; the12 R020 paths and3 fresh R030 paths remain separate cohorts.","",
        "## What the thesis can currently ask","", "1. Under specified laboratory-market rules, how do agent information/persona/policy affect intended orders, actual execution, exposure and market outcomes?\n2. What do factual summaries/reflection explain, and what are their costs/limits, relative to the corrected simple condition?","",
        "These are controlled within-model questions. Passing accounting checks, low regime gaps or higher returns does not demonstrate human behaviour or external market realism.","",
        "## Reference map","", "[Kopanyi-Peuker & Weber (2024)](https://alexandria.unisg.ch/entities/publication/db4aabe2-939b-4008-b6d1-04cb0f16381e) varies market end-time assumptions and reports similar price dynamics. Only the primary published abstract/metadata was accessible here; no full-method replication is claimed. Our disclosure-only pilot differs from indefinite stochastic stopping and should not be expected to reproduce a selected human result.","",
        "[Ratliff-Crain et al. (arXiv v2,2024)](https://arxiv.org/html/2311.07738v2) examines Dow30 intraday data and finds support for8 of11 stylized facts, emphasizing asset/time construction. Use return/magnitude dependence as diagnostics, not a universal11-item checklist or numerical threshold for this tiny session-auction model. Full HTML reviewed; underlying dataset not obtained.","",
        "## Saved background evidence","", "|Setting (three seeds each)|Gap %|Return ACF1|Abs-return ACF1|Turnover %/session|MM volume %|MM boundary %|Cash growth %|", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for g,label in zip(GROUPS,LABELS):
        m=means[g];lines.append(f"|{label}|{100*m['mean_absolute_relative_gap']:.2f}|{m['acf_returns_lag1']:.3f}|{m['acf_absolute_returns_lag1']:.3f}|{100*m['turnover_per_round']:.3f}|{100*m['volume_weighted_mm_share']:.2f}|{100*m['mm_boundary_fraction']:.2f}|{100*m['aggregate_cash_growth']:.2f}|")
    lines += ["", "![Saved background diagnostics](background_diagnostics.png)","", "Five-payout averaging increases first-lag return dependence and reduces turnover in all six matched comparisons (two skew settings x3 shared seeds). Those six pairs are not six independent seeds. Removing skew changes gaps/activity without supplying an external realism target. A lower valuation gap alone cannot select the preferred environment.","",
        "Read all lag1-10 curves in report.json/figure; a single lag or short curve cannot validate or disprove long memory. Retain original skew.02/window1. This system accumulates cash from dividends/interest and redistributes holdings, so stationarity has not been established. Quiet rule paths do not establish that LLMs generate stylized facts;24-round live paths are especially inadequate for that claim.","",
        "## Next useful decisions","", "Keep the current environment as a declared laboratory and use the one bounded recording-length pilot alongside it. For the eventual leading behavioural/news result, choose at most ONE reasonable background sensitivity (e.g. inventory-skew removal) rather than selecting the lowest-gap setting. Preserve actual opportunity/intention/acceptance/fill, counterpart wealth and both passive marks. A news claim needs controlled message availability separately from economic change, or must be called a bundled-shock study. Downside opportunity and no-signal controls remain core work; A/B/C need not multiply each new question.","",
        "No human validation, universal component benefit, calibrated liquidity, inferential horizon effect, volatility-tail exponent or risk-adjusted model superiority follows. Reused data are evidence synthesis, not new confirmation."]
    (OUT/"READOUT.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    write_json(OUT/"artifact_manifest.json",{p.name:sha256(p) for p in OUT.iterdir() if p.is_file()})
    print(json.dumps(dict(output=str(OUT),means=means),indent=2))


if __name__=="__main__":main()
