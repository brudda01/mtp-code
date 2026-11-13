"""One explicit post-transport-error continuation, never a hidden HTTP retry."""
import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import shutil

import yaml

from sim.config import load_config,parse_config
from sim.engine import run
from sim.llm.usage import RequestPacer
from sim.news_pilot import SEEDS,extract_probes,load_study,market_metrics,run_probes
from sim.provenance import sha256,write_json

STUDY=Path(__file__).resolve().parent/"20261102_202946_news_pilot_786a0370"
CONT=STUDY/"continuation_1"


def prepare():
    study=load_study(STUDY)
    parent=json.loads((STUDY/"summary.json").read_text())
    index=json.loads((STUDY/"runs.json").read_text())
    assert parent["status"]=="stopped" and len(index)==10
    failed=index[-1];summary=json.loads((STUDY/failed["run_path"] / "summary.json").read_text())
    assert failed["status"]=="provider_error" and summary["rounds"]==0
    completed=[r for r in index if r["status"]=="completed" and not r["parse_failures"]]
    done={(r["brain"],r["seed"],r["cell"]) for r in completed}
    remaining=[]
    for item in study["schedule"]:
        key=(item["brain"],item["seed"],item["cell"])
        if key in done:continue
        cfg=load_config(STUDY/item["config"]).to_dict()
        if key==(failed["brain"],failed["seed"],failed["cell"]):
            cfg["llm_limits"]["max_requests"]-=failed["usage"]["requests_made"]
            cfg["llm_limits"]["max_reserved_tokens"]-=failed["usage"]["reserved_tokens"]
        validated=parse_config(cfg)
        original=load_config(STUDY/item["config"]).to_dict()
        check=validated.to_dict()
        assert {k:v for k,v in check.items() if k!="llm_limits"}=={k:v for k,v in original.items() if k!="llm_limits"}
        remaining.append((item,validated))
    assert len(completed)==9 and len(remaining)==7
    assert sum(r["usage"]["requests_made"] for r in index)+sum(c.llm_limits.max_requests for _,c in remaining)+48<=688
    assert sum(r["usage"]["reserved_tokens"] for r in index)+sum(c.llm_limits.max_reserved_tokens for _,c in remaining)+1000000<=9000000
    CONT.mkdir(exist_ok=False);(CONT/"configs").mkdir()
    schedule=[]
    for item,cfg in remaining:
        path=CONT/"configs"/Path(item["config"]).name
        path.write_text(yaml.safe_dump(cfg.to_dict()),encoding="utf-8")
        schedule.append({**item,"config":path.relative_to(CONT).as_posix(),"config_sha256":sha256(path)})
    shutil.copyfile(Path(__file__),CONT/"driver_source.py")
    write_json(CONT/"plan.json",dict(status="prepared_before_calls",parent_study_sha256=sha256(STUDY/"study.json"),
        parent_summary_sha256=sha256(STUDY/"summary.json"),driver_sha256=sha256(Path(__file__)),
        completed_prefix=completed,failed_prefix=[failed],schedule=schedule,
        decision="Manual single continuation after reviewing URLError/no HTTP status. Original study remains stopped. Restart only the failed zero-financial-round arm with fresh responses, then unstarted arms. Do not pool its unexecuted prefix. Economic/prompt/model/source settings unchanged; used attempts/reservations deducted from its arm cap. If another failure occurs, stop without further restart.",
        limitations="Separate delivery times/phase; not an uninterrupted study. Unknown failed usage remains in reliability. No favourable-response selection."))
    print(json.dumps(dict(continuation=str(CONT),remaining_markets=len(schedule),
        first_limits=remaining[0][1].to_dict()["llm_limits"],parent_attempts=sum(r["usage"]["requests_made"] for r in index)),indent=2))


def execute():
    load_study(STUDY)
    plan=json.loads((CONT/"plan.json").read_text())
    assert sha256(Path(__file__))==plan["driver_sha256"]
    assert sha256(STUDY/"study.json")==plan["parent_study_sha256"]
    assert sha256(STUDY/"summary.json")==plan["parent_summary_sha256"]
    for item in plan["schedule"]:assert sha256(CONT/item["config"])==item["config_sha256"]
    if (CONT/"execution.json").exists():raise ValueError("continuation already started; never restart blindly")
    write_json(CONT/"execution.json",dict(pid=os.getpid(),started_utc=datetime.now(timezone.utc).isoformat(),plan_sha256=sha256(CONT/"plan.json")))
    pacer=RequestPacer(10,60000);index=[];status="running";failure_type=None
    try:
        for item in plan["schedule"]:
            write_json(CONT/"progress.json",dict(status=status,completed_markets=len(index),active=item))
            path=Path(run(CONT/item["config"],output_root=CONT/"market_runs",request_pacer=pacer))
            summary=json.loads((path/"summary.json").read_text())
            entry={**item,"run_path":path.relative_to(STUDY).as_posix(),"status":summary["status"],
                "parse_failures":summary["parse_failures"],"manifest_sha256":sha256(path/"manifest.json"),"usage":summary["llm_usage"]}
            index.append(entry);write_json(CONT/"runs.json",index)
            if summary["status"]!="completed" or summary["rounds"]!=20 or summary["parse_failures"]:
                status="stopped";failure_type=summary["failure_type"] or "persistent_parse_failure";break
            write_json(STUDY/f"metrics_{item['brain']}_{item['cell']}_{item['seed']}.json",market_metrics(path))
            print(f"continuation market {len(index)}/7 {item['cell']} seed {item['seed']}",flush=True)
        else:
            completed=plan["completed_prefix"]+index
            cases=[]
            for seed in SEEDS:
                control=next(r for r in completed if r["brain"]=="qwen" and r["seed"]==seed and r["cell"]=="control")
                cases.extend(extract_probes(STUDY/control["run_path"],seed))
            write_json(CONT/"progress.json",dict(status="running",completed_markets=7,active={"phase":"same_state_probes"}))
            probes=run_probes(CONT,cases,pacer)
            status="completed_through_continuation" if probes["status"]=="completed" else "stopped"
            failure_type=probes["failure_type"] or (probes["status"] if status=="stopped" else None)
    except BaseException as exc:
        status="interrupted" if isinstance(exc,KeyboardInterrupt) else "failed";failure_type=type(exc).__name__
        raise
    finally:
        completed=plan["completed_prefix"]+[r for r in index if r["status"]=="completed" and not r["parse_failures"]]
        write_json(CONT/"completed_market_index.json",completed)
        write_json(CONT/"all_attempted_markets.json",json.loads((STUDY/"runs.json").read_text())+index)
        write_json(CONT/"summary.json",dict(status=status,completed_markets=len(completed),recorded_continuation_arms=len(index),
            failure_type=failure_type,finished_utc=datetime.now(timezone.utc).isoformat(),plan_sha256=sha256(CONT/"plan.json")))
        write_json(CONT/"progress.json",dict(status=status,completed_markets=sum(r["status"]=="completed" for r in index),active=None))
    print(f"{status} -> {CONT}",flush=True)


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("action",choices=("prepare","run"));args=parser.parse_args()
    prepare() if args.action=="prepare" else execute()
