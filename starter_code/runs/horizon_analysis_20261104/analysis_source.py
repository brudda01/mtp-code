"""Audit R032 after termination; missing planned endpoints stay missing."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import zipfile
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sim.config import load_config
from sim.evaluation import evaluate_run,read_rows
from sim.news_pilot import market_metrics
from sim.provenance import sha256,write_json
from sim.sequential_markets import resources,verify_market
from runs.horizon_pilot_20261104 import BASE,SEEDS,USAGE,VERSION,validate,read


def lines(path):return [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines()]


def group_marks(ev):
    groups={g:dict(agents=0,initial_market_wealth=0,auction=0,regime_benchmark=0) for g in ("targets","market_maker","other_traders")}
    for a in ev["accounts"]:
        key="targets" if int(a["agent_id"].rsplit("_",1)[1]) in (12,13) else "market_maker" if a["type"]=="MarketMakerAgent" else "other_traders"
        g=groups[key];g["agents"]+=1;g["initial_market_wealth"]+=a["initial_market_wealth"]
        for mark in ("auction","regime_benchmark"):g[mark]+=a["marks"][mark]["active_minus_passive"]
    assert all(abs(sum(g[m] for g in groups.values()))<1e-7 for m in ("auction","regime_benchmark"))
    return groups


def audit_source(path):
    m=verify_market(path)
    with zipfile.ZipFile(path/"source.zip") as z:
        assert all(hashlib.sha256(z.read(n)).hexdigest()==d for n,d in m["source_sha256"].items())
    return m


def analyze(root,output):
    root=Path(root);output=Path(output);p=validate(root);summary=read(root/"summary.json")
    assert summary["status"] in ("completed","completed_with_missing","stopped","failed","interrupted")
    output.mkdir(exist_ok=False);refs=read(root/"baseline_runs.json");baseline=[];arms=[];requests=[];common_personas={};first={};all_outcome_checks=0
    for e in refs:
        path=root/e["run_path"];audit_source(path);assert sha256(path/"manifest.json")==e["manifest_sha256"]
        mt=market_metrics(path);baseline.append({**e,"evaluation":mt["evaluation"],"event_metrics":mt["event_metrics"],"target_rounds":mt["target_rounds"]})
    index=read(root/"runs.json") if (root/"runs.json").exists() else []
    actual_paths={x.resolve() for x in (root/"market_runs").glob("*") if x.is_dir()}
    assert actual_paths=={(root/e["run_path"]).resolve() for e in index},"Unindexed raw run exists: inspect it rather than omit evidence"
    for e in index:
        path=root/e["run_path"];m=audit_source(path);assert sha256(path/"manifest.json")==e["manifest_sha256"]
        assert m["research_adapter"]["driver_sha256"]==p["driver_sha256"] and m["research_adapter"]["visibility"]==e["visibility"]
        s=read(path/"summary.json");cfg=load_config(path/"config.yaml");prices=read_rows(path/"prices.csv")
        reference=root/next(r["run_path"] for r in refs if r["seed"]==e["seed"] and r["cell"]=="shock")
        assert resources(path)==resources(reference)
        assert [r["dividend"] for r in prices]==[r["dividend"] for r in read_rows(reference/"prices.csv")[:len(prices)]]
        personas=read(path/"personas.json");assert personas==common_personas.setdefault(e["seed"],personas)
        calls=[r for r in lines(path/"llm_requests.jsonl") if r["record_type"]=="model_call"];requests+=calls
        records=lines(path/"llm_calls.jsonl");outcomes=lines(path/"agent_outcomes.jsonl")
        assert len(calls)==s["llm_usage"]["requests_made"] and len({r["call_id"] for r in calls})==len(calls)
        for call in calls:
            assert call["call_type"]=="decision" and call["max_tokens"]==8192 and call["temperature_sent"]==.3 and call["reasoning_effort"]=="low"
            assert call["base_prompt_version"]=="simple_A_v2" and call["research_adapter_version"]==VERSION and call["horizon_visibility"]==e["visibility"]
            if call["status"]=="returned":assert call["response_metadata"]["model"]=="qwen-3.8-27b"
            user=call["messages"][1]["content"];rnd=call["round"]
            prefix=f"Round {rnd}/24." if e["visibility"]=="shown" else f"Round {rnd}."
            assert user.startswith(prefix) and "The stock continues beyond the recorded episode" in call["messages"][0]["content"]
            memory=json.loads(user.split("Your recent verified outcomes: ",1)[1].split("\nDecide your order",1)[0])
            actual=[r["outcome"] for r in outcomes if r["agent_id"]==call["agent_id"] and r["outcome"]["round"]<rnd][-5:]
            assert memory==actual;all_outcome_checks+=1
            if rnd==1 and call["json_attempt"]==1 and call["transport_attempt"]==1:first[e["seed"],e["visibility"],call["agent_id"]]=call["messages"]
        bygroup={}
        for call in calls:bygroup.setdefault(call["request_group_id"],[]).append(call)
        for group in bygroup.values():
            assert len(group)<=2
            if len(group)==2:
                assert group[0]["status"]=="error" and group[0]["transport_retry_planned"]
                for key in ("messages","temperature","max_tokens","reasoning_effort","json_mode"):assert group[0][key]==group[1][key]
        ev=evaluate_run(path) if prices else None
        mt=market_metrics(path) if len(prices)>=11 else None
        if ev:
            states=read_rows(path/"agents_state.csv")
            assert s["max_cash_conservation_error"]<1e-7 and all(float(r["cash"])>=-1e-7 and int(r["shares"])>=0 for r in states)
            assert all(sum(int(r["shares"]) for r in states if int(r["round"])==i)==1450 for i in range(1,len(prices)+1))
            assert 0<=ev["metrics"]["mm_inventory_min"]<=ev["metrics"]["mm_inventory_max"]<=300
            assert all(abs(v)<1e-7 for v in ev["aggregate_active_minus_passive"].values())
        else:states=[]
        targets={};headroom=[]
        for aid in personas:
            rows=[] if mt is None else [r for r in mt["target_rounds"] if r["agent_id"]==aid]
            late=[r for r in rows if 22<=r["round"]<=24];complete=s["rounds"]==24 and s["status"]=="completed" and not any(e["operational_failures"].values())
            primary=None if not complete else dict(executed_buy=sum(r["executed_buy"] for r in late),executed_sell=sum(r["executed_sell"] for r in late),net=sum(r["executed_signed"] for r in late),gross=sum(r["executed_buy"]+r["executed_sell"] for r in late))
            if primary is not None:
                holdings={int(r["round"]):int(r["shares"]) for r in states if r["agent_id"]==aid}
                assert primary["net"]==holdings[24]-holdings[21]
            tradeperiod={}
            for label,predicate in (("pre",lambda r:r["round"]<11),("post",lambda r:r["round"]>=11),("last3",lambda r:22<=r["round"]<=24)):
                rr=[r for r in rows if predicate(r)];accepted=sum(r["accepted_quantity"] for r in rr);filled=sum(r["executed_buy"]+r["executed_sell"] for r in rr)
                tradeperiod[label]=dict(requested_signed=sum(r["requested_signed"] for r in rr if r["requested_signed"] is not None),requested_gross=sum(abs(r["requested_signed"]) for r in rr if r["requested_signed"] is not None),accepted_signed=sum(r["accepted_signed"] for r in rr if r["accepted_signed"] is not None),accepted_gross=accepted,executed_net=sum(r["executed_signed"] for r in rr),executed_gross=filled,fill_fraction=None if not accepted else filled/accepted)
            marks=None if ev is None else next(a["marks"] for a in ev["accounts"] if a["agent_id"]==aid)
            own=[r for r in records if r["record_type"]=="decision" and r["agent_id"]==aid and r["round"]>=22]
            targets[aid]=dict(name=personas[aid]["name"],primary_last3=primary,trading=tradeperiod,terminal_marks=marks,last3_decisions=own)
            for at in (10,21):
                rowsat=[r for r in states if int(r["round"])==at and r["agent_id"]==aid]
                if not rowsat:continue
                state=rowsat[0];price=float(prices[at-1]["price"]);cash=float(state["cash"]);shares=int(state["shares"])
                low=math.ceil(price*(1-cfg.market.price_band)/cfg.market.tick-1e-12)*cfg.market.tick
                headroom.append(dict(agent_id=aid,after_round=at,cash=cash,shares=shares,stock_weight=shares*price/float(state["wealth"]),best_band_limit_buy_capacity=math.floor(cash/(low*(1+cfg.market.transaction_tax))+1e-12),market_buy_capacity=math.floor(cash/(price*(1+cfg.market.price_band)*(1+cfg.market.transaction_tax))+1e-12)))
        uncleared=[r for r in records if r["record_type"]=="decision" and r["round"]>s["rounds"]]
        tail=np.asarray([float(r["price"]) for r in prices[20:24]])
        drawdown=None if len(prices)<24 else float(np.max(1-tail/np.maximum.accumulate(tail)))
        arms.append({**e,"summary":s,"market_metrics":None if ev is None else ev["metrics"],"population_marks":None if ev is None else group_marks(ev),"targets":targets,"headroom":headroom,"event_metrics":None if mt is None else mt["event_metrics"],"target_rounds":[] if mt is None else mt["target_rounds"],"uncleared_decisions":uncleared,"price_path":prices,
            "primary_combined_last3_net":None if any(t["primary_last3"] is None for t in targets.values()) else sum(t["primary_last3"]["net"] for t in targets.values()),
            "last3_price_return":None if len(prices)<24 else float(prices[23]["price"])/float(prices[20]["price"])-1,"last3_max_drawdown_from_round21":drawdown})
    first_pairs=0
    for seed in SEEDS:
        for aid in ("llm_012","llm_013"):
            if (seed,"shown",aid) in first and (seed,"hidden",aid) in first:
                x,y=first[seed,"shown",aid],first[seed,"hidden",aid]
                assert x[0]==y[0] and x[1]["content"].replace("Round 1/24.","Round 1.",1)==y[1]["content"];first_pairs+=1
    contrasts=[]
    for seed in SEEDS:
        by={e["visibility"]:e for e in arms if e["seed"]==seed}
        if len(by)<2 or any(e["primary_combined_last3_net"] is None for e in by.values()):
            contrasts.append(dict(seed=seed,status="planned_endpoint_missing",primary_shown_minus_hidden=None));continue
        shown,hidden=by["shown"],by["hidden"]
        contrasts.append(dict(seed=seed,status="complete_pair",primary_shown_minus_hidden=shown["primary_combined_last3_net"]-hidden["primary_combined_last3_net"],
            by_agent={aid:shown["targets"][aid]["primary_last3"]["net"]-hidden["targets"][aid]["primary_last3"]["net"] for aid in shown["targets"]},
            last3_price_return_contrast=shown["last3_price_return"]-hidden["last3_price_return"],
            post_mean_gap_contrast=shown["event_metrics"]["post_mean_absolute_relative_gap"]-hidden["event_metrics"]["post_mean_absolute_relative_gap"],
            marks_contrast={aid:{m:shown["targets"][aid]["terminal_marks"][m]["excess_return"]-hidden["targets"][aid]["terminal_marks"][m]["excess_return"] for m in ("auction","regime_benchmark")} for aid in shown["targets"]}))
    usage={k:sum(e["usage"][k] for e in arms) for k in USAGE}
    assert usage["requests_made"]==len(requests) and usage["requests_made"]<=360 and usage["reserved_tokens"]<=4400000
    assert sum(r["usage"]["total_tokens"] for r in requests if r.get("usage") and r["usage"]["source"]=="provider")==usage["provider_reported_tokens"]
    unattempted=[e for e in p["arms"] if not any((e["seed"],e["visibility"])==(a["seed"],a["visibility"]) for a in arms)]
    report=dict(version="horizon_analysis_v1",protocol_sha256=sha256(root/"protocol.json"),study=str(root),summary=summary,usage=usage,baseline=baseline,arms=arms,primary_contrasts=contrasts,unattempted=unattempted,
        audit=dict(actual_own_history_prompt_checks=all_outcome_checks,first_prompt_pairs_only_prefix_diff=first_pairs,source_output_hashes=True,matching_dividends_resources_personas=True),
        limitations=p["limitations"],interpretation="One provider draw per condition and two exogenous scenarios; descriptive treatment contrasts with sampling/date/order/feedback uncertainty, no significance or stable causal/general horizon improvement. Bundled shocks do not isolate news. Partial terminal outcomes remain missing, not zero/HOLD/shortened endpoints. Rule replacements equal resources, not identical order-size policies or intrinsic intelligence comparisons.")
    write_json(output/"report.json",report);shutil.copyfile(__file__,output/"analysis_source.py")
    fig,ax=plt.subplots(2,2,figsize=(11,7),layout="constrained")
    for col,seed in enumerate(SEEDS):
        seedarms=[a for a in arms if a["seed"]==seed]
        if seedarms and seedarms[0]["price_path"]:
            pp=seedarms[0]["price_path"]
            ax[0,col].plot([int(r["round"]) for r in pp],[float(r["fundamental"]) for r in pp],color="black",ls="--",label="Regime benchmark (private)")
        for a in seedarms:
            pp=a["price_path"];label=f"{a['visibility']} ({a['rounds']}/24)"
            ax[0,col].plot([int(r["round"]) for r in pp],[float(r["price"]) for r in pp],label=label,marker=".")
            rr=a["target_rounds"];rounds=sorted({r["round"] for r in rr})
            ax[1,col].plot(rounds,[sum(r["executed_signed"] for r in rr if r["round"]<=n) for n in rounds],label=label,marker=".")
        ax[0,col].set_title(f"Seed {seed}: {'positive' if seed==7403 else 'negative'} bundled shock")
        for row in (0,1):
            ax[row,col].axvline(11,color="gray",ls=":");ax[row,col].axvspan(21.5,24.5,color="gray",alpha=.1);ax[row,col].grid(alpha=.2)
            if ax[row,col].get_legend_handles_labels()[0]:ax[row,col].legend()
        ax[0,col].set_ylabel("Auction price");ax[1,col].set_ylabel("Cumulative target net executed shares");ax[1,col].set_xlabel("Auction round")
    fig.suptitle("Recording-length disclosure pilot: one model draw per condition")
    fig.savefig(output/"horizon_paths.png",dpi=180);fig.savefig(output/"horizon_paths.pdf");plt.close(fig)
    text=["# R032 recording-length disclosure pilot","",f"Status: **{summary['status']}**. {summary['completed_markets']}/4 planned markets complete24 rounds. No automatic retry, omitted failed outcome or endpoint substitution. See protocol for frozen endpoints and limits.","", "Only the first user label Round n/24. versus Round n. changes from round1. Continuing stock, end-of-run valuation, economic rules, personas, Qwen8192/low/temp.3 and common exogenous scenarios remain. Own endogenous paths/model draws differ. Base simple_A_v2 plus horizon_visibility_v1_from_round1 is preserved in each actual request. This is NOT indefinite stochastic stopping or a human replication.","", "## Frozen primary: last-three-round executed net flow","", "Buy minus sell, rounds22-24. Combined flow is the sum of two target actors; target-to-target trades cancel in net flow. Partial24-round endpoints are missing. Positive contrast means shown-length targets bought more/sold less; it is not automatically beneficial or more realistic.","", "|Seed|Shown net shares|Hidden net shares|Shown minus hidden|", "|---|---:|---:|---:|"]
    for c in contrasts:
        by={a["visibility"]:a for a in arms if a["seed"]==c["seed"]}
        val=lambda v:by[v]["primary_combined_last3_net"] if v in by else None
        text.append(f"|{c['seed']}|{val('shown')}|{val('hidden')}|{c['primary_shown_minus_hidden']}|")
    text += ["", "## Actor outcomes and both terminal marks","", "Conditional active-minus-passive excess return, percentage points of initial market wealth. Neither terminal mark implies liquidation or risk-adjusted skill. All population counterpart gains/losses and rule companions remain in report.json.","", "|Seed|Disclosure|Actor|Last3 buys|Last3 sells|Auction excess pp|Benchmark excess pp|", "|---|---|---|---:|---:|---:|---:|"]
    for a in arms:
        for aid,t in a["targets"].items():
            late=t["primary_last3"];marks=t["terminal_marks"]
            text.append(f"|{a['seed']}|{a['visibility']}|{t['name']}|{None if late is None else late['executed_buy']}|{None if late is None else late['executed_sell']}|{'missing' if marks is None or late is None else format(100*marks['auction']['excess_return'],'.2f')}|{'missing' if marks is None or late is None else format(100*marks['regime_benchmark']['excess_return'],'.2f')}|")
    text += ["", "## Market and execution context","", "All financial measures below require a clean completed24-round arm. Gap is relative to a private internal regime benchmark, not empirical pricing accuracy. MM volume is full-run union involvement; target volume is post-event union involvement. Their periods/denominators differ.","", "|Seed|Disclosure|Post gap %|Post target volume %|MM volume %|Last3 price return %|Last3 max drawdown %|", "|---|---|---:|---:|---:|---:|---:|"]
    for a in arms:
        good=a["primary_combined_last3_net"] is not None
        def fmt(v):return "missing" if not good or v is None else f"{100*v:.2f}"
        event=a["event_metrics"] or {};market=a["market_metrics"] or {}
        text.append(f"|{a['seed']}|{a['visibility']}|{fmt(event.get('post_mean_absolute_relative_gap'))}|{fmt(event.get('target_union_volume_share'))}|{fmt(market.get('volume_weighted_mm_share'))}|{fmt(a['last3_price_return'])}|{fmt(a['last3_max_drawdown_from_round21'])}|")
    text += ["", "Last3 price return is P24/P21-1. Drawdown is the largest peak-to-subsequent-close fall over closes21-24. Both are secondary; neither overrides the frozen primary flow. Exposure/capacity at21 is a consequence of the from-round1 policy treatment, not a matched pre-treatment covariate.","", "![Pilot paths](horizon_paths.png)","", "## Cost, failures and limits","",f"{usage['requests_made']} HTTP attempts; {usage['provider_reported_tokens']} provider-reported tokens; {usage['reserved_tokens']} conservative token reservations; {usage['unknown_usage_requests']} unknown-usage requests; {usage['blocked_requests']} blocked. Provider sampling seed/backend fingerprint unavailable. No reflection calls.","", "Report includes all completed/partial/uncleared orders, source/config/prompt hashes, actual recent-history checks, opportunity before news/last3, requested/accepted/filled quantities, MM/inventory, prices and both marks for all accounts. A missing planned terminal value must not be replaced by the last observed prefix; partial observations remain separately available.","",p["limitations"],"", "News is a forecast plus actual permanent dividend shift. One seed per direction cannot establish a directional interaction or isolated headline effect. Four rule companions are economic benchmarks, not identical-sized policy controls or independent LLM repetitions. Do not pool this adapter with original-v2 A/B/C as though prompts were identical. No automatic default or broader grid is justified by this pilot alone."]
    (output/"READOUT.md").write_text("\n".join(text)+"\n",encoding="utf-8")
    write_json(output/"artifact_manifest.json",{f.name:sha256(f) for f in output.iterdir() if f.is_file()})
    print(json.dumps(dict(output=str(output),usage=usage,contrasts=contrasts,summary=summary),indent=2));return report


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--study",required=True);parser.add_argument("--output",required=True);args=parser.parse_args();analyze(args.study,args.output)
