"""R033: fresh common histories, conditional headline trials, real one-step settlement."""
import argparse
import copy
from dataclasses import asdict
from datetime import datetime,timezone
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import time
import uuid
import zipfile
import numpy as np
import yaml
import sim.engine as engine
from sim.agents.base import Agent,Observation
from sim.agents.rule_agents import RULE_AGENTS
from sim.config import load_config,parse_config
from sim.evaluation import read_rows
from sim.llm.client import LLMClient
from sim.llm.usage import UsageBudget,RequestPacer,ProviderUnavailable,UsageLimitExceeded
from sim.market import CallAuctionMarket,Order,settle
from sim.news_controls import HEADLINE
from sim.provenance import sha256,write_json,start_manifest,finish_manifest
from sim.sequential_markets import recipe,verify_market
from runs.horizon_pilot_20261104 import visibility

BASE=Path(__file__).resolve().parents[1]
VERSION="matched_news_auctions_v1_A_common_hidden_length"
SEEDS=(9623,10729)
SNAPSHOTS=(2,6)
TARGETS=("llm_012","llm_013")
NEWS={"silent":None,"positive":HEADLINE,"negative":HEADLINE.replace("20% rise","20% fall")}
FACTORS=(1.,.8,1.2)
USAGE=("requests_made","reserved_tokens","provider_reported_tokens","unknown_usage_requests","blocked_requests")

def read(path):return json.loads(Path(path).read_text(encoding="utf-8"))
def lines(path):return [json.loads(s) for s in Path(path).read_text(encoding="utf-8").splitlines()]

def source_config(seed,mode="A"):
    cfg=recipe(seed,mode,combined=False,rounds=6).to_dict();cfg["name"]=f"news_auction_source_{mode}_s{seed}"
    if mode=="A":cfg["llm_limits"].update(max_requests=40,max_reserved_tokens=600000)
    return parse_config(cfg)

def prepare(output_root="runs"):
    root=Path(output_root)/(time.strftime("%Y%m%d_%H%M%S_")+"news_auctions_"+uuid.uuid4().hex[:8]);root.mkdir(parents=True,exist_ok=False);(root/"configs").mkdir()
    configs=[]
    for seed in SEEDS:
        for mode in ("A","rules"):
            cfg=source_config(seed,mode);path=root/"configs"/f"{mode}_{seed}.yaml";path.write_text(yaml.safe_dump(cfg.to_dict()),encoding="utf-8")
            configs.append(dict(seed=seed,mode=mode,config=path.relative_to(root).as_posix(),config_sha256=sha256(path)))
    sources={p.relative_to(BASE).as_posix():sha256(p) for p in sorted((BASE/"sim").rglob("*.py"))}
    for name in ("news_auctions_20261104.py","horizon_pilot_20261104.py","sequential_tail_20261104.py"):sources["runs/"+name]=sha256(BASE/"runs"/name)
    with zipfile.ZipFile(root/"prepared_source.zip","w",zipfile.ZIP_DEFLATED) as z:
        for name in sources:z.write(BASE/name,name)
    shutil.copyfile(__file__,root/"driver_source.py")
    protocol=dict(version=VERSION,status="frozen_before_generation",created_utc=datetime.now(timezone.utc).isoformat(),
        parent_revision=subprocess.check_output(["git","rev-parse","HEAD"],cwd=BASE,text=True).strip(),working_tree_status=subprocess.check_output(["git","status","--short"],cwd=BASE,text=True).splitlines(),
        configs=configs,source_sha256=sources,source_archive_sha256=sha256(root/"prepared_source.zip"),driver_sha256=sha256(__file__),
        seeds=list(SEEDS),source_rounds=6,snapshot_rounds=list(SNAPSHOTS),condition="A",headlines=NEWS,repetitions=3,economic_factors=list(FACTORS),
        state_selection="All4 predesignated seed/round frames. No screening on price, choices, cash, holdings, capacity, news response or desired signs. Source histories quiet and genuine A actions/outcomes. Source replies never reused as silent trials.",
        prompts="Common hidden recording length adapter from round1 in both sources and all trials, original continuing-stock/system/economics/personas unchanged. Declared research variant, NOT selected realistic default or a horizon comparison. Exact silent snapshot messages must reproduce source messages; only headline changes within frame.",
        design="36 conditional single auctions(4 frames x3 headlines x3 fresh joint reply repetitions),72 fresh choices, both target slots jointly replaced in a fixed12-background order book. Allocation RNG reset to same captured source pre-auction state. Not36 independent full markets;4 frames nested in2 fresh histories. No provider sampling seed/fingerprint assumed.",
        primary="Within each frame/repetition, headline-minus-silent executed signed target flow(buy-sell), per actor and combined. Show all3 draws/contexts and requested/accepted/gross/fills, not only means. No directional financial pass gate or inferential/pseudoreplicated significance claim.",
        economics="Current hidden mean factors1/.8/1.2 are SAME-ORDER counterfactual settlements: draw source current dividend scaled by factor, private regime benchmark scaled, same auction RNG/orders/execution. They are not extra behavioural trials; information is unavailable at order cutoff. No claim about later learning, equilibrium price discovery, news accuracy or long-run profits.",
        rules="Conditional F/M target-policy substitutions on identical source accounts/observations with specified original parameters, all3 headlines must give identical orders/fills. Equal current resources, not a full rule-population or intrinsic intelligence comparison.",
        metrics="Requested/accepted/executed signed/gross flow, own limits versus actual clearing/fills, sell/buy headroom, price/volume/fill/MM/inventory, cash/share conservation, all accounts and auction/benchmark one-auction stay-put excess normalized by opening market wealth. Counterfactual marks are not liquidation/risk-adjusted alpha/welfare.",
        limits=dict(source_per_arm_requests=40,source_per_arm_reservations=600000,query_requests=108,query_reservations=2000000,total_requests=188,total_reservations=3200000,normal_source_choices=24,normal_query_choices=72,reflections=0),
        failure_policy="Each source/conditional case attempted once. Existing one shared extra transport/503 attempt on identical messages. First fatal provider/output/budget or persistent parse fallback stops whole phase. No incomplete joint auction settled, missing partner HOLD, automatic continuation, old-state substitution, selected retries or prefix splicing.",
        limitations="Two source histories,4 correlated frames and3 model draws per headline. Fresh request repetitions are not guaranteed independent backend samples. Both focal actors treated jointly; effects not isolated traits. No human realism validation, universal response/component upgrade, selected new default or model switch.")
    write_json(root/"protocol.json",protocol);write_json(root/"preparation.json",dict(protocol_sha256=sha256(root/"protocol.json")))
    print(f"prepared -> {root}",flush=True);return root

def validate(root):
    root=Path(root);p=read(root/"protocol.json")
    if sha256(root/"protocol.json")!=read(root/"preparation.json")["protocol_sha256"] or p["version"]!=VERSION:raise ValueError("protocol drift")
    for name,digest in p["source_sha256"].items():
        if sha256(BASE/name)!=digest:raise ValueError("source drift")
    if sha256(root/"prepared_source.zip")!=p["source_archive_sha256"] or sha256(root/"driver_source.py")!=p["driver_sha256"]:raise ValueError("archive/driver drift")
    for e in p["configs"]:
        if sha256(root/e["config"])!=e["config_sha256"]:raise ValueError("config drift")
    return p

def parsed_order(row):
    return Order(row["agent_id"],row["side"],int(row["quantity"]),None if row["limit_price"] in (None,"") else float(row["limit_price"]),int(row["round"]),row.get("reasoning",""),row.get("validation_note",""))

def case_agent(frame,aid,news,client=None,budget=None,log_fn=None):
    obs=Observation(**copy.deepcopy(frame["observations"][aid]));obs.news=[] if NEWS[news] is None else [NEWS[news]]
    def record(item):
        if log_fn:log_fn({**item,"source_adapter_prompt_version":item.get("prompt_version"),"prompt_version":VERSION,"research_version":VERSION})
    with visibility("hidden"):
        agent=engine.LLMAgent(aid,obs.my_cash,obs.my_shares,np.random.default_rng(0),
            params=dict(condition="A",memory_window=5,reflect_every=0,max_tokens=8192,tick=frame["market"]["tick"],transport_retries=1,retry_http_503=True,round_unit=obs.round_unit),
            persona=frame["personas"][aid],client=client,budget=budget,log_fn=record,temperature=.3,
            initial_price=obs.price_history[-1],initial_cost=obs.my_avg_cost,transaction_tax=frame["market"]["transaction_tax"],price_band=frame["market"]["price_band"])
    agent.memory=copy.deepcopy(frame["memory"][aid]);return agent,obs

def messages(frame,aid,news):
    agent,obs=case_agent(frame,aid,news)
    return [dict(role="system",content=agent.system_prompt("KGP")),dict(role="user",content=agent.user_prompt(obs))]

def extract_frames(path,seed):
    path=Path(path);verify_market(path);cfg=load_config(path/"config.yaml");prices=read_rows(path/"prices.csv");orders=read_rows(path/"orders.csv");trades=read_rows(path/"trades.csv");states=read_rows(path/"agents_state.csv")
    calls=[r for r in lines(path/"llm_requests.jsonl") if r["record_type"]=="model_call" and r["json_attempt"]==r["transport_attempt"]==1]
    parameters={k:getattr(cfg.market,k) for k in ("tick","price_band","transaction_tax")}
    outcomes=lines(path/"agent_outcomes.jsonl");personas=read(path/"personas.json");market=CallAuctionMarket(**parameters,rng=engine.make_rngs(seed)["allocation"]);result=[]
    for rnd in range(1,len(prices)+1):
        raw=[o for o in orders if int(o["round"])==rnd];before=copy.deepcopy(market.rng.bit_generator.state)
        previous=cfg.asset.initial_price if rnd==1 else float(prices[rnd-2]["price"])
        price,fills,_=market.clear([parsed_order(o) for o in raw],previous,rnd)
        assert price==float(prices[rnd-1]["price"]) and [asdict(t) for t in fills]==[{"round":int(t["round"]),"buyer_id":t["buyer_id"],"seller_id":t["seller_id"],"quantity":int(t["quantity"]),"price":float(t["price"])} for t in trades if int(t["round"])==rnd]
        if rnd not in SNAPSHOTS:continue
        opening=[r for r in states if int(r["round"])==rnd-1]
        frame=dict(frame_id=f"s{seed}_r{rnd}",seed=seed,round=rnd,source_path=str(path),source_manifest_sha256=sha256(path/"manifest.json"),market=parameters,opening=opening,
            allocation_rng_state=before,previous_price=previous,dividend=float(prices[rnd-1]["dividend"]),benchmark=float(prices[rnd-1]["fundamental"]),risk_free=cfg.asset.risk_free,
            source_orders=raw,background_orders=[o for o in raw if o["agent_id"] not in TARGETS],personas=personas,observations={},memory={},source_price=price,source_trades=[asdict(t) for t in fills])
        for aid in TARGETS:
            state=next(r for r in opening if r["agent_id"]==aid);history=[cfg.asset.initial_price]+[float(r["price"]) for r in prices[:rnd-1]]
            recent=[f"r{t['round']}: {'bought' if t['buyer_id']==aid else 'sold'} {t['quantity']} @ {float(t['price']):.2f}" for t in trades if int(t["round"])<rnd and aid in (t["buyer_id"],t["seller_id"])]
            frame["observations"][aid]=asdict(Observation(rnd,cfg.rounds,history[-cfg.observation.price_history_len:],int(prices[rnd-2]["volume"]),float(prices[rnd-2]["dividend"]),cfg.asset.risk_free,None,[],[],float(state["cash"]),int(state["shares"]),float(state["avg_cost"]),float(state["wealth"]),recent[-5:],cfg.time.round_unit))
            frame["memory"][aid]=[r["outcome"] for r in outcomes if r["agent_id"]==aid and r["outcome"]["round"]<rnd][-5:]
            original=next(r for r in calls if r["agent_id"]==aid and r["round"]==rnd)
            assert messages(frame,aid,"silent")==original["messages"]
        frame["messages"]={n:{aid:messages(frame,aid,n) for aid in TARGETS} for n in NEWS};result.append(frame)
    assert len(result)==2;return result

def execute_auction(frame,target_orders,factor):
    assert factor in FACTORS and set(target_orders)==set(TARGETS)
    agents={r["agent_id"]:Agent(r["agent_id"],float(r["cash"]),int(r["shares"]),np.random.default_rng(0),initial_price=frame["previous_price"],initial_cost=float(r["avg_cost"]),transaction_tax=frame["market"]["transaction_tax"],price_band=frame["market"]["price_band"]) for r in frame["opening"]}
    orders=[parsed_order(o) for o in frame["background_orders"]]+[copy.deepcopy(target_orders[a]) for a in TARGETS]
    checked=[]
    for aid in agents:
        checked.extend(agents[aid].validate_orders([o for o in orders if o.agent_id==aid],frame["previous_price"]))
    checked.sort(key=lambda o:(o.agent_id,o.side))
    market=CallAuctionMarket(**frame["market"],rng=np.random.default_rng());market.rng.bit_generator.state=copy.deepcopy(frame["allocation_rng_state"])
    price,trades,unmatched=market.clear(checked,frame["previous_price"],frame["round"])
    cash=math.fsum(a.cash for a in agents.values());shares=sum(a.shares for a in agents.values());settle(trades,agents,market)
    dividend=frame["dividend"]*factor;benchmark=frame["benchmark"]*factor;income={a.agent_id:a.pay_dividend(dividend,frame["risk_free"]) for a in agents.values()}
    error=math.fsum(a.cash for a in agents.values())-(cash-market.tax_collected+math.fsum(sum(v) for v in income.values()))
    assert abs(error)<1e-7 and sum(a.shares for a in agents.values())==shares==1450
    assert all(a.cash>=-1e-7 and a.shares>=0 for a in agents.values()) and agents["mark_000"].shares<=300
    accounts=[]
    for r in frame["opening"]:
        aid=r["agent_id"];a=agents[aid];c=float(r["cash"]);s=int(r["shares"]);wealth=c+s*frame["previous_price"];passive_cash=c*(1+frame["risk_free"])+s*dividend
        marks={k:dict(active_wealth=a.cash+a.shares*p,passive_wealth=passive_cash+s*p,excess_amount=a.cash+a.shares*p-passive_cash-s*p,excess_return=(a.cash+a.shares*p-passive_cash-s*p)/wealth) for k,p in (("auction",price),("regime_benchmark",benchmark))}
        accounts.append(dict(agent_id=aid,source_type=r["type"],opening_wealth=wealth,opening_cash=c,opening_shares=s,closing_cash=a.cash,closing_shares=a.shares,marks=marks))
    assert all(abs(sum(a["marks"][m]["excess_amount"] for a in accounts))<1e-7 for m in ("auction","regime_benchmark"))
    targets={}
    for aid in TARGETS:
        o=next(o for o in checked if o.agent_id==aid);buy=sum(t.quantity for t in trades if t.buyer_id==aid);sell=sum(t.quantity for t in trades if t.seller_id==aid)
        targets[aid]=dict(accepted=asdict(o),executed_buy=buy,executed_sell=sell,executed_net=buy-sell,executed_gross=buy+sell)
    volume=sum(t.quantity for t in trades);maker=sum(t.quantity for t in trades if "mark_000" in (t.buyer_id,t.seller_id));submitted=sum(o.quantity for o in checked if o.side!="hold")
    return dict(economic_factor=factor,price=price,trades=[asdict(t) for t in trades],unmatched_volume=unmatched,volume=volume,fill_rate=0 if not submitted else 2*volume/submitted,mm_volume_fraction=None if not volume else maker/volume,mm_closing_shares=agents["mark_000"].shares,dividend=dividend,private_benchmark=benchmark,cash_error=error,accounts=accounts,targets=targets)

def settlements(frame,orders):
    results=[execute_auction(frame,orders,f) for f in FACTORS]
    assert all((r["price"],r["trades"],r["targets"])==(results[0]["price"],results[0]["trades"],results[0]["targets"]) for r in results)
    return results

def rule_choices(frame,news):
    cfg=source_config(frame["seed"],"rules");slots=[g for g in cfg.agents for _ in range(g.count)];result={}
    for aid,slot in zip(TARGETS,(12,13)):
        group=slots[slot];agent,obs=case_agent(frame,aid,news)
        rule=RULE_AGENTS[group.type](aid,agent.cash,agent.shares,np.random.default_rng(0),params=group.params,initial_price=frame["previous_price"],initial_cost=agent.avg_cost,transaction_tax=frame["market"]["transaction_tax"],price_band=frame["market"]["price_band"])
        result[aid]=rule.decide(obs)
    return result

def freeze_battery(root,entries):
    root=Path(root);frames=[]
    for e in entries:frames+=extract_frames(root/e["run_path"],e["seed"])
    controls=[]
    for f in frames:
        original={aid:parsed_order(next(o for o in f["source_orders"] if o["agent_id"]==aid)) for aid in TARGETS};replayed=execute_auction(f,original,1.)
        assert replayed["price"]==f["source_price"] and replayed["trades"]==f["source_trades"]
        bynews={n:settlements(f,rule_choices(f,n)) for n in NEWS}
        assert bynews["silent"]==bynews["positive"]==bynews["negative"]
        controls.append(dict(frame_id=f["frame_id"],orders={a:asdict(o) for a,o in rule_choices(f,"silent").items()},settlements=bynews["silent"],headline_negative_control=True,source_auction_exactly_reproduced=True))
    schedule=[];names=list(NEWS)
    for rep in (1,2,3):
        for idx in (range(4) if rep!=2 else reversed(range(4))):
            order=names[(idx+rep-1)%3:]+names[:(idx+rep-1)%3]
            for ni,n in enumerate(order):schedule.append(dict(case_id=f"{frames[idx]['frame_id']}_{n}_rep{rep}",frame_id=frames[idx]["frame_id"],headline=n,repetition=rep,agent_order=list(TARGETS if (idx+rep+ni)%2 else reversed(TARGETS))))
    battery=dict(version=VERSION,frames=frames,schedule=schedule,rule_controls=controls)
    write_json(root/"battery.json",battery);write_json(root/"battery_seal.json",dict(sha256=sha256(root/"battery.json")))
    return battery

def run_queries(root,battery,pacer):
    root=Path(root);query=root/"queries";query.mkdir(exist_ok=False)
    cfg=source_config(SEEDS[0]).to_dict();cfg["name"]="matched_news_conditional_auctions";cfg["llm_limits"].update(max_requests=108,max_reserved_tokens=2000000);cfg=parse_config(cfg)
    (query/"config.yaml").write_text(yaml.safe_dump(cfg.to_dict()),encoding="utf-8");shutil.copyfile(root/"battery.json",query/"battery.json")
    manifest=start_manifest(query,cfg);manifest.update(experiment_kind=VERSION,protocol_sha256=sha256(root/"protocol.json"),battery_sha256=sha256(root/"battery.json"),driver_sha256=sha256(__file__),config_scope="Profile only: actual same-state observations,accounts,orders,RNG and exact messages in battery. Conditional auctions, not a sequential full market.")
    write_json(query/"manifest.json",manifest)
    budget=UsageBudget(**asdict(cfg.llm_limits));budget.pacer=pacer;llm=cfg.agents[-1].llm;frames={f["frame_id"]:f for f in battery["frames"]};index=[];choices=[];status="running";failure=None;current=None
    with (query/"llm_requests.jsonl").open("w",encoding="utf-8") as requests,(query/"llm_calls.jsonl").open("w",encoding="utf-8") as calls:
        def log(item):
            tagged={**item,**current,"study_call_id":current["case_id"]+"::"+item.get("call_id",item.get("agent_id","")),"study_request_group_id":current["case_id"]+"::"+item.get("request_group_id","")}
            stream=requests if item["record_type"] in ("model_call","request_blocked") else calls;stream.write(json.dumps(tagged,allow_nan=False)+"\n");stream.flush()
        try:
            for item in battery["schedule"]:
                current=dict(item);write_json(root/"progress.json",dict(status="queries_running",completed_auctions=len(index),active=item,llm_usage=budget.snapshot()))
                frame=frames[item["frame_id"]];orders={}
                for aid in item["agent_order"]:
                    client=LLMClient(model=llm.model,base_url=llm.base_url,timeout=llm.timeout_seconds,reasoning_effort=llm.reasoning_effort,send_temperature=llm.send_temperature)
                    agent,obs=case_agent(frame,aid,item["headline"],client,budget,log)
                    actual=[dict(role="system",content=agent.system_prompt("KGP")),dict(role="user",content=agent.user_prompt(obs))]
                    assert actual==frame["messages"][item["headline"]][aid]
                    order=agent.decide(obs);valid=not any((agent.parse_failures,agent.api_failures,agent.output_truncations))
                    choices.append({**item,"agent_id":aid,"intent":agent.last_intent,"accepted":asdict(order),"valid":valid});write_json(query/"choices.json",choices)
                    if not valid:raise ValueError("operational_fallback_no_joint_settlement")
                    orders[aid]=order
                index.append({**item,"settlements":settlements(frame,orders)});write_json(query/"auctions.json",index)
            status="completed"
        except (ProviderUnavailable,UsageLimitExceeded) as exc:status="stopped";failure=type(exc).__name__
        except BaseException as exc:
            status="interrupted" if isinstance(exc,KeyboardInterrupt) else "failed";failure=type(exc).__name__
            if not isinstance(exc,ValueError) or str(exc)!="operational_fallback_no_joint_settlement":raise
        finally:
            summary=dict(status=status,rounds=0,completed_auctions=len(index),planned_auctions=36,delivered_choices=len(choices),failure_type=failure,incomplete_case=current if status!="completed" else None,llm_usage=budget.snapshot(),finished_utc=datetime.now(timezone.utc).isoformat())
            write_json(query/"summary.json",summary);requests.flush();calls.flush();finish_manifest(query,manifest,summary)
    return summary

def execute(root):
    root=Path(root);p=validate(root)
    if (root/"execution.json").exists():raise ValueError("study already started; no automatic restart")
    if any((x/"execution.json").exists() for x in root.parent.glob("*_news_auctions_*") if x.resolve()!=root.resolve()):raise ValueError("study version already attempted")
    with (root/"execution.json").open("x") as f:json.dump(dict(pid=os.getpid(),started_utc=datetime.now(timezone.utc).isoformat(),protocol_sha256=sha256(root/"protocol.json")),f)
    pacer=RequestPacer(10,60000);entries=[];status="running";failure=None;query=None
    try:
        for e in [e for e in p["configs"] if e["mode"]=="A"]:
            write_json(root/"progress.json",dict(status="source_running",completed_sources=len(entries),active=e))
            with visibility("hidden"):path=Path(engine.run(root/e["config"],output_root=root/"source_runs",request_pacer=pacer))
            s=read(path/"summary.json");verify_market(path)
            entries.append({**e,"run_path":path.relative_to(root).as_posix(),"manifest_sha256":sha256(path/"manifest.json"),"status":s["status"],"rounds":s["rounds"],"usage":s["llm_usage"]});write_json(root/"source_runs.json",entries)
            if s["status"]!="completed" or s["rounds"]!=6 or any(s[k] for k in ("parse_failures","api_failures","output_truncations")):
                status="stopped";failure=s["failure_type"] or "operational_fallback";break
        else:
            battery=freeze_battery(root,entries);query=run_queries(root,battery,pacer);status=query["status"];failure=query["failure_type"]
    except BaseException as exc:
        status="interrupted" if isinstance(exc,KeyboardInterrupt) else "failed";failure=type(exc).__name__;raise
    finally:
        usage={k:sum(e["usage"][k] for e in entries)+(query["llm_usage"][k] if query else 0) for k in USAGE}
        # If an unexpected query exception escaped, its sealed summary still carries usage.
        if query is None and (root/"queries/summary.json").exists():
            query=read(root/"queries/summary.json");usage={k:sum(e["usage"][k] for e in entries)+query["llm_usage"][k] for k in USAGE}
        assert usage["requests_made"]<=188 and usage["reserved_tokens"]<=3200000
        summary=dict(status=status,completed_sources=sum(e["status"]=="completed" and e["rounds"]==6 for e in entries),planned_sources=2,completed_auctions=0 if not query else query["completed_auctions"],planned_auctions=36,failure_type=failure,usage=usage,finished_utc=datetime.now(timezone.utc).isoformat())
        write_json(root/"summary.json",summary);write_json(root/"progress.json",dict(**summary,active=None))
    print(f"{status} -> {root}",flush=True);return root

if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("action",choices=("prepare","run"));parser.add_argument("--study");parser.add_argument("--output-root",default="runs");args=parser.parse_args()
    if args.action=="prepare":prepare(args.output_root)
    else:execute(args.study)
