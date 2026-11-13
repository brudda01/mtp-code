"""Read-only R025 analysis. Partial/missing choices never become HOLD zeros."""
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from sim.agents.llm_agent import REFLECTION_TEMPLATE
from sim.llm.client import dotenv_api_key
from sim.news_components import CONDITIONS, NEWS, comparisons, validate
from sim.provenance import sha256, write_json

ROOT=Path(__file__).resolve().parent/"20261103_023441_news_components_da6bdf79"
OUTPUT=ROOT.parent/"component_analysis_20261103"


def read(path, default):
    return json.loads(path.read_text()) if path.exists() else default


def lines(path):
    result=[]
    if path.exists():
        for line in path.read_text().splitlines():
            try:result.append(json.loads(line))
            except json.JSONDecodeError:pass  # Only a live file's trailing partial line.
    return result


def analyze():
    protocol,frames,manifest=validate(ROOT)
    summary=read(ROOT/"summary.json",dict(status="running",completed_decisions=0))
    final=(ROOT/"summary.json").exists()
    if final:
        for name,digest in manifest["output_sha256"].items():assert sha256(ROOT/name)==digest,name
    with zipfile.ZipFile(ROOT/"source.zip") as z:
        for name,digest in manifest["source_sha256"].items():assert hashlib.sha256(z.read(name)).hexdigest()==digest,name
    results=read(ROOT/"results.json",[]);chains=read(ROOT/"reflection_chains.json",[])
    records=lines(ROOT/"llm_requests.jsonl");inputs=lines(ROOT/"decision_inputs.jsonl")
    calls=[r for r in records if r["record_type"]=="model_call"]
    definitions={f["frame_id"]:f for f in frames}
    input_map={(r["frame_id"],r["repetition"],r["condition"],r["news"]):r for r in inputs}
    chain_map={(c["frame_id"],c["repetition"]):c for c in chains}
    assert len(input_map)==len(inputs)
    assert len({r["call_id"] for r in calls})==len(calls)
    groups=defaultdict(list);cost=defaultdict(Counter);errors=[]
    for call in calls:
        groups[call["request_group_id"]].append(call)
        k=f"{call['condition']}_{call['call_type']}";cost[k]["http_attempts"]+=1
        cost[k]["reserved_tokens"]+=call["reservation"]["input_token_estimate"]+call["reservation"]["max_output_tokens"]
        if call.get("usage"):cost[k]["reported_tokens"]+=call["usage"]["total_tokens"]
        else:cost[k]["unknown_usage"]+=1
        if call["status"]=="error":
            errors.append({k:call.get(k) for k in ("call_id","error_type","http_status","transport_diagnostics","retry_category","retry_wait_seconds")})
        if call["call_type"]=="decision" and call["json_attempt"]==1:
            key=(call["frame_id"],call["repetition"],call["condition"],call["news"])
            assert call["messages"]==input_map[key]["messages"]
        if call["call_type"]=="reflection":
            f=definitions[call["frame_id"]];p=f["persona"];step=call["history_round"]
            chain=chain_map.get((call["frame_id"],call["repetition"]),{"steps":[]})
            previous="none" if step==5 else next(s["diary"] for s in chain["steps"] if s["round"]==5)
            expected=[dict(role="system",content=REFLECTION_TEMPLATE.format(name=p["name"],risk=p["risk_tolerance"],
                style=p["strategy_inclination"],horizon=p["horizon"],biases=p["bias_clauses"])),
                dict(role="user",content="Previous reflection (fallible): "+previous+"\nVerified recent outcomes: "+json.dumps(f["reflection_windows"][str(step)],allow_nan=False))]
            assert call["messages"]==expected
            assert call["temperature_sent"]==0 and not call["json_mode"]
    for group in groups.values():
        assert len(group)<=2
        if len(group)>1:
            assert group[0]["status"]=="error" and group[0]["transport_retry_planned"]
            for k in ("messages","temperature","max_tokens","reasoning_effort","json_mode"):
                assert group[0][k]==group[1][k]
    for row in inputs:
        if row["condition"] in ("A","B"):
            assert row["messages"]==definitions[row["frame_id"]]["fixed_messages"][row["condition"]][row["news"]]
            assert row["diary"] is None
        else:
            diary=chain_map[row["frame_id"],row["repetition"]]["steps"][-1]["diary"]
            assert row["diary"]==diary
            base=definitions[row["frame_id"]]["fixed_messages"]["B"][row["news"]]
            assert row["messages"][0]==base[0]
            assert row["messages"][1]["content"].replace("Your reflection (beliefs may be wrong): "+diary+"\n","")==base[1]["content"]
    contrast=comparisons(results,frames)
    if final:
        assert contrast==read(ROOT/"contrasts.json",{})
        usage=summary["llm_usage"]
        assert len(calls)==usage["requests_made"]<=264
        assert sum(c["reserved_tokens"] for c in cost.values())==usage["reserved_tokens"]<=4000000
        assert sum(c["reported_tokens"] for c in cost.values())==usage["provider_reported_tokens"]
    else:usage={"scope":"Final usage unavailable while an HTTP request may be in flight."}
    cells=[]
    for f in frames:
        for condition in CONDITIONS:
            for news in NEWS:
                r=[x for x in results if x["frame_id"]==f["frame_id"] and x["condition"]==condition and x["news"]==news]
                valid=[x for x in r if x["valid_choice"]]
                values=[x["accepted_signed_quantity"] for x in valid]
                cells.append(dict(frame_id=f["frame_id"],condition=condition,news=news,completed=len(r),valid=len(valid),
                    signed_requested=[x["requested_signed_quantity"] for x in valid],signed_accepted=values,
                    mean_accepted=None if not values else float(np.mean(values)),
                    sd_accepted=None if len(values)<2 else float(np.std(values,ddof=1)),
                    action_counts=dict(Counter(x["accepted"]["side"] for x in valid)),
                    resource_reductions=sum(x["resource_reduced"] for x in valid),
                    impossible_at_any_allowed_price=sum(x["possible_execution_prices"]==[] for x in valid)))
    OUTPUT.mkdir(exist_ok=True)
    secret_values={v.encode() for name in ("API_KEY","BHARATCODE_API_KEY","GEMINI_API_KEY","NVIDIA_API_KEY")
                   if (v:=dotenv_api_key(name)) and len(v)>=8}
    scanned=0
    for p in ROOT.rglob("*"):
        if not p.is_file():continue
        assert not p.name.startswith(".env")
        if p.suffix==".zip":
            with zipfile.ZipFile(p) as z:
                for name in z.namelist():
                    assert Path(name).name!=".env" and not any(v in z.read(name) for v in secret_values)
                    scanned+=1
        else:
            assert not any(v in p.read_bytes() for v in secret_values)
            scanned+=1
    report=dict(status=summary,protocol_sha256=sha256(ROOT/"protocol.json"),
        frames=[{k:f[k] for k in ("frame_id","seed","agent_id","constraints","source_manifest_sha256")} for f in frames],
        cells=cells,contrasts=contrast,usage=usage,cost_by_condition_and_call_type=dict(cost),errors=errors,
        returned_models=dict(Counter(r.get("response_metadata",{}).get("model","unreported") for r in calls if r["status"]=="returned")),
        attempt_kinds=dict(Counter(r.get("attempt_kind") for r in calls)),
        delivery_retry_outcomes=[dict(group_id=k,kind=rows[1]["attempt_kind"],recovered=rows[1]["status"]=="returned") for k,rows in groups.items() if len(rows)==2],
        coverage=dict(delivered_decisions=len(results),planned_decisions=108,
            covered_cells=sum(c["completed"]>0 for c in cells),planned_cells=36,
            cells_with_three_replies=sum(c["completed"]==3 for c in cells)),
        completed_reflection_chains=chains,
        audit=dict(final_output_hashes_checked=final,source_and_copied_evidence_hashes_verified=True,
            exact_A_B_and_reflection_inputs_verified=True,C_diary_only_difference_from_B_verified=True,
            delivery_retries_preserve_inputs=True,secret_scan_passed=True,scanned_members=scanned),
        limitations=protocol["scope"],analysis_source_sha256=sha256(Path(__file__)))
    write_json(OUTPUT/"report.json",report)
    done={(r["frame_id"],r["repetition"],r["condition"],r["news"]) for r in results}
    pending=[];new_chains=[];retained_chains=[]
    for block in protocol["schedule"]:
        missing=[dict(frame_id=block["frame_id"],repetition=block["repetition"],**choice) for choice in block["choices"]
                 if (block["frame_id"],block["repetition"],choice["condition"],choice["news"]) not in done]
        if not missing:continue
        pending+=missing
        chain=chain_map.get((block["frame_id"],block["repetition"]))
        if chain and len(chain["steps"])==2:retained_chains.append(chain)
        else:new_chains.append(dict(frame_id=block["frame_id"],repetition=block["repetition"]))
    write_json(OUTPUT/"remaining_work.json",dict(status="inventory_only_no_execution_or_resume_implemented",
        pending_decisions=pending,new_two_reflection_blocks=new_chains,existing_pre_news_diaries_to_retain=retained_chains,
        planned_remaining_normal_calls=len(pending)+2*len(new_chains),
        prior_summary_sha256=sha256(ROOT/"summary.json") if final else None,
        remaining_request_cap=None if not final else 264-usage["requests_made"],
        remaining_reservation_cap=None if not final else 4000000-usage["reserved_tokens"],
        note="Inventory for a future explicit linked continuation, not an automatic restart. Retain all prior usage/failed calls/completed choices, same frozen inputs/model and the existing diary. Do not rerun successful cells or pool another model's replies."))
    text=["# News and A/B/C on common recorded histories", "",f"Status: **{summary['status']}**; {len(results)}/108 decisions. All outcomes are queries without executions.","",
        "A uses raw observations and actual recent outcomes. B adds computed facts. C adds two generated reflections on the same actual A-market past, with its pre-news diary shared across headline variants. Three fresh repetitions per cell were planned; delivered counts are shown below. Four reused actual states, not held-out markets or an endogenous C trajectory. This is not a news-retention or profitability experiment.","",
        f"Coverage: {sum(c['completed']>0 for c in cells)}/36 cells have any response; {sum(c['completed']==3 for c in cells)}/36 have all three planned repeats. Delivery gaps cannot establish a mode benefit. [Remaining-work inventory](remaining_work.json) records pending inputs and budgets; it does not resume the study.", "",
        "| Frame | Stock weight | Market-buy capacity | Sell capacity |", "| --- | ---: | ---: | ---: |"]
    for f in frames:
        c=f["constraints"];text.append(f"| {f['frame_id']} | {100*c['stock_weight']:.2f}% | {c['market_buy_capacity']} | {c['sell_capacity']} |")
    text += ["", "Signed accepted shares by repetition (missing replies are not HOLD zeros). Positive quantities buy; negative quantities sell. No direction is a correctness oracle.","",
        "| Frame / mode | No headline | Positive | Negative | Positive minus silent | Negative minus silent |",
        "| --- | --- | --- | --- | --- | --- |"]
    for f in frames:
        for condition in CONDITIONS:
            row=[c for c in cells if c["frame_id"]==f["frame_id"] and c["condition"]==condition]
            values=[", ".join(f"{v:+g}" for v in next(c for c in row if c["news"]==news)["signed_accepted"]) or "missing" for news in NEWS]
            deltas=[]
            for news in ("positive","negative"):
                q=[r["accepted_signed_quantity"] for r in contrast["news_minus_silent"] if r["frame_id"]==f["frame_id"] and r["condition"]==condition and r["news"]==news]
                deltas.append(", ".join("missing" if v is None else f"{v:+g}" for v in q))
            text.append(f"| {f['frame_id']} / {condition} | "+" | ".join(values+deltas)+" |")
    text += ["", "Arjun's natural frames cannot fund even one executable buy, while both can sell. That constrains positive-news order responses; persona and headroom are not separately randomized. Reporting accepted orders also does not predict fills. Full requested orders, limits, resource reductions, descriptive variation and missing/failed cases are in report.json and the raw run.","",
        "## Cost and interpretation", "", f"Usage: `{json.dumps(usage)}`.", "",
        "Reflection and decision costs are separated in report.json. Each two-call C chain is shared across three experimental headline branches; that amortization is not a deployment cost estimate. Model: BharatCode qwen-3.8-27b, decision temperature0.3/reflection0, low effort, cap4096, timeout180; sampling unseeded. Common prompt suite v2, memory5, C reflects at5/10 on actual records.","",
        "Do not infer full-market effects, human realism or general component superiority from this small conditional study. All cells and directions are retained; further market confirmation needs genuine sequential trajectories and independent scenarios.","",
        "[News contrasts](news_contrasts.pdf) | [Full report and audit](report.json)", ""]
    (OUTPUT/"READOUT.md").write_text("\n".join(text),encoding="utf-8")
    fig,axes=plt.subplots(2,2,figsize=(10,7),constrained_layout=True)
    colors=("#356999","#d2812a","#63944c")
    for ax,f in zip(axes.flat,frames):
        observed=[];missing_modes=[]
        for j,condition in enumerate(CONDITIONS):
            available=0
            for i,news in enumerate(("positive","negative")):
                vals=[r["accepted_signed_quantity"] for r in contrast["news_minus_silent"] if r["frame_id"]==f["frame_id"] and r["condition"]==condition and r["news"]==news and r["accepted_signed_quantity"] is not None]
                if vals:
                    observed+=vals;available+=len(vals)
                    x=i+(j-1)*.19
                    ax.scatter(x+np.linspace(-.035,.035,len(vals)),vals,color=colors[j],s=22,alpha=.8)
                    ax.scatter(x,float(np.mean(vals)),marker="D",color=colors[j],s=35,label=condition if i==0 else None)
            if not available:missing_modes.append(condition)
        if observed and all(v==0 for v in observed):ax.set_ylim(-1,1);ax.set_yticks([-1,0,1])
        if missing_modes:ax.text(.02,.97,"No complete news pair: "+", ".join(missing_modes),transform=ax.transAxes,va="top",fontsize=8)
        ax.axhline(0,color="gray",linestyle="--",linewidth=1)
        ax.set_xlim(-.45,1.45);ax.set_xticks([0,1],["Positive minus silent","Negative minus silent"],fontsize=8)
        ax.set_title(f"{f['frame_id']}: {100*f['constraints']['stock_weight']:.1f}% stock; buy cap{f['constraints']['market_buy_capacity']}",fontsize=9)
        ax.set_ylabel("Signed accepted shares: difference")
        ax.grid(axis="y",alpha=.15)
    if axes[0,0].get_legend_handles_labels()[0]:axes[0,0].legend(title="Mode",fontsize=8)
    fig.suptitle(f"{summary['status']}: {len(results)}/108 decisions; A raw / B facts / C actual-history reflection\nDots = delivered repeats; diamonds = means. No executions or market replications.",fontsize=11)
    fig.savefig(OUTPUT/"news_contrasts.png",dpi=180);fig.savefig(OUTPUT/"news_contrasts.pdf");plt.close(fig)
    shutil.copyfile(Path(__file__),OUTPUT/"analysis_source.py")
    shutil.copyfile(Path(__file__).parents[1]/"tests/test_news_components.py",OUTPUT/"test_news_components.py")
    write_json(OUTPUT/"artifact_hashes.json",{p.name:sha256(p) for p in OUTPUT.iterdir() if p.is_file() and p.name!="artifact_hashes.json"})
    print(json.dumps(dict(status=summary.get("status"),completed_decisions=len(results),cost=dict(cost),errors=errors),indent=2))


if __name__=="__main__":analyze()
