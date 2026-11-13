"""Linked R023 delivery phase: only unfinished arms, explicit per-HTTP retries."""
import argparse
import ast
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import zipfile

import yaml

from sim.config import load_config,parse_config
from sim.engine import run
from sim.llm.usage import RequestPacer
from sim.news_pilot import SEEDS,extract_probes,market_metrics,run_probes
from sim.provenance import sha256,write_json

ROOT=Path(__file__).resolve().parents[1]
STUDY=ROOT/"runs/20261102_202946_news_pilot_786a0370"
RECOVERY=STUDY/"recovery_transport_v3"


def source_checks():
    original=json.loads((STUDY/"study.json").read_text())
    assert sha256(STUDY/"study.json")=="0a901d2fc24f41d5c7a2207c741f46a34df14e60d1ad0b61733eb621c72d7355"
    allowed={"sim/config.py","sim/agents/llm_agent.py","sim/engine.py","sim/provenance.py","sim/news_pilot.py"}
    changed={name for name,digest in original["source_sha256"].items() if sha256(ROOT/name)!=digest}
    assert changed==allowed,changed
    with zipfile.ZipFile(STUDY/"prepared_source.zip") as archive:
        old_agent=ast.parse(archive.read("sim/agents/llm_agent.py"));new_agent=ast.parse((ROOT/"sim/agents/llm_agent.py").read_text())
        names={"SYSTEM_TEMPLATE","USER_TEMPLATE","REFLECTION_TEMPLATE","MARKET_RULES_TEMPLATE","PROMPT_VERSION","CONDITION_VERSIONS"}
        def constants(tree):
            return {n.targets[0].id:ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign)
                    and isinstance(n.targets[0],ast.Name) and n.targets[0].id in names}
        assert constants(old_agent)==constants(new_agent)
        def methods(tree):
            cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=="LLMAgent")
            return {n.name:ast.dump(n,include_attributes=False) for n in cls.body if isinstance(n,ast.FunctionDef)}
        old,new=methods(old_agent),methods(new_agent)
        for name in ("system_prompt","user_prompt","factual_summary","decide","end_round","reflect_if_due","_extract_json"):
            assert old[name]==new[name],name
        class StripDeliveryCounters(ast.NodeTransformer):
            def visit_Dict(self,node):
                self.generic_visit(node)
                pairs=[(k,v) for k,v in zip(node.keys,node.values) if not
                       (isinstance(k,ast.Constant) and k.value in ("transport_retries","json_repairs"))]
                node.keys=[k for k,v in pairs];node.values=[v for k,v in pairs];return node
        old_engine=ast.parse(archive.read("sim/engine.py"));new_engine=ast.parse((ROOT/"sim/engine.py").read_text())
        strip=StripDeliveryCounters()
        assert ast.dump(strip.visit(old_engine),include_attributes=False)==ast.dump(strip.visit(new_engine),include_attributes=False)
    return dict(changed_files=sorted(changed),protected_prompt_policy_methods_equal=True,
                engine_equal_after_delivery_parameters_and_summary_counters_removed=True)


def prepare():
    checks=source_checks();study=json.loads((STUDY/"study.json").read_text())
    prior=json.loads((STUDY/"runs.json").read_text())+json.loads((STUDY/"continuation_1/runs.json").read_text())
    assert len(prior)==13
    complete=[r for r in prior if r["status"]=="completed" and not r["parse_failures"]]
    done={(r["brain"],r["seed"],r["cell"]) for r in complete}
    prepared=[]
    for item in study["schedule"]:
        key=(item["brain"],item["seed"],item["cell"])
        if key in done:continue
        cfg=load_config(STUDY/item["config"]).to_dict();reference=load_config(STUDY/item["config"]).to_dict()
        used=[r for r in prior if (r["brain"],r["seed"],r["cell"])==key]
        cfg["llm_limits"]["max_requests"]-=sum(r["usage"]["requests_made"] for r in used)
        cfg["llm_limits"]["max_reserved_tokens"]-=sum(r["usage"]["reserved_tokens"] for r in used)
        cfg["agents"][-1]["llm"]["transport_retries"]=1
        reference["agents"][-1]["llm"]["transport_retries"]=1
        assert {k:v for k,v in cfg.items() if k!="llm_limits"}=={k:v for k,v in reference.items() if k!="llm_limits"}
        prepared.append((item,parse_config(cfg)))
    assert len(complete)==11 and len(prepared)==5
    assert sum(r["usage"]["requests_made"] for r in prior)+sum(c.llm_limits.max_requests for _,c in prepared)+48<=688
    assert sum(r["usage"]["reserved_tokens"] for r in prior)+sum(c.llm_limits.max_reserved_tokens for _,c in prepared)+1000000<=9000000
    RECOVERY.mkdir(exist_ok=False);(RECOVERY/"configs").mkdir()
    schedule=[]
    for item,cfg in prepared:
        path=RECOVERY/"configs"/Path(item["config"]).name
        path.write_text(yaml.safe_dump(cfg.to_dict()),encoding="utf-8")
        schedule.append({**item,"config":path.relative_to(RECOVERY).as_posix(),"config_sha256":sha256(path)})
    source={p.relative_to(ROOT).as_posix():sha256(p) for p in sorted((ROOT/"sim").rglob("*.py"))}
    with zipfile.ZipFile(RECOVERY/"prepared_source.zip","w",zipfile.ZIP_DEFLATED) as archive:
        for name in source:archive.write(ROOT/name,name)
    shutil.copyfile(Path(__file__),RECOVERY/"driver_source.py")
    write_json(RECOVERY/"plan.json",dict(version="news_delivery_recovery_v3_retry1",status="frozen_before_calls",
        source_checks=checks,source_sha256=source,source_archive_sha256=sha256(RECOVERY/"prepared_source.zip"),
        driver_sha256=sha256(Path(__file__)),original_study_sha256=sha256(STUDY/"study.json"),
        parent_summaries={str(p.relative_to(STUDY)):sha256(p) for p in (STUDY/"summary.json",STUDY/"continuation_1/summary.json")},
        parent_revision=subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip(),
        working_tree_status=subprocess.check_output(["git","status","--short"],cwd=ROOT,text=True).splitlines(),
        prior_attempts=prior,completed_prefix=complete,schedule=schedule,
        bounds=dict(previous_requests=142,previous_reservations=1709925,remaining_market_request_caps=[c.llm_limits.max_requests for _,c in prepared],
                    remaining_market_reservation_caps=[c.llm_limits.max_reserved_tokens for _,c in prepared],probe_requests=48,probe_reservations=1000000),
        decision="User resumed. One opt-in logged/paced/budgeted transport retry per request group; no HTTP/certificate/output-cap retries. Fresh full combined/1441 arm; retain its previous nine-round partial separately, never pool prefixes. Other four arms unstarted. No restart of completed data. Model/prompts/policy/economics unchanged; delivery handling/source/profile version differs. No further phase restart on terminal failure.",
        limitations="Linked phases over different times; unknown failed usage retained. This is feasibility, not an uninterrupted replication or a causal before/after transport-performance comparison."))
    print(json.dumps(dict(recovery=str(RECOVERY),checks=checks,remaining=5,
                         first_limits=prepared[0][1].to_dict()["llm_limits"]),indent=2))


def execute():
    plan=json.loads((RECOVERY/"plan.json").read_text())
    assert sha256(Path(__file__))==plan["driver_sha256"]
    for name,digest in plan["source_sha256"].items():assert sha256(ROOT/name)==digest,name
    for name,digest in plan["parent_summaries"].items():assert sha256(STUDY/name)==digest
    for item in plan["schedule"]:assert sha256(RECOVERY/item["config"])==item["config_sha256"]
    # Exclusive marker prevents even simultaneous duplicate starts.
    with (RECOVERY/"execution.json").open("x") as stream:
        json.dump(dict(pid=os.getpid(),started_utc=datetime.now(timezone.utc).isoformat(),plan_sha256=sha256(RECOVERY/"plan.json")),stream)
    pacer=RequestPacer(10,60000);index=[];status="running";failure_type=None
    try:
        for item in plan["schedule"]:
            write_json(RECOVERY/"progress.json",dict(status=status,completed_markets=len(index),active=item))
            path=Path(run(RECOVERY/item["config"],output_root=RECOVERY/"market_runs",request_pacer=pacer))
            summary=json.loads((path/"summary.json").read_text())
            entry={**item,"run_path":path.relative_to(STUDY).as_posix(),"status":summary["status"],
                   "parse_failures":summary["parse_failures"],"manifest_sha256":sha256(path/"manifest.json"),"usage":summary["llm_usage"]}
            index.append(entry);write_json(RECOVERY/"runs.json",index)
            if summary["status"]!="completed" or summary["rounds"]!=20 or summary["parse_failures"]:
                status="stopped";failure_type=summary["failure_type"] or "persistent_parse_failure";break
            write_json(RECOVERY/f"metrics_{item['brain']}_{item['cell']}_{item['seed']}.json",market_metrics(path))
            print(f"recovery market {len(index)}/5 {item['cell']} seed {item['seed']}",flush=True)
        else:
            complete=plan["completed_prefix"]+index;cases=[]
            for seed in SEEDS:
                control=next(r for r in complete if r["brain"]=="qwen" and r["seed"]==seed and r["cell"]=="control")
                cases.extend(extract_probes(STUDY/control["run_path"],seed))
            write_json(RECOVERY/"progress.json",dict(status="running",completed_markets=5,active={"phase":"same_state_probes"}))
            probes=run_probes(RECOVERY,cases,pacer,transport_retries=1)
            status="completed_through_delivery_recovery" if probes["status"]=="completed" else "stopped"
            failure_type=probes["failure_type"] or (probes["status"] if status=="stopped" else None)
    except BaseException as exc:
        status="interrupted" if isinstance(exc,KeyboardInterrupt) else "failed";failure_type=type(exc).__name__
        raise
    finally:
        completed=plan["completed_prefix"]+[r for r in index if r["status"]=="completed" and not r["parse_failures"]]
        write_json(RECOVERY/"completed_market_index.json",completed)
        write_json(RECOVERY/"all_attempted_markets.json",plan["prior_attempts"]+index)
        write_json(RECOVERY/"summary.json",dict(status=status,completed_markets=len(completed),recorded_recovery_arms=len(index),
            failure_type=failure_type,finished_utc=datetime.now(timezone.utc).isoformat(),plan_sha256=sha256(RECOVERY/"plan.json")))
        write_json(RECOVERY/"progress.json",dict(status=status,completed_markets=sum(r["status"]=="completed" for r in index),active=None))
    print(f"{status} -> {RECOVERY}",flush=True)


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("action",choices=("prepare","run"));args=parser.parse_args()
    prepare() if args.action=="prepare" else execute()
