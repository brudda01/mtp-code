"""Analyze every frozen news arm; distinguish market paths from same-state queries."""
import hashlib
import json
import math
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
from sim.config import load_config
from sim.market import CallAuctionMarket
from sim.provenance import sha256,write_json

ROOT=Path(__file__).resolve().parents[1]
STUDY=ROOT/"runs/20261102_202946_news_pilot_786a0370"
OUTPUT=ROOT/"runs/news_query_first_analysis_20261102"


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
    query_phase=STUDY/"delivery_v4_query_first"
    query_plan=json.loads((query_phase/"plan.json").read_text())
    if (query_phase/"runs.json").exists():index+=json.loads((query_phase/"runs.json").read_text())
    if (query_phase/"summary.json").exists():summary=json.loads((query_phase/"summary.json").read_text())
    else:summary={"status":"in_progress","progress":json.loads((query_phase/"progress.json").read_text())}
    OUTPUT.mkdir(exist_ok=True)
    shutil.copyfile(Path(__file__),OUTPUT/"analysis_source.py")
    arms=[];paths={};partial_paths=[];partial_event_evidence=[];all_usage=[];source_maps=[];cash_errors=[];headline_visibility=[]
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
        metric_root=(query_phase if entry["run_path"].startswith("delivery_v4_query_first/") else
                     recovery if entry["run_path"].startswith("recovery_transport_v3/") else STUDY)
        saved=metric_root/f"metrics_{entry['brain']}_{entry['cell']}_{entry['seed']}.json"
        assert json.loads(saved.read_text())==metrics
        paths[entry["brain"],entry["seed"],entry["cell"]]=p
        if entry["brain"]=="qwen" and CELLS[entry["cell"]][1]:
            model_calls=[json.loads(s) for s in (p/"llm_requests.jsonl").read_text().splitlines() if json.loads(s)["record_type"]=="model_call"]
            for aid in ("llm_012","llm_013"):
                headline_visibility.append(dict(seed=entry["seed"],cell=entry["cell"],agent_id=aid,
                    literal_original_headline_in_user_input_rounds=sorted({r["round"] for r in model_calls if r["agent_id"]==aid and protocol["market_design"]["headline"] in r["messages"][1]["content"]}),
                    scope="Literal structured-news visibility only. Prior order reasoning can carry beliefs beyond the raw outcome-memory window; absence of this exact sentence does not establish semantic forgetting or a reflection benefit."))
        accounts=metrics["evaluation"]["accounts"]
        targets=[a for a in accounts if int(a["agent_id"].rsplit("_",1)[1]) in (12,13)]
        trading=[]
        for aid in sorted({r["agent_id"] for r in metrics["target_rounds"]}):
            for period in ("pre_event", "post_event"):
                rows=[r for r in metrics["target_rounds"] if r["agent_id"]==aid and
                      (r["round"]<EVENT_ROUND)==(period=="pre_event")]
                trading.append(dict(agent_id=aid,period=period,rounds=len(rows),
                    active_accepted_rounds=sum(r["accepted_quantity"]>0 for r in rows),
                    gross_requested_shares=None if entry["brain"]=="rules" else sum(abs(r["requested_signed"]) for r in rows if r["requested_signed"] is not None),
                    gross_accepted_shares=sum(r["accepted_quantity"] for r in rows),
                    gross_executed_shares=sum(r["executed_buy"]+r["executed_sell"] for r in rows),
                    net_executed_shares=sum(r["executed_signed"] for r in rows)))
        arms.append(dict(brain=entry["brain"],seed=entry["seed"],cell=entry["cell"],
            run_path=entry["run_path"],event_metrics=metrics["event_metrics"],
            overall_metrics=metrics["evaluation"]["metrics"],event_decisions=metrics["event_decisions"],
            target_passive_comparisons=targets,target_trading_by_period=trading))
    source_sets={hashlib.sha256(json.dumps(m,sort_keys=True).encode()).hexdigest():m for m in source_maps}
    assert len(source_sets)<=3
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
    probes=[];probe_summaries=[];probe_frames=[]
    probe_rows={}
    for seed_subset in SEEDS:
        probe_path=query_phase/f"probes_seed_{seed_subset}"/"same_state_probes"
        if not (probe_path/"summary.json").exists():continue
        probe_manifest=verify_manifest(probe_path)
        probe_summary=json.loads((probe_path/"summary.json").read_text())
        probe_summaries.append(dict(source_scenario_seed=seed_subset,probe_stub_config_seed=probe_manifest["seed"],
            seed_note="Source-frame seed is stored in battery.json. The no-execution probe stub uses config seed1441 for both subsets; no economic or fill RNG is drawn by these queries. Provider sampling is unseeded.",**probe_summary))
        all_usage.append(probe_summary["llm_usage"])
        battery=json.loads((probe_path/"battery.json").read_text())
        assert sha256(probe_path/"battery.json")==probe_manifest["battery_sha256"]
        definitions={c["case_id"]:c for c in battery["cases"]}
        cfg=load_config(probe_path/"config.yaml")
        market=CallAuctionMarket(cfg.market.tick,cfg.market.price_band,cfg.market.transaction_tax)
        for case in battery["cases"]:
            if case["announce"]:continue
            source_run=Path(case["source_run"])
            assert sha256(source_run/"manifest.json")==case["source_manifest_sha256"]
            source_call=next(r for r in map(json.loads,(source_run/"llm_requests.jsonl").read_text().splitlines())
                             if r["record_type"]=="model_call" and r["call_id"]==case["source_call_id"])
            assert source_call["messages"]==case["messages"]
            announced=next(c for c in battery["cases"] if c["agent_id"]==case["agent_id"] and c["announce"])
            assert {k:v for k,v in announced["observation"].items() if k!="news"}=={k:v for k,v in case["observation"].items() if k!="news"}
            assert announced["memory"]==case["memory"] and announced["persona"]==case["persona"]
            assert announced["messages"][0]==case["messages"][0]
            obs=case["observation"];price=obs["price_history"][-1]
            cash,shares=obs["my_cash"],obs["my_shares"]
            lo,hi=market.price_bounds(price);tax=cfg.market.transaction_tax
            probe_frames.append(dict(seed=seed_subset,agent_id=case["agent_id"],persona_name=case["persona"]["name"],
                cash=cash,shares=shares,price=price,stock_weight=shares*price/obs["my_wealth"],
                executable_price_bounds=[lo,hi],
                market_buy_reservation_capacity=math.floor(cash/(price*(1+cfg.market.price_band)*(1+tax))+1e-12),
                upper_bound_buy_capacity_at_lowest_execution_price=math.floor(cash/(lo*(1+tax))+1e-12),
                sell_capacity=shares,
                scope="Derived from stored actual account and common exchange rules. The lower-price capacity is an upper bound, not a guaranteed fill. Within-frame headline contrasts keep this state fixed; cross-frame/persona differences do not isolate a trait."))
        results=json.loads((probe_path/"results.json").read_text())
        calls=[json.loads(s) for s in (probe_path/"llm_requests.jsonl").read_text().splitlines() if json.loads(s)["record_type"]=="model_call"]
        for call in calls:
            if call.get("json_attempt",1)==1:
                assert call["messages"]==definitions[call["case_id"]]["messages"]
        probe_rows.update({(r["case_id"],r["repetition"]):r for r in results})
    for seed in SEEDS:
        for aid in ("llm_012","llm_013"):
            for n in (1,2,3):
                silent,announced=(probe_rows.get((f"s{seed}_{aid}_{variant}",n)) for variant in ("silent","announced"))
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
        headline_visibility_audit=headline_visibility,
        probe_summaries=probe_summaries,probe_frame_constraints=probe_frames,
        completed_matched_probe_pairs=sum(r["announced_minus_silent_accepted"] is not None for r in probes),
        usage_scope="Finalized market arms and finalized probe subsets only; excludes any active unfinalized arm during in-progress reporting.",
        usage=usage,max_cash_error=max(cash_errors,default=None),
        study_sha256=sha256(STUDY/"study.json"),source_sets=source_sets,
        recovery_plan_sha256=sha256(query_phase/"plan.json"),source_checks=query_plan["source_checks"],
        delivery_note="Three source/delivery profiles: zero-retry, transport-only and optional-503/query-first. Prompt/policy/economics checked unchanged. Linked later phases, not an uninterrupted study or causal delivery before/after.",
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
        fig,ax=plt.subplots(figsize=(10,4.5),constrained_layout=True)
        for i,(seed,aid) in enumerate((s,a) for s in SEEDS for a in ("llm_012","llm_013")):
            vals=[r["announced_minus_silent_accepted"] for r in probes if r["seed"]==seed and r["agent_id"]==aid and r["announced_minus_silent_accepted"] is not None]
            if vals:
                ax.scatter(i+np.linspace(-.1,.1,len(vals)),vals,color="#2d659b",s=35)
                ax.scatter(i,float(np.mean(vals)),marker="D",color="#bd681f",s=40)
        ax.axhline(0,color="gray",linestyle="--")
        frames={(f["seed"],f["agent_id"]):f for f in probe_frames}
        labels=[]
        for s in SEEDS:
            for a in ("llm_012","llm_013"):
                label=f"{s}\n{'Meera' if a=='llm_012' else 'Arjun'}"
                if (s,a) in frames:
                    f=frames[s,a];label+=f"\n{100*f['stock_weight']:.1f}% stock; buy cap {f['market_buy_reservation_capacity']}"
                else:label+="\nnot yet observed"
                labels.append(label)
        ax.set_xticks(range(4),labels,fontsize=8)
        ax.set_xlim(-.45,3.45)
        ax.set_ylabel("Announced minus silent: signed accepted shares")
        ax.set_title("Same stored event state, three fresh replies per condition\nNo orders execute; diamond = mean, dots = repetitions",fontsize=11)
        fig.savefig(OUTPUT/"same_state_news.png",dpi=180);fig.savefig(OUTPUT/"same_state_news.pdf");plt.close(fig)
    shutil.copyfile(ROOT/"tests/test_news_pilot.py",OUTPUT/"test_news_pilot.py")
    shutil.copyfile(ROOT/"tests/test_transport_retry.py",OUTPUT/"test_transport_retry.py")
    # A short human-readable companion; all nulls and all scheduled arms retained.
    lines=["# Exploratory news pilot", "", f"Status: **{summary['status']}**. {complete_live}/8 live markets complete.", "",
        "Qwen `qwen-3.8-27b` at BharatCode; prompt suite `comparable_agents_v2_disclosed_rules`, condition A, memory 5, temperature 0.3, low reasoning effort, output cap 4096. Fourteen equal-resource slots; two specified rule slots replaced by two bundled LLM personas. Twenty rounds, event at 11; two exogenous seeds. Model draws are unseeded. Linked delivery phases are preserved separately.", "",
        "The completed pilot shows context-dependent order responses: Meera's first-seed positive contrast is mixed in the second seed; Arjun's two HOLD-only frames cannot fund a buy. Combined real-change/news markets have smaller average benchmark gaps in both seeds, but differing pre-event states prevent a clean causal price claim. One combined arm also has 90 accepted Meera buy shares and no fills. These distinctions motivate confirmation rather than a provider switch.", "",
        "## Same stored state: headline versus silence", "",
        "Three fresh replies per condition in each actual control-market event frame. Only the uncertain positive dividend forecast changes. These orders never execute. Buy capacity below uses the common conservative market-order reservation, not a guaranteed fill.", "",
        "| Seed / frame | Stock weight | Market buy cap | Silent signed orders | Announced signed orders | Paired differences |",
        "| --- | ---: | ---: | --- | --- | --- |"]
    for seed in SEEDS:
        for aid in ("llm_012","llm_013"):
            frame=next((f for f in probe_frames if f["seed"]==seed and f["agent_id"]==aid),None)
            pairs=[p for p in probes if p["seed"]==seed and p["agent_id"]==aid]
            def values(key):return ", ".join("missing" if p[key] is None else f"{p[key]:+g}" for p in pairs)
            lines.append(f"| {seed} / {'Meera' if aid=='llm_012' else 'Arjun'} | "
                +("missing | missing" if frame is None else f"{100*frame['stock_weight']:.2f}% | {frame['market_buy_reservation_capacity']}")
                +f" | {values('silent_requested')} | {values('announced_requested')} | {values('announced_minus_silent_accepted')} |")
    lines += ["", "Constraint context matters: a nearly fully invested account with no buying headroom cannot express a positive-news response by buying. A HOLD does not by itself reveal an unchanged belief. Personas differ on several traits and arrive at different states; cross-frame differences do not isolate personality.", "",
        "## Market outcomes", "", "Post-event gaps are mean absolute price deviations from the configured stationary-regime benchmark (mean dividend / cash rate), not an externally calibrated true price. The assigned regime is hidden; an uncertain forecast does not give traders an immediately known correct price. Full markets match exogenous innovations and initial resources, but live states already differ before news. Paired price differences therefore do not identify a clean causal headline effect.", "",
        "| Seed / cell | Live pre-event close | Live post mean | Live post gap | Rule post gap | Live target involvement | Live target submitted / accepted / filled shares after news |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- |"]
    for seed in SEEDS:
        for cell in CELLS:
            live=by.get(("qwen",seed,cell));rule=by[("rules",seed,cell)]
            if live is None:
                lines.append(f"| {seed} / {cell} | missing | missing | missing | {100*rule['event_metrics']['post_mean_absolute_relative_gap']:.2f}% | missing | missing |")
                continue
            e=live["event_metrics"];trading=[t for t in live["target_trading_by_period"] if t["period"]=="post_event"]
            q=[sum(t[k] for t in trading) for k in ("gross_requested_shares","gross_accepted_shares","gross_executed_shares")]
            involvement="no trades" if e["target_union_volume_share"] is None else f"{100*e['target_union_volume_share']:.1f}%"
            lines.append(f"| {seed} / {cell} | {e['pre_event_price']:.2f} | {e['post_mean_price']:.2f} | {100*e['post_mean_absolute_relative_gap']:.2f}% | {100*rule['event_metrics']['post_mean_absolute_relative_gap']:.2f}% | {involvement} | {' / '.join(map(str,q))} |")
    lines += ["", "Target involvement counts each market trade once even if both target agents trade with each other. Submitted/accepted/filled quantities instead count target trader legs; they are not the same denominator. Larger order sizes can increase a policy's market influence, so these are comparisons of specified policies rather than intrinsic LLM superiority.", "",
        "## Conditional passive comparison", "",
        "Every target account is retained. Values are active-minus-passive returns in percentage points using the same initial wealth denominator. The passive account keeps its initial shares and earns the realized dividends and cash interest on this market's price path. This is not a separate no-trading equilibrium or risk-adjusted alpha. Auction and regime-benchmark terminal marks are both shown.", "",
        "| Seed / cell | Meera: auction / benchmark | Arjun: auction / benchmark |",
        "| --- | ---: | ---: |"]
    for seed in SEEDS:
        for cell in CELLS:
            live=by.get(("qwen",seed,cell))
            if live is None:lines.append(f"| {seed} / {cell} | missing | missing |");continue
            accounts={a["agent_id"]:a for a in live["target_passive_comparisons"]}
            vals=[" / ".join(f"{100*accounts[a]['marks'][m]['excess_return']:+.2f}" for m in ("auction","regime_benchmark")) for a in ("llm_012","llm_013")]
            lines.append(f"| {seed} / {cell} | {vals[0]} | {vals[1]} |")
    lines += ["", "## Interpretation boundary", "",
        "Two short exogenous scenarios and three replies per fixed frame are exploratory evidence. They do not establish stable market dynamics, human realism, herding, generalized profitability, or A/B/C benefits. Earlier incomplete attempts remain in report.json and the raw study tree; they are not spliced into full runs or pooled as additional independent markets. Negative, constrained and unfilled cases are retained.", "",
        "The A simple / B factual summaries / C reflection comparison remains available and has not been replaced by this A-only pilot. Further confirmation should distinguish news meaning, portfolio headroom, limit execution and policy sizing before expanding model/provider comparisons.", "",
        "Artifacts: [market paths](market_paths.pdf), [same-state orders and headroom](same_state_news.pdf), [full report](report.json), and [delivery/provenance audit](delivery_audit.json).", ""]
    (OUTPUT/"READOUT.md").write_text("\n".join(lines),encoding="utf-8")
    write_json(OUTPUT/"artifact_hashes.json",{p.name:sha256(p) for p in OUTPUT.iterdir() if p.is_file() and p.name!="artifact_hashes.json"})
    print(json.dumps(dict(status=summary,usage=usage,same_state=probes,
        markets=[dict(brain=a["brain"],seed=a["seed"],cell=a["cell"],**a["event_metrics"]) for a in arms]),indent=2))


if __name__=="__main__":analyze()
