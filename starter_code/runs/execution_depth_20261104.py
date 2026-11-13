"""One post-hoc CURRENT-book MM depth sensitivity; no new responses/history."""
import copy
from dataclasses import asdict,replace
from pathlib import Path
import shutil
import numpy as np
from sim.agents.base import Observation
from sim.agents.rule_agents import MarketMakerAgent
from sim.config import load_config
from sim.market import Order
from sim.provenance import sha256,write_json
from runs.news_auctions_20261104 import read,parsed_order,settlements,TARGETS
from runs.retrospective_execution_20261104 import OUT,PARENT

def main():
    folder=OUT/"depth_sensitivity";folder.mkdir(exist_ok=False);base=read(OUT/"report.json");definitions={f["frame_id"]:f for f in read(PARENT/"frames.json")}
    write_json(folder/"protocol.json",dict(status="posthoc_frozen_before_variant_computation",base_report_sha256=sha256(OUT/"report.json"),script_sha256=sha256(__file__),change="CURRENT MM quote_size10 to20 only, all36 cases. Same opening resources,spread,skew/cap,13 remaining actor policies, source history and captured RNG. No regenerated history, new response/repetition, calibrated liquidity or default selection."))
    shutil.copyfile(__file__,folder/"analysis_source.py");contexts=copy.deepcopy(base["contexts"]);quotes=[]
    for seed,c in contexts.items():
        cfg=load_config(Path(c["source_path"])/"config.yaml");params=next(g.params for g in cfg.agents if g.type=="market_maker");assert params["quote_size"]==10
        state=next(r for r in c["opening"] if r["agent_id"]=="mark_000");f=next(f for f in definitions.values() if f["seed"]==int(seed));obs=Observation(**f["observation"])
        obs=replace(obs,my_cash=float(state["cash"]),my_shares=int(state["shares"]),my_avg_cost=float(state["avg_cost"]),my_wealth=float(state["wealth"]),my_recent_trades=[])
        def orders(size):
            maker=MarketMakerAgent("mark_000",float(state["cash"]),int(state["shares"]),np.random.default_rng(0),params={**params,"quote_size":size},initial_price=c["previous_price"],initial_cost=float(state["avg_cost"]),transaction_tax=c["market"]["transaction_tax"],price_band=c["market"]["price_band"])
            return maker.decide(obs)
        original=[parsed_order(o) for o in c["background_orders"] if o["agent_id"]=="mark_000"]
        signature=lambda oo:[(o.side,o.quantity,o.limit_price,o.round) for o in sorted(oo,key=lambda o:o.side)]
        assert signature(orders(10))==signature(original)
        larger=orders(20);c["background_orders"]=[o for o in c["background_orders"] if o["agent_id"]!="mark_000"]+[asdict(o) for o in larger]
        quotes.append(dict(seed=int(seed),opening_cash=obs.my_cash,opening_shares=obs.my_shares,params=params,original=[asdict(o) for o in original],larger=[asdict(o) for o in larger]))
    records=[]
    for r in base["records"]:
        c=contexts[str(r["seed"])];aid=r["agent_id"];oo={a:parsed_order(next(o for o in c["source_orders"] if o["agent_id"]==a)) for a in TARGETS};oo[aid]=Order(**{**r["original_accepted"],"agent_id":aid})
        runs=settlements(c,oo);own=runs[0]["targets"][aid]
        records.append(dict(frame_id=r["frame_id"],news=r["news"],repetition=r["repetition"],accepted_signed=r["accepted_signed"],executed_signed=own["executed_net"],price=runs[0]["price"],same_order_settlements=runs))
    contrasts=[]
    for prior in base["contrasts"]:
        matched=lambda n:next(r for r in records if (r["frame_id"],r["news"],r["repetition"])==(prior["frame_id"],n,prior["repetition"]))
        a,b=matched(prior["news"]),matched("silent")
        contrasts.append({**prior,"base_executed_signed":prior["executed_signed"],"executed_signed":a["executed_signed"]-b["executed_signed"],"base_price_contrast":prior["price"],"price":a["price"]-b["price"]})
    write_json(folder/"report.json",dict(version="posthoc_current_book_depth_v1",new_api_calls=0,new_behavioural_replies=0,quotes=quotes,records=records,contrasts=contrasts,limitations="Post-hoc current-book-only robustness, same two old markets/four reused frames and existing replies. Not a full-history sensitivity, independent replication, calibrated improvement or new default."))
    text=["# One post-hoc liquidity-depth check","", "Only the market maker's CURRENT quote_size changes10->20; cash/inventory/spread/skew/cap, other traders' original orders and all old focal replies/history/RNG remain. Both original size10 books reproduce first. Both states accept20-share bids/asks under their actual resources. This is not a regenerated market history, empirical calibration, extra reply sample or selected better default. Chosen after base results; all36 cases included.","", "|Frame|News|Mean accepted|Filled contrasts: original / deeper|Mean filled: original / deeper|", "|---|---|---:|---|---|"]
    for fid in base["original_constraints"]:
        for n in ("positive","negative"):
            rr=[r for r in contrasts if r["frame_id"]==fid and r["news"]==n];old=[r["base_executed_signed"] for r in rr];new=[r["executed_signed"] for r in rr]
            text.append(f"|{fid}|{n}|{np.mean([r['accepted_signed'] for r in rr]):.2f}|{old} / {new}|{np.mean(old):.2f} / {np.mean(new):.2f}|")
    text += ["", "All72 base/variant conditional auctions use canonical validation/settlement and finite-MM accounting. Same-order payout/benchmark variants are not extra auctions/replies. Keep accepted-versus-filled and state-specific results; this check cannot establish real-world liquidity or long-run robustness."]
    (folder/"READOUT.md").write_text("\n".join(text)+"\n",encoding="utf-8");write_json(folder/"artifact_manifest.json",{p.name:sha256(p) for p in folder.iterdir() if p.is_file()})
    print((folder/"READOUT.md").read_text(encoding="utf-8"));print('quotes',[(r['seed'],[(o['side'],o['quantity']) for o in r['larger']]) for r in quotes])

if __name__=="__main__":main()
