"""Frozen four-cell feasibility study with equal slots and same-state news probes."""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import time
import uuid
import zipfile

import numpy as np
import yaml

from sim.agents.base import Observation
from sim.agents.llm_agent import LLMAgent, PROMPT_VERSION
from sim.background_check import slot_recipe
from sim.behaviour_run import PROFILE, score_choice
from sim.config import load_config, parse_config
from sim.engine import run
from sim.evaluation import evaluate_run, read_rows
from sim.llm.client import LLMClient
from sim.llm.usage import OutputLimitExceeded, ProviderUnavailable, RequestPacer, UsageBudget, UsageLimitExceeded
from sim.news_controls import CELLS, FINANCIAL_FILES, HEADLINE
from sim.provenance import finish_manifest, sha256, start_manifest, write_json

VERSION="news_live_pilot_v2_matched_event_probes"
SEEDS=(1441,2882)
ROUNDS,EVENT_ROUND=20,11


def market_recipe(seed, cell, brain):
    if brain not in ("rules","qwen"):raise ValueError("brain must be rules or qwen")
    cfg=slot_recipe(seed,brain="rules" if brain=="rules" else "mock",rounds=ROUNDS).to_dict()
    cfg["name"]=f"news_{brain}_{cell}_s{seed}"
    shift,announce=CELLS[cell]
    event=dict(round=EVENT_ROUND,announce=announce)
    if announce:event["headline"]=HEADLINE
    if shift:event["effect"]={"dbar_mult":1.2}
    cfg["news"]=[event]
    if brain=="qwen":
        cfg["llm_limits"]=dict(max_requests=80,max_reserved_tokens=1000000,max_cost_usd=0,
                               requests_per_minute=10,input_tokens_per_minute=60000,stop_on_api_error=True)
        cfg["agents"][-1]["llm"]=dict(provider="openai_compatible",condition="A",memory_window=5,
            reflect_every=0,send_temperature=True,input_usd_per_million=0,output_usd_per_million=0,**PROFILE)
    return parse_config(cfg)


def prepare(output_root="runs"):
    root=Path(output_root)/(time.strftime("%Y%m%d_%H%M%S_")+"news_pilot_"+uuid.uuid4().hex[:8])
    root.mkdir(parents=True);(root/"configs").mkdir()
    source=Path(__file__).resolve().parent
    sources={"sim/"+p.relative_to(source).as_posix():sha256(p) for p in sorted(source.rglob("*.py"))}
    with zipfile.ZipFile(root/"prepared_source.zip","w",zipfile.ZIP_DEFLATED) as archive:
        for name in sources:archive.write(source.parent/name,name)
    schedule=[]
    for brain in ("rules","qwen"):
        for seed in SEEDS:
            order=list(CELLS) if seed==SEEDS[0] else list(reversed(CELLS))
            for cell in order:
                cfg=market_recipe(seed,cell,brain)
                path=root/"configs"/f"{brain}_{cell}_{seed}.yaml"
                path.write_text(yaml.safe_dump(cfg.to_dict()),encoding="utf-8")
                schedule.append(dict(brain=brain,seed=seed,cell=cell,config=path.relative_to(root).as_posix(),
                                     config_sha256=sha256(path)))
    protocol=dict(version=VERSION,prompt_suite_version=PROMPT_VERSION,status="frozen_before_calls",
        parent_revision=subprocess.check_output(["git","rev-parse","HEAD"],cwd=source,text=True).strip(),
        working_tree_status=subprocess.check_output(["git","status","--short"],cwd=source,text=True).splitlines(),
        source_sha256=sources,source_archive_sha256=sha256(root/"prepared_source.zip"),schedule=schedule,
        market_design=dict(seeds=SEEDS,rounds=ROUNDS,event_round=EVENT_ROUND,cells=CELLS,
            headline=HEADLINE,shift_multiplier=1.2,reveal_fundamental=False,condition="A",
            cash=160000,shares=1450,slots=14,targets=[12,13],mm_skew=.02,dividend_window=1),
        amendment="Preserves v1 market settings. Adds all eight equal-slot rule counterparts and 24 fresh matched-state queries to distinguish immediate headline response from stochastic pre-event market divergence.",
        snapshot_design="All two LLM frames in each seed's CONTROL at round 11, actual observations/outcomes through round 10 only; no-headline versus forecast, three fresh repetitions, reverse order in repeat 2. Deterministic frame selection, not based on outcomes. Freeze exact messages before probe calls.",
        limits=dict(planned_market_decisions=320,max_market_attempts=640,max_market_reservations=8000000,
                    planned_probe_decisions=24,max_probe_attempts=48,max_probe_reservations=1000000,
                    total_max_attempts=688,total_max_reservations=9000000),
        metrics="Event/round-level target-slot requested, accepted and executed signed quantities; target trade involvement (union trades) and trade-leg share; all price paths/pre-event differences, post-event benchmark gap, liquidity/turnover and censored half-gap time; both conditional passive-relative wealth marks. Same-state probes report signed accepted headline-minus-no-headline contrasts. No profitability/direction pass oracle.",
        stops="Whole study stops on incomplete market, provider/output/budget error or persistent parse failure. No HTTP retries, model swap or automatic study restart. Partial runs remain visible.",
        limitations="Two independent exogenous seeds, two bundled personas, twenty rounds/ten post-event rounds: feasibility and exploratory leads only. Model draws unseeded. Full market pairs have matched exogenous paths, not identical states. Same-state queries do not execute or identify full market price effects. Rule replacement contrasts concern these policies/personas in these fixed slots, not intrinsic LLM superiority. No human validation or A/B/C benefit claim.")
    write_json(root/"study.json",protocol)
    print(f"prepared -> {root}",flush=True)
    return root


def load_study(root):
    root=Path(root);study=json.loads((root/"study.json").read_text())
    if study["version"]!=VERSION or study["prompt_suite_version"]!=PROMPT_VERSION:
        raise ValueError("study/prompt version drift")
    source=Path(__file__).resolve().parents[1]
    for name,digest in study["source_sha256"].items():
        if sha256(source/name)!=digest:raise ValueError("prepared source drift; no API calls")
    if sha256(root/"prepared_source.zip")!=study["source_archive_sha256"]:raise ValueError("source archive drift")
    if len(study["schedule"])!=16:raise ValueError("expected all sixteen market arms")
    for item in study["schedule"]:
        path=root/item["config"]
        if sha256(path)!=item["config_sha256"]:raise ValueError("frozen config drift")
        if load_config(path)!=market_recipe(item["seed"],item["cell"],item["brain"]):
            raise ValueError("recipe no longer matches frozen study")
    return study


def json_lines(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines()]


def target_ids(root):
    return [r["agent_id"] for r in read_rows(Path(root)/"initial_state.csv") if int(r["agent_id"].rsplit("_",1)[1]) in (12,13)]


def market_metrics(path):
    path=Path(path);evaluation=evaluate_run(path)
    prices=read_rows(path/"prices.csv");trades=read_rows(path/"trades.csv");orders=read_rows(path/"orders.csv")
    targets=target_ids(path);personas=json.loads((path/"personas.json").read_text())
    decisions={(r["agent_id"],r["round"]):r for r in json_lines(path/"llm_calls.jsonl") if r["record_type"]=="decision"}
    records=[]
    def signed(side,qty):return qty*(1 if side=="buy" else -1 if side=="sell" else 0)
    for row in orders:
        aid=row["agent_id"];rnd=int(row["round"])
        if aid not in targets:continue
        decision=decisions.get((aid,rnd));valid=decision is None or decision["failure_type"] is None
        own=[t for t in trades if int(t["round"])==rnd and aid in (t["buyer_id"],t["seller_id"])]
        bought=sum(int(t["quantity"]) for t in own if t["buyer_id"]==aid)
        sold=sum(int(t["quantity"]) for t in own if t["seller_id"]==aid)
        records.append(dict(round=rnd,agent_id=aid,slot=int(aid.rsplit("_",1)[1]),
            persona=personas.get(aid),valid_choice=valid,
            requested_signed=None if decision is None or not valid else signed(decision["intent"]["side"],decision["intent"]["quantity"]),
            accepted_signed=None if not valid else signed(row["side"],int(row["quantity"])),
            accepted_side=row["side"],accepted_quantity=int(row["quantity"]),
            executed_buy=bought,executed_sell=sold,executed_signed=bought-sold,
            validation_note=row["validation_note"],failure_type=None if decision is None else decision["failure_type"]))
    post=[r for r in prices if int(r["round"])>=EVENT_ROUND]
    p10=float(prices[EVENT_ROUND-2]["price"]);new_benchmark=float(prices[EVENT_ROUND-1]["fundamental"])
    first_half=next((int(r["round"])-EVENT_ROUND for r in post
                     if abs(float(r["price"])-new_benchmark)<=.5*abs(p10-new_benchmark)),None)
    post_trades=[t for t in trades if int(t["round"])>=EVENT_ROUND]
    total=sum(int(t["quantity"]) for t in post_trades)
    involved=sum(int(t["quantity"]) for t in post_trades if t["buyer_id"] in targets or t["seller_id"] in targets)
    legs=sum(int(t["quantity"])*((t["buyer_id"] in targets)+(t["seller_id"] in targets)) for t in post_trades)
    return dict(evaluation=evaluation,target_rounds=records,event_decisions=[r for r in records if r["round"]==EVENT_ROUND],
        event_metrics=dict(pre_event_price=p10,pre_mean_price=float(np.mean([float(r["price"]) for r in prices[:EVENT_ROUND-1]])),
            event_price=float(prices[EVENT_ROUND-1]["price"]),
            event_log_return=float(np.log(float(prices[EVENT_ROUND-1]["price"])/p10)),
            post_mean_price=float(np.mean([float(r["price"]) for r in post])),
            post_mean_absolute_relative_gap=float(np.mean([abs(float(r["price"])/float(r["fundamental"])-1) for r in post])),
            half_pre_event_gap_time=first_half,half_gap_right_censored=first_half is None,
            target_union_volume_share=None if total==0 else involved/total,
            target_trade_leg_share=None if total==0 else legs/(2*total),post_total_volume=total),
        timing_note="Half-gap time starts at event round (lag 0), uses the new regime benchmark and pre-event close, and is null/censored if not reached. It is not a causal headline-response latency. Requested quantities unavailable for rules; fills come from actual trades.")


def probe_agent(case,client=None,budget=None,log_fn=None,*,transport_retries=0,retry_http_503=False):
    obs=Observation(**case["observation"])
    agent=LLMAgent(case["case_id"],obs.my_cash,obs.my_shares,np.random.default_rng(0),
        params=dict(condition="A",memory_window=5,max_tokens=4096,tick=.1,transport_retries=transport_retries,retry_http_503=retry_http_503),persona=case["persona"],
        client=client,budget=budget,log_fn=log_fn,temperature=.3,
        initial_price=obs.price_history[-1],initial_cost=obs.my_avg_cost)
    agent.memory=case["memory"]
    return agent


def extract_probes(control_path,seed):
    root=Path(control_path);cfg=load_config(root/"config.yaml")
    prices=read_rows(root/"prices.csv");trades=read_rows(root/"trades.csv")
    accounts={r["agent_id"]:r for r in read_rows(root/"agents_state.csv") if int(r["round"])==EVENT_ROUND-1}
    personas=json.loads((root/"personas.json").read_text())
    calls=[r for r in json_lines(root/"llm_requests.jsonl") if r["record_type"]=="model_call" and r["round"]==EVENT_ROUND
           and r["call_id"].rsplit(":",1)[-1]=="1"]
    outcomes=json_lines(root/"agent_outcomes.jsonl");result=[]
    assert len(calls)==2 and not cfg.reveal_fundamental
    for call in calls:
        aid=call["agent_id"];account=accounts[aid]
        history=[cfg.asset.initial_price]+[float(r["price"]) for r in prices[:EVENT_ROUND-1]]
        recent=[]
        for t in trades:
            if int(t["round"])>=EVENT_ROUND:continue
            if aid in (t["buyer_id"],t["seller_id"]):
                verb="bought" if aid==t["buyer_id"] else "sold"
                recent.append(f"r{t['round']}: {verb} {t['quantity']} @ {float(t['price']):.2f}")
        memory=[r["outcome"] for r in outcomes if r["agent_id"]==aid and r["outcome"]["round"]<EVENT_ROUND][-5:]
        previous=prices[EVENT_ROUND-2]
        obs=Observation(EVENT_ROUND,ROUNDS,history[-cfg.observation.price_history_len:],int(previous["volume"]),
            float(previous["dividend"]),cfg.asset.risk_free,None,[],[],float(account["cash"]),int(account["shares"]),
            float(account["avg_cost"]),float(account["wealth"]),recent[-5:],cfg.time.round_unit)
        for announce in (False,True):
            raw=asdict(obs);raw["news"]=[HEADLINE] if announce else []
            case=dict(case_id=f"s{seed}_{aid}_{'announced' if announce else 'silent'}",seed=seed,agent_id=aid,
                announce=announce,observation=raw,persona=personas[aid],memory=memory,
                source_run=str(root),source_manifest_sha256=sha256(root/"manifest.json"),source_call_id=call["call_id"])
            agent=probe_agent(case)
            case["messages"]=[dict(role="system",content=agent.system_prompt("KGP")),dict(role="user",content=agent.user_prompt(Observation(**raw)))]
            if not announce and case["messages"]!=call["messages"]:
                raise ValueError("actual event snapshot did not reproduce original prompt")
            result.append(case)
    return result


def run_probes(root,cases,pacer,*,transport_retries=0,retry_http_503=False,max_requests=48,max_reserved_tokens=1000000):
    root=Path(root);target=root/"same_state_probes";target.mkdir()
    schedule=[dict(case_id=c["case_id"],repetition=n) for n in (1,2,3) for c in (cases if n!=2 else list(reversed(cases)))]
    write_json(target/"battery.json",dict(version=VERSION,cases=cases,schedule=schedule,
        scope="Actual control-market round-11 frames, only headline availability changes. Fresh independent requests; no executions or market effects. State/wording fixed before these calls."))
    cfg=market_recipe(SEEDS[0],"control","qwen").to_dict()
    cfg["name"]="news_same_state_probes";cfg["llm_limits"]["max_requests"]=max_requests
    cfg["llm_limits"]["max_reserved_tokens"]=max_reserved_tokens
    cfg["agents"][-1]["llm"]["transport_retries"]=transport_retries
    cfg["agents"][-1]["llm"]["retry_http_503"]=retry_http_503
    cfg=parse_config(cfg);llm=cfg.agents[-1].llm
    (target/"config.yaml").write_text(yaml.safe_dump(cfg.to_dict()),encoding="utf-8")
    manifest=start_manifest(target,cfg)
    manifest.update(experiment_kind="same_state_news_queries",endpoints=[llm.base_url],battery_sha256=sha256(target/"battery.json"),
        config_scope="Driver/profile only. Snapshot accounts/personas/exact messages in battery.json; no financial rounds.")
    write_json(target/"manifest.json",manifest)
    client=LLMClient(model=llm.model,base_url=llm.base_url,timeout=llm.timeout_seconds,reasoning_effort=llm.reasoning_effort)
    budget=UsageBudget(**asdict(cfg.llm_limits));budget.pacer=pacer
    definitions={c["case_id"]:c for c in cases};results=[];status="running";failure_type=None;current={}
    with (target/"llm_requests.jsonl").open("w",encoding="utf-8") as stream:
        def record(item):stream.write(json.dumps({**item,**current},allow_nan=False)+"\n");stream.flush()
        try:
            for item in schedule:
                current=dict(item);case=definitions[item["case_id"]]
                agent=probe_agent(case,client,budget,record,transport_retries=transport_retries,retry_http_503=retry_http_503);obs=Observation(**case["observation"])
                agent.agent_id=f"{case['case_id']}:r{item['repetition']}"
                messages=[dict(role="system",content=agent.system_prompt("KGP")),dict(role="user",content=agent.user_prompt(obs))]
                if messages!=case["messages"]:raise ValueError("snapshot prompt drift")
                before=budget.requests;order=agent.decide(obs)
                choice={**item,**score_choice(agent,order,obs),"request_count":budget.requests-before}
                results.append(choice);write_json(target/"results.json",results)
                write_json(target/"progress.json",dict(completed_decisions=len(results),planned_decisions=len(schedule),llm_usage=budget.snapshot()))
                if not choice["valid_choice"]:status="parse_failure";break
            else:status="completed"
        except (ProviderUnavailable,UsageLimitExceeded) as exc:
            status="provider_error" if isinstance(exc,ProviderUnavailable) else "output_truncated" if isinstance(exc,OutputLimitExceeded) else "budget_exhausted"
            failure_type=type(exc).__name__
        except BaseException as exc:
            status="interrupted" if isinstance(exc,KeyboardInterrupt) else "failed"
            failure_type=type(exc).__name__
            raise
        finally:
            write_json(target/"results.json",results)
            summary=dict(status=status,rounds=0,completed_decisions=len(results),planned_decisions=len(schedule),
                         failure_type=failure_type,llm_usage=budget.snapshot())
            write_json(target/"summary.json",summary);stream.flush();finish_manifest(target,manifest,summary)
    return summary


def execute(root):
    root=Path(root);study=load_study(root)
    if (root/"execution.json").exists():raise ValueError("study already started; inspect artifacts, never blindly restart")
    write_json(root/"execution.json",dict(started_utc=datetime.now(timezone.utc).isoformat(),pid=os.getpid(),study_sha256=sha256(root/"study.json")))
    pacer=RequestPacer(10,60000);index=[];status="running";failure_type=None
    try:
        for item in study["schedule"]:
            write_json(root/"progress.json",dict(status=status,completed_markets=len(index),active=item))
            path=Path(run(root/item["config"],output_root=root/"market_runs",request_pacer=pacer if item["brain"]=="qwen" else None))
            summary=json.loads((path/"summary.json").read_text())
            entry={**item,"run_path":path.relative_to(root).as_posix(),"status":summary["status"],"parse_failures":summary["parse_failures"],"manifest_sha256":sha256(path/"manifest.json"),"usage":summary["llm_usage"]}
            index.append(entry);write_json(root/"runs.json",index)
            if summary["status"]!="completed" or summary["rounds"]!=ROUNDS or summary["parse_failures"]:
                status="stopped";failure_type=summary["failure_type"] or "persistent_parse_failure";break
            write_json(root/f"metrics_{item['brain']}_{item['cell']}_{item['seed']}.json",market_metrics(path))
            print(f"study market {len(index)}/16: {item['brain']} {item['cell']} seed {item['seed']}",flush=True)
            if len(index)==8:
                # Do not spend API calls until the complete rule negative controls pass.
                for seed in SEEDS:
                    paths={e["cell"]:root/e["run_path"] for e in index if e["seed"]==seed}
                    for a,b in (("control","headline_only"),("fundamentals_only","combined")):
                        for name in FINANCIAL_FILES:assert (paths[a]/name).read_bytes()==(paths[b]/name).read_bytes()
        else:
            cases=[]
            for seed in SEEDS:
                control=next(e for e in index if e["brain"]=="qwen" and e["cell"]=="control" and e["seed"]==seed)
                cases.extend(extract_probes(root/control["run_path"],seed))
            write_json(root/"progress.json",dict(status="running",completed_markets=16,active={"phase":"same_state_probes"}))
            probe_summary=run_probes(root,cases,pacer)
            status="completed" if probe_summary["status"]=="completed" else "stopped"
            failure_type=probe_summary["failure_type"] or (probe_summary["status"] if status!="completed" else None)
    except BaseException as exc:
        status="interrupted" if isinstance(exc,KeyboardInterrupt) else "failed";failure_type=type(exc).__name__
        raise
    finally:
        completed=sum(e["status"]=="completed" for e in index)
        write_json(root/"summary.json",dict(status=status,completed_markets=completed,recorded_market_arms=len(index),
            usable_markets=sum(e["status"]=="completed" and not e["parse_failures"] for e in index),planned_markets=16,
            failure_type=failure_type,finished_utc=datetime.now(timezone.utc).isoformat(),study_sha256=sha256(root/"study.json")))
        write_json(root/"progress.json",dict(status=status,completed_markets=completed,recorded_market_arms=len(index),active=None))
    print(f"{status} study -> {root}",flush=True)
    return root


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("action",choices=("prepare","run"))
    parser.add_argument("--study");parser.add_argument("--output-root",default="runs");args=parser.parse_args()
    if args.action=="prepare":prepare(args.output_root)
    else:
        if not args.study:parser.error("run requires --study; preparation never calls an API")
        execute(args.study)
