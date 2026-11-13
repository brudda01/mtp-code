"""R033 audit: conditional effects, all replies/missing cells, no long-market claims."""
import argparse
from collections import Counter
import json
import math
from pathlib import Path
import shutil
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sim.provenance import sha256,write_json
from sim.market import Order
from sim.evaluation import read_rows
from runs.news_auctions_20261104 import (BASE,VERSION,TARGETS,SEEDS,SNAPSHOTS,NEWS,USAGE,read,lines,validate,verify_market,extract_frames,settlements,rule_choices)

def marks_groups(settlement):
    result={g:{m:0. for m in ("auction","regime_benchmark")} for g in ("targets","market_maker","other_traders")}
    for a in settlement["accounts"]:
        group="targets" if a["agent_id"] in TARGETS else "market_maker" if a["agent_id"]=="mark_000" else "other_traders"
        for mark in result[group]:result[group][mark]+=a["marks"][mark]["excess_amount"]
    assert all(abs(sum(g[m] for g in result.values()))<1e-7 for m in ("auction","regime_benchmark"));return result

def analyze(root,output):
    root=Path(root);out=Path(output);p=validate(root);s=read(root/"summary.json");assert s["status"]!="running"
    out.mkdir(exist_ok=False);source=[];calls=[];blocks=[]
    entries=read(root/"source_runs.json") if (root/"source_runs.json").exists() else []
    assert {(root/e["run_path"]).resolve() for e in entries}=={x.resolve() for x in (root/"source_runs").glob("*") if x.is_dir()},"Unindexed source must be audited, not omitted"
    for e in entries:
        path=root/e["run_path"];m=verify_market(path);assert sha256(path/"manifest.json")==e["manifest_sha256"]
        summary=read(path/"summary.json");rr=lines(path/"llm_requests.jsonl");cc=[r for r in rr if r["record_type"]=="model_call"];calls+=cc;blocks += [r for r in rr if r["record_type"]=="request_blocked"]
        source.append({**e,"summary":summary,"http_records":len(cc),"delivered_choices":[r for r in lines(path/"llm_calls.jsonl") if r["record_type"]=="decision"]})
        assert summary["max_cash_conservation_error"]<1e-7
    battery=read(root/"battery.json") if (root/"battery.json").exists() else None;query=None;choices=[];auctions=[];frames=[];qrecords=[];ownchecks=0
    if battery:
        assert sha256(root/"battery.json")==read(root/"battery_seal.json")["sha256"]
        fresh=[f for e in entries for f in extract_frames(root/e["run_path"],e["seed"])]
        assert battery["frames"]==fresh;frames=battery["frames"]
        for f,control in zip(frames,battery["rule_controls"]):
            computed={n:settlements(f,rule_choices(f,n)) for n in NEWS}
            assert computed["silent"]==computed["positive"]==computed["negative"]==control["settlements"]
        q=root/"queries";verify_market(q);query=read(q/"summary.json");rr=lines(q/"llm_requests.jsonl");qcalls=[r for r in rr if r["record_type"]=="model_call"];calls+=qcalls;blocks += [r for r in rr if r["record_type"]=="request_blocked"]
        choices=read(q/"choices.json") if (q/"choices.json").exists() else [];auctions=read(q/"auctions.json") if (q/"auctions.json").exists() else [];qrecords=lines(q/"llm_calls.jsonl")
        assert len({r["study_call_id"] for r in qcalls})==len(qcalls)
        frameby={f["frame_id"]:f for f in frames};schedule={i["case_id"]:i for i in battery["schedule"]}
        for c in qcalls:
            f=frameby[c["frame_id"]];assert c["messages"][:2]==f["messages"][c["headline"]][c["agent_id"]]
            assert c["prompt_version"]==VERSION and c["condition"]=="A";ownchecks+=1
        bygroup={}
        for c in qcalls:bygroup.setdefault(c["study_request_group_id"],[]).append(c)
        for g in bygroup.values():
            assert len(g)<=2
            if len(g)==2:
                assert g[0]["status"]=="error" and g[0]["transport_retry_planned"]
                for key in ("messages","temperature","max_tokens","json_mode","reasoning_effort"):assert g[0][key]==g[1][key]
        bychoice={(c["case_id"],c["agent_id"]):c for c in choices};assert len(bychoice)==len(choices)
        for a in auctions:
            item=schedule[a["case_id"]];assert all(a[k]==item[k] for k in item)
            orders={aid:Order(**bychoice[a["case_id"],aid]["accepted"]) for aid in TARGETS}
            assert all(bychoice[a["case_id"],aid]["valid"] for aid in TARGETS)
            assert settlements(frameby[a["frame_id"]],orders)==a["settlements"]
    for c in calls:
        assert c["max_tokens"]==8192 and c["temperature_sent"]==.3 and c["reasoning_effort"]=="low"
        if c["status"]=="returned":assert c["response_metadata"]["model"]=="qwen-3.8-27b"
    measured=[];opportunities=[]
    for f in frames:
        for aid in TARGETS:
            obs=f["observations"][aid];price=f["previous_price"];band=f["market"]["price_band"];tick=f["market"]["tick"];tax=f["market"]["transaction_tax"]
            low=math.ceil(price*(1-band)/tick-1e-12)*tick
            opportunities.append(dict(frame_id=f["frame_id"],agent_id=aid,cash=obs["my_cash"],shares=obs["my_shares"],stock_weight=obs["my_shares"]*price/obs["my_wealth"],market_buy_capacity=math.floor(obs["my_cash"]/(price*(1+band)*(1+tax))+1e-12),best_band_buy_capacity=math.floor(obs["my_cash"]/(low*(1+tax))+1e-12)))
    for a in auctions:
        primary=a["settlements"][0];targets={}
        for aid in TARGETS:
            c=next(c for c in choices if c["case_id"]==a["case_id"] and c["agent_id"]==aid);t=primary["targets"][aid]
            signed=lambda order:order["quantity"]*(1 if order["side"]=="buy" else -1 if order["side"]=="sell" else 0)
            targets[aid]=dict(requested_signed=signed(c["intent"]),accepted_signed=signed(t["accepted"]),**t)
        measured.append({**{k:a[k] for k in ("case_id","frame_id","headline","repetition")},"targets":targets,"combined_executed_net":sum(t["executed_net"] for t in targets.values()),"price":primary["price"],"volume":primary["volume"],"fill_rate":primary["fill_rate"],"mm_volume_fraction":primary["mm_volume_fraction"],"settlement_groups":[dict(economic_factor=x["economic_factor"],groups=marks_groups(x)) for x in a["settlements"]]})
    contrasts=[]
    for seed in SEEDS:
        for rnd in SNAPSHOTS:
            fid=f"s{seed}_r{rnd}"
            for headline in ("positive","negative"):
                for rep in (1,2,3):
                    by={r["headline"]:r for r in measured if r["frame_id"]==fid and r["repetition"]==rep}
                    complete=headline in by and "silent" in by
                    value=None if not complete else by[headline]["combined_executed_net"]-by["silent"]["combined_executed_net"]
                    agents=None if not complete else {aid:{k:by[headline]["targets"][aid][k]-by["silent"]["targets"][aid][k] for k in ("requested_signed","accepted_signed","executed_net","executed_gross")} for aid in TARGETS}
                    contrasts.append(dict(frame_id=fid,headline=headline,repetition=rep,complete=complete,combined_executed_net=value,agents=agents,price_contrast=None if not complete else by[headline]["price"]-by["silent"]["price"]))
    actual_http=len(calls);reserved_only=sum(bool(r.get("attempts",[{}])[0].get("reservation")) for r in blocks)
    assert s["usage"]["requests_made"]==actual_http+reserved_only
    assert sum(c["usage"]["total_tokens"] for c in calls if c.get("usage") and c["usage"]["source"]=="provider")==s["usage"]["provider_reported_tokens"]
    complete_ids={r["case_id"] for r in auctions};uncleared=[c for c in choices if c["case_id"] not in complete_ids]
    missing_cases=[] if not battery else [i for i in battery["schedule"] if i["case_id"] not in complete_ids]
    report=dict(version="matched_news_auction_analysis_v1",protocol_sha256=sha256(root/"protocol.json"),summary=s,query_summary=query,sources=source,source_frames=len(frames),opportunities=opportunities,measured_auctions=measured,primary_contrasts=contrasts,
        query_choices=choices,uncleared_choices=uncleared,unsettled_cases=missing_cases,rule_controls=[] if not battery else battery["rule_controls"],
        audit=dict(actual_http_records=actual_http,reserved_only_blocked=reserved_only,query_actual_message_checks=ownchecks,source_snapshot_reconstruction=True if battery else "not_generated",source_outputs_hash_checked=True,settlements_recomputed=len(auctions)*3,failed_attempts=[{k:c.get(k) for k in ("agent_id","round","call_type","case_id","http_status","error_type","transport_attempt","transport_retry_planned")} for c in calls if c["status"]=="error"],finish_reasons=dict(Counter(c.get("response_metadata",{}).get("finish_reason") or "unknown" for c in calls))),
        estimand=p["primary"],limitations=p["limitations"],economics=p["economics"],rules=p["rules"])
    write_json(out/"report.json",report);shutil.copyfile(__file__,out/"analysis_source.py")
    text=["# R033: matched-state headline effects with real single-auction execution","",f"Status **{s['status']}**. Sources complete{s['completed_sources']}/2; joint auctions settled{s['completed_auctions']}/36. No replacement endpoint, model switch, old-frame substitution or unfilled partner treated as HOLD.","", "Four predetermined frames at rounds2/6 of two fresh quiet A histories; three fresh joint draws per headline. Both focal actors treated together. Background orders and captured allocation RNG held fixed. Actual production validation/clearing/settlement/payout functions used. This is a conditional immediate response, not36 independent sequential markets, an isolated trait test or human validation.","", "## Frozen primary: headline minus no headline","", "Net executed buy-minus-sell shares. Three entries are distinct fresh reply pairs on the same frame; reply sampling is unseeded. Missing comparisons stay missing. Every requested/accepted/executed choice, signed/gross and price/mark outcome is in report.json/raws.","", "|Frame|Headline|Combined net contrasts(three draws)|Meera net contrasts|Arjun net contrasts|", "|---|---|---|---|---|"]
    for seed in SEEDS:
        for rnd in SNAPSHOTS:
            fid=f"s{seed}_r{rnd}"
            for n in ("positive","negative"):
                rr=[r for r in contrasts if r["frame_id"]==fid and r["headline"]==n]
                vals=lambda aid: [None if not r["complete"] else r["agents"][aid]["executed_net"] for r in rr]
                text.append(f"|{fid}|{n}|{[r['combined_executed_net'] for r in rr]}|{vals('llm_012')}|{vals('llm_013')}|")
    if frames:
        fig,axes=plt.subplots(2,2,figsize=(11,8),layout="constrained")
        for ax,f in zip(axes.flat,frames):
            for j,(aid,n) in enumerate((a,n) for a in TARGETS for n in ("positive","negative")):
                rr=[r for r in contrasts if r["frame_id"]==f["frame_id"] and r["headline"]==n and r["complete"]]
                vv=[r["agents"][aid]["executed_net"] for r in rr];color="C2" if n=="positive" else "C3"
                if len(vv)==3:ax.bar(j,np.mean(vv),color=color,alpha=.25)
                ax.scatter([j+(r["repetition"]-2)*.09 for r in rr],vv,color=color,s=35)
                if len(vv)<3:ax.text(j,0,f"{len(vv)}/3",ha="center",va="bottom",fontsize=8)
            ax.set_title(f["frame_id"]);ax.set_xticks(range(4),["Meera +","Meera -","Arjun +","Arjun -"]);ax.axhline(0,color="black",lw=.6);ax.grid(axis="y",alpha=.2);ax.set_ylabel("Headline - silent net executed shares")
        fig.suptitle("Conditional single auctions: dots are reply draws, bars full three-draw means")
        fig.savefig(out/"headline_execution.png",dpi=180);fig.savefig(out/"headline_execution.pdf");plt.close(fig)
        text += ["", "![Headline effects](headline_execution.png)","", "Bars appear only for complete three-draw cells; dots are available contrasts, not independent market replications. Source histories/frames are correlated. No inferential significance or equivalence claim."]
    text += ["", "## What economic changes and rule controls mean","",p["economics"],"",p["rules"],"", "One-auction stay-put holds the SAME opening shares/cash, receives the same current payout and values at the same auction/private benchmark; its denominator is opening market wealth. It is not the original-lifetime passive account. All counterpart gains/losses are retained; aggregate excess cancels in this zero-tax closed-share economy. No risk-adjusted alpha, liquidation or welfare claim.","", "## Delivery, cost and missing evidence","",f"Budgeted requests{s['usage']['requests_made']}, actual completed HTTP records{actual_http}, reported tokens{s['usage']['provider_reported_tokens']}, conservative reservations{s['usage']['reserved_tokens']}, unknown usages{s['usage']['unknown_usage_requests']}, blocked{s['usage']['blocked_requests']}. No provider model seed/backend fingerprint available.","",f"Delivered conditional choices{len(choices)}; unsettled delivered choices{len(uncleared)}. Conditional trials are not attempted until both sources and all reconstruction/control gates pass. If sources stop before generation, no headline result exists; all primary cells remain missing.","",p["limitations"],"", "Interpret these results before any sequential extension or alternative background. Do not tune headline/persona words, exposure or order sizes to manufacture expected signs, or expand into A/B/C/provider grids automatically. Original A/B/C/defaults remain intact."]
    (out/"READOUT.md").write_text("\n".join(text)+"\n",encoding="utf-8");write_json(out/"artifact_manifest.json",{f.name:sha256(f) for f in out.iterdir() if f.is_file()})
    print(json.dumps(dict(output=str(out),summary=s,complete_contrasts=sum(c["complete"] for c in contrasts),uncleared_choices=len(uncleared),audit=report["audit"]),indent=2));return report

if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--study",required=True);parser.add_argument("--output",required=True);a=parser.parse_args();analyze(a.study,a.output)
