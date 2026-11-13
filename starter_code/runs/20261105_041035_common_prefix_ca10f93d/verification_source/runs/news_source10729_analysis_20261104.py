"""R035 phase audit; explicitly retains absent9623 and conditional-study limits."""
import argparse
from dataclasses import asdict
import json
import math
from pathlib import Path
import shutil
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sim.market import Order
from sim.provenance import sha256,write_json
from runs import news_source10729_20261104 as driver

def analyze(root,output):
    root=Path(root);out=Path(output);p=driver.validate(root);s=driver.read(root/"summary.json");assert s["status"]!="running";out.mkdir(exist_ok=False)
    old=driver.read(driver.PARENT/"summary.json");entries=driver.read(root/"source_runs.json") if (root/"source_runs.json").exists() else []
    assert {(root/e["run_path"]).resolve() for e in entries}=={x.resolve() for x in (root/"source_runs").glob("*") if x.is_dir()},"Unindexed source must not be omitted"
    calls=[];blocked=[];sources=[];b=None;frames=[];choices=[];auctions=[];query=None;prompt_checks=0
    for e in entries:
        path=root/e["run_path"];driver.parent.verify_market(path);assert sha256(path/"manifest.json")==e["manifest_sha256"]
        rs=driver.parent.lines(path/"llm_requests.jsonl");calls += [r for r in rs if r["record_type"]=="model_call"];blocked += [r for r in rs if r["record_type"]=="request_blocked"]
        ss=driver.read(path/"summary.json");assert ss["max_cash_conservation_error"]<1e-7
        sources.append({**e,"summary":ss,"decisions":[r for r in driver.parent.lines(path/"llm_calls.jsonl") if r["record_type"]=="decision"]})
    if (root/"battery.json").exists():
        b=driver.read(root/"battery.json");assert sha256(root/"battery.json")==driver.read(root/"battery_seal.json")["sha256"]
        frames=[f for e in entries for f in driver.parent.extract_frames(root/e["run_path"],e["seed"])];assert frames==b["frames"]
        assert len(frames)==2 and all(f["seed"]==10729 for f in frames) and len(b["schedule"])==18
        for f,c in zip(frames,b["rule_controls"]):
            controls={n:driver.parent.settlements(f,driver.parent.rule_choices(f,n)) for n in driver.parent.NEWS}
            assert controls["silent"]==controls["positive"]==controls["negative"]==c["settlements"]
        q=root/"queries";driver.parent.verify_market(q);query=driver.read(q/"summary.json")
        choices=driver.read(q/"choices.json") if (q/"choices.json").exists() else [];auctions=driver.read(q/"auctions.json") if (q/"auctions.json").exists() else []
        rs=driver.parent.lines(q/"llm_requests.jsonl");qc=[r for r in rs if r["record_type"]=="model_call"];calls+=qc;blocked += [r for r in rs if r["record_type"]=="request_blocked"]
        assert len({r["study_call_id"] for r in qc})==len(qc)
        fb={f["frame_id"]:f for f in frames};schedule={i["case_id"]:i for i in b["schedule"]};bychoice={(c["case_id"],c["agent_id"]):c for c in choices};assert len(bychoice)==len(choices)
        groups={}
        for r in qc:
            assert r["messages"][:2]==fb[r["frame_id"]]["messages"][r["headline"]][r["agent_id"]] and r["prompt_version"]==driver.parent.VERSION and r["phase_version"]==driver.VERSION
            groups.setdefault(r["study_request_group_id"],[]).append(r);prompt_checks+=1
        for group in groups.values():
            assert len(group)<=2
            if len(group)==2:
                assert group[0]["status"]=="error" and group[0]["transport_retry_planned"]
                for k in ("messages","temperature","max_tokens","json_mode","reasoning_effort"):assert group[0][k]==group[1][k]
        for a in auctions:
            assert all(a[k]==v for k,v in schedule[a["case_id"]].items())
            orders={aid:Order(**bychoice[a["case_id"],aid]["accepted"]) for aid in driver.parent.TARGETS}
            assert all(bychoice[a["case_id"],aid]["valid"] for aid in orders)
            assert driver.parent.settlements(fb[a["frame_id"]],orders)==a["settlements"]
    for r in calls:
        assert r["max_tokens"]==8192 and r["temperature_sent"]==.3 and r["reasoning_effort"]=="low"
        if r["status"]=="returned":assert r["response_metadata"]["model"]=="qwen-3.8-27b"
    reserved_only=sum(bool(r.get("attempts",[{}])[0].get("reservation")) for r in blocked)
    assert s["usage"]["requests_made"]==len(calls)+reserved_only
    assert s["usage"]["provider_reported_tokens"]==sum(r["usage"]["total_tokens"] for r in calls if r.get("usage") and r["usage"]["source"]=="provider")
    assert s["cumulative_usage"]=={k:s["usage"][k]+old["usage"][k] for k in driver.parent.USAGE}
    opportunities=[];rows=[]
    for f in frames:
        for aid in driver.parent.TARGETS:
            obs=f["observations"][aid];price=f["previous_price"];tax=f["market"]["transaction_tax"];band=f["market"]["price_band"];tick=f["market"]["tick"];low=math.ceil(price*(1-band)/tick-1e-12)*tick
            opportunities.append(dict(frame_id=f["frame_id"],agent_id=aid,cash=obs["my_cash"],shares=obs["my_shares"],stock_weight=obs["my_shares"]*price/obs["my_wealth"],market_buy_capacity=math.floor(obs["my_cash"]/(price*(1+band)*(1+tax))+1e-12),best_band_buy_capacity=math.floor(obs["my_cash"]/(low*(1+tax))+1e-12)))
    for a in auctions:
        first=a["settlements"][0];targets={}
        for aid in driver.parent.TARGETS:
            c=next(c for c in choices if c["case_id"]==a["case_id"] and c["agent_id"]==aid);t=first["targets"][aid]
            signed=lambda o:o["quantity"]*(1 if o["side"]=="buy" else -1 if o["side"]=="sell" else 0)
            targets[aid]={**t,"requested_signed":signed(c["intent"]),"accepted_signed":signed(t["accepted"])}
        rows.append({**{k:a[k] for k in ("case_id","frame_id","headline","repetition")},"targets":targets,"combined_executed_net":sum(t["executed_net"] for t in targets.values()),"price":first["price"],"volume":first["volume"],"fill_rate":first["fill_rate"],"mm_fraction":first["mm_volume_fraction"]})
    contrasts=[]
    for seed in (9623,10729):
        for rnd in (2,6):
            fid=f"s{seed}_r{rnd}"
            for news in ("positive","negative"):
                for rep in (1,2,3):
                    by={r["headline"]:r for r in rows if r["frame_id"]==fid and r["repetition"]==rep};complete=news in by and "silent" in by
                    agents=None if not complete else {aid:{k:by[news]["targets"][aid][k]-by["silent"]["targets"][aid][k] for k in ("requested_signed","accepted_signed","executed_net","executed_gross")} for aid in driver.parent.TARGETS}
                    contrasts.append(dict(frame_id=fid,headline=news,repetition=rep,complete=complete,agents=agents,combined_executed_net=None if not complete else by[news]["combined_executed_net"]-by["silent"]["combined_executed_net"],price_contrast=None if not complete else by[news]["price"]-by["silent"]["price"]))
    settled_ids={a["case_id"] for a in auctions};uncleared=[c for c in choices if c["case_id"] not in settled_ids]
    report=dict(version="news10729_phase_audit_v1",summary=s,query_summary=query,sources=sources,source_frames=frames,opportunities=opportunities,choices=choices,auctions=auctions,measured_auctions=rows,contrasts=contrasts,uncleared_choices=uncleared,parent_missing_source9623=True,
        audit=dict(source_output_hashes=True,source_history_and_original_auction_replay=bool(frames),query_exact_message_checks=prompt_checks,recomputed_settlement_variants=len(auctions)*3,http_records=len(calls),reserved_only_blocked=reserved_only,parent_inventory_unchanged=True,errors=[{k:r.get(k) for k in ("agent_id","round","case_id","error_type","http_status","transport_attempt","transport_retry_planned")} for r in calls if r["status"]=="error"]),limitations=p["limitations"],protocol_sha256=sha256(root/"protocol.json"))
    write_json(out/"report.json",report);shutil.copyfile(__file__,out/"analysis_source.py")
    text=["# R035: previously untouched source10729, linked independent-source gate","",f"Phase status **{s['status']}**; source completed{s['completed_sources']}/1; conditional auctions settled{s['completed_auctions']}/18. Original planned study remains{s['completed_sources']}/2 histories and{s['completed_auctions']}/36 auctions: failed9623 remains missing. No restart, substituted frame or historical-response reuse.","", "One fresh6-round quiet A history with predefined frames2/6, three fresh joint reply draws/headline. Same opening states/12 background tapes/captured RNG within frame, both focal actors treated together. Original Qwen8192/low/temp.3/common-hidden A variant. This is a single-history conditional one-auction pilot, not independent full-market replication or continuation of the old4096/shown-length query sample.","", "## Frozen headline-minus-silent executed signed shares","", "Three entries are fresh reply pairs on identical input states, not three independently generated market histories. Missing cells stay missing; no inferential/equivalence/general human/news-sign claim.","", "|Frame|News|Combined contrasts(3 draws)|Meera contrasts|Arjun contrasts|", "|---|---|---|---|---|"]
    for seed in (9623,10729):
        for rnd in (2,6):
            fid=f"s{seed}_r{rnd}"
            for n in ("positive","negative"):
                rr=[r for r in contrasts if r["frame_id"]==fid and r["headline"]==n];vv=lambda aid:[None if not r["complete"] else r["agents"][aid]["executed_net"] for r in rr]
                text.append(f"|{fid}|{n}|{[r['combined_executed_net'] for r in rr]}|{vv('llm_012')}|{vv('llm_013')}|")
    if frames:
        fig,axes=plt.subplots(1,2,figsize=(11,4),layout="constrained")
        for ax,f in zip(axes,frames):
            for j,(aid,n) in enumerate((a,n) for a in driver.parent.TARGETS for n in ("positive","negative")):
                rr=[r for r in contrasts if r["frame_id"]==f["frame_id"] and r["headline"]==n and r["complete"]];values=[r["agents"][aid]["executed_net"] for r in rr];color="C2" if n=="positive" else "C3"
                if len(values)==3:ax.bar(j,np.mean(values),color=color,alpha=.25)
                ax.scatter([j+(r["repetition"]-2)*.08 for r in rr],values,color=color,s=30)
                if len(values)<3:ax.text(j,0,f"{len(values)}/3",ha="center",fontsize=8)
            ax.set_title(f["frame_id"]);ax.set_xticks(range(4),["Meera +","Meera -","Arjun +","Arjun -"]);ax.axhline(0,color="black",lw=.5);ax.grid(axis="y",alpha=.2);ax.set_ylabel("Headline - silent executed net shares")
        fig.suptitle("One fresh history / two correlated frames: no full-market/human validation")
        fig.savefig(out/"headline_execution.png",dpi=180);fig.savefig(out/"headline_execution.pdf");plt.close(fig)
        text += ["", "![Conditional execution](headline_execution.png)","", "Dots are fresh response-pair contrasts; bars only complete3-draw means. Both frames derive from ONE history."]
    text += ["", "## Economics, controls and accounting","",p["economics"],"",p["rules"],"", "All actual conditional orders/fills/quotes/prices/MM/counterpart accounts and BOTH one-auction stay-put marks are in report.json/queries/auctions.json. Missing partner choices are never settled. The auction-mark wealth difference is income/exposure accounting, not immediate trading skill; private benchmark marks are not executable prices.","", "## Delivery and scope","",f"This phase:{s['usage']}. Including preserved R033 failures:{s['cumulative_usage']}. Parent budget/failures/source files stay unchanged; only independent-source gating was amended. Backend/model sampling seed unavailable. No data/financial-sign selection or new default.","",f"Unsettled delivered query choices:{len(uncleared)}. If source generation fails, no fresh frame or headline outcome exists. Failed9623's original18 auctions remain unattempted regardless of this phase's outcome.","",p["limitations"],"", "No further seed/provider/recovery phase is automatic. Interpret outcomes and limitations before a new scientific design; do not retry until the expected sign appears."]
    (out/"READOUT.md").write_text("\n".join(text)+"\n",encoding="utf-8");write_json(out/"artifact_manifest.json",{x.name:sha256(x) for x in out.iterdir() if x.is_file()})
    print(json.dumps(dict(output=str(out),summary=s,complete_directional_contrasts=sum(r["complete"] for r in contrasts),audit=report["audit"]),indent=2));return report

if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--study",required=True);parser.add_argument("--output",required=True);a=parser.parse_args();analyze(a.study,a.output)
