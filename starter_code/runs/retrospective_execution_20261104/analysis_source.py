"""R034 OFFLINE only: original A replies through original one-focal auction books."""
import copy
from dataclasses import asdict
from datetime import datetime,timezone
import json
from pathlib import Path
import shutil
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sim.config import load_config
from sim.engine import make_rngs
from sim.evaluation import read_rows
from sim.agents.llm_agent import LLMAgent
from sim.market import CallAuctionMarket,Order
from sim.news_components import validate as validate_components
from sim.provenance import sha256,write_json
from runs.news_auctions_20261104 import BASE,TARGETS,read,lines,parsed_order,settlements,verify_market

PARENT=BASE/"runs/20261103_023441_news_components_da6bdf79"
PHASE=BASE/"runs/20261103_172911_components_continue_f62a08f1"
TAIL=BASE/"runs/20261103_174525_components_tail_90002a97"
OLD_REPORT=BASE/"runs/component_final_analysis_20261103/report.json"
OUT=BASE/"runs/retrospective_execution_20261104"

def context(path,seed):
    manifest=verify_market(path);cfg=load_config(path/"config.yaml")
    for name in ("sim/market.py","sim/agents/base.py","sim/assets.py"):assert manifest["source_sha256"][name]==sha256(BASE/name)
    parameters={k:getattr(cfg.market,k) for k in ("tick","price_band","transaction_tax")}
    market=CallAuctionMarket(**parameters,rng=make_rngs(seed)["allocation"]);prices=read_rows(path/"prices.csv");orders=read_rows(path/"orders.csv");trades=read_rows(path/"trades.csv");states=read_rows(path/"agents_state.csv");frame=None
    for rnd,actual in enumerate(prices,1):
        raw=[o for o in orders if int(o["round"])==rnd];rng=copy.deepcopy(market.rng.bit_generator.state);previous=cfg.asset.initial_price if rnd==1 else float(prices[rnd-2]["price"])
        price,fills,_=market.clear([parsed_order(o) for o in raw],previous,rnd)
        assert price==float(actual["price"]) and [asdict(t) for t in fills]==[dict(round=rnd,buyer_id=t["buyer_id"],seller_id=t["seller_id"],quantity=int(t["quantity"]),price=float(t["price"])) for t in trades if int(t["round"])==rnd]
        if rnd==11:
            frame=dict(seed=seed,round=11,source_path=str(path),source_manifest_sha256=sha256(path/"manifest.json"),market=parameters,opening=[r for r in states if int(r["round"])==10],allocation_rng_state=rng,previous_price=previous,dividend=float(actual["dividend"]),benchmark=float(actual["fundamental"]),risk_free=cfg.asset.risk_free,source_orders=raw,background_orders=[o for o in raw if o["agent_id"] not in TARGETS],source_price=price,source_trades=[asdict(t) for t in fills])
    assert frame is not None
    original={aid:parsed_order(next(o for o in frame["source_orders"] if o["agent_id"]==aid)) for aid in TARGETS}
    replay=settlements(frame,original)[0]
    assert (replay["price"],replay["trades"])==(frame["source_price"],frame["source_trades"])
    return frame

def main():
    _,frames,_=validate_components(PARENT);OUT.mkdir(exist_ok=False)
    inputs=[p for root in (PARENT,PHASE,TAIL) for p in root.rglob("*") if p.is_file()]
    inputs.append(OLD_REPORT)
    protocol=dict(version="retrospective_A_execution_v1",status="frozen_before_replay_not_before_original_queries",created_utc=datetime.now(timezone.utc).isoformat(),
        selection="ALL36 already-observed valid A replies,4 agent frames/3 news/3 original reply draws. No new model reply; question chosen after old order contrasts, not independent prospective confirmation.",
        intervention="Replace ONLY focal order in original round11 book; other13 traders' orders and opening resources fixed, original allocation RNG. Not a joint public-news market: other LLM cannot respond anew. No new behavioural repetitions/full markets/trait or human validation.",
        primary="Accepted/requested headline-minus-silent compared with counterfactual EXECUTED signed focal shares for each frame/repetition. Report all signs, quotes, fills, price/counterparts and both one-auction stay-put marks.",
        economics="Base current dividend/benchmark unchanged across headlines. Same-order factors1/.8/1.2 only counterfactual payout/mark sensitivities; not extra model draws, signal validation or endogenous shock paths.",
        original_profile="Original Qwen qwen-3.8-27b4096/low/temp.3;comparable_agents_v2_disclosed_rules/simple_A_v2, original shown recording length and actual A history. Not pooled with8192/hidden-length R033.",
        source_and_code_sha256={p.relative_to(BASE).as_posix():sha256(p) for p in inputs},
        analysis_sha256=sha256(__file__),execution_helper_sha256=sha256(BASE/"runs/news_auctions_20261104.py"))
    write_json(OUT/"protocol.json",protocol);shutil.copyfile(__file__,OUT/"analysis_source.py")
    results=[r for r in read(TAIL/"combined_results.json") if r["condition"]=="A"]
    assert len(results)==36 and all(r["valid_choice"] for r in results)
    assert len({(r["frame_id"],r["news"],r["repetition"]) for r in results})==36
    calls=[c for root in (PARENT,PHASE,TAIL) for c in lines(root/"llm_requests.jsonl") if c["record_type"]=="model_call" and c["condition"]=="A" and c["call_type"]=="decision"]
    byinput={}
    for root in (PARENT,PHASE,TAIL):
        for row in lines(root/"decision_inputs.jsonl"):
            if row["condition"]=="A":
                key=(row["frame_id"],row["news"],row["repetition"])
                if key in byinput:assert byinput[key]==row
                byinput[key]=row
    assert len(byinput)==36
    contexts={seed:context(PARENT/"sources"/str(seed),seed) for seed in (1441,2882)}
    definitions={f["frame_id"]:f for f in frames};records=[]
    for result in results:
        f=definitions[result["frame_id"]];ctx=contexts[f["seed"]];aid=f["agent_id"]
        assert ctx["source_manifest_sha256"]==f["source_manifest_sha256"]
        own=next(a for a in ctx["opening"] if a["agent_id"]==aid)
        assert (float(own["cash"]),int(own["shares"]),float(own["avg_cost"]),float(own["wealth"]))==(f["observation"]["my_cash"],f["observation"]["my_shares"],f["observation"]["my_avg_cost"],f["observation"]["my_wealth"])
        key=(f["frame_id"],result["news"],result["repetition"]);assert byinput[key]["messages"]==f["fixed_messages"]["A"][result["news"]]
        cc=[c for c in calls if (c["frame_id"],c["news"],c["repetition"])==key]
        assert cc and all(c["messages"]==byinput[key]["messages"] and c["max_tokens"]==4096 and c["temperature_sent"]==.3 and c["reasoning_effort"]=="low" for c in cc)
        returned=[c for c in cc if c["status"]=="returned"];assert len(returned)==1 and returned[0]["response_metadata"]["model"]=="qwen-3.8-27b"
        parsed=LLMAgent._extract_json(returned[0]["raw"])
        assert parsed["action"]==result["intent"]["side"] and parsed["quantity"]==result["intent"]["quantity"] and parsed.get("limit_price")==result["intent"]["limit_price"]
        orders={a:parsed_order(next(o for o in ctx["source_orders"] if o["agent_id"]==a)) for a in TARGETS}
        retargeted={**result["accepted"],"agent_id":aid};orders[aid]=Order(**retargeted)
        executed=settlements(ctx,orders);primary=executed[0];ownfill=primary["targets"][aid]
        assert ownfill["accepted"]==retargeted
        records.append(dict(frame_id=f["frame_id"],agent_id=aid,seed=f["seed"],news=result["news"],repetition=result["repetition"],
            original_intent=result["intent"],original_accepted=result["accepted"],requested_signed=result["requested_signed_quantity"],accepted_signed=result["accepted_signed_quantity"],
            executed_signed=ownfill["executed_net"],executed_gross=ownfill["executed_gross"],price=primary["price"],volume=primary["volume"],mm_fraction=primary["mm_volume_fraction"],
            source_response_call_id=returned[0]["call_id"],same_order_settlements=executed))
    old={ (r["frame_id"],r["news"],r["repetition"]):r for r in read(OLD_REPORT)["contrasts"]["news_minus_silent"] if r["condition"]=="A"}
    contrasts=[]
    for f in frames:
        for news in ("positive","negative"):
            for rep in (1,2,3):
                a=next(r for r in records if (r["frame_id"],r["news"],r["repetition"])==(f["frame_id"],news,rep));b=next(r for r in records if (r["frame_id"],r["news"],r["repetition"])==(f["frame_id"],"silent",rep))
                d={k:a[k]-b[k] for k in ("requested_signed","accepted_signed","executed_signed","executed_gross","price")}
                assert d["accepted_signed"]==old[f["frame_id"],news,rep]["accepted_signed_quantity"]
                contrasts.append(dict(frame_id=f["frame_id"],news=news,repetition=rep,**d))
    for name,digest in protocol["source_and_code_sha256"].items():assert sha256(BASE/name)==digest
    report=dict(version="retrospective_A_execution_v1",new_api_calls=0,new_behavioural_replies=0,original_A_http_attempts=len(calls),original_A_reported_tokens=sum(c["usage"]["total_tokens"] for c in calls if c.get("usage")),
        original_constraints={f["frame_id"]:f["constraints"] for f in frames},contexts=contexts,records=records,contrasts=contrasts,
        audit=dict(source_markets_full_auction_replays=2,source_round11_account_and_trade_replays=2,old_reply_and_exact_input_checks=36,accepted_orders_unchanged_except_id=True,counterfactual_auctions=36,same_order_accounting_variants=108,all_old_accepted_contrasts_reproduced=True,physics_source_hashes_identical=True),
        limitations=protocol["selection"]+" "+protocol["intervention"]+" "+protocol["original_profile"])
    write_json(OUT/"report.json",report)
    fig,axes=plt.subplots(2,2,figsize=(11,8),layout="constrained")
    for ax,f in zip(axes.flat,frames):
        for j,news in enumerate(("positive","negative")):
            rows=[r for r in contrasts if r["frame_id"]==f["frame_id"] and r["news"]==news]
            for offset,key,color,label,marker in ((-.13,"accepted_signed","gray","Accepted order","o"),(.13,"executed_signed","C0","Counterfactual fill","x")):
                values=[r[key] for r in rows];ax.bar(j+offset,np.mean(values),width=.23,color=color,alpha=.25,label=label if j==0 else None)
                ax.scatter([j+offset+(r["repetition"]-2)*.035 for r in rows],values,color=color,marker=marker,s=35)
        ax.set_title(f["frame_id"]);ax.set_xticks((0,1),("Positive headline","Negative headline"));ax.axhline(0,color="black",lw=.6);ax.grid(axis="y",alpha=.2);ax.set_ylabel("Headline - silent signed shares");ax.legend(fontsize=8)
    fig.suptitle("RETROSPECTIVE replay of existing A replies; no new model samples")
    fig.savefig(OUT/"accepted_vs_filled.png",dpi=180);fig.savefig(OUT/"accepted_vs_filled.pdf");plt.close(fig)
    text=["# R034: can the previously recorded news orders actually fill?","", "OFFLINE RETROSPECTIVE analysis of all36 existing A-only R025-R027 replies. **Zero new API calls or behavioural replies.** Same four reused agent frames/two markets and three original reply draws. Original Qwen4096/v2 shown-length prompts; separate from the unrun R0338192/common-hidden trials. Question chosen after observing old order contrasts, not independent prospective confirmation.","", "Each order replaces ONLY its focal trader's original round11 order. Other13 traders' actual orders, opening portfolios and original allocation RNG stay fixed. The other LLM cannot respond anew to the headline. These are conditional one-agent execution counterfactuals, not historical fills, joint public-news market effects or long-run equilibrium outcomes.","", "## Headline minus silent: all original draws","", "Signed shares: buy positive, sell negative. Reduced selling can be a positive contrast without a buy. An accepted contrast is a submitted demand change, not necessarily a fill. Price effects and counterparty fills can also change; no desired-sign pass rule.","", "|Frame|News|Accepted contrasts(3)|Counterfactual filled contrasts(3)|Mean accepted / filled|", "|---|---|---|---|---|"]
    for f in frames:
        for n in ("positive","negative"):
            rr=[r for r in contrasts if r["frame_id"]==f["frame_id"] and r["news"]==n];aa=[r["accepted_signed"] for r in rr];ee=[r["executed_signed"] for r in rr]
            text.append(f"|{f['frame_id']}|{n}|{aa}|{ee}|{np.mean(aa):.2f} / {np.mean(ee):.2f}|")
    text += ["", "![Accepted versus replayed fills](accepted_vs_filled.png)","", "Dots are the three previously generated replies; bars their descriptive means. Four frames are correlated within two source markets. This does not add independent observations or justify inferential significance/human-bias claims.","", "## Economics, accounts and verification","", "Base dividend/private benchmark held fixed for headline comparisons. Three SAME-ORDER payout/mark variants1/.8/1.2 have identical price/trades; they are not new response draws or actual subsequent shock trajectories. One-auction stay-put holds opening shares/cash, earns the same current cashflows and uses the same terminal mark; normalization is opening market wealth, not the original-lifetime passive account. Both marks and ALL counterpart account outcomes are retained in report.json. Aggregate excess cancels at zero tax; no welfare, liquidation or risk-adjusted alpha follows.","", "Both original20-round source markets exactly replayed price-by-price/trade-by-trade. Original round11 accounts/auction, all36 raw replies/exact input messages and24 prior accepted contrasts reproduce. Current market/accounting/asset source hashes match the source snapshots. Original accepted orders stay unchanged except mapping experiment-specific IDs back to source account IDs. All36 canonical auctions/108 same-order settlements pass cash/share/finite-MM checks.","", "This extends interpretation of an existing query study with the missing execution mechanism. R033 still has no source/behavioural result: its failed source is not replaced here. Fresh-state headline/price confirmation, joint behavioural feedback and modest background robustness remain unverified. No production/default/A/B/C/model change or automatic extra experiment."]
    (OUT/"READOUT.md").write_text("\n".join(text)+"\n",encoding="utf-8");write_json(OUT/"artifact_manifest.json",{p.name:sha256(p) for p in OUT.iterdir() if p.is_file()})
    print(json.dumps(dict(output=str(OUT),new_api_calls=0,audit=report["audit"],contrasts=contrasts),indent=2));return report

if __name__=="__main__":main()
