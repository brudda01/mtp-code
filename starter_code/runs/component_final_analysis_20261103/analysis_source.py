"""R025-27 audit: scheduled cases, valid orders and missing outputs stay distinct."""
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
from sim.component_continuation import validate as validate_continuation
from runs.component_tail_20261103 import validate as validate_tail
from sim.provenance import sha256, write_json

PARENT=Path(__file__).resolve().parent/"20261103_023441_news_components_da6bdf79"
PHASE=Path(__file__).resolve().parent/"20261103_172911_components_continue_f62a08f1"
ROOT=Path(__file__).resolve().parent/"20261103_174525_components_tail_90002a97"
OUTPUT=ROOT.parent/"component_final_analysis_20261103"


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
    protocol,frames,parent_manifest=validate(PARENT)
    phase_plan,phase_frames,phase_manifest=validate_continuation(PHASE)
    plan,child_frames,manifest=validate_tail(ROOT)
    assert frames==child_frames
    parent_summary=read(PARENT/"summary.json",{})
    middle_summary=read(PHASE/"summary.json",{})
    phase_summary=read(ROOT/"summary.json",dict(status="running",completed_decisions=0))
    final=(ROOT/"summary.json").exists()
    for path,m,is_final in ((PARENT,parent_manifest,True),(PHASE,phase_manifest,True),(ROOT,manifest,final)):
        if is_final:
            for name,digest in m["output_sha256"].items():assert sha256(path/name)==digest,name
        with zipfile.ZipFile(path/"source.zip") as z:
            for name,digest in m["source_sha256"].items():assert hashlib.sha256(z.read(name)).hexdigest()==digest,name
    results=plan["prior_cases"]+read(ROOT/"results.json",[])
    assert len({(r["frame_id"],r["repetition"],r["condition"],r["news"]) for r in results})==len(results)
    chains=plan["prior_chains"]
    for c in read(ROOT/"reflection_chains.json",[]):
        found=next((old for old in chains if (old["frame_id"],old["repetition"])==(c["frame_id"],c["repetition"])),None)
        if found is not None:assert c.get("inherited") and found["steps"]==c["steps"]
        else:chains.append(c)
    summary=dict(status=phase_summary["status"],
        completed_decisions=len(results),completed_reflections=sum(len(c["steps"]) for c in chains),
        valid_decisions=sum(r["valid_choice"] for r in results),failed_decisions=sum(not r["valid_choice"] for r in results),
        parent_phase=parent_summary,continuation_phase=middle_summary,completion_phase=phase_summary)
    records=lines(PARENT/"llm_requests.jsonl")+lines(PHASE/"llm_requests.jsonl")+lines(ROOT/"llm_requests.jsonl")
    inputs=lines(PARENT/"decision_inputs.jsonl")+lines(PHASE/"decision_inputs.jsonl")+lines(ROOT/"decision_inputs.jsonl")
    calls=[r for r in records if r["record_type"]=="model_call"]
    definitions={f["frame_id"]:f for f in frames}
    input_map={};reissued=0
    for r in inputs:
        k=(r["frame_id"],r["repetition"],r["condition"],r["news"])
        if k in input_map:assert input_map[k]==r;reissued+=1
        input_map[k]=r
    chain_map={(c["frame_id"],c["repetition"]):c for c in chains}
    assert len(input_map)+reissued==len(inputs)
    assert len({r["call_id"] for r in calls})==len(calls)
    call_index={r["call_id"]:r for r in calls}
    for result in results:
        if result.get("failure_type")=="output_truncated":
            source=call_index[result["source_call_id"]]
            assert source["response_metadata"]["finish_reason"]=="length" and source["max_tokens"]==4096
            assert not result["valid_choice"] and result["accepted_signed_quantity"] is None and result["accepted"] is None
            assert all(source[k]==result[k] for k in ("frame_id","repetition","condition","news"))
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
    news_summary=[];mode_summary=[]
    for f in frames:
        for condition in CONDITIONS:
            for news in ("positive","negative"):
                rows=[r for r in contrast["news_minus_silent"] if r["frame_id"]==f["frame_id"] and r["condition"]==condition and r["news"]==news]
                vals=[r["accepted_signed_quantity"] for r in rows if r["accepted_signed_quantity"] is not None]
                news_summary.append(dict(frame_id=f["frame_id"],condition=condition,news=news,available_contrasts=len(vals),
                    mean=None if not vals else float(np.mean(vals)),sd=None if len(vals)<2 else float(np.std(vals,ddof=1)),
                    sign_counts=dict(negative=sum(v<0 for v in vals),zero=sum(v==0 for v in vals),positive=sum(v>0 for v in vals)),
                    by_repetition=[r["accepted_signed_quantity"] for r in rows]))
        for news in NEWS:
            for name in ("B-A","C-B"):
                rows=[r for r in contrast["adjacent_mode_contrasts"] if r["frame_id"]==f["frame_id"] and r["news"]==news and r["contrast"]==name]
                vals=[r["accepted_signed_quantity"] for r in rows if r["accepted_signed_quantity"] is not None]
                mode_summary.append(dict(frame_id=f["frame_id"],news=news,contrast=name,available_contrasts=len(vals),
                    mean=None if not vals else float(np.mean(vals)),by_repetition=[r["accepted_signed_quantity"] for r in rows]))
    if final:
        assert contrast==read(ROOT/"combined_contrasts.json",{})
        usage=dict(parent_summary["llm_usage"])
        for k in ("requests_made","reserved_tokens","provider_reported_tokens","unknown_usage_requests","failed_requests","blocked_requests","reserved_cost_usd","observed_cost_estimate_usd"):
            usage[k]=parent_summary["llm_usage"][k]+middle_summary["llm_usage"][k]+phase_summary["llm_usage"][k]
        usage["provider_stopped"]=phase_summary["llm_usage"]["provider_stopped"]
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
                by_rep={x["repetition"]:x for x in r}
                cells.append(dict(frame_id=f["frame_id"],condition=condition,news=news,completed=len(r),valid=len(valid),failed=len(r)-len(valid),
                    signed_requested=[x["requested_signed_quantity"] for x in valid],signed_accepted=values,
                    accepted_by_repetition=[None if n not in by_rep or not by_rep[n]["valid_choice"] else by_rep[n]["accepted_signed_quantity"] for n in (1,2,3)],
                    mean_accepted=None if not values else float(np.mean(values)),
                    sd_accepted=None if len(values)<2 else float(np.std(values,ddof=1)),
                    action_counts=dict(Counter(x["accepted"]["side"] for x in valid)),
                    resource_reductions=sum(x["resource_reduced"] for x in valid),
                    impossible_at_any_allowed_price=sum(x["possible_execution_prices"]==[] for x in valid)))
    OUTPUT.mkdir(exist_ok=True)
    secret_values={v.encode() for name in ("API_KEY","BHARATCODE_API_KEY","GEMINI_API_KEY","NVIDIA_API_KEY")
                   if (v:=dotenv_api_key(name)) and len(v)>=8}
    scanned=0
    for p in list(PARENT.rglob("*"))+list(PHASE.rglob("*"))+list(ROOT.rglob("*")):
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
    report=dict(status=summary,protocol_sha256=sha256(PARENT/"protocol.json"),continuation_plan_sha256=sha256(ROOT/"plan.json"),
        delivery_note="Three linked phases: original503 stop; later output-cap stop; explicit post-failure independent-case stop amendment. Same model alias/prompts/economics/4096 cap; capped query kept missing, never resampled. Provider/budget/reflection failures still terminal. First-repeat final-frame C news spans the time gap. Reused states, not human/full-market validation or causal delivery improvement.",
        identically_reissued_input_count=reissued,
        frames=[{k:f[k] for k in ("frame_id","seed","agent_id","constraints","source_manifest_sha256")} for f in frames],
        cells=cells,contrasts=contrast,news_contrast_summary=news_summary,mode_contrast_summary=mode_summary,
        usage=usage,cost_by_condition_and_call_type=dict(cost),errors=errors,
        returned_models=dict(Counter(r.get("response_metadata",{}).get("model","unreported") for r in calls if r["status"]=="returned")),
        attempt_kinds=dict(Counter(r.get("attempt_kind") for r in calls)),
        delivery_retry_outcomes=[dict(group_id=k,kind=rows[1]["attempt_kind"],recovered=rows[1]["status"]=="returned") for k,rows in groups.items() if len(rows)==2],
        coverage=dict(resolved_cases=len(results),valid_decisions=sum(r["valid_choice"] for r in results),failed_decisions=sum(not r["valid_choice"] for r in results),planned_decisions=108,
            covered_cells=sum(c["completed"]>0 for c in cells),planned_cells=36,
            cells_with_three_resolved_slots=sum(c["completed"]==3 for c in cells),cells_with_three_valid_replies=sum(c["valid"]==3 for c in cells)),
        failed_choice_records=[r for r in results if not r["valid_choice"]],
        query_failures_by_condition=dict(Counter((r["condition"]+":"+r.get("failure_type","unspecified")) for r in results if not r["valid_choice"])),
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
    text=["# News and A/B/C on common recorded histories", "",f"Status: **{summary['status']}**; {len(results)}/108 cases resolved, {summary['valid_decisions']} valid orders and {summary['failed_decisions']} failed/missing. No executions.","",
        "A uses raw observations and actual recent outcomes. B adds computed facts. C adds two generated reflections on the same actual A-market past, with its pre-news diary shared across headline variants. Three fresh repetitions per cell were planned; delivered counts are shown below. Four reused actual states, not held-out markets or an endogenous C trajectory. This is not a news-retention or profitability experiment.","",
        f"Coverage: {sum(c['completed']>0 for c in cells)}/36 cells have resolved slots; {sum(c['valid']==3 for c in cells)}/36 have three valid replies. Missing outputs are not HOLD zeros. [Remaining-work inventory](remaining_work.json) records unresolved inputs/budgets; it does not resume the study.", "",
        "| Frame | Stock weight | Market-buy capacity | Sell capacity |", "| --- | ---: | ---: | ---: |"]
    if final and len(results)==108:
        findings=["## What this experiment shows", "",
            "**HOLD can be a response to good news.** In Arjun's seed2882 state, A requests sells of 100/80/0 shares without news and HOLD/HOLD/HOLD after the positive forecast. The mean headline-minus-silent change is +60 signed shares, although no BUY is affordable. Measuring BUY frequency alone would miss this response. These are order intentions, not executed shares.", "",
            "**There is no uniform component upgrade here.** In Meera's seed2882 state, positive-news contrasts are-50/-30/+40 for A,-20/+20/0 for B and+20/+20/+30 for C. C is more consistent in that particular contrast. In her other state, B's contrasts are+20/+10/+10 and C's+20/+10/0. Negative-news patterns differ too. Baseline no-news decisions also change across modes; larger headline contrasts do not by themselves establish better trading or human realism.", "",
            "**Constraints are part of the explanation.** Arjun's seed1441 frame produces HOLD in all 27 valid queries, including nine negative-news queries with 192 shares available to sell. Buying limits do not explain every null, and a HOLD does not reveal whether beliefs changed.", "",
            f"**Reflection adds measured cost.** The 24 reflection calls used {cost['C_reflection']['reported_tokens']:,} reported tokens, beyond C's decision calls. A used {cost['A_decision']['reported_tokens']:,}, B {cost['B_decision']['reported_tokens']:,}, and C decisions {cost['C_decision']['reported_tokens']:,} reported tokens. One C decision exhausted 4096 reasoning tokens and returned no order; it stays missing and was never resampled. Sharing each diary across three branches makes these experimental costs, not deployment estimates.", "",
            "These are exploratory conditional results on four reused states. Keep A as the reference and B/C selectable; test execution, market paths and costs in fresh sequential markets before promoting a more complex agent.", ""]
        i=text.index("| Frame | Stock weight | Market-buy capacity | Sell capacity |")
        text[i:i]=findings+["## Stored account states", ""]
    for f in frames:
        c=f["constraints"];text.append(f"| {f['persona']['name'].split()[0]} / {f['seed']} | {100*c['stock_weight']:.2f}% | {c['market_buy_capacity']} | {c['sell_capacity']} |")
    text += ["", "Signed accepted shares by repetition (missing replies are not HOLD zeros). Positive quantities buy; negative quantities sell. No direction is a correctness oracle.","",
        "| Frame / mode | No headline | Positive | Negative | Positive minus silent | Negative minus silent |",
        "| --- | --- | --- | --- | --- | --- |"]
    for f in frames:
        for condition in CONDITIONS:
            row=[c for c in cells if c["frame_id"]==f["frame_id"] and c["condition"]==condition]
            values=[", ".join("missing" if v is None else f"{v:+g}" for v in next(c for c in row if c["news"]==news)["accepted_by_repetition"]) for news in NEWS]
            deltas=[]
            for news in ("positive","negative"):
                q=[r["accepted_signed_quantity"] for r in contrast["news_minus_silent"] if r["frame_id"]==f["frame_id"] and r["condition"]==condition and r["news"]==news]
                deltas.append(", ".join("missing" if v is None else f"{v:+g}" for v in q))
            text.append(f"| {f['persona']['name'].split()[0]} / {f['seed']} / {condition} | "+" | ".join(values+deltas)+" |")
    text += ["", "## Mean headline-minus-silent contrasts", "", "Shares, with available matched-frame repetitions in parentheses. These are descriptive repeated replies, not independent markets or confidence intervals. Missing replies are excluded explicitly, never imputed as zero.", "",
        "| Frame / mode | Positive minus silent | Negative minus silent |", "| --- | ---: | ---: |"]
    for f in frames:
        for condition in CONDITIONS:
            vals=[]
            for news in ("positive","negative"):
                row=next(r for r in news_summary if r["frame_id"]==f["frame_id"] and r["condition"]==condition and r["news"]==news)
                vals.append("missing" if row["mean"] is None else f"{row['mean']:+.2f} (n={row['available_contrasts']})")
            text.append(f"| {f['persona']['name'].split()[0]} / {f['seed']} / {condition} | {vals[0]} | {vals[1]} |")
    text += ["", "Arjun's natural frames cannot fund even one executable buy, while both can sell. That constrains positive-news order responses; persona and headroom are not separately randomized. Reporting accepted orders also does not predict fills. Full requested orders, limits, resource reductions, descriptive variation and missing/failed cases are in report.json and the raw run.","",
        "## Cost and interpretation", "", (f"{usage['requests_made']} HTTP attempts;{usage['provider_reported_tokens']:,} provider-reported tokens plus{usage['unknown_usage_requests']} unknown-usage requests. Conservative reservations:{usage['reserved_tokens']:,}/{usage['max_reserved_tokens']:,}; request cap{usage['max_requests']}. Full accounting is in report.json." if final else "Final usage awaits completion; raw returned-call costs are in report.json."), "",
        "Reflection and decision costs are separated in report.json. Each two-call C chain is shared across three experimental headline branches; that amortization is not a deployment cost estimate. Model: BharatCode qwen-3.8-27b, decision temperature0.3/reflection0, low effort, cap4096, timeout180; sampling unseeded. Common prompt suite v2, memory5, C reflects at5/10 on actual records.","",
        "Three linked phases are preserved: an early503 stop, a later output-cap stop, and an explicit post-failure batch-stop amendment that retains capped replies as missing and attempts the other independent cases. No failed choice was resampled or given a larger budget. First-repeat final-frame C news replies span a delivery-time gap. The model alias has no pinned backend fingerprint. These limitations remain even when every scheduled case is resolved.", "",
        "Do not infer full-market effects, human realism or general component superiority from this small conditional study. C/B also includes retention of older common-history facts, not only extra reasoning. All cells and directions are retained; further market confirmation needs genuine sequential trajectories and independent scenarios.","",
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
                    if len(vals)<3:ax.annotate(f"n={len(vals)}",(x,float(np.mean(vals))),xytext=(0,7),textcoords="offset points",ha="center",fontsize=8,color=colors[j])
            if not available:missing_modes.append(condition)
        if observed and all(v==0 for v in observed):ax.set_ylim(-1,1);ax.set_yticks([-1,0,1])
        if missing_modes:ax.text(.02,.97,"No complete news pair: "+", ".join(missing_modes),transform=ax.transAxes,va="top",fontsize=8)
        ax.axhline(0,color="gray",linestyle="--",linewidth=1)
        ax.set_xlim(-.45,1.45);ax.set_xticks([0,1],["Positive minus silent","Negative minus silent"],fontsize=8)
        ax.set_title(f"{f['persona']['name'].split()[0]} / {f['seed']}: {100*f['constraints']['stock_weight']:.1f}% stock; buy cap{f['constraints']['market_buy_capacity']}",fontsize=9)
        ax.set_ylabel("Signed accepted shares: difference")
        ax.grid(axis="y",alpha=.15)
    if axes[0,0].get_legend_handles_labels()[0]:axes[0,0].legend(title="Mode",fontsize=8)
    fig.suptitle(f"{len(results)}/108 cases resolved: {summary['valid_decisions']} valid, {summary['failed_decisions']} missing; A raw / B facts / C reflection\nDots = valid contrasts; diamonds = means. No executions or market replications.",fontsize=11)
    fig.savefig(OUTPUT/"news_contrasts.png",dpi=180);fig.savefig(OUTPUT/"news_contrasts.pdf");plt.close(fig)
    shutil.copyfile(Path(__file__),OUTPUT/"analysis_source.py")
    shutil.copyfile(Path(__file__).parents[1]/"tests/test_news_components.py",OUTPUT/"test_news_components.py")
    write_json(OUTPUT/"artifact_hashes.json",{p.name:sha256(p) for p in OUTPUT.iterdir() if p.is_file() and p.name!="artifact_hashes.json"})
    print(json.dumps(dict(status=summary.get("status"),completed_decisions=len(results),cost=dict(cost),errors=errors),indent=2))


if __name__=="__main__":analyze()
