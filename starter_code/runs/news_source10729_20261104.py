"""R035: explicit independent-source gate for ONLY R033's untouched source10729."""
import argparse
from dataclasses import asdict
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import shutil
import time
import uuid
import zipfile
import yaml
import sim.engine as engine
from sim.config import load_config,parse_config
from sim.llm.client import LLMClient
from sim.llm.usage import UsageBudget,RequestPacer,ProviderUnavailable,UsageLimitExceeded
from sim.provenance import sha256,write_json,start_manifest,finish_manifest
from runs import news_auctions_20261104 as parent
from runs.horizon_pilot_20261104 import visibility

BASE=parent.BASE
PARENT=BASE/"runs/20261104_055619_news_auctions_a2e319da"
VERSION="news_source_independent_gate_10729_v1"
read=parent.read

def inventory(root):return {p.relative_to(root).as_posix():sha256(p) for p in root.rglob("*") if p.is_file()}

def prepare(output_root="runs"):
    p=parent.validate(PARENT);s=read(PARENT/"summary.json");entries=read(PARENT/"source_runs.json")
    assert s["status"]=="stopped" and [(e["seed"],e["rounds"]) for e in entries]==[(9623,0)]
    assert s["usage"]["requests_made"]==2 and s["usage"]["reserved_tokens"]==22284 and not (PARENT/"queries").exists()
    e=next(e for e in p["configs"] if e["seed"]==10729 and e["mode"]=="A")
    root=Path(output_root)/(time.strftime("%Y%m%d_%H%M%S_")+"news_source10729_"+uuid.uuid4().hex[:8]);root.mkdir(parents=True,exist_ok=False);(root/"configs").mkdir()
    shutil.copyfile(PARENT/e["config"],root/"configs/source.yaml");shutil.copyfile(__file__,root/"driver_source.py")
    sources={**p["source_sha256"],"runs/news_source10729_20261104.py":sha256(__file__)}
    with zipfile.ZipFile(root/"prepared_source.zip","w",zipfile.ZIP_DEFLATED) as z:
        for n in sources:z.write(BASE/n,n)
    protocol=dict(version=VERSION,status="frozen_before_new_calls",created_utc=datetime.now(timezone.utc).isoformat(),parent_path=str(PARENT),parent_inventory=inventory(PARENT),parent_protocol_sha256=sha256(PARENT/"protocol.json"),prior_usage=s["usage"],
        source_config_sha256=sha256(root/"configs/source.yaml"),source_sha256=sources,source_archive_sha256=sha256(root/"prepared_source.zip"),driver_sha256=sha256(__file__),
        amendment="User proceed authorizes source-independent gating for ONLY originally unattempted10729. Failed9623 stays missing; never restart/substitute it. If clean10729 and exact history/replay/rule gates pass, execute only original frame-index2/3 cases. R033's both-sources gate explicitly relaxed before calls. No other factor changed.",
        prompt_note="Original common-hidden A research variant, Qwen8192/low/temp.3/180s/memory5/no reflection. Original continuing-stock/system/economics/personas/public info. Initial source prompt may match failed9623; this starts a different originally planned exogenous seed, not a path restart or seeded provider sampling.",
        schedule="One original6-round source10729; frames2/6.18 original scheduled conditional auctions,36 fresh decisions. Same original absolute frame indices2/3, headline and actor rotation; missing9623 contributes no generated frames/trials. No data/response/headroom filtering.",
        primary=p["primary"],economics=p["economics"],rules=p["rules"],
        limits=dict(source_max_requests=40,source_max_reservations=600000,query_max_requests=54,query_max_reservations=1000000,phase_max_requests=94,phase_max_reservations=1600000,campaign_max_requests=188,campaign_max_reservations=3200000),
        failure_policy=p["failure_policy"]+" No next seed/delivery phase after this gate; parent partial/unknowns retained. Existing one-extra transport/503 limit unchanged.",
        limitations="Only ONE fresh source history, two correlated frames,3 reply draws/headline; not the completed two-history R033 or independent full-market repetitions. Joint conditional one-auction outcomes, not sequential feedback, lasting price discovery, trait/human validation or uniform news effect. Do not pool with R0344096/v2 shown-length retrospective replies. No new default/ABC/model switch.")
    write_json(root/"protocol.json",protocol);write_json(root/"preparation.json",dict(protocol_sha256=sha256(root/"protocol.json")))
    print(f"prepared -> {root}",flush=True);return root

def validate(root):
    root=Path(root);p=read(root/"protocol.json");parent.validate(PARENT)
    if p["version"]!=VERSION or sha256(root/"protocol.json")!=read(root/"preparation.json")["protocol_sha256"]:raise ValueError("protocol drift")
    if inventory(PARENT)!=p["parent_inventory"]:raise ValueError("parent evidence drift")
    for n,d in p["source_sha256"].items():
        if sha256(BASE/n)!=d:raise ValueError("source drift")
    for path,d in ((root/"configs/source.yaml",p["source_config_sha256"]),(root/"driver_source.py",p["driver_sha256"]),(root/"prepared_source.zip",p["source_archive_sha256"])):
        if sha256(path)!=d:raise ValueError("config/archive drift")
    return p

def freeze_battery(root,path):
    root=Path(root);frames=parent.extract_frames(path,10729);assert [(f["seed"],f["round"]) for f in frames]==[(10729,2),(10729,6)]
    controls=[]
    for f in frames:
        bynews={n:parent.settlements(f,parent.rule_choices(f,n)) for n in parent.NEWS}
        assert bynews["silent"]==bynews["positive"]==bynews["negative"]
        controls.append(dict(frame_id=f["frame_id"],orders={a:asdict(o) for a,o in parent.rule_choices(f,"silent").items()},settlements=bynews["silent"],headline_negative_control=True,source_auction_exactly_reproduced=True))
    schedule=[];names=list(parent.NEWS)
    for rep in (1,2,3):
        for idx in ((2,3) if rep!=2 else (3,2)):
            order=names[(idx+rep-1)%3:]+names[:(idx+rep-1)%3]
            for ni,n in enumerate(order):schedule.append(dict(case_id=f"{frames[idx-2]['frame_id']}_{n}_rep{rep}",frame_id=frames[idx-2]["frame_id"],headline=n,repetition=rep,agent_order=list(parent.TARGETS if (idx+rep+ni)%2 else reversed(parent.TARGETS))))
    b=dict(version=parent.VERSION,phase_version=VERSION,frames=frames,schedule=schedule,rule_controls=controls,missing_parent_source=9623)
    write_json(root/"battery.json",b);write_json(root/"battery_seal.json",dict(sha256=sha256(root/"battery.json")));return b

def queries(root,battery,pacer):
    root=Path(root);q=root/"queries";q.mkdir(exist_ok=False)
    cfg=load_config(root/"configs/source.yaml").to_dict();cfg["name"]="news10729_conditional_auctions";cfg["llm_limits"].update(max_requests=54,max_reserved_tokens=1000000);cfg=parse_config(cfg)
    (q/"config.yaml").write_text(yaml.safe_dump(cfg.to_dict()),encoding="utf-8");shutil.copyfile(root/"battery.json",q/"battery.json")
    manifest=start_manifest(q,cfg);manifest.update(experiment_kind=parent.VERSION,phase_version=VERSION,protocol_sha256=sha256(root/"protocol.json"),battery_sha256=sha256(root/"battery.json"),driver_sha256=sha256(__file__),config_scope="Profile only; actual10729 snapshot accounts/prompts/orderbooks/RNG in battery. Parent9623 remains missing.")
    write_json(q/"manifest.json",manifest);budget=UsageBudget(**asdict(cfg.llm_limits));budget.pacer=pacer;llm=cfg.agents[-1].llm
    frames={f["frame_id"]:f for f in battery["frames"]};index=[];choices=[];status="running";failure=None;current=None
    with (q/"llm_requests.jsonl").open("w",encoding="utf-8") as req,(q/"llm_calls.jsonl").open("w",encoding="utf-8") as calls:
        def log(item):
            row={**item,**current,"phase_version":VERSION,"study_call_id":current["case_id"]+"::"+item.get("call_id",item.get("agent_id","")),"study_request_group_id":current["case_id"]+"::"+item.get("request_group_id","")}
            stream=req if item["record_type"] in ("model_call","request_blocked") else calls;stream.write(json.dumps(row,allow_nan=False)+"\n");stream.flush()
        try:
            for item in battery["schedule"]:
                current=dict(item);write_json(root/"progress.json",dict(status="queries_running",completed_auctions=len(index),planned_phase_auctions=18,active=item,llm_usage=budget.snapshot()))
                frame=frames[item["frame_id"]];orders={}
                for aid in item["agent_order"]:
                    client=LLMClient(model=llm.model,base_url=llm.base_url,timeout=llm.timeout_seconds,reasoning_effort=llm.reasoning_effort,send_temperature=llm.send_temperature)
                    agent,obs=parent.case_agent(frame,aid,item["headline"],client,budget,log)
                    actual=[dict(role="system",content=agent.system_prompt("KGP")),dict(role="user",content=agent.user_prompt(obs))];assert actual==frame["messages"][item["headline"]][aid]
                    order=agent.decide(obs);valid=not any((agent.parse_failures,agent.api_failures,agent.output_truncations))
                    choices.append({**item,"agent_id":aid,"intent":agent.last_intent,"accepted":asdict(order),"valid":valid});write_json(q/"choices.json",choices)
                    if not valid:raise ValueError("operational_fallback_no_joint_settlement")
                    orders[aid]=order
                index.append({**item,"settlements":parent.settlements(frame,orders)});write_json(q/"auctions.json",index)
            status="completed_phase_schedule"
        except (ProviderUnavailable,UsageLimitExceeded) as exc:status="stopped";failure=type(exc).__name__
        except BaseException as exc:
            status="interrupted" if isinstance(exc,KeyboardInterrupt) else "failed";failure=type(exc).__name__
            if not isinstance(exc,ValueError) or str(exc)!="operational_fallback_no_joint_settlement":raise
        finally:
            summary=dict(status=status,rounds=0,completed_auctions=len(index),planned_auctions=18,original_study_planned_auctions=36,delivered_choices=len(choices),failure_type=failure,incomplete_case=current if status!="completed_phase_schedule" else None,llm_usage=budget.snapshot(),finished_utc=datetime.now(timezone.utc).isoformat())
            write_json(q/"summary.json",summary);req.flush();calls.flush();finish_manifest(q,manifest,summary)
    return summary

def execute(root):
    root=Path(root);p=validate(root)
    if (root/"execution.json").exists():raise ValueError("phase already started")
    if any((x/"execution.json").exists() for x in root.parent.glob("*_news_source10729_*") if x.resolve()!=root.resolve()):raise ValueError("10729 already attempted in another phase")
    with (root/"execution.json").open("x") as f:json.dump(dict(pid=os.getpid(),started_utc=datetime.now(timezone.utc).isoformat(),protocol_sha256=sha256(root/"protocol.json")),f)
    pacer=RequestPacer(10,60000);source=None;query=None;status="running";failure=None
    try:
        write_json(root/"progress.json",dict(status="source_running",active=dict(seed=10729),completed_auctions=0))
        with visibility("hidden"):path=Path(engine.run(root/"configs/source.yaml",output_root=root/"source_runs",request_pacer=pacer))
        summary=read(path/"summary.json");parent.verify_market(path)
        source=dict(seed=10729,mode="A",run_path=path.relative_to(root).as_posix(),manifest_sha256=sha256(path/"manifest.json"),status=summary["status"],rounds=summary["rounds"],usage=summary["llm_usage"]);write_json(root/"source_runs.json",[source])
        if summary["status"]!="completed" or summary["rounds"]!=6 or any(summary[k] for k in ("parse_failures","api_failures","output_truncations")):status="stopped";failure=summary["failure_type"] or "operational_fallback"
        else:query=queries(root,freeze_battery(root,path),pacer);status=query["status"];failure=query["failure_type"]
    except BaseException as exc:
        status="interrupted" if isinstance(exc,KeyboardInterrupt) else "failed";failure=type(exc).__name__;raise
    finally:
        if query is None and (root/"queries/summary.json").exists():query=read(root/"queries/summary.json")
        usage={k:(source["usage"][k] if source else 0)+(query["llm_usage"][k] if query else 0) for k in parent.USAGE}
        cumulative={k:usage[k]+p["prior_usage"][k] for k in usage}
        assert usage["requests_made"]<=94 and usage["reserved_tokens"]<=1600000 and cumulative["requests_made"]<=188 and cumulative["reserved_tokens"]<=3200000
        s=dict(status=status,completed_sources=int(bool(source and source["status"]=="completed" and source["rounds"]==6)),planned_phase_sources=1,original_study_planned_sources=2,completed_auctions=0 if not query else query["completed_auctions"],planned_phase_auctions=18,original_study_planned_auctions=36,missing_source9623=True,failure_type=failure,usage=usage,cumulative_usage=cumulative,finished_utc=datetime.now(timezone.utc).isoformat())
        write_json(root/"summary.json",s);write_json(root/"progress.json",dict(**s,active=None))
    print(f"{status} -> {root}",flush=True);return root

if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("action",choices=("prepare","run"));parser.add_argument("--study");parser.add_argument("--output-root",default="runs");a=parser.parse_args()
    if a.action=="prepare":prepare(a.output_root)
    else:execute(a.study)
