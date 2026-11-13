"""R036: sequential visible/silent true shifts from matched initial states."""
import argparse
from contextlib import contextmanager
from datetime import datetime,timezone
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
from sim.config import parse_config
from sim.evaluation import evaluate_run,read_rows
from sim.llm.usage import RequestPacer
from sim.news_controls import FINANCIAL_FILES,HEADLINE
from sim.provenance import sha256,write_json
from sim.sequential_markets import recipe as base_recipe,resources,verify_market
from runs.horizon_pilot_20261104 import visibility

BASE=Path(__file__).resolve().parents[1]
VERSION="initial_news_A_v1_explicit_prior_reference"
SEEDS=(13111,14227)
CELLS={"quiet":(1.,False),"up_silent":(1.2,False),"up_visible":(1.2,True),"down_silent":(.8,False),"down_visible":(.8,True)}
ORDERS={13111:("quiet","up_silent","up_visible","down_visible","down_silent"),14227:("down_silent","down_visible","quiet","up_visible","up_silent")}
TARGETS=("llm_012","llm_013")
USAGE=("requests_made","reserved_tokens","provider_reported_tokens","unknown_usage_requests","blocked_requests")

def read(path):return json.loads(Path(path).read_text(encoding="utf-8"))
def lines(path):return [json.loads(s) for s in Path(path).read_text(encoding="utf-8").splitlines()]

@contextmanager
def disclosure():
    with visibility("hidden"):
        previous=engine.LLMAgent
        class InitialReferenceAgent(previous):
            def __init__(self,*args,**kwargs):
                original=kwargs.get("log_fn") or (lambda item:None)
                def log(item):original({**item,"upstream_prompt_version":item.get("prompt_version"),"prompt_version":VERSION,"initial_reference_version":"explicit_prior_reference_v1"})
                kwargs["log_fn"]=log;super().__init__(*args,**kwargs)
            def user_prompt(self,obs):
                prompt=super().user_prompt(obs)
                if obs.round==1:
                    old=f"Previous round: volume {obs.last_volume}, dividend paid {obs.last_dividend} per share."
                    if old not in prompt:raise ValueError("initial prompt template drift")
                    new=f"Initialization references: volume {obs.last_volume}; prior dividend {obs.last_dividend} per share. No earlier auction or paid dividend is recorded in this episode."
                    prompt=prompt.replace(old,new,1)
                return prompt
        engine.LLMAgent=InitialReferenceAgent
        try:yield
        finally:engine.LLMAgent=previous

def recipe(seed,cell,brain="A"):
    cfg=base_recipe(seed,brain,combined=False,rounds=12).to_dict();cfg["name"]=f"initial_news_{brain}_{cell}_s{seed}_r12"
    factor,visible=CELLS[cell]
    cfg["news"]=[] if cell=="quiet" else [dict(round=1,announce=visible,effect=dict(dbar_mult=factor),**({"headline":HEADLINE if factor>1 else HEADLINE.replace("20% rise","20% fall")} if visible else {}))]
    if brain=="A":cfg["llm_limits"].update(max_requests=40,max_reserved_tokens=700000)
    return parse_config(cfg)

def prepare(output_root="runs"):
    root=Path(output_root)/(time.strftime("%Y%m%d_%H%M%S_")+"initial_news_"+uuid.uuid4().hex[:8]);root.mkdir(parents=True,exist_ok=False);(root/"configs").mkdir()
    def save(cfg,label):
        path=root/"configs"/(label+".yaml");path.write_text(yaml.safe_dump(cfg.to_dict()),encoding="utf-8");return dict(config=path.relative_to(root).as_posix(),config_sha256=sha256(path))
    baselines=[dict(seed=s,cell=c,**save(recipe(s,c,"rules"),f"rules_{s}_{c}")) for s in SEEDS for c in CELLS]
    blocks=[dict(seed=s,arms=[dict(seed=s,cell=c,**save(recipe(s,c),f"A_{s}_{c}")) for c in ORDERS[s]]) for s in SEEDS]
    names={p.relative_to(BASE).as_posix():sha256(p) for p in (BASE/"sim").rglob("*.py")}
    for name in ("initial_news_20261104.py","horizon_pilot_20261104.py","sequential_tail_20261104.py"):names["runs/"+name]=sha256(BASE/"runs"/name)
    with zipfile.ZipFile(root/"prepared_source.zip","w",zipfile.ZIP_DEFLATED) as z:
        for name in names:z.write(BASE/name,name)
    shutil.copyfile(__file__,root/"driver_source.py")
    p=dict(version=VERSION,status="frozen_before_runs",created_utc=datetime.now(timezone.utc).isoformat(),parent_revision=subprocess.check_output(["git","rev-parse","HEAD"],cwd=BASE,text=True).strip(),working_tree_status=subprocess.check_output(["git","status","--short"],cwd=BASE,text=True).splitlines(),
        source_sha256=names,source_archive_sha256=sha256(root/"prepared_source.zip"),driver_sha256=sha256(__file__),baselines=baselines,blocks=blocks,seeds=list(SEEDS),rounds=12,event_round=1,condition="A",
        question="Incremental visible-versus-silent forecast effect under the SAME real permanent mean shift, from matched initial states, with endogenous joint downstream feedback. Quiet reference for silent-regime contrasts; direction is not a pass oracle.",
        initial_information="All base initial means/reference dividends.02 and price100/resources/personas identical within seed. Event applied at round1; hidden new regime not disclosed in first silent prompt. Round1 explicitly labels supplied dividend as initialization prior, not verified payment. All later paid observations remain literal. Common hidden recording length/continuing-stock rule. New research variant, no tested before/after semantic benefit or production default change.",
        primary="Within each seed, visible-minus-silent cumulative executed target signed flow(buys-sells) over rounds1-3, separately up/down, per actor and combined. A partial path can support this only if all3 financial rounds complete without model fallback;12-round terminal outcomes stay missing unless full path clean.",
        secondary="First-auction requested/accepted/executed/gross flow and price/volume/counterparty response; all12-round paths/gaps/turnover/fill/MM/inventory, natural headroom/exposure, both full-horizon conditional passive auction/private-benchmark marks and all counterparts/costs. Silent up/down minus quiet as secondary regime contrasts. No risk-adjusted alpha/welfare/human-realism oracle.",
        gates="All10 zero-API rule companions first; same-regime visible/silent financial CSVs identical, all5 initial rule books/trades identical, quiet dividends scaled1.2/.8, resources/cash/shares/MM/passive accounting. Live first silent inputs match across quiet/up/down; visible first inputs differ only headline; personas/initial resources/12 background first orders match. Later divergence is a treatment/feedback outcome.",
        profile=dict(model="qwen-3.8-27b",temperature=.3,max_tokens=8192,reasoning_effort="low",timeout_seconds=180,memory_window=5,reflections=0,provider_seed=None,backend_fingerprint=None),
        limits=dict(per_arm_requests=40,per_arm_reservations=700000,phase_requests=400,phase_reservations=7000000,normal_decisions=240),
        failure_policy="Existing first fatal provider/output/budget or persistent parse fallback stops whole campaign; existing one shared identical-message extra transport/503 attempt. No next seed after failure, automatic restart, selected resampling, prefix splicing or model/billing switch. Partial/uncleared/unknown usage retained. Continue predeclared block2 only after clean technical block1 gates, regardless of financial signs.",
        limitations="Only2 exogenous scenarios, one unseeded model path per condition; not10 independent treatment repetitions. Initial event lacks established pre-event trends; later paths include model-sampling/feedback variation. No human validation, universal headline effect, long-run stylized facts or intrinsic LLM superiority. F/M companions are specified equal-slot policies that ignore text. New prompt variant not pooled with old matched-query studies or interpreted as a semantic-before/after improvement. Initial prior is shared, not a disclosed new-regime oracle. A raw reasoning history can carry news beliefs beyond the5-round window.")
    write_json(root/"protocol.json",p);write_json(root/"preparation.json",dict(protocol_sha256=sha256(root/"protocol.json")))
    print(f"prepared -> {root}",flush=True);return root

def validate(root):
    root=Path(root);p=read(root/"protocol.json")
    if p["version"]!=VERSION or sha256(root/"protocol.json")!=read(root/"preparation.json")["protocol_sha256"]:raise ValueError("protocol drift")
    for name,digest in p["source_sha256"].items():
        if sha256(BASE/name)!=digest:raise ValueError("source drift")
    if sha256(root/"prepared_source.zip")!=p["source_archive_sha256"] or sha256(root/"driver_source.py")!=p["driver_sha256"]:raise ValueError("archive drift")
    for e in p["baselines"]+[a for b in p["blocks"] for a in b["arms"]]:
        if sha256(root/e["config"])!=e["config_sha256"]:raise ValueError("config drift")
    return p

def baseline_gates(root,index):
    for seed in SEEDS:
        paths={e["cell"]:root/e["run_path"] for e in index if e["seed"]==seed}
        assert len(paths)==5 and all(resources(path)==resources(paths["quiet"]) for path in paths.values())
        first=lambda path,name:[r for r in read_rows(path/name) if int(r["round"])==1]
        for path in paths.values():
            assert first(path,"orders.csv")==first(paths["quiet"],"orders.csv") and first(path,"trades.csv")==first(paths["quiet"],"trades.csv")
        quiet=read_rows(paths["quiet"]/"prices.csv")
        for cell,path in paths.items():assert all(np.isclose(float(b["dividend"]),float(a["dividend"])*CELLS[cell][0],rtol=1e-13,atol=1e-15) for a,b in zip(quiet,read_rows(path/"prices.csv")))
        for direction in ("up","down"):
            for name in FINANCIAL_FILES:assert (paths[direction+"_silent"]/name).read_bytes()==(paths[direction+"_visible"]/name).read_bytes()

def baselines(root):
    root=Path(root);p=validate(root)
    if (root/"baseline_summary.json").exists():
        assert read(root/"baseline_summary.json")["status"]=="completed";index=read(root/"baseline_runs.json")
        for e in index:verify_market(root/e["run_path"]);assert sha256(root/e["run_path"]/"manifest.json")==e["manifest_sha256"]
        baseline_gates(root,index);return index
    if (root/"baseline_execution.json").exists():raise ValueError("earlier baseline attempt incomplete")
    write_json(root/"baseline_execution.json",dict(pid=os.getpid()));index=[];status="failed"
    try:
        for e in p["baselines"]:
            path=Path(engine.run(root/e["config"],output_root=root/"baseline_runs"));ss=read(path/"summary.json");verify_market(path);ev=evaluate_run(path)
            assert ss["status"]=="completed" and ss["rounds"]==12 and ss["llm_usage"]["requests_made"]==0 and ss["max_cash_conservation_error"]<1e-7
            assert 0<=ev["metrics"]["mm_inventory_min"]<=ev["metrics"]["mm_inventory_max"]<=300 and all(abs(x)<1e-7 for x in ev["aggregate_active_minus_passive"].values())
            index.append({**e,"run_path":path.relative_to(root).as_posix(),"manifest_sha256":sha256(path/"manifest.json")});write_json(root/"baseline_runs.json",index)
        baseline_gates(root,index);status="completed"
    finally:write_json(root/"baseline_summary.json",dict(status=status,completed=len(index),planned=10))
    return index

def first_input_gates(root,index,seed):
    entries=[e for e in index if e["seed"]==seed];assert len(entries)==5;paths={e["cell"]:root/e["run_path"] for e in entries};personas=read(paths["quiet"]/"personas.json")
    first={}
    for cell,path in paths.items():
        assert resources(path)==resources(paths["quiet"]) and read(path/"personas.json")==personas
        rr=[r for r in lines(path/"llm_requests.jsonl") if r["record_type"]=="model_call" and r["round"]==1 and r["json_attempt"]==r["transport_attempt"]==1]
        first[cell]={r["agent_id"]:r["messages"] for r in rr};assert set(first[cell])==set(TARGETS)
        background=[r for r in read_rows(path/"orders.csv") if r["round"]=="1" and r["agent_id"] not in TARGETS]
        quiet=[r for r in read_rows(paths["quiet"]/"orders.csv") if r["round"]=="1" and r["agent_id"] not in TARGETS];assert background==quiet
    for aid in TARGETS:
        assert first["quiet"][aid]==first["up_silent"][aid]==first["down_silent"][aid]
        for direction in ("up","down"):
            a,b=first[direction+"_visible"][aid],first[direction+"_silent"][aid];headline=HEADLINE if direction=="up" else HEADLINE.replace("20% rise","20% fall")
            assert a[0]==b[0] and a[1]["content"].replace("News today: "+headline+"\n","",1)==b[1]["content"]
            assert "Initialization references:" in a[1]["content"] and "Previous round:" not in a[1]["content"]
    return dict(seed=seed,initial_resources_personas_silent_prompts_and_backgrounds_equal=True,visible_initial_difference_only_headline=True)

def execute(root):
    root=Path(root);p=validate(root)
    if (root/"execution.json").exists():raise ValueError("study already started")
    if any((x/"execution.json").exists() for x in root.parent.glob("*_initial_news_*") if x.resolve()!=root.resolve()):raise ValueError("campaign version already attempted")
    refs=baselines(root)
    with (root/"execution.json").open("x") as f:json.dump(dict(pid=os.getpid(),started_utc=datetime.now(timezone.utc).isoformat(),protocol_sha256=sha256(root/"protocol.json")),f)
    pacer=RequestPacer(10,60000);index=[];status="running";failure=None;block_checks=[]
    try:
        for block in p["blocks"]:
            for e in block["arms"]:
                write_json(root/"progress.json",dict(status="running",recorded_markets=len(index),active=e))
                with disclosure():path=Path(engine.run(root/e["config"],output_root=root/"market_runs",request_pacer=pacer))
                ss=read(path/"summary.json");m=verify_market(path);m["research_adapter"]=dict(version=VERSION,driver_sha256=p["driver_sha256"],protocol_sha256=sha256(root/"protocol.json"),first_reference="supplied initialization prior, not paid observation",base_suite=m["prompt_suite_version"]);write_json(path/"manifest.json",m)
                entry={**e,"run_path":path.relative_to(root).as_posix(),"manifest_sha256":sha256(path/"manifest.json"),"status":ss["status"],"rounds":ss["rounds"],"usage":ss["llm_usage"],"operational_failures":{k:ss[k] for k in ("parse_failures","api_failures","output_truncations","reflection_failures")}}
                index.append(entry);write_json(root/"runs.json",index)
                ref=root/next(r["run_path"] for r in refs if (r["seed"],r["cell"])==(e["seed"],e["cell"]))
                pp=read_rows(path/"prices.csv");assert resources(path)==resources(ref) and ss["max_cash_conservation_error"]<1e-7
                assert [r["dividend"] for r in pp]==[r["dividend"] for r in read_rows(ref/"prices.csv")[:len(pp)]]
                assert sum(r["usage"]["requests_made"] for r in index)<=400 and sum(r["usage"]["reserved_tokens"] for r in index)<=7000000
                clean=ss["status"]=="completed" and ss["rounds"]==12 and not any(entry["operational_failures"].values())
                if not clean:status="stopped";failure=ss["failure_type"] or "operational_fallback";break
                print(f"completed {e['cell']} seed{e['seed']}",flush=True)
            if status=="stopped":break
            block_checks.append(first_input_gates(root,index,block["seed"]));write_json(root/"block_checks.json",block_checks)
        else:status="completed"
    except BaseException as exc:
        status="interrupted" if isinstance(exc,KeyboardInterrupt) else "failed";failure=type(exc).__name__;raise
    finally:
        s=dict(status=status,recorded_markets=len(index),planned_markets=10,completed_markets=sum(e["status"]=="completed" and e["rounds"]==12 and not any(e["operational_failures"].values()) for e in index),completed_blocks=len(block_checks),failure_type=failure,usage={k:sum(e["usage"][k] for e in index) for k in USAGE},finished_utc=datetime.now(timezone.utc).isoformat())
        write_json(root/"summary.json",s);write_json(root/"progress.json",dict(**s,active=None))
    print(f"{status} -> {root}",flush=True);return root

if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("action",choices=("prepare","baselines","run"));parser.add_argument("--study");parser.add_argument("--output-root",default="runs");a=parser.parse_args()
    if a.action=="prepare":prepare(a.output_root)
    elif a.action=="baselines":baselines(a.study)
    else:execute(a.study)
