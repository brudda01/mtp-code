"""Fresh endogenous A/B/C markets, frozen three-seed design, one block per run."""
import argparse
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

from sim.agents.llm_agent import PROMPT_VERSION
from sim.behaviour_run import PROFILE
from sim.config import load_config, parse_config
from sim.engine import run
from sim.evaluation import evaluate_run, read_rows
from sim.llm.usage import RequestPacer
from sim.news_controls import FINANCIAL_FILES, HEADLINE
from sim.news_pilot import market_metrics, market_recipe
from sim.provenance import sha256, write_json

VERSION="sequential_abc_market_gate_v1_output8192"
SEEDS=(4103,5209,6317)
ROUNDS=24
EVENT_ROUND=11
BACKGROUND_ROUNDS=600


def recipe(seed, mode, *, combined=True, rounds=ROUNDS):
    if mode not in ("rules","A","B","C"):raise ValueError("unknown market mode")
    cfg=market_recipe(seed,"combined" if combined else "control","rules" if mode=="rules" else "qwen").to_dict()
    cfg.update(name=f"sequential_{mode}_{'combined' if combined else 'quiet'}_s{seed}_r{rounds}",rounds=rounds)
    cfg["news"]=[dict(round=EVENT_ROUND,announce=True,headline=HEADLINE,effect=dict(dbar_mult=1.2))] if combined else []
    if mode!="rules":
        cfg["agents"][-1]["llm"].update(condition=mode,memory_window=5,reflect_every=5 if mode=="C" else 0,
            max_tokens=8192,transport_retries=1,retry_http_503=True)
        cfg["llm_limits"].update(max_requests=90,max_reserved_tokens=1100000,max_cost_usd=0,
            requests_per_minute=10,input_tokens_per_minute=60000,stop_on_api_error=True)
    return parse_config(cfg)


def prepare(output_root="runs"):
    root=Path(output_root)/(time.strftime("%Y%m%d_%H%M%S_")+"sequential_markets_"+uuid.uuid4().hex[:8])
    root.mkdir(parents=True,exist_ok=False);(root/"configs").mkdir()
    baseline=[];blocks=[]
    def save(cfg,label):
        path=root/"configs"/(label+".yaml");path.write_text(yaml.safe_dump(cfg.to_dict()),encoding="utf-8")
        return dict(config=path.relative_to(root).as_posix(),config_sha256=sha256(path))
    for seed in SEEDS:
        for label,combined,rounds in (("quiet",False,ROUNDS),("combined",True,ROUNDS),("long_quiet",False,BACKGROUND_ROUNDS)):
            baseline.append(dict(seed=seed,cell=label,rounds=rounds,**save(recipe(seed,"rules",combined=combined,rounds=rounds),f"rules_{label}_{seed}")))
    for i,seed in enumerate(SEEDS):
        modes=list("ABC");modes=modes[i:]+modes[:i]
        blocks.append(dict(seed=seed,arms=[dict(mode=mode,**save(recipe(seed,mode),f"{mode}_{seed}")) for mode in modes]))
    base=Path(__file__).resolve().parents[1]
    sources={p.relative_to(base).as_posix():sha256(p) for p in sorted((base/"sim").rglob("*.py"))}
    with zipfile.ZipFile(root/"prepared_source.zip","w",zipfile.ZIP_DEFLATED) as z:
        for name in sources:z.write(base/name,name)
    protocol=dict(version=VERSION,status="frozen_before_runs",prompt_suite_version=PROMPT_VERSION,
        source_sha256=sources,source_archive_sha256=sha256(root/"prepared_source.zip"),
        parent_revision=subprocess.check_output(["git","rev-parse","HEAD"],cwd=base,text=True).strip(),
        working_tree_status=subprocess.check_output(["git","status","--short"],cwd=base,text=True).splitlines(),
        seeds=list(SEEDS),rounds=ROUNDS,event_round=EVENT_ROUND,background_rounds=BACKGROUND_ROUNDS,
        baselines=baseline,blocks=blocks,profile={**PROFILE,"max_tokens":8192},
        planned=dict(per_block_decisions=2*ROUNDS*3,per_block_reflections=2*sum(r%5==0 for r in range(1,ROUNDS)),
            campaign_requests=9*2*ROUNDS+3*2*sum(r%5==0 for r in range(1,ROUNDS)),
            per_arm_max_requests=90,per_arm_max_reservations=1100000,
            first_block_max_requests=270,first_block_max_reservations=3300000,
            campaign_max_requests=810,campaign_max_reservations=9900000),
        gate="All nine rule companions first, accounting/resource/path checks only. Run ONE seed block per explicit execution; no later-seed calls during the first gate. Never gate on favourable economic outcomes.",
        failure_policy="Existing endogenous engine policy unchanged: fatal provider/output/budget stops arm/block; parse safe-HOLD or failed-reflection retained diary is logged, makes the arm operationally affected and stops further arms after that run. No bad-case/arm rerun or prefix splicing. Independent-case continue-on-failure policy is NOT used.",
        metrics="Actual requested/accepted/executed target orders, gross/net sizing, union participation and trade-leg share, price/event paths and gap, censored descriptive half-gap time, turnover/fills/MM dependence, all accounts under conditional passive auction/benchmark marks, complete failure/cost metadata.",
        limitations="Fresh predesignated seeds, initially n=1 live gate; all three needed for the planned small replication.24 rounds are not stylized-fact validation;600-round rule backgrounds are descriptive and uncalibrated. Mode policies differ from round1, so pre-event states diverge; common shock does not identify a causal headline effect. C has genuine own endogenous history. Specified equal-resource rule replacements do not standardize order size or establish intrinsic LLM superiority. New common8192 profile is not pooled with old4096 probes; no backend fingerprint/model seed assumed.")
    write_json(root/"protocol.json",protocol)
    write_json(root/"preparation.json",dict(protocol_sha256=sha256(root/"protocol.json")))
    print(f"prepared -> {root}",flush=True)
    return root


def validate(root):
    root=Path(root);p=json.loads((root/"protocol.json").read_text())
    if sha256(root/"protocol.json")!=json.loads((root/"preparation.json").read_text())["protocol_sha256"]:raise ValueError("protocol drift")
    if p["version"]!=VERSION or p["prompt_suite_version"]!=PROMPT_VERSION:raise ValueError("study version drift")
    base=Path(__file__).resolve().parents[1]
    for name,digest in p["source_sha256"].items():
        if sha256(base/name)!=digest:raise ValueError("prepared source drift")
    if sha256(root/"prepared_source.zip")!=p["source_archive_sha256"]:raise ValueError("archive drift")
    for item in p["baselines"]+[a for b in p["blocks"] for a in b["arms"]]:
        if sha256(root/item["config"])!=item["config_sha256"]:raise ValueError("config drift")
    return p


def resources(path):
    return [(r["cash"],r["shares"],r["wealth"]) for r in read_rows(Path(path)/"initial_state.csv")]


def verify_market(path):
    path=Path(path);m=json.loads((path/"manifest.json").read_text())
    for name,digest in m["output_sha256"].items():
        if sha256(path/name)!=digest:raise ValueError("run output drift")
    return m


def baselines(root):
    root=Path(root);p=validate(root)
    if (root/"baseline_summary.json").exists():
        s=json.loads((root/"baseline_summary.json").read_text())
        if s["status"]!="completed":raise ValueError("earlier baseline incomplete")
        index=json.loads((root/"baseline_runs.json").read_text())
        for e in index:
            verify_market(root/e["run_path"])
            if sha256(root/e["run_path"]/"manifest.json")!=e["manifest_sha256"]:raise ValueError("baseline manifest drift")
        return index
    with (root/"baseline_execution.json").open("x") as stream:json.dump(dict(pid=os.getpid()),stream)
    index=[];status="running"
    try:
        for item in p["baselines"]:
            path=Path(run(root/item["config"],output_root=root/"baseline_runs"))
            s=json.loads((path/"summary.json").read_text());e=evaluate_run(path)
            assert s["status"]=="completed" and s["rounds"]==item["rounds"]
            assert s["llm_usage"]["requests_made"]==0 and s["max_cash_conservation_error"]<1e-7
            assert 0<=e["metrics"]["mm_inventory_min"]<=e["metrics"]["mm_inventory_max"]<=300
            assert all(abs(v)<1e-7 for v in e["aggregate_active_minus_passive"].values())
            write_json(root/f"baseline_evaluation_{item['cell']}_{item['seed']}.json",e)
            index.append({**item,"run_path":path.relative_to(root).as_posix(),"manifest_sha256":sha256(path/"manifest.json")})
            write_json(root/"baseline_runs.json",index)
        for seed in p["seeds"]:
            paths={i["cell"]:root/i["run_path"] for i in index if i["seed"]==seed}
            assert resources(paths["quiet"])==resources(paths["combined"])==resources(paths["long_quiet"])
            quiet,shock=(read_rows(paths[c]/"prices.csv") for c in ("quiet","combined"))
            assert [(r["price"],r["volume"]) for r in quiet[:EVENT_ROUND]]==[(r["price"],r["volume"]) for r in shock[:EVENT_ROUND]]
            assert all(np.isclose(float(b["dividend"]),float(a["dividend"])*(1.2 if int(a["round"])>=EVENT_ROUND else 1),rtol=1e-13,atol=1e-15) for a,b in zip(quiet,shock))
            for name in FINANCIAL_FILES:
                assert read_rows(paths["quiet"]/name)==[r for r in read_rows(paths["long_quiet"]/name) if "round" not in r or int(r["round"])<=p["rounds"]]
        status="completed"
    finally:write_json(root/"baseline_summary.json",dict(status="completed" if status=="completed" else "failed",completed=len(index),planned=len(p["baselines"])))
    return index


def execute_block(root, seed):
    root=Path(root);p=validate(root)
    if seed not in p["seeds"]:raise ValueError("unplanned seed")
    number=p["seeds"].index(seed)
    for prior_seed in p["seeds"][:number]:
        prior=root/f"block_{prior_seed}"/"summary.json"
        if not prior.exists() or json.loads(prior.read_text())["status"]!="completed":raise ValueError("earlier block must complete first")
    block=root/f"block_{seed}"
    if (block/"execution.json").exists():raise ValueError("block already started; inspect evidence, never rerun blindly")
    baseline=baselines(root);block.mkdir(exist_ok=False)
    with (block/"execution.json").open("x") as stream:json.dump(dict(pid=os.getpid(),started_utc=datetime.now(timezone.utc).isoformat(),protocol_sha256=sha256(root/"protocol.json")),stream)
    pacer=RequestPacer(10,60000);index=[];status="running";failure_type=None
    schedule=p["blocks"][number]["arms"]
    reference=root/next(e["run_path"] for e in baseline if e["seed"]==seed and e["cell"]=="combined")
    try:
        for item in schedule:
            write_json(block/"progress.json",dict(status=status,completed_markets=len(index),active=item))
            path=Path(run(root/item["config"],output_root=block/"market_runs",request_pacer=pacer))
            s=json.loads((path/"summary.json").read_text());verify_market(path)
            assert s["max_cash_conservation_error"]<1e-7 and resources(path)==resources(reference)
            prices=read_rows(path/"prices.csv");ref=read_rows(reference/"prices.csv")
            assert [r["dividend"] for r in prices]==[r["dividend"] for r in ref[:len(prices)]]
            entry={**item,"seed":seed,"run_path":path.relative_to(root).as_posix(),"manifest_sha256":sha256(path/"manifest.json"),
                "status":s["status"],"rounds":s["rounds"],"usage":s["llm_usage"],
                "operational_failures":{k:s[k] for k in ("parse_failures","api_failures","reflection_failures","output_truncations")}}
            index.append(entry);write_json(block/"runs.json",index)
            if len(prices)>=EVENT_ROUND:write_json(block/f"metrics_{item['mode']}.json",market_metrics(path))
            if s["status"]!="completed" or s["rounds"]!=p["rounds"] or any(entry["operational_failures"].values()):
                status="stopped";failure_type=s["failure_type"] or "operational_fallback";break
            print(f"completed live {item['mode']} seed{seed}",flush=True)
        else:status="completed"
    except BaseException as exc:
        status="interrupted" if isinstance(exc,KeyboardInterrupt) else "failed";failure_type=type(exc).__name__
        raise
    finally:
        write_json(block/"summary.json",dict(status=status,seed=seed,completed_markets=sum(e["status"]=="completed" and e["rounds"]==p["rounds"] for e in index),
            recorded_markets=len(index),planned_markets=3,failure_type=failure_type,finished_utc=datetime.now(timezone.utc).isoformat()))
        write_json(block/"progress.json",dict(status=status,completed_markets=len(index),active=None))
    print(f"{status} block -> {block}",flush=True)
    return block


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("action",choices=("prepare","run"))
    parser.add_argument("--study");parser.add_argument("--seed",type=int);parser.add_argument("--output-root",default="runs")
    args=parser.parse_args()
    if args.action=="prepare":prepare(args.output_root)
    else:
        if not args.study or args.seed is None:parser.error("run requires --study and --seed")
        execute_block(args.study,args.seed)
