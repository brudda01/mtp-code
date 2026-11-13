"""R041 terminal audit: preserve nested repeats, censoring and all signs."""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import shutil
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sim.config import load_config
from sim.evaluation import evaluate_run,read_rows
from sim.provenance import sha256,write_json
from runs import downside_confirmation_20261104 as d
from runs.initial_news_analysis_20261104 import trading,account_reconstruction,grouped_accounts


def initial_checks(root,arms):
    count=0;background_count=0
    for seed in d.SEEDS:
        selected=[a for a in arms if a["seed"]==seed]
        if not selected:continue
        reference=root/selected[0]["run_path"];anchor={};books=[]
        for a in selected:
            path=root/a["run_path"]
            assert d.base.resources(path)==d.base.resources(reference) and d.read(path/"personas.json")==d.read(reference/"personas.json")
            for aid,messages in a["first_messages"].items():
                system,user=messages;content=user["content"]
                if a["visible"]:
                    assert content.count("News today: "+d.HEADLINE+"\n")==1
                    content=content.replace("News today: "+d.HEADLINE+"\n","",1)
                else:assert d.HEADLINE not in content
                if aid in anchor:assert (system,content)==anchor[aid]
                else:anchor[aid]=(system,content)
                count+=1
            if a["prices"]:
                books.append([x for x in read_rows(path/"orders.csv") if x["round"]=="1" and x["agent_id"] not in d.TARGETS]);background_count+=1
        if books:assert all(x==books[0] for x in books)
    return dict(initial_messages_checked=count,available_first_background_books_checked=background_count)


def analyze(root,output):
    root=Path(root);out=Path(output);p=d.validate(root);summary=d.read(root/"summary.json")
    assert summary["status"]!="running";out.mkdir(exist_ok=False)
    baselines=d.read(root/"baseline_runs.json");d.baseline_gates(root,baselines);base=[];arms=[];all_calls=[];blocked=[];history_checks=0
    for e in baselines:
        path=root/e["run_path"];d.base.verify_market(path);assert sha256(path/"manifest.json")==e["manifest_sha256"]
        ev=evaluate_run(path);base.append({**e,"evaluation":ev,"groups":grouped_accounts(ev),"account_reconstruction":account_reconstruction(path,load_config(path/"config.yaml"))})
    index=d.read(root/"runs.json") if (root/"runs.json").exists() else []
    assert {(root/e["run_path"]).resolve() for e in index}=={x.resolve() for x in (root/"market_runs").glob("*") if x.is_dir()},"Unindexed market cannot be omitted"
    for e in index:
        path=root/e["run_path"];manifest=d.base.verify_market(path);assert sha256(path/"manifest.json")==e["manifest_sha256"] and manifest["research_adapter"]["version"]==d.VERSION
        cfg=load_config(path/"config.yaml");ss=d.read(path/"summary.json");prices=read_rows(path/"prices.csv");outcomes=d.base.lines(path/"agent_outcomes.jsonl")
        records=d.base.lines(path/"llm_requests.jsonl");calls=[x for x in records if x["record_type"]=="model_call"];all_calls+=calls;blocked += [x for x in records if x["record_type"]=="request_blocked"]
        groups=defaultdict(list);first={}
        for c in calls:
            groups[c["request_group_id"]].append(c)
            assert c["call_type"]=="decision" and c["max_tokens"]==8192 and c["temperature_sent"]==.3 and c["reasoning_effort"]=="low" and c["prompt_version"]==d.VERSION
            if c["status"]=="returned":assert c["response_metadata"]["model"]=="qwen-3.8-27b"
            user=c["messages"][1]["content"];assert user.startswith(f"Round {c['round']}.")
            assert ("Initialization references:" in user)==(c["round"]==1)
            if c["round"]==1 and c["json_attempt"]==c["transport_attempt"]==1:first[c["agent_id"]]=c["messages"]
            memory=json.loads(user.split("Your recent verified outcomes: ",1)[1].split("\nDecide your order",1)[0])
            actual=[r["outcome"] for r in outcomes if r["agent_id"]==c["agent_id"] and r["outcome"]["round"]<c["round"]][-5:]
            assert memory==actual;history_checks+=1
        for g in groups.values():
            assert len(g)<=2
            if len(g)==2:
                assert g[0]["status"]=="error" and g[0]["transport_retry_planned"]
                for key in ("messages","temperature","max_tokens","reasoning_effort","json_mode"):assert g[0][key]==g[1][key]
        ref=root/next(x["run_path"] for x in baselines if (x["seed"],x["background"],x["visible"])==(e["seed"],e["background"],e["visible"]))
        assert d.base.resources(path)==d.base.resources(ref) and ss["max_cash_conservation_error"]<1e-7
        assert [x["dividend"] for x in prices]==[x["dividend"] for x in read_rows(ref/"prices.csv")[:len(prices)]]
        ev=evaluate_run(path) if prices else None
        if ev:
            states=read_rows(path/"agents_state.csv");assert all(float(x["cash"])>=-1e-7 and int(x["shares"])>=0 for x in states)
            assert all(sum(int(x["shares"]) for x in states if int(x["round"])==rnd)==1450 for rnd in range(1,len(prices)+1))
            assert 0<=ev["metrics"]["mm_inventory_min"]<=ev["metrics"]["mm_inventory_max"]<=300
        rr,early,first_auction,uncleared=trading(path,cfg,live=True)
        clean=ss["status"]=="completed" and ss["rounds"]==8 and not any(e["operational_failures"].values())
        arms.append({**e,"summary":ss,"prices":prices,"first_messages":first,"trading":rr,"early3":early,"first_auction":first_auction,"uncleared_choices":uncleared,
                     "full_clean":clean,"full_horizon_evaluation":ev if clean else None,"observed_prefix_evaluation":ev,"observed_prefix_groups":None if not ev else grouped_accounts(ev),"account_reconstruction":account_reconstruction(path,cfg)})
    controls=initial_checks(root,arms);contrasts=[]
    for seed in d.SEEDS:
        for rep in (1,2):
            for background in ("original","no_skew"):
                by={a["visible"]:a for a in arms if (a["seed"],a["repetition"],a["background"])==(seed,rep,background)};a,b=by.get(True),by.get(False)
                early=bool(a and b and a["early3"] is not None and b["early3"] is not None);full=bool(a and b and a["full_clean"] and b["full_clean"])
                actors=None if not early else {aid:{k:a["early3"][aid][k]-b["early3"][aid][k] for k in ("requested_signed","accepted_signed","executed_net","executed_gross")} for aid in d.TARGETS}
                marks=None
                if full:
                    aa={x["agent_id"]:x for x in a["full_horizon_evaluation"]["accounts"]};bb={x["agent_id"]:x for x in b["full_horizon_evaluation"]["accounts"]}
                    marks={aid:{m:aa[aid]["marks"][m]["excess_return"]-bb[aid]["marks"][m]["excess_return"] for m in ("auction","regime_benchmark")} for aid in d.TARGETS}
                contrasts.append(dict(seed=seed,repetition=rep,background=background,early3_available=early,actors=actors,combined_executed=None if not early else sum(x["executed_net"] for x in actors.values()),full8_available=full,
                    terminal_price_contrast=None if not full else float(a["prices"][-1]["price"])-float(b["prices"][-1]["price"]),mean_gap_contrast=None if not full else a["full_horizon_evaluation"]["metrics"]["mean_absolute_relative_gap"]-b["full_horizon_evaluation"]["metrics"]["mean_absolute_relative_gap"],passive_excess_contrasts=marks))
    sensitivities=[]
    for seed in d.SEEDS:
        for rep in (1,2):
            c={x["background"]:x for x in contrasts if (x["seed"],x["repetition"])==(seed,rep)};a,b=c["no_skew"],c["original"];available=a["early3_available"] and b["early3_available"]
            sensitivities.append(dict(seed=seed,repetition=rep,available=available,combined_response_difference=None if not available else a["combined_executed"]-b["combined_executed"],actor_response_difference=None if not available else {aid:a["actors"][aid]["executed_net"]-b["actors"][aid]["executed_net"] for aid in d.TARGETS}))
    usage=summary["usage"];reserved_only=sum(bool(x.get("attempts",[{}])[0].get("reservation")) for x in blocked)
    assert usage["requests_made"]==len(all_calls)+reserved_only
    assert usage["provider_reported_tokens"]==sum(x["usage"]["total_tokens"] for x in all_calls if x.get("usage") and x["usage"]["source"]=="provider")
    planned=[a for b in p["blocks"] for a in b["arms"]]
    unattempted=[a for a in planned if not any((x["seed"],x["repetition"],x["background"],x["visible"])==(a["seed"],a["repetition"],a["background"],a["visible"]) for x in arms)]
    report=dict(version="downside_repeated_audit_v1",protocol_sha256=sha256(root/"protocol.json"),summary=summary,baselines=base,arms=arms,headline_contrasts=contrasts,background_response_differences=sensitivities,unattempted=unattempted,
        audit=dict(**controls,actual_history_request_checks=history_checks,http_records=len(all_calls),reserved_only_blocked=reserved_only,rule_and_raw_hashes_verified=True,errors=[{k:x.get(k) for k in ("agent_id","round","error_type","http_status","transport_attempt","transport_retry_planned")} for x in all_calls if x["status"]=="error"],json_repair_attempts=sum(x["json_attempt"]>1 and x["transport_attempt"]==1 for x in all_calls)),limitations=p["limitations"])
    write_json(out/"report.json",report);shutil.copyfile(__file__,out/"analysis_source.py");render(out,report)
    write_json(out/"artifact_manifest.json",{x.name:sha256(x) for x in out.iterdir() if x.is_file()})
    print(json.dumps(dict(output=str(out),summary=summary,headline_contrasts=contrasts,background_response_differences=sensitivities,audit=report["audit"]),indent=2));return report


def render(out,report):
    summary=report["summary"];text=["# R041: repeated downside-news / market-background confirmation","",f"Status:{summary['status']};{summary['completed_markets']}/16 clean full8 paths,{summary['recorded_markets']} attempted,{len(report['unattempted'])} unattempted. All missing/uncleared/failed prefixes retained.","", "Two fresh exogenous histories x2 new unseeded model repetitions x2 MM backgrounds xvisible/silent genuine one-time initial dividend-level fall. Repeats nest in two histories,not four independent seeds or sixteen independent treatment replications. Natural initial portfolios/personas/background books match; later feedback/provider draws differ. New clarified candidate passed an EXPLICIT reading check; natural-trading understanding is not guaranteed. No pooling with older ambiguous-wording studies,preferred sign,default selection or human/long-run/trait/model-superiority claim.","", "## Frozen primary: visible minus silent signed EXECUTED shares, rounds1-3","", "Triples are requested / accepted / filled contrasts. Positive can mean more buying or less selling. Repeated requests/offers are not distinct shares. Early3 requires three valid cleared rounds in both arms; full8 endpoints require clean complete paths. A later stop does not erase an observed early endpoint; service censoring remains a limitation.","", "|Seed|Repeat|MM background|Meera requested/accepted/filled|Arjun requested/accepted/filled|Combined filled|","|---|---|---|---|---|---:|"]
    for c in report["headline_contrasts"]:
        fmt=lambda aid:"missing" if not c["early3_available"] else "/".join(str(c["actors"][aid][k]) for k in ("requested_signed","accepted_signed","executed_net"))
        text.append(f"|{c['seed']}|{c['repetition']}|{c['background']}|{fmt('llm_012')}|{fmt('llm_013')}|{c['combined_executed']}|")
    text += ["", "## Secondary: no-skew response minus original-background response", "", "Difference of the two descriptive headline contrasts; provider noise and endogenous paths remain. No inferential confidence interval or background-invariant response claim.","", "|Seed|Repeat|Combined filled response difference|Meera / Arjun difference|","|---|---|---:|---|"]
    for c in report["background_response_differences"]:
        actors="missing" if not c["available"] else "/".join(str(c["actor_response_difference"][aid]) for aid in d.TARGETS)
        text.append(f"|{c['seed']}|{c['repetition']}|{c['combined_response_difference']}|{actors}|")
    text += ["", "## Full8 secondary headline contrasts", "", "Excess differences use common initial market wealth; both conditional passive marks. No liquidation,risk-adjusted alpha or equilibrium no-trading counterfactual. Private mean/r benchmark is an internal risk-neutral reference,not human pricing accuracy.","", "|Seed|Repeat|Background|Close difference|Mean gap difference pp|Meera auction/benchmark pp|Arjun auction/benchmark pp|","|---|---|---|---:|---:|---|---|"]
    for c in report["headline_contrasts"]:
        fmt=lambda aid:"missing" if not c["full8_available"] else "/".join(f"{100*c['passive_excess_contrasts'][aid][m]:.3f}" for m in ("auction","regime_benchmark"))
        gap="missing" if not c["full8_available"] else f"{100*c['mean_gap_contrast']:.3f}"
        text.append(f"|{c['seed']}|{c['repetition']}|{c['background']}|{c['terminal_price_contrast']}|{gap}|{fmt('llm_012')}|{fmt('llm_013')}|")
    text += ["", "![All attempted paired price paths](paired_paths.png)","", f"Usage:{summary['usage']}. Audit:{report['audit']}.","", "All actor per-round limits/headroom/exposure/requested/accepted/buy/sell/gross/net executions,first auction,counterpart groups,baseline evaluations,passive marks,observed prefixes and unattempted slots remain in report.json. Full accounts reconstruct independently from trades/interest/dividends. Eight-round market paths are response studies,not long-run stylized-fact evidence. F/M controls ignore headlines; equal resources do not equate sizing or prove intrinsic LLM superiority. Only truthful downside forecasts studied; no inference about misleading news,all signs or trust calibration. A/B/C/defaults unchanged. See protocol for source/profile/failure seals."]
    (out/"READOUT.md").write_text("\n".join(text)+"\n",encoding="utf-8")
    fig,axes=plt.subplots(4,2,figsize=(11,12),layout="constrained")
    for row,(seed,rep) in enumerate((s,r) for s in d.SEEDS for r in (1,2)):
        for col,background in enumerate(("original","no_skew")):
            ax=axes[row,col];ax.step([0,1,8],[100,80,80],where="post",color="black",ls="--",label="Private shifted benchmark")
            arms=[a for a in report["arms"] if (a["seed"],a["repetition"],a["background"])==(seed,rep,background)]
            for a in arms:
                pp=a["prices"];ax.plot([0]+[int(x["round"]) for x in pp],[100]+[float(x["price"]) for x in pp],color="C1" if a["visible"] else "C0",marker=".",label=f"{'visible' if a['visible'] else 'silent'} ({len(pp)}/8)")
            if not arms:ax.text(.5,.5,"Not attempted",transform=ax.transAxes,ha="center")
            ax.set(title=f"{seed},repeat{rep},{background}",xlabel="Auction round",ylabel="Closing price",xlim=(0,8));ax.grid(alpha=.2);ax.legend(fontsize=7)
    fig.suptitle("Fresh downside response: two scenarios,two model repeats; no path selection")
    fig.savefig(out/"paired_paths.png",dpi=160);fig.savefig(out/"paired_paths.pdf");plt.close(fig)


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--study",required=True);parser.add_argument("--output",required=True);args=parser.parse_args();analyze(args.study,args.output)
