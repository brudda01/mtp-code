"""Audit the entire fixed-state diagnostic; all contexts, nulls and repetitions."""
import csv
import hashlib
import json
from pathlib import Path
import shutil
from collections import Counter

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from sim.behaviour_run import contrasts, validate_battery
from sim.provenance import sha256, write_json

ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/"runs/20261102_195440_behaviour_qwen_ee95d92d"
ORIGINAL=ROOT/"runs/20261102_193749_behaviour_inputs_5e633670/battery.json"
OUTPUT=ROOT/"runs/behaviour_analysis_20261102"


def stats(values):
    v=[x for x in values if x is not None]
    return dict(values=values,n=len(v),mean=None if not v else float(np.mean(v)),
                positive=sum(x>0 for x in v),zero=sum(x==0 for x in v),negative=sum(x<0 for x in v))


def analyze():
    summary=json.loads((RUN/"summary.json").read_text())
    manifest=json.loads((RUN/"manifest.json").read_text())
    battery=json.loads((RUN/"battery.json").read_text())
    definitions=validate_battery(battery)
    results=json.loads((RUN/"results.json").read_text())
    requests=[json.loads(line) for line in (RUN/"llm_requests.jsonl").read_text().splitlines()]
    calls=[r for r in requests if r["record_type"]=="model_call"]
    assert (RUN/"battery.json").read_bytes()==ORIGINAL.read_bytes()
    assert sha256(ORIGINAL)=="67929bd362979762633eef024c2ce88e2ec3b8db2b36af2fd4eef34dc30246b1"
    assert sha256(RUN/"battery.json")==manifest["battery_sha256"]
    assert manifest["status"]==summary["status"]
    assert sha256(RUN/"source.zip")==manifest["source_archive_sha256"]
    for name,digest in manifest["output_sha256"].items():assert sha256(RUN/name)==digest,name
    for name,digest in manifest["source_sha256"].items():assert sha256(ROOT/name)==digest,name
    assert len(calls)==summary["llm_usage"]["requests_made"]
    assert len({(r["case_id"],r["repetition"]) for r in results})==len(results)
    assert [(r["case_id"],r["repetition"]) for r in results]==[
        (r["case_id"],r["repetition"]) for r in battery["schedule"][:len(results)]]
    for row in calls:
        if row["call_id"].rsplit(":",1)[-1]=="1":
            assert row["messages"]==definitions[row["case_id"]]["messages"]
        assert row["temperature"]==.3 and row["max_tokens"]==4096 and row["reasoning_effort"]=="low"
    feasible=0
    for row in results:
        if not row["valid_choice"]:continue
        obs=definitions[row["case_id"]]["observation"];order=row["accepted"]
        q=order["quantity"]
        assert type(q) is int and q>=0
        if order["side"]=="sell":assert q<=obs["my_shares"]
        if order["side"]=="buy":
            ceiling=obs["price_history"][-1]*1.2
            reserve=min(order["limit_price"],ceiling) if order["limit_price"] is not None else ceiling
            assert q*reserve<=obs["my_cash"]+1e-8
        if order["side"]=="hold":assert q==0
        assert row["executions"] is None
        feasible+=1
    comparison=contrasts(results,definitions)
    assert comparison==json.loads((RUN/"contrasts.json").read_text())
    risk=[]
    for context in ("rising","falling"):
        for wording in ("label","description"):
            group=[r for r in comparison["risk"] if r["context"]==context and r["wording"]==wording]
            risk.append(dict(context=context,wording=wording,
                accepted=stats([r["high_minus_low_accepted"] for r in group]),
                requested=stats([r["high_minus_low_requested"] for r in group])))
    basis=[dict(wording=w,interaction=stats([r["trait_by_basis_sell_interaction"] for r in comparison["gain_loss"] if r["wording"]==w]))
           for w in ("pain","weight")]
    case_rows=[]
    for case in battery["cases"]:
        selected=[r for r in results if r["case_id"]==case["case_id"]]
        action_counts=Counter(r["accepted"]["side"] if r["valid_choice"] else "invalid" for r in selected)
        case_rows.append(dict(case_id=case["case_id"],family=case["family"],factors=case["factors"],
            requested=stats([r["requested_signed_quantity"] for r in selected]),
            accepted=stats([r["accepted_signed_quantity"] for r in selected]),
            actions=dict(action_counts),resource_reduced=sum(r["resource_reduced"] is True for r in selected)))
    message_groups={}
    for case in battery["cases"]:
        message_groups.setdefault(case["messages_sha256"],[]).append(case["case_id"])
    duplicate_groups=[]
    for digest,ids in message_groups.items():
        if len(ids)>1:
            group=[r for r in results if r["case_id"] in ids]
            duplicate_groups.append(dict(messages_sha256=digest,case_ids=ids,
                actions=dict(Counter(r["accepted"]["side"] for r in group)),
                signed_quantities=[r["accepted_signed_quantity"] for r in group]))
    OUTPUT.mkdir(exist_ok=True)
    shutil.copyfile(Path(__file__),OUTPUT/"analysis_source.py")
    report=dict(status=summary["status"],run=RUN.relative_to(ROOT).as_posix(),
        completed_decisions=len(results),valid_choices=feasible,feasible_accepted_orders=feasible,
        request_count=len(calls),repaired_decisions=sum(r["repaired"] for r in results),
        resource_reduced_choices=sum(r["resource_reduced"] is True for r in results),
        actions=dict(Counter(r["accepted"]["side"] if r["valid_choice"] else "invalid" for r in results)),
        family_actions={family:dict(Counter(r["accepted"]["side"] if r["valid_choice"] else "invalid"
                                            for r in results if r["family"]==family))
                        for family in ("risk","gain_loss")},
        risk_overall=stats([r["high_minus_low_accepted"] for r in comparison["risk"]]),
        basis_interaction_overall=stats([r["trait_by_basis_sell_interaction"] for r in comparison["gain_loss"]]),
        risk_by_context_wording=risk,basis_by_wording=basis,case_rows=case_rows,
        distinct_first_attempt_message_pairs=len(message_groups),
        supplementary_identical_input_groups=duplicate_groups,
        supplementary_note="Identical neutral-input grouping diagnoses sampling variation after the main contrasts; not a new predeclared significance test.",
        usage=summary["llm_usage"],source_parent=manifest["parent_revision"],
        working_tree_status=manifest["working_tree_status"],source_sha256=manifest["source_sha256"],
        run_manifest_sha256=sha256(RUN/"manifest.json"),battery_sha256=sha256(ORIGINAL),
        analysis_source_sha256=sha256(Path(__file__)),
        returned_model_metadata=[row.get("response_metadata",{}) for row in calls],
        interpretation="Exploratory frozen synthetic-state contrasts, three fresh responses per case. No market outcomes or human validation. States/wordings are not independent market repeats; model sampling is unseeded. All nulls/negative signs and duplicate neutral prompts retained. Values are requested/accepted choices, never executions.")
    write_json(OUTPUT/"report.json",report)
    with (OUTPUT/"all_choices.csv").open("w",newline="",encoding="utf-8") as f:
        fields=["case_id","repetition","family","valid_choice","requested_signed_quantity","accepted_signed_quantity","accepted_sell_quantity","resource_reduced","request_count","repaired"]
        writer=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore");writer.writeheader();writer.writerows(results)
    fig,axes=plt.subplots(1,2,figsize=(11,4.5),constrained_layout=True)
    for ax,groups,labels,title in (
        (axes[0],[r["accepted"]["values"] for r in risk],[r["context"]+"\n"+r["wording"] for r in risk],"High minus low risk: signed accepted shares"),
        (axes[1],[r["interaction"]["values"] for r in basis],[r["wording"] for r in basis],"Gain/loss selling: trait-by-basis interaction")):
        for i,group in enumerate(groups):
            vals=[v for v in group if v is not None]
            if vals:
                ax.scatter(i+np.linspace(-.1,.1,len(vals)),vals,color="#285b8b",s=35)
                ax.scatter(i,float(np.mean(vals)),marker="D",color="#b86528",s=40,zorder=4)
        ax.axhline(0,color="gray",linestyle="--",linewidth=1)
        ax.set_xticks(range(len(labels)),labels)
        ax.set_title(title,fontsize=10);ax.set_ylabel("Shares");ax.grid(axis="y",alpha=.15)
    axes[1].set_ylim(-110,90)
    axes[1].text(.5,.88,"Gain/loss replies: 23 HOLD, 1 BUY, no SELL.\nThe selling contrast has limited information here.",
                 transform=axes[1].transAxes,ha="center",va="top",fontsize=9)
    fig.suptitle("Qwen fixed-state behavioural diagnostic\nDots = each of three fresh response repetitions; diamond = mean. No action is a pass/fail oracle.",fontsize=11)
    fig.savefig(OUTPUT/"trait_contrasts.png",dpi=180);fig.savefig(OUTPUT/"trait_contrasts.pdf");plt.close(fig)
    shutil.copyfile(ROOT/"tests/test_behaviour_run.py",OUTPUT/"test_behaviour_run.py")
    write_json(OUTPUT/"artifact_hashes.json",{p.name:sha256(p) for p in OUTPUT.iterdir() if p.is_file() and p.name!="artifact_hashes.json"})
    print(json.dumps({k:report[k] for k in ("status","completed_decisions","valid_choices","request_count","repaired_decisions","resource_reduced_choices","actions","risk_overall","basis_interaction_overall","risk_by_context_wording","basis_by_wording","usage")},indent=2))
    return report


if __name__=="__main__":analyze()
