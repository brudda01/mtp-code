"""R032: frozen A-only recording-length pilot; no simulator-source changes."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
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
from sim.agents.llm_agent import LLMAgent, PROMPT_VERSION
from sim.config import parse_config
from sim.evaluation import evaluate_run, read_rows
from sim.llm.usage import RequestPacer
from sim.news_controls import HEADLINE
from sim.news_pilot import market_metrics
from sim.provenance import sha256, write_json
from sim.sequential_markets import recipe, resources, verify_market
from runs.sequential_tail_20261104 import terminal_double503

BASE=Path(__file__).resolve().parents[1]
VERSION="horizon_visibility_v1_from_round1"
SEEDS=(7403,8517)
ARMS=((7403,"shown"),(7403,"hidden"),(8517,"hidden"),(8517,"shown"))
USAGE=("requests_made","reserved_tokens","provider_reported_tokens","unknown_usage_requests","blocked_requests")


def read(path):return json.loads(Path(path).read_text(encoding="utf-8"))


def config(seed, mode="A", quiet=False):
    cfg=recipe(seed,mode,combined=not quiet).to_dict()
    cfg["name"]=f"horizon_{mode}_{'quiet' if quiet else 'shock'}_s{seed}"
    if not quiet and seed==8517:
        cfg["news"][0].update(headline=HEADLINE.replace("20% rise","20% fall"),effect=dict(dbar_mult=.8))
    return parse_config(cfg)


@contextmanager
def visibility(mode):
    if mode not in ("shown","hidden"):raise ValueError("unknown horizon condition")
    if engine.LLMAgent is not LLMAgent:raise ValueError("agent binding already changed")
    class HorizonAgent(LLMAgent):
        def __init__(self,*args,**kwargs):
            super().__init__(*args,**kwargs)
            original=self.log_fn
            def log(record):
                tagged={**record,"base_prompt_version":record.get("prompt_version"),
                    "prompt_version":f"simple_A_v2+{VERSION}:{mode}",
                    "horizon_visibility":mode,"research_adapter_version":VERSION}
                original(tagged)
            self.log_fn=log
        def user_prompt(self,obs):
            prompt=super().user_prompt(obs)
            prefix=f"Round {obs.round}/{obs.total_rounds}."
            if not prompt.startswith(prefix):raise ValueError("base prompt prefix drift")
            return prompt if mode=="shown" else f"Round {obs.round}."+prompt[len(prefix):]
    engine.LLMAgent=HorizonAgent
    try:yield
    finally:engine.LLMAgent=LLMAgent


def prepare(output_root="runs"):
    root=Path(output_root)/(time.strftime("%Y%m%d_%H%M%S_")+"horizon_pilot_"+uuid.uuid4().hex[:8])
    root.mkdir(parents=True,exist_ok=False);(root/"configs").mkdir()
    def save(cfg,label):
        path=root/"configs"/(label+".yaml");path.write_text(yaml.safe_dump(cfg.to_dict()),encoding="utf-8")
        return dict(config=path.relative_to(root).as_posix(),config_sha256=sha256(path))
    baselines=[dict(seed=s,cell=c,**save(config(s,"rules",quiet=c=="quiet"),f"rules_{s}_{c}")) for s in SEEDS for c in ("quiet","shock")]
    arms=[dict(seed=s,visibility=v,**save(config(s),f"A_{s}_{v}")) for s,v in ARMS]
    sources={p.relative_to(BASE).as_posix():sha256(p) for p in sorted((BASE/"sim").rglob("*.py"))}
    with zipfile.ZipFile(root/"prepared_source.zip","w",zipfile.ZIP_DEFLATED) as z:
        for name in sources:z.write(BASE/name,name)
    shutil.copyfile(__file__,root/"driver_source.py")
    # Imported helper is part of the frozen executable source, too.
    helper=BASE/"runs/sequential_tail_20261104.py";shutil.copyfile(helper,root/"helper_source.py")
    p=dict(version=VERSION,status="frozen_before_any_runs",created_utc=datetime.now(timezone.utc).isoformat(),
        parent_revision=subprocess.check_output(["git","rev-parse","HEAD"],cwd=BASE,text=True).strip(),
        working_tree_status=subprocess.check_output(["git","status","--short"],cwd=BASE,text=True).splitlines(),
        source_sha256=sources,source_archive_sha256=sha256(root/"prepared_source.zip"),
        driver_sha256=sha256(__file__),helper_sha256=sha256(helper),base_prompt_suite=PROMPT_VERSION,
        seeds=list(SEEDS),rounds=24,event_round=11,condition="A",arms=arms,baselines=baselines,
        treatment="Only first user line changes from Round n/24. to Round n.; applied before request logging from round1. Both retain stock continuation, end-of-run valuation, rules, personas and identical economic configs. Own actual histories develop independently; no old-context redaction or replay.",
        profile=dict(model="qwen-3.8-27b",temperature=.3,reasoning_effort="low",max_tokens=8192,timeout_seconds=180,memory_window=5,reflections=0,model_seed=None,provider_fingerprint=None),
        primary="For each seed, shown-minus-hidden target executed net signed flow (buys-sells) in rounds22-24, combined and separately for each target. Also report gross flow and holdings change; fixed initial target shares200 normalization if used. Two-sided descriptive estimates, no directional pass rule.",
        secondary="Requested/accepted/executed quantities, opportunity/headroom, exposure, all price/news paths and regime gaps, final three-round drawdown, volume/MM participation/inventory, both conditional passive wealth marks and all other accounts, cost and failures. Deadline wording is a qualitative audit, not an intent detector.",
        controls="Four zero-API quiet/shock rule companions first. Identical resources and within-seed exogenous paths; only accounting/path checks gate live. No long-background rerun or financial sign/gap gate.",
        news="7403 forecast20% rise plus actual permanent mean*1.2;8517 forecast20% fall plus actual mean*.8. Bundled shocks, not isolated headline effects; one seed per direction cannot identify sign interaction.",
        limits=dict(per_arm_requests=90,per_arm_reserved_tokens=1100000,phase_requests=360,phase_reserved_tokens=4400000,normal_decisions=192,normal_reflections=0),
        failure_policy="Each market once. Existing fatal within-market output/provider/budget policy and one shared transport/503 extra attempt. Only terminal same-request double503 allows next untouched market after60s; other errors or logged parse/reflection fallback stop batch. Retain all partial/cancelled outputs; no splicing, bad-case rerun or automatic restart.",
        limitations="Exploratory two exogenous scenarios, one live model draw each condition; no inferential/general horizon effect or human replication. Number of recording rounds is undisclosed, not indefinite stochastic stopping: end-of-run wording remains. Endogenous pre-event states differ. Unseeded provider sampling, date/order and own-history feedback confound exact repeatability. No selected default, model switch or new A/B/C efficacy claim.")
    write_json(root/"protocol.json",p);write_json(root/"preparation.json",dict(protocol_sha256=sha256(root/"protocol.json")))
    print(f"prepared -> {root}",flush=True);return root


def validate(root):
    root=Path(root);p=read(root/"protocol.json")
    if sha256(root/"protocol.json")!=read(root/"preparation.json")["protocol_sha256"]:raise ValueError("protocol drift")
    if p["version"]!=VERSION or [(e["seed"],e["visibility"]) for e in p["arms"]]!=list(ARMS):raise ValueError("schedule drift")
    for name,digest in p["source_sha256"].items():
        if sha256(BASE/name)!=digest:raise ValueError("sim source drift")
    for path,digest in ((Path(__file__),p["driver_sha256"]),(root/"driver_source.py",p["driver_sha256"]),(BASE/"runs/sequential_tail_20261104.py",p["helper_sha256"]),(root/"helper_source.py",p["helper_sha256"]),(root/"prepared_source.zip",p["source_archive_sha256"])):
        if sha256(path)!=digest:raise ValueError("research source drift")
    for e in p["arms"]+p["baselines"]:
        if sha256(root/e["config"])!=e["config_sha256"]:raise ValueError("config drift")
    return p


def baselines(root):
    root=Path(root);p=validate(root)
    if (root/"baseline_runs.json").exists():raise ValueError("baseline already attempted")
    entries=[]
    for item in p["baselines"]:
        path=Path(engine.run(root/item["config"],output_root=root/"baseline_runs"));s=read(path/"summary.json");verify_market(path)
        ev=evaluate_run(path)
        assert s["status"]=="completed" and s["rounds"]==24 and s["llm_usage"]["requests_made"]==0
        assert s["max_cash_conservation_error"]<1e-7 and 0<=ev["metrics"]["mm_inventory_min"]<=ev["metrics"]["mm_inventory_max"]<=300
        assert all(abs(v)<1e-7 for v in ev["aggregate_active_minus_passive"].values())
        entries.append({**item,"run_path":path.relative_to(root).as_posix(),"manifest_sha256":sha256(path/"manifest.json")})
        write_json(root/"baseline_runs.json",entries)
    for seed in SEEDS:
        paths={e["cell"]:root/e["run_path"] for e in entries if e["seed"]==seed}
        assert resources(paths["quiet"])==resources(paths["shock"])
        q,s=(read_rows(paths[c]/"prices.csv") for c in ("quiet","shock"))
        assert q[:10]==s[:10]
        assert all(np.isclose(float(b["dividend"]),float(a["dividend"])*((1.2 if seed==7403 else .8) if int(a["round"])>=11 else 1),rtol=1e-13,atol=1e-15) for a,b in zip(q,s))
    write_json(root/"baseline_summary.json",dict(status="completed",completed=4,checks="resources,10-round quiet prefixes,dividend scaling,finite MM,cash/passive cancellation"))
    return entries


def execute(root):
    root=Path(root);p=validate(root)
    if (root/"execution.json").exists():raise ValueError("study already started; no automatic restart")
    for other in root.parent.glob("*_horizon_pilot_*"):
        if other.resolve()!=root.resolve() and (other/"execution.json").exists():raise ValueError("pilot already attempted in another phase")
    refs=read(root/"baseline_runs.json")
    if read(root/"baseline_summary.json")["status"]!="completed" or len(refs)!=4:raise ValueError("baseline gate incomplete")
    for e in refs:
        verify_market(root/e["run_path"])
        if sha256(root/e["run_path"]/"manifest.json")!=e["manifest_sha256"]:raise ValueError("baseline drift")
    with (root/"execution.json").open("x") as f:json.dump(dict(pid=os.getpid(),started_utc=datetime.now(timezone.utc).isoformat(),protocol_sha256=sha256(root/"protocol.json")),f)
    pacer=RequestPacer(10,60000);index=[];status="running";failure=None
    try:
        for n,item in enumerate(p["arms"]):
            write_json(root/"progress.json",dict(status="running",recorded_markets=len(index),active=item))
            with visibility(item["visibility"]):path=Path(engine.run(root/item["config"],output_root=root/"market_runs",request_pacer=pacer))
            s=read(path/"summary.json");manifest=verify_market(path)
            # Manifest excludes itself from output hashes. Add the frozen adapter provenance, never rewrite sealed outputs.
            manifest["research_adapter"]=dict(version=VERSION,visibility=item["visibility"],driver_sha256=p["driver_sha256"],protocol_sha256=sha256(root/"protocol.json"),base_suite=PROMPT_VERSION,actual_prompt_version=f"simple_A_v2+{VERSION}:{item['visibility']}")
            write_json(path/"manifest.json",manifest)
            reference=root/next(e["run_path"] for e in refs if e["seed"]==item["seed"] and e["cell"]=="shock")
            prices=read_rows(path/"prices.csv")
            assert resources(path)==resources(reference) and s["max_cash_conservation_error"]<1e-7
            assert [r["dividend"] for r in prices]==[r["dividend"] for r in read_rows(reference/"prices.csv")[:len(prices)]]
            entry={**item,"run_path":path.relative_to(root).as_posix(),"manifest_sha256":sha256(path/"manifest.json"),"status":s["status"],"rounds":s["rounds"],"usage":s["llm_usage"],"operational_failures":{k:s[k] for k in ("parse_failures","api_failures","reflection_failures","output_truncations")}}
            clean=s["status"]=="completed" and s["rounds"]==24 and not any(entry["operational_failures"].values())
            entry["terminal_double503"]=not clean and s["status"]=="provider_error" and terminal_double503(path)
            index.append(entry);write_json(root/"runs.json",index)
            assert sum(e["usage"]["requests_made"] for e in index)<=360 and sum(e["usage"]["reserved_tokens"] for e in index)<=4400000
            if len(prices)>=11:write_json(root/f"metrics_{item['seed']}_{item['visibility']}.json",market_metrics(path))
            if not clean:
                failure=s["failure_type"] or "operational_fallback"
                if not entry["terminal_double503"]:status="stopped";break
                if n<len(p["arms"])-1:
                    write_json(root/"progress.json",dict(status="cooldown_after503",recorded_markets=len(index),active=None,cooldown_seconds=60));time.sleep(60)
            print(f"recorded {item['visibility']} seed{item['seed']} {s['rounds']}/24 {s['status']}",flush=True)
        else:status="completed" if all(e["status"]=="completed" and not any(e["operational_failures"].values()) for e in index) else "completed_with_missing"
    except BaseException as exc:
        status="interrupted" if isinstance(exc,KeyboardInterrupt) else "failed";failure=type(exc).__name__;raise
    finally:
        summary=dict(status=status,recorded_markets=len(index),planned_markets=4,completed_markets=sum(e["status"]=="completed" and e["rounds"]==24 and not any(e["operational_failures"].values()) for e in index),failure_type=failure,finished_utc=datetime.now(timezone.utc).isoformat())
        write_json(root/"summary.json",summary);write_json(root/"progress.json",dict(**summary,active=None))
    print(f"{status} -> {root}",flush=True);return root


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("action",choices=("prepare","baselines","run"));parser.add_argument("--study");parser.add_argument("--output-root",default="runs");args=parser.parse_args()
    if args.action=="prepare":prepare(args.output_root)
    elif args.action=="baselines":baselines(args.study)
    else:execute(args.study)
