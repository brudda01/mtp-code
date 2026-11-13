"""R030: attempt only the four untouched markets; preserve both failed C paths."""
import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import shutil
import time
import uuid

from sim.engine import run
from sim.evaluation import read_rows
from sim.llm.usage import RequestPacer
from sim.news_pilot import market_metrics
from sim.provenance import sha256,write_json
from sim.sequential_markets import resources,validate,verify_market
from runs.sequential_next_20261103 import validate_phase as validate_prior

BASE=Path(__file__).resolve().parents[1]
PARENT=BASE/"runs/20261103_183126_sequential_markets_bb927356"
PRIOR=BASE/"runs/20261103_195320_sequential_next_fd0fc07c"
VERSION="sequential_remaining_four_v1"
SLOTS=((5209,"A"),(6317,"C"),(6317,"A"),(6317,"B"))


def read(path):return json.loads(Path(path).read_text())


def inventory(root):return {p.relative_to(root).as_posix():sha256(p) for p in root.rglob("*") if p.is_file()}


def prepare(output_root="runs"):
    p=validate(PARENT);validate_prior(PRIOR)
    old=[(PARENT,e) for e in read(PARENT/"block_4103/runs.json")]+[(PRIOR,e) for e in read(PRIOR/"block_5209/runs.json")]
    if [(e["seed"],e["mode"],e["rounds"]) for _,e in old]!=[(4103,"A",24),(4103,"B",24),(4103,"C",22),(5209,"B",24),(5209,"C",19)]:raise ValueError("prior coverage differs")
    for root,e in old:
        verify_market(root/e["run_path"])
        if sha256(root/e["run_path"]/"manifest.json")!=e["manifest_sha256"]:raise ValueError("old manifest drift")
    usage={k:sum(e["usage"][k] for _,e in old) for k in ("requests_made","reserved_tokens","provider_reported_tokens","unknown_usage_requests","blocked_requests")}
    if usage["requests_made"]!=247 or usage["reserved_tokens"]!=4150340:raise ValueError("unexpected campaign checkpoint")
    if any((PARENT/f"block_{s}").exists() for s in (5209,6317)):raise ValueError("unexpected parent execution")
    root=Path(output_root)/(time.strftime("%Y%m%d_%H%M%S_")+"sequential_tail_"+uuid.uuid4().hex[:8])
    root.mkdir(parents=True,exist_ok=False);(root/"configs").mkdir()
    arms=[]
    for seed,mode in SLOTS:
        e=next(a for b in p["blocks"] if b["seed"]==seed for a in b["arms"] if a["mode"]==mode)
        shutil.copyfile(PARENT/e["config"],root/e["config"]);arms.append(dict(seed=seed,**e))
    shutil.copyfile(Path(__file__),root/"driver_source.py")
    amendment=dict(version=VERSION,status="frozen_before_calls",created_utc=datetime.now(timezone.utc).isoformat(),
        parents=[dict(path=str(x),files_sha256=inventory(x)) for x in (PARENT,PRIOR)],
        parent_protocol_sha256=sha256(PARENT/"protocol.json"),driver_sha256=sha256(Path(__file__)),prior_usage=usage,arms=arms,
        change="Only between-independent-market stopping: retain terminal double503 as missing, cool down60 seconds, then attempt the next untouched scheduled market. Never retry/splice either old C or a failed new market.",
        unchanged="Byte-identical frozen configs and all simulator/economic/prompt/persona/model source; Qwen8192/low/temp.3/reflection0,24 rounds/event11,memory5/C reflect5, same one shared extra transport/503 attempt and fatal within-market policy.",
        failure_policy="Only terminal same-request double503 permits a next independent market after60s. Other provider/auth/quota/transport, budget/output, reflection/parse fallback or integrity errors stop the batch. All four markets attempted at most once; no automatic restart or additional seed.",
        limits=dict(phase_max_requests=360,phase_max_reservations=4400000,campaign_max_requests=810,campaign_max_reservations=9900000),
        normal_calls=dict(decisions=192,reflections=8),
        limitations="Old C4103/5209 remain22/19 partial; at most ONE complete A/B/C scenario (6317). Different execution dates/provider draws unseeded. No isolated headline effect, uniform component upgrade, human realism, pooling4096 samples or causal before/after delivery claim.")
    assert usage["requests_made"]+360<=810 and usage["reserved_tokens"]+4400000<=9900000
    write_json(root/"amendment.json",amendment);write_json(root/"preparation.json",dict(amendment_sha256=sha256(root/"amendment.json")))
    print(f"prepared -> {root}",flush=True);return root


def validate_tail(root):
    root=Path(root);a=read(root/"amendment.json")
    if sha256(root/"amendment.json")!=read(root/"preparation.json")["amendment_sha256"]:raise ValueError("amendment drift")
    if a["version"]!=VERSION or [(e["seed"],e["mode"]) for e in a["arms"]]!=list(SLOTS):raise ValueError("schedule drift")
    if sha256(Path(__file__))!=a["driver_sha256"] or sha256(root/"driver_source.py")!=a["driver_sha256"]:raise ValueError("driver drift")
    validate(PARENT);validate_prior(PRIOR)
    for parent in a["parents"]:
        if inventory(Path(parent["path"]))!=parent["files_sha256"]:raise ValueError("parent evidence drift")
    for e in a["arms"]:
        if sha256(root/e["config"])!=e["config_sha256"]:raise ValueError("config drift")
    return a


def terminal_double503(path):
    rows=[r for line in (path/"llm_requests.jsonl").read_text().splitlines() if (r:=json.loads(line))["record_type"]=="model_call"]
    if len(rows)<2:return False
    x,y=rows[-2:]
    return x["status"]==y["status"]=="error" and x.get("http_status")==y.get("http_status")==503 and x["request_group_id"]==y["request_group_id"] and x.get("transport_retry_planned") is True and y.get("transport_retry_planned") is False


def execute(root):
    root=Path(root);a=validate_tail(root)
    if (root/"execution.json").exists():raise ValueError("phase already started; no automatic restart")
    for other in root.parent.glob("*_sequential_tail_*"):
        if other.resolve()!=root.resolve() and (other/"execution.json").exists() and (other/"amendment.json").exists():
            if read(other/"amendment.json")["parent_protocol_sha256"]==a["parent_protocol_sha256"]:raise ValueError("remaining schedule already attempted in another phase")
    write_json(root/"execution.json",dict(pid=os.getpid(),started_utc=datetime.now(timezone.utc).isoformat(),amendment_sha256=sha256(root/"amendment.json")))
    pacer=RequestPacer(10,60000);index=[];status="running";failure=None
    try:
        for position,item in enumerate(a["arms"]):
            write_json(root/"progress.json",dict(status="running",recorded_markets=len(index),active=item))
            path=Path(run(root/item["config"],output_root=root/"market_runs",request_pacer=pacer))
            s=read(path/"summary.json");verify_market(path);prices=read_rows(path/"prices.csv")
            reference=PARENT/next(e["run_path"] for e in read(PARENT/"baseline_runs.json") if e["seed"]==item["seed"] and e["cell"]=="combined")
            assert s["max_cash_conservation_error"]<1e-7 and resources(path)==resources(reference)
            assert [r["dividend"] for r in prices]==[r["dividend"] for r in read_rows(reference/"prices.csv")[:len(prices)]]
            entry={**item,"run_path":path.relative_to(root).as_posix(),"manifest_sha256":sha256(path/"manifest.json"),
                "status":s["status"],"rounds":s["rounds"],"usage":s["llm_usage"],
                "operational_failures":{k:s[k] for k in ("parse_failures","api_failures","reflection_failures","output_truncations")}}
            clean=s["status"]=="completed" and s["rounds"]==24 and not any(entry["operational_failures"].values())
            entry["terminal_double503"]=not clean and s["status"]=="provider_error" and terminal_double503(path)
            index.append(entry);write_json(root/"runs.json",index)
            totals={k:sum(e["usage"][k] for e in index) for k in ("requests_made","reserved_tokens")}
            assert totals["requests_made"]<=360 and totals["reserved_tokens"]<=4400000
            assert totals["requests_made"]+a["prior_usage"]["requests_made"]<=810
            assert totals["reserved_tokens"]+a["prior_usage"]["reserved_tokens"]<=9900000
            if len(prices)>=11:write_json(root/f"metrics_{item['seed']}_{item['mode']}.json",market_metrics(path))
            if not clean:
                failure=s["failure_type"] or "operational_fallback"
                if not entry["terminal_double503"]:status="stopped";break
                if position<len(a["arms"])-1:
                    write_json(root/"progress.json",dict(status="cooldown_after503",recorded_markets=len(index),active=None,cooldown_seconds=60))
                    time.sleep(60)
            print(f"recorded {item['mode']} seed{item['seed']} {s['rounds']}/24 {s['status']}",flush=True)
        else:status="completed" if all(e["status"]=="completed" and not any(e["operational_failures"].values()) for e in index) else "completed_with_missing"
    except BaseException as exc:
        status="interrupted" if isinstance(exc,KeyboardInterrupt) else "failed";failure=type(exc).__name__;raise
    finally:
        summary=dict(status=status,recorded_markets=len(index),planned_markets=4,
            completed_markets=sum(e["status"]=="completed" and e["rounds"]==24 and not any(e["operational_failures"].values()) for e in index),
            failure_type=failure,finished_utc=datetime.now(timezone.utc).isoformat())
        write_json(root/"summary.json",summary);write_json(root/"progress.json",dict(**summary,active=None))
    print(f"{status} -> {root}",flush=True);return root


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("action",choices=("prepare","run"));parser.add_argument("--study")
    args=parser.parse_args()
    if args.action=="prepare":prepare()
    else:execute(args.study)
