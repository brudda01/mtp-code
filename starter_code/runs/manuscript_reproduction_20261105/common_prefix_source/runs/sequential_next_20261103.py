"""R029: one sealed independent seed after R028's preserved delivery stop."""
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
from sim.sequential_markets import baselines,resources,validate,verify_market

VERSION="sequential_independent_seed_continuation_v1"


def read(path):return json.loads(Path(path).read_text())


def parent_evidence(parent):
    parent=Path(parent).resolve();p=validate(parent);baselines(parent)
    summary=read(parent/"block_4103/summary.json")
    index=read(parent/"block_4103/runs.json")
    if summary["status"]!="stopped" or summary["failure_type"]!="ProviderUnavailable":raise ValueError("requires recorded provider stop")
    if [(e["mode"],e["status"],e["rounds"]) for e in index]!=[("A","completed",24),("B","completed",24),("C","provider_error",22)]:raise ValueError("unexpected parent coverage")
    usage={k:sum(e["usage"][k] for e in index) for k in ("requests_made","reserved_tokens","provider_reported_tokens","unknown_usage_requests","blocked_requests")}
    hashes={}
    for path in parent.rglob("*"):
        if path.is_file():hashes[path.relative_to(parent).as_posix()]=sha256(path)
    for entry in index:
        path=parent/entry["run_path"];verify_market(path)
        if sha256(path/"manifest.json")!=entry["manifest_sha256"]:raise ValueError("parent manifest drift")
    errors=[r for s in (parent/index[-1]["run_path"]/"llm_requests.jsonl").read_text().splitlines() if (r:=json.loads(s)).get("status")=="error"]
    if len(errors)!=2 or any(r.get("http_status")!=503 for r in errors):raise ValueError("requires observed double503")
    if usage["requests_made"]!=150:raise ValueError("unexpected parent attempt count")
    return p,usage,hashes


def prepare(parent,output_root="runs"):
    parent=Path(parent).resolve();p,usage,hashes=parent_evidence(parent)
    if any((parent/f"block_{s}").exists() for s in (5209,6317)):raise ValueError("later parent seed already started")
    root=Path(output_root)/(time.strftime("%Y%m%d_%H%M%S_")+"sequential_next_"+uuid.uuid4().hex[:8])
    root.mkdir(parents=True,exist_ok=False);(root/"configs").mkdir()
    schedule=p["blocks"][1]["arms"]
    for a in schedule:shutil.copyfile(parent/a["config"],root/a["config"])
    shutil.copyfile(Path(__file__),root/"driver_source.py")
    amendment=dict(version=VERSION,status="frozen_before_calls",created_utc=datetime.now(timezone.utc).isoformat(),
        parent=str(parent),parent_files_sha256=hashes,parent_protocol_sha256=sha256(parent/"protocol.json"),
        driver_sha256=sha256(Path(__file__)),parent_usage=usage,seed=5209,arms=schedule,rounds=p["rounds"],
        change="Only between-seed stopping: user try now authorizes next predesignated independent seed5209 B/C/A despite first block delivery stop. Never retry or splice C4103; within-market/within-block stops unchanged.",
        unchanged="All simulator sources, exact copied configs, Qwen/model/prompts/personas/economics,8192 cap/temp.3/reflection0/low, own executed C history and one shared extra transport/503 attempt.",
        limits=dict(phase_max_requests=270,phase_max_reservations=3300000,campaign_max_requests=810,campaign_max_reservations=9900000),
        scope="ONE fresh seed block only; no seed6317 API calls. First scheduled real decision is availability check; stop on fatal provider/output/budget or operational fallback, no automatic restart. Existing nine rule companions reused without generation.",
        limitations="C4103 remains22-round partial, not replaced. At most two complete independent A/B/C scenarios if later frozen seed6317 completes; model generations unseeded. No causal news isolation, component/human-realism upgrade or pooled4096 comparison.")
    if usage["requests_made"]+270>810 or usage["reserved_tokens"]+3300000>9900000:raise ValueError("campaign allowance insufficient")
    write_json(root/"amendment.json",amendment);write_json(root/"preparation.json",dict(amendment_sha256=sha256(root/"amendment.json")))
    print(f"prepared -> {root}",flush=True);return root


def validate_phase(root):
    root=Path(root);a=read(root/"amendment.json")
    if sha256(root/"amendment.json")!=read(root/"preparation.json")["amendment_sha256"]:raise ValueError("amendment drift")
    if a["version"]!=VERSION or a["seed"]!=5209 or [e["mode"] for e in a["arms"]]!=list("BCA"):raise ValueError("schedule drift")
    if sha256(Path(__file__))!=a["driver_sha256"] or sha256(root/"driver_source.py")!=a["driver_sha256"]:raise ValueError("driver drift")
    parent=Path(a["parent"]);validate(parent)
    for name,digest in a["parent_files_sha256"].items():
        if sha256(parent/name)!=digest:raise ValueError("parent evidence drift")
    if {p.relative_to(parent).as_posix() for p in parent.rglob("*") if p.is_file()}!=set(a["parent_files_sha256"]):raise ValueError("parent inventory drift")
    for entry in a["arms"]:
        if sha256(root/entry["config"])!=entry["config_sha256"]:raise ValueError("config drift")
    return a


def execute(root):
    root=Path(root);a=validate_phase(root);block=root/"block_5209"
    if block.exists():raise ValueError("phase already started; no duplicate or automatic restart")
    for other in root.parent.glob("*_sequential_next_*"):
        if other.resolve()==root.resolve():continue
        if (other/"amendment.json").exists() and (other/"block_5209/execution.json").exists():
            prior=read(other/"amendment.json")
            if prior["parent"]==a["parent"] and prior["seed"]==5209:raise ValueError("seed already attempted in another linked phase")
    parent=Path(a["parent"]);baseline=read(parent/"baseline_runs.json")
    reference=parent/next(e["run_path"] for e in baseline if e["seed"]==5209 and e["cell"]=="combined")
    block.mkdir();write_json(block/"execution.json",dict(pid=os.getpid(),started_utc=datetime.now(timezone.utc).isoformat(),amendment_sha256=sha256(root/"amendment.json")))
    pacer=RequestPacer(10,60000);index=[];status="running";failure=None
    try:
        for item in a["arms"]:
            write_json(block/"progress.json",dict(status=status,recorded_markets=len(index),active=item))
            path=Path(run(root/item["config"],output_root=block/"market_runs",request_pacer=pacer))
            s=read(path/"summary.json");verify_market(path);prices=read_rows(path/"prices.csv")
            assert s["max_cash_conservation_error"]<1e-7 and resources(path)==resources(reference)
            assert [r["dividend"] for r in prices]==[r["dividend"] for r in read_rows(reference/"prices.csv")[:len(prices)]]
            entry={**item,"seed":5209,"run_path":path.relative_to(root).as_posix(),"manifest_sha256":sha256(path/"manifest.json"),
                "status":s["status"],"rounds":s["rounds"],"usage":s["llm_usage"],
                "operational_failures":{k:s[k] for k in ("parse_failures","api_failures","reflection_failures","output_truncations")}}
            index.append(entry);write_json(block/"runs.json",index)
            totals={k:sum(e["usage"][k] for e in index) for k in ("requests_made","reserved_tokens")}
            assert totals["requests_made"]<=270 and totals["reserved_tokens"]<=3300000
            assert totals["requests_made"]+a["parent_usage"]["requests_made"]<=810
            assert totals["reserved_tokens"]+a["parent_usage"]["reserved_tokens"]<=9900000
            if len(prices)>=11:write_json(block/f"metrics_{item['mode']}.json",market_metrics(path))
            if s["status"]!="completed" or s["rounds"]!=24 or any(entry["operational_failures"].values()):
                status="stopped";failure=s["failure_type"] or "operational_fallback";break
            print(f"completed live {item['mode']} seed5209",flush=True)
        else:status="completed"
    except BaseException as exc:
        status="interrupted" if isinstance(exc,KeyboardInterrupt) else "failed";failure=type(exc).__name__;raise
    finally:
        summary=dict(status=status,seed=5209,recorded_markets=len(index),planned_markets=3,
            completed_markets=sum(e["status"]=="completed" and e["rounds"]==24 and not any(e["operational_failures"].values()) for e in index),
            failure_type=failure,finished_utc=datetime.now(timezone.utc).isoformat())
        write_json(block/"summary.json",summary);write_json(block/"progress.json",dict(**summary,active=None))
    print(f"{status} block -> {block}",flush=True);return block


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("action",choices=("prepare","run"));parser.add_argument("--parent");parser.add_argument("--study")
    args=parser.parse_args()
    if args.action=="prepare":prepare(args.parent)
    else:execute(args.study)
