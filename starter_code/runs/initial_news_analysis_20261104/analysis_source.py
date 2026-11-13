"""R036 audit: early3 executed response and eligible full12 sequential outcomes."""
import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
import shutil
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sim.config import load_config
from sim.evaluation import evaluate_run,read_rows
from sim.provenance import sha256,write_json
from runs import initial_news_20261104 as d

def grouped_accounts(ev):
    groups={g:{m:0. for m in ("auction","regime_benchmark")} for g in ("targets","market_maker","other_traders")}
    for a in ev["accounts"]:
        group="targets" if int(a["agent_id"].rsplit("_",1)[1]) in (12,13) else "market_maker" if a["type"]=="MarketMakerAgent" else "other_traders"
        for mark in groups[group]:groups[group][mark]+=a["marks"][mark]["active_minus_passive"]
    assert all(abs(sum(g[m] for g in groups.values()))<1e-7 for m in ("auction","regime_benchmark"));return groups

def account_reconstruction(path,cfg):
    """Independently rebuild every account from fills, interest and dividends."""
    previous={r["agent_id"]:(float(r["cash"]),int(r["shares"])) for r in read_rows(path/"initial_state.csv")}
    states={(int(r["round"]),r["agent_id"]):r for r in read_rows(path/"agents_state.csv")}
    trades=read_rows(path/"trades.csv");checks=0;cash_error=wealth_error=0.
    for p in read_rows(path/"prices.csv"):
        rnd=int(p["round"]);price=float(p["price"]);dividend=float(p["dividend"])
        current={aid:[cash,shares] for aid,(cash,shares) in previous.items()}
        for t in trades:
            if int(t["round"])!=rnd:continue
            quantity=int(t["quantity"]);value=quantity*float(t["price"])
            buyer,seller=current[t["buyer_id"]],current[t["seller_id"]]
            buyer[0]-=value*(1+cfg.market.transaction_tax);buyer[1]+=quantity
            seller[0]+=value;seller[1]-=quantity
        for aid,(cash,shares) in current.items():
            cash=cash*(1+cfg.asset.risk_free)+shares*dividend
            state=states[rnd,aid];assert shares==int(state["shares"])
            cash_error=max(cash_error,abs(cash-float(state["cash"])))
            wealth_error=max(wealth_error,abs(cash+shares*price-float(state["wealth"])))
            checks+=1;previous[aid]=(cash,shares)
    assert cash_error<1e-7 and wealth_error<1e-7
    return dict(account_rounds=checks,max_cash_error=cash_error,max_auction_wealth_error=wealth_error)


def trading(path,cfg,*,live):
    initial=read_rows(path/"initial_state.csv");states=read_rows(path/"agents_state.csv");prices=read_rows(path/"prices.csv");trades=read_rows(path/"trades.csv");orders=read_rows(path/"orders.csv")
    targets=[r["agent_id"] for r in initial if int(r["agent_id"].rsplit("_",1)[1]) in (12,13)]
    decisions={(r["agent_id"],r["round"]):r for r in d.lines(path/"llm_calls.jsonl") if r["record_type"]=="decision"};records=[]
    for o in orders:
        aid=o["agent_id"];rnd=int(o["round"])
        if aid not in targets:continue
        choice=decisions.get((aid,rnd));valid=not live or bool(choice and choice.get("failure_type") is None)
        before=next(r for r in (initial if rnd==1 else states) if r["agent_id"]==aid and (rnd==1 or int(r["round"])==rnd-1))
        price=cfg.asset.initial_price if rnd==1 else float(prices[rnd-2]["price"]);cash=float(before["cash"]);shares=int(before["shares"])
        buy=sum(int(t["quantity"]) for t in trades if int(t["round"])==rnd and t["buyer_id"]==aid);sell=sum(int(t["quantity"]) for t in trades if int(t["round"])==rnd and t["seller_id"]==aid)
        signed=lambda side,q:q*(1 if side=="buy" else -1 if side=="sell" else 0)
        low=math.ceil(price*(1-cfg.market.price_band)/cfg.market.tick-1e-12)*cfg.market.tick
        records.append(dict(agent_id=aid,round=rnd,valid_choice=valid,requested=None if choice is None else choice["intent"],requested_signed=None if not valid or choice is None else signed(choice["intent"]["side"],choice["intent"]["quantity"]),
            accepted_side=o["side"],accepted_quantity=int(o["quantity"]),accepted_limit=None if o["limit_price"]=="" else float(o["limit_price"]),accepted_signed=signed(o["side"],int(o["quantity"])),executed_buy=buy,executed_sell=sell,executed_net=buy-sell,executed_gross=buy+sell,
            opening_cash=cash,opening_shares=shares,opening_price=price,opening_stock_weight=shares*price/float(before["wealth"]),market_buy_capacity=math.floor(cash/(price*(1+cfg.market.price_band)*(1+cfg.market.transaction_tax))+1e-12),best_band_buy_capacity=math.floor(cash/(low*(1+cfg.market.transaction_tax))+1e-12),failure_type=None if choice is None else choice.get("failure_type")))
    early=None
    if len(prices)>=3 and all(any(r["agent_id"]==aid and r["round"]==rnd and r["valid_choice"] for r in records) for aid in targets for rnd in (1,2,3)):
        early={aid:{k:sum(r[k] for r in records if r["agent_id"]==aid and r["round"]<=3 and r[k] is not None) for k in ("accepted_signed","executed_net","executed_gross")} for aid in targets}
        if live:
            for aid in targets:early[aid]["requested_signed"]=sum(r["requested_signed"] for r in records if r["agent_id"]==aid and r["round"]<=3)
    first_valid=bool(prices) and all(any(r["agent_id"]==aid and r["round"]==1 and r["valid_choice"] for r in records) for aid in targets)
    first=None if not first_valid else dict(price=float(prices[0]["price"]),volume=int(prices[0]["volume"]),trades=[t for t in trades if t["round"]=="1"],targets=[r for r in records if r["round"]==1])
    uncleared=[r for r in decisions.values() if r["round"]>len(prices)]
    return records,early,first,uncleared

def available_initial_checks(root,arms):
    checks=[]
    for seed in d.SEEDS:
        selected=[a for a in arms if a["seed"]==seed];by={a["cell"]:a for a in selected}
        if not selected:continue
        reference=root/selected[0]["run_path"]
        for a in selected:
            path=root/a["run_path"];assert d.resources(path)==d.resources(reference) and d.read(path/"personas.json")==d.read(reference/"personas.json")
        for aid in d.TARGETS:
            silent=[by[c]["first_messages"][aid] for c in ("quiet","up_silent","down_silent") if c in by and aid in by[c]["first_messages"]]
            if silent:assert all(m==silent[0] for m in silent)
            for direction in ("up","down"):
                v,s=by.get(direction+"_visible"),by.get(direction+"_silent")
                if not v or not s or aid not in v["first_messages"] or aid not in s["first_messages"]:continue
                x,y=v["first_messages"][aid],s["first_messages"][aid];headline=d.HEADLINE if direction=="up" else d.HEADLINE.replace("20% rise","20% fall")
                assert x[0]==y[0] and x[1]["content"].replace("News today: "+headline+"\n","",1)==y[1]["content"]
                checks.append(dict(seed=seed,agent_id=aid,direction=direction,initial_difference_only_headline=True))
        background=[]
        for a in selected:
            if a["rounds"]:
                background.append([r for r in read_rows(root/a["run_path"]/"orders.csv") if r["round"]=="1" and r["agent_id"] not in d.TARGETS])
        if background:assert all(b==background[0] for b in background)
    return checks

def analyze(root,output):
    root=Path(root);out=Path(output);p=d.validate(root);summary=d.read(root/"summary.json");assert summary["status"]!="running";out.mkdir(exist_ok=False)
    baseline=d.read(root/"baseline_runs.json");d.baseline_gates(root,baseline);base=[];arms=[];all_calls=[];blocked=[];history_checks=0
    for e in baseline:
        path=root/e["run_path"];d.verify_market(path);assert sha256(path/"manifest.json")==e["manifest_sha256"]
        cfg=load_config(path/"config.yaml");ev=evaluate_run(path);rr,early,first,_=trading(path,cfg,live=False)
        base.append({**e,"evaluation":ev,"groups":grouped_accounts(ev),"trading":rr,"early3":early,"first_auction":first,"account_reconstruction":account_reconstruction(path,cfg)})
    index=d.read(root/"runs.json") if (root/"runs.json").exists() else []
    assert {(root/e["run_path"]).resolve() for e in index}=={x.resolve() for x in (root/"market_runs").glob("*") if x.is_dir()},"Unindexed run must not be omitted"
    for e in index:
        path=root/e["run_path"];m=d.verify_market(path);assert sha256(path/"manifest.json")==e["manifest_sha256"] and m["research_adapter"]["version"]==d.VERSION
        cfg=load_config(path/"config.yaml");s=d.read(path/"summary.json");prices=read_rows(path/"prices.csv");calls=[r for r in d.lines(path/"llm_requests.jsonl") if r["record_type"]=="model_call"];all_calls+=calls;blocked += [r for r in d.lines(path/"llm_requests.jsonl") if r["record_type"]=="request_blocked"]
        outcomes=d.lines(path/"agent_outcomes.jsonl");groups=defaultdict(list);first={}
        for c in calls:
            groups[c["request_group_id"]].append(c)
            assert c["call_type"]=="decision" and c["max_tokens"]==8192 and c["temperature_sent"]==.3 and c["reasoning_effort"]=="low" and c["prompt_version"]==d.VERSION
            if c["status"]=="returned":assert c["response_metadata"]["model"]=="qwen-3.8-27b"
            user=c["messages"][1]["content"];assert user.startswith(f"Round {c['round']}.")
            assert ("Initialization references:" in user)==(c["round"]==1)
            if c["round"]==1:
                assert "Previous round:" not in user
                if c["json_attempt"]==c["transport_attempt"]==1:first[c["agent_id"]]=c["messages"]
            memory=json.loads(user.split("Your recent verified outcomes: ",1)[1].split("\nDecide your order",1)[0]);actual=[r["outcome"] for r in outcomes if r["agent_id"]==c["agent_id"] and r["outcome"]["round"]<c["round"]][-5:]
            assert memory==actual;history_checks+=1
        for g in groups.values():
            assert len(g)<=2
            if len(g)==2:
                assert g[0]["status"]=="error" and g[0]["transport_retry_planned"]
                for key in ("messages","temperature","max_tokens","reasoning_effort","json_mode"):assert g[0][key]==g[1][key]
        ref=root/next(r["run_path"] for r in baseline if (r["seed"],r["cell"])==(e["seed"],e["cell"]))
        assert d.resources(path)==d.resources(ref) and [r["dividend"] for r in prices]==[r["dividend"] for r in read_rows(ref/"prices.csv")[:len(prices)]] and s["max_cash_conservation_error"]<1e-7
        ev=evaluate_run(path) if prices else None
        if ev:
            states=read_rows(path/"agents_state.csv");assert all(float(r["cash"])>=-1e-7 and int(r["shares"])>=0 for r in states)
            assert all(sum(int(r["shares"]) for r in states if int(r["round"])==rnd)==1450 for rnd in range(1,len(prices)+1))
            assert 0<=ev["metrics"]["mm_inventory_min"]<=ev["metrics"]["mm_inventory_max"]<=300
            assert all(abs(v)<1e-7 for v in ev["aggregate_active_minus_passive"].values())
        rr,early,fir,uncleared=trading(path,cfg,live=True);clean=s["status"]=="completed" and s["rounds"]==12 and not any(e["operational_failures"].values())
        arms.append({**e,"summary":s,"first_messages":first,"prices":prices,"trading":rr,"early3":early,"first_auction":fir,"uncleared_choices":uncleared,"full_clean":clean,"full_horizon_evaluation":ev if clean else None,"observed_prefix_evaluation":ev,"observed_prefix_groups":None if not ev else grouped_accounts(ev),"account_reconstruction":account_reconstruction(path,cfg)})
    initial_checks=available_initial_checks(root,arms)
    def comparison(seed,left,right,kind):
        by={a["cell"]:a for a in arms if a["seed"]==seed};a,b=by.get(left),by.get(right);valid=bool(a and b and a["early3"] is not None and b["early3"] is not None)
        aa=None if not valid else {aid:{k:a["early3"][aid][k]-b["early3"][aid][k] for k in ("requested_signed","accepted_signed","executed_net","executed_gross")} for aid in d.TARGETS}
        full=bool(a and b and a["full_clean"] and b["full_clean"]);marks=None
        if full:
            accounts=lambda arm:{r["agent_id"]:r for r in arm["full_horizon_evaluation"]["accounts"]}
            av,bv=accounts(a),accounts(b);marks={aid:{m:av[aid]["marks"][m]["excess_return"]-bv[aid]["marks"][m]["excess_return"] for m in ("auction","regime_benchmark")} for aid in d.TARGETS}
        return dict(seed=seed,kind=kind,left=left,right=right,early3_available=valid,actors=aa,combined_early3_executed=None if not valid else sum(v["executed_net"] for v in aa.values()),full12_available=full,
            terminal_price_contrast=None if not full else float(a["prices"][-1]["price"])-float(b["prices"][-1]["price"]),mean_gap_contrast=None if not full else a["full_horizon_evaluation"]["metrics"]["mean_absolute_relative_gap"]-b["full_horizon_evaluation"]["metrics"]["mean_absolute_relative_gap"],passive_excess_contrasts=marks)
    headline=[comparison(seed,direction+"_visible",direction+"_silent","headline_"+direction) for seed in d.SEEDS for direction in ("up","down")]
    economic=[comparison(seed,direction+"_silent","quiet","regime_"+direction) for seed in d.SEEDS for direction in ("up","down")]
    usage=summary["usage"];reserved_only=sum(bool(r.get("attempts",[{}])[0].get("reservation")) for r in blocked)
    assert usage["requests_made"]==len(all_calls)+reserved_only and usage["provider_reported_tokens"]==sum(c["usage"]["total_tokens"] for c in all_calls if c.get("usage") and c["usage"]["source"]=="provider")
    unattempted=[e for b in p["blocks"] for e in b["arms"] if not any((a["seed"],a["cell"])==(e["seed"],e["cell"]) for a in arms)]
    report=dict(version="initial_news_sequential_audit_v1",protocol_sha256=sha256(root/"protocol.json"),summary=summary,baseline=base,arms=arms,headline_contrasts=headline,economic_contrasts=economic,unattempted=unattempted,
        audit=dict(own_actual_history_checks=history_checks,available_initial_pair_checks=initial_checks,rule_controls_and_output_hashes=True,http_records=len(all_calls),reserved_only_blocked=reserved_only,errors=[{k:c.get(k) for k in ("agent_id","round","error_type","http_status","transport_attempt","transport_retry_planned")} for c in all_calls if c["status"]=="error"]),limitations=p["limitations"])
    write_json(out/"report.json",report);shutil.copyfile(__file__,out/"analysis_source.py")
    fig,axes=plt.subplots(2,2,figsize=(11,8),layout="constrained")
    for row,seed in enumerate(d.SEEDS):
        by={a["cell"]:a for a in arms if a["seed"]==seed}
        for col,direction in enumerate(("up","down")):
            ax=axes[row,col];factor=1.2 if direction=="up" else .8;ax.step([0,1,12],[100,100*factor,100*factor],where="post",color="black",ls="--",label="Shifted benchmark (quiet: 100)")
            plotted=False
            for cell,color in (("quiet","gray"),(direction+"_silent","C0"),(direction+"_visible","C1")):
                if cell not in by:continue
                a=by[cell];pp=a["prices"];ax.plot([0]+[int(r["round"]) for r in pp],[100]+[float(r["price"]) for r in pp],label=f"{cell} ({len(pp)}/12)",color=color,marker=".");plotted=True
            if not plotted:ax.text(.5,.5,"No live market attempted",transform=ax.transAxes,ha="center")
            ax.set_title(f"Seed {seed}: {direction}");ax.set(xlim=(0,12),xlabel="Auction round",ylabel="Auction closing price");ax.grid(alpha=.2);ax.legend(fontsize=7)
    fig.suptitle("Initial-state sequential pilot: one model path per condition/seed")
    fig.savefig(out/"sequential_paths.png",dpi=180);fig.savefig(out/"sequential_paths.pdf");plt.close(fig)
    text=["# R036: initial-state sequential headline/economic controls","",f"Status **{summary['status']}**; {summary['completed_markets']}/10 clean12-round markets, {summary['recorded_markets']} attempted, {len(unattempted)} unattempted. Partial/cancelled choices and unknown costs retained. No failed-path splice/resampling/model switch.","", "True dividend-mean shifts at INITIAL1, visible/silent within regime have the SAME exogenous payouts and initial accounts/personas/backgrounds. First silent prompts match quiet/up/down; visible first messages differ only headline. Subsequent divergence is part of the treatment/feedback path plus unseeded model draws, not pre-event state differences. Two scenarios, one model path per condition; no inferential/general human/news effect.","", "Shared research prompt clarifies supplied initial dividend as a PRIOR REFERENCE, not a paid observation in this recording. Hidden episode length/continuing-stock rule common. Production v2/A/B/C/defaults unchanged; no controlled old/new semantic benefit or pooling with older prompt studies.","", "## Frozen primary: visible minus silent signed executed shares in rounds1-3","", "Early endpoints are available only when both paths have all3 financial rounds and valid choices. A later technical stop does not erase that predeclared observed endpoint;12-round outcomes remain missing unless clean/full. Do not assume censored paths are representative.","", "|Seed|Shift|Meera requested / accepted / filled|Arjun requested / accepted / filled|Combined filled|", "|---|---|---|---|---:|"]
    for c in headline:
        fmt=lambda aid:"missing" if not c["early3_available"] else "/".join(str(c["actors"][aid][k]) for k in ("requested_signed","accepted_signed","executed_net"))
        text.append(f"|{c['seed']}|{c['kind']}|{fmt('llm_012')}|{fmt('llm_013')}|{c['combined_early3_executed']}|")
    text += ["", "## Secondary full12 headline contrasts","", "Excess differences in percentage points of common initial market wealth, BOTH conditional passive marks. These are not liquidation, risk-adjusted skill, aggregate welfare or human-realism scores. Gap is a private internal risk-neutral reference, not empirical pricing accuracy.","", "|Seed|Shift|Terminal price difference|Mean gap difference pp|Meera excess auction / benchmark pp|Arjun excess auction / benchmark pp|", "|---|---|---:|---:|---|---|"]
    for c in headline:
        fmt=lambda aid:"missing" if not c["full12_available"] else "/".join(f"{100*c['passive_excess_contrasts'][aid][m]:.2f}" for m in ("auction","regime_benchmark"))
        text.append(f"|{c['seed']}|{c['kind']}|{c['terminal_price_contrast']}|{None if c['mean_gap_contrast'] is None else round(100*c['mean_gap_contrast'],3)}|{fmt('llm_012')}|{fmt('llm_013')}|")
    text += ["", "![All attempted sequential price paths](sequential_paths.png)","", "## Delivery and interpretation limits","",f"Usage:{usage}. All observed-prefix evaluations, target round histories/headroom/order limits/actual fills, volume/MM/inventory, full-lifetime passive marks/counterpart groups, first-auction controls, silent-regime-minus-quiet comparisons and unattempted slots are in report.json. Prefix evaluations are not substituted for missing12-round values.","",p["limitations"],"", "At-start treatment solves pre-event divergence for this design, but removes established pre-news trend context. Private current mean does not enter initial silent input; first-silent action differences can arise from model sampling. Do not interpret them as reactions to unavailable information.12 rounds cannot validate long-run stylized facts. F/M rules ignore headlines by construction, so their exact negative controls do not prove LLM superiority. Higher/lower benchmark gaps and profits alone do not establish realism. No post-hoc word/parameter/provider/reflective-mode grid is authorized by a preferred sign."]
    (out/"READOUT.md").write_text("\n".join(text)+"\n",encoding="utf-8");write_json(out/"artifact_manifest.json",{x.name:sha256(x) for x in out.iterdir() if x.is_file()})
    print(json.dumps(dict(output=str(out),summary=summary,headline_contrasts=headline,audit=report["audit"]),indent=2));return report

if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--study",required=True);parser.add_argument("--output",required=True);a=parser.parse_args();analyze(a.study,a.output)
