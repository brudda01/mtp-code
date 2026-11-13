"""Analyze every frozen news arm; distinguish market paths from same-state queries."""
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from sim.news_controls import CELLS, FINANCIAL_FILES
from sim.news_pilot import EVENT_ROUND, ROUNDS, SEEDS, load_study, market_metrics, probe_agent
from sim.agents.base import Observation
from sim.evaluation import read_rows
from sim.provenance import sha256,write_json

ROOT=Path(__file__).resolve().parents[1]
STUDY=ROOT/"runs/20261102_202946_news_pilot_786a0370"
OUTPUT=ROOT/"runs/news_recovery_analysis_20261102"


def verify_manifest(path):
    m=json.loads((path/"manifest.json").read_text())
    assert sha256(path/"source.zip")==m["source_archive_sha256"]
    for name,digest in m["output_sha256"].items():assert sha256(path/name)==digest,(path,name)
    with zipfile.ZipFile(path/"source.zip") as archive:
        for name,digest in m["source_sha256"].items():
            assert hashlib.sha256(archive.read(name)).hexdigest()==digest,(path,name)
    return m


def analyze():
    protocol=json.loads((STUDY/"study.json").read_text())
    assert sha256(STUDY/"study.json")=="0a901d2fc24f41d5c7a2207c741f46a34df14e60d1ad0b61733eb621c72d7355"
    summary=json.loads((STUDY/"summary.json").read_text())
    index=json.loads((STUDY/"runs.json").read_text())
    parent_summary=summary
    continuation=STUDY/"continuation_1"
    if (continuation/"summary.json").exists():
        summary=json.loads((continuation/"summary.json").read_text())
        index+=json.loads((continuation/"runs.json").read_text())
    recovery=STUDY/"recovery_transport_v3"
    recovery_plan=json.loads((recovery/"plan.json").read_text())
    if (recovery/"summary.json").exists():
        summary=json.loads((recovery/"summary.json").read_text())
        index+=json.loads((recovery/"runs.json").read_text())
    OUTPUT.mkdir(exist_ok=True)
    shutil.copyfile(Path(__file__),OUTPUT/"analysis_source.py")
    arms=[];paths={};partial_paths=[];partial_event_evidence=[];all_usage=[];source_maps=[];cash_errors=[]
    for entry in index:
        p=STUDY/entry["run_path"];manifest=verify_manifest(p)
        assert sha256(p/"manifest.json")==entry["manifest_sha256"]
        run_summary=json.loads((p/"summary.json").read_text())
        all_usage.append(run_summary["llm_usage"]);source_maps.append(manifest["source_sha256"])
        if run_summary["status"]!="completed" or run_summary["parse_failures"]:
            if read_rows(p/"prices.csv"):partial_paths.append({**entry,"path":p})
            if run_summary["rounds"]>=EVENT_ROUND:
                partial=market_metrics(p)
                partial_event_evidence.append(dict(run_path=entry["run_path"],cell=entry["cell"],seed=entry["seed"],
                    observed_rounds=run_summary["rounds"],observed_post_event_rounds=run_summary["rounds"]-EVENT_ROUND+1,
                    event_decisions=partial["event_decisions"],event_metrics=partial["event_metrics"],
                    scope="Partial horizon only; excluded from complete-arm comparisons and end-of-episode performance. Never joined to an earlier partial."))
            continue
        cash_errors.append(run_summary["max_cash_conservation_error"])
        metrics=market_metrics(p)
        metric_root=recovery if entry["run_path"].startswith("recovery_transport_v3/") else STUDY
        saved=metric_root/f"metrics_{entry['brain']}_{entry['cell']}_{entry['seed']}.json"
        assert json.loads(saved.read_text())==metrics
        paths[entry["brain"],entry["seed"],entry["cell"]]=p
        accounts=metrics["evaluation"]["accounts"]
        targets=[a for a in accounts if int(a["agent_id"].rsplit("_",1)[1]) in (12,13)]
        arms.append(dict(brain=entry["brain"],seed=entry["seed"],cell=entry["cell"],
            run_path=entry["run_path"],event_metrics=metrics["event_metrics"],
            overall_metrics=metrics["evaluation"]["metrics"],event_decisions=metrics["event_decisions"],
            target_passive_comparisons=targets))
    source_sets={hashlib.sha256(json.dumps(m,sort_keys=True).encode()).hexdigest():m for m in source_maps}
    assert len(source_sets)<=2
    checks=[]
    for seed in SEEDS:
        available={(brain,cell):path for (brain,s,c),path in paths.items() if s==seed for cell in (c,)}
        if ("rules","control") not in available:continue
        base=read_rows(available["rules","control"]/"prices.csv")
        reference=[(r["cash"],r["shares"],r["wealth"]) for r in read_rows(available["rules","control"]/"initial_state.csv")]
        for (brain,cell),path in available.items():
            price=read_rows(path/"prices.csv")
            shift,announce=CELLS[cell]
            for a,b in zip(base,price):
                factor=1.2 if shift and int(b["round"])>=EVENT_ROUND else 1
                assert np.isclose(float(b["dividend"]),factor*float(a["dividend"]),rtol=1e-13,atol=1e-15)
            initial=read_rows(path/"initial_state.csv")
            resources=[(r["cash"],r["shares"],r["wealth"]) for r in initial]
            assert resources==reference
        for a,b in (("control","headline_only"),("fundamentals_only","combined")):
            for name in FINANCIAL_FILES:
                assert (available["rules",a]/name).read_bytes()==(available["rules",b]/name).read_bytes()
        checks.append(dict(seed=seed,verified_complete_arms=len(available),equal_slot_resources=True,matched_dividend_innovations=True,
                           rule_headline_pairs_exact=True))
    by={(r["brain"],r["seed"],r["cell"]):r for r in arms}
    exploratory=[]
    for brain in ("rules","qwen"):
        for seed in SEEDS:
            for a,b in (("control","headline_only"),("fundamentals_only","combined")):
                if not all((brain,seed,c) in by for c in (a,b)):continue
                x,y=(by[brain,seed,c]["event_metrics"] for c in (a,b))
                exploratory.append(dict(brain=brain,seed=seed,silent_cell=a,announced_cell=b,
                    pre_event_close_difference=y["pre_event_price"]-x["pre_event_price"],
                    pre_mean_price_difference=y["pre_mean_price"]-x["pre_mean_price"],
                    event_price_difference=y["event_price"]-x["event_price"],
                    post_mean_price_difference=y["post_mean_price"]-x["post_mean_price"],
                    post_gap_difference=y["post_mean_absolute_relative_gap"]-x["post_mean_absolute_relative_gap"],
                    interpretation="Matched exogenous runs; stochastic pre-event state differences retained. Not a clean causal headline effect."))
    brain_contrasts=[]
    for seed in SEEDS:
        for cell in CELLS:
            if not all((brain,seed,cell) in by for brain in ("rules","qwen")):continue
            rule,qwen=(by[brain,seed,cell] for brain in ("rules","qwen"))
            brain_contrasts.append(dict(seed=seed,cell=cell,
                post_gap_delta=qwen["event_metrics"]["post_mean_absolute_relative_gap"]-rule["event_metrics"]["post_mean_absolute_relative_gap"],
                turnover_delta=qwen["overall_metrics"]["turnover_per_round"]-rule["overall_metrics"]["turnover_per_round"],
                scope="Two specified rule slots replaced by two specified bundled LLM personas; not intrinsic brain superiority."))
    probes=[];probe_summary=None
    probe_path=recovery/"same_state_probes"
    if (probe_path/"summary.json").exists():
        probe_manifest=verify_manifest(probe_path)
        probe_summary=json.loads((probe_path/"summary.json").read_text())
        all_usage.append(probe_summary["llm_usage"])
        battery=json.loads((probe_path/"battery.json").read_text())
        assert sha256(probe_path/"battery.json")==probe_manifest["battery_sha256"]
        definitions={c["case_id"]:c for c in battery["cases"]}
        results=json.loads((probe_path/"results.json").read_text())
        calls=[json.loads(s) for s in (probe_path/"llm_requests.jsonl").read_text().splitlines() if json.loads(s)["record_type"]=="model_call"]
        for call in calls:
            if call.get("json_attempt",1)==1:
                assert call["messages"]==definitions[call["case_id"]]["messages"]
        rows={(r["case_id"],r["repetition"]):r for r in results}
        for seed in SEEDS:
            for aid in ("llm_012","llm_013"):
                for n in (1,2,3):
                    silent,announced=(rows.get((f"s{seed}_{aid}_{variant}",n)) for variant in ("silent","announced"))
                    delta=None if silent is None or announced is None or not (silent["valid_choice"] and announced["valid_choice"]) else announced["accepted_signed_quantity"]-silent["accepted_signed_quantity"]
                    probes.append(dict(seed=seed,agent_id=aid,repetition=n,
                        silent_requested=None if silent is None else silent["requested_signed_quantity"],
                        announced_requested=None if announced is None else announced["requested_signed_quantity"],
                        announced_minus_silent_accepted=delta))
    usage={key:sum(u[key] for u in all_usage) for key in
           ("requests_made","reserved_tokens","provider_reported_tokens","unknown_usage_requests","failed_requests","blocked_requests")}
    completed_keys={(r["brain"],r["seed"],r["cell"]) for r in arms}
    write_json(OUTPUT/"report.json",dict(version=protocol["version"],study_status=summary,parent_phase_status=parent_summary,
        arms=arms,all_recorded_market_statuses=index,
        unfinished_arms=[r for r in protocol["schedule"] if (r["brain"],r["seed"],r["cell"]) not in completed_keys],
        partial_price_paths=[{k:v for k,v in r.items() if k!="path"} for r in partial_paths],
        partial_event_evidence=partial_event_evidence,
        checks=checks,exploratory_announcement_run_contrasts=exploratory,
        specified_slot_brain_contrasts=brain_contrasts,same_state_probe_contrasts=probes,
        probe_summary=probe_summary,usage=usage,max_cash_error=max(cash_errors,default=None),
        study_sha256=sha256(STUDY/"study.json"),source_sets=source_sets,
        recovery_plan_sha256=sha256(recovery/"plan.json"),source_checks=recovery_plan["source_checks"],
        delivery_note="Two source/delivery profiles: earlier zero-retry phases and linked opt-in retry phase. Prompt/policy/economics checked unchanged, but this is not an uninterrupted study or a causal before/after delivery comparison.",
        analysis_source_sha256=sha256(Path(__file__)),
        interpretation=protocol["limitations"]))
    fig,axes=plt.subplots(2,2,figsize=(11,7),sharex=True,constrained_layout=True)
    for i,seed in enumerate(SEEDS):
        for j,(silent,announced) in enumerate((("control","headline_only"),("fundamentals_only","combined"))):
            ax=axes[i,j]
            for brain,style in (("qwen","-"),("rules","--")):
                for cell,color in ((silent,"#2d659b"),(announced,"#bd681f")):
                    if (brain,seed,cell) not in paths:continue
                    data=read_rows(paths[brain,seed,cell]/"prices.csv")
                    ax.plot([int(r["round"]) for r in data],[float(r["price"]) for r in data],style,
                            color=color,label=f"{brain}: {'headline' if cell==announced else 'silent'}",linewidth=1.4)
            for entry in partial_paths:
                if entry["seed"]!=seed or entry["cell"] not in (silent,announced):continue
                data=read_rows(entry["path"]/"prices.csv")
                ax.plot([int(r["round"]) for r in data],[float(r["price"]) for r in data],":",
                        color="#bd681f" if entry["cell"]==announced else "#2d659b",alpha=.6)
                ax.annotate(f"partial {data[-1]['round']}/20",(int(data[-1]["round"]),float(data[-1]["price"])),fontsize=8)
            ax.axvline(EVENT_ROUND,color="gray",linestyle=":",alpha=.7)
            ax.set_title(f"Seed {seed}: {'actual +20% mean shift' if j else 'no mean shift'}",fontsize=10)
            ax.set_ylabel("Auction price");ax.grid(alpha=.15)
            if not any(("qwen",seed,c) in paths for c in (silent,announced)):
                ax.text(.5,.9,"Live arms incomplete/unstarted for this seed",transform=ax.transAxes,
                        ha="center",fontsize=8)
    axes[0,0].legend(fontsize=8,ncols=2)
    for ax in axes[-1]:ax.set_xlabel("Round (event at 11)")
    complete_live=sum(a["brain"]=="qwen" for a in arms)
    fig.suptitle(f"News feasibility pilot: {complete_live}/8 live arms complete; earlier partial paths labelled\n"
                 "Linked delivery phases; rule headline/silent paths coincide; live pre-event states differ.",fontsize=12)
    fig.savefig(OUTPUT/"market_paths.png",dpi=180);fig.savefig(OUTPUT/"market_paths.pdf");plt.close(fig)
    if probes:
        fig,ax=plt.subplots(figsize=(8,4),constrained_layout=True)
        for i,(seed,aid) in enumerate((s,a) for s in SEEDS for a in ("llm_012","llm_013")):
            vals=[r["announced_minus_silent_accepted"] for r in probes if r["seed"]==seed and r["agent_id"]==aid and r["announced_minus_silent_accepted"] is not None]
            if vals:
                ax.scatter(i+np.linspace(-.1,.1,len(vals)),vals,color="#2d659b",s=35)
                ax.scatter(i,float(np.mean(vals)),marker="D",color="#bd681f",s=40)
        ax.axhline(0,color="gray",linestyle="--")
        ax.set_xticks(range(4),[f"{s}\n{'Meera' if a=='llm_012' else 'Arjun'}" for s in SEEDS for a in ("llm_012","llm_013")])
        ax.set_ylabel("Announced minus silent: signed accepted shares")
        ax.set_title("Same stored event state, three fresh replies per condition\nNo orders execute; diamond = mean, dots = repetitions",fontsize=11)
        fig.savefig(OUTPUT/"same_state_news.png",dpi=180);fig.savefig(OUTPUT/"same_state_news.pdf");plt.close(fig)
    shutil.copyfile(ROOT/"tests/test_news_pilot.py",OUTPUT/"test_news_pilot.py")
    shutil.copyfile(ROOT/"tests/test_transport_retry.py",OUTPUT/"test_transport_retry.py")
    write_json(OUTPUT/"artifact_hashes.json",{p.name:sha256(p) for p in OUTPUT.iterdir() if p.is_file() and p.name!="artifact_hashes.json"})
    print(json.dumps(dict(status=summary,usage=usage,same_state=probes,
        markets=[dict(brain=a["brain"],seed=a["seed"],cell=a["cell"],**a["event_metrics"]) for a in arms]),indent=2))


if __name__=="__main__":analyze()
