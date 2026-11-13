"""R041: fresh repeated downside-news markets under two fixed MM backgrounds."""
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
import yaml
from sim.config import parse_config
from sim.evaluation import evaluate_run, read_rows
from sim.llm.usage import RequestPacer
from sim.provenance import sha256, write_json
from runs import candidate_reading_20261104 as reading
from runs import initial_news_20261104 as base

BASE=base.BASE
GATE=BASE/"runs/20261104_160858_candidate_reading_89b6e200"
VERSION="downside_repeated_background_v1_clarified_level"
SEEDS=(20611,21727)
CELLS=(("original",False),("original",True),("no_skew",True),("no_skew",False))
USAGE=base.USAGE
TARGETS=base.TARGETS
HEADLINE=reading.prior.headline("down")


def read(path):return base.read(path)


def verify_reading(root):
    p=reading.validate(root);gate=read(root/"gate.json");summary=read(root/"summary.json");results=read(root/"results.json")
    assert gate["protocol_sha256"]==sha256(root/"protocol.json") and gate["cases_sha256"]==sha256(root/"cases.json")
    assert gate["results_sha256"]==sha256(root/"results.json") and gate["summary_sha256"]==sha256(root/"summary.json")
    assert gate["passed"] and summary["status"]=="completed" and summary["gate_passed"] and summary["delivered"]==12 and summary["level_fields"]==36
    assert len(results)==12 and all(x["valid_numeric_reading"] and len(x["matches_level"])==3 and all(x["matches_level"]) for x in results)
    for case in read(root/"cases.json").values():
        if case["direction"]=="down":assert HEADLINE in case["messages"][1]["content"]
    for name,digest in read(root/"output_manifest.json").items():assert sha256(root/name)==digest
    return p


@contextmanager
def disclosure():
    with base.disclosure():
        previous=base.engine.LLMAgent
        class ConfirmationAgent(previous):
            def __init__(self,*args,**kwargs):
                original=kwargs.get("log_fn") or (lambda item:None)
                def log(item):original({**item,"upstream_prompt_version":item.get("prompt_version"),"prompt_version":VERSION,"headline_version":"one_time_expected_level_v1"})
                kwargs["log_fn"]=log;super().__init__(*args,**kwargs)
        base.engine.LLMAgent=ConfirmationAgent
        try:yield
        finally:base.engine.LLMAgent=previous


def recipe(seed,background,visible,*,brain="A",repetition=0):
    raw=base.recipe(seed,"down_visible" if visible else "down_silent",brain).to_dict()
    raw["rounds"]=8;raw["name"]=f"downside_{brain}_{seed}_{background}_{'visible' if visible else 'silent'}_rep{repetition}"
    raw["agents"][0]["params"]["inventory_skew"]=.02 if background=="original" else 0
    if visible:raw["news"][0]["headline"]=HEADLINE
    if brain=="A":raw["llm_limits"].update(max_requests=24,max_reserved_tokens=450000)
    return parse_config(raw)


def prepare(output="runs",*,gate_root=GATE):
    gate_root=Path(gate_root);verify_reading(gate_root)
    root=Path(output)/(time.strftime("%Y%m%d_%H%M%S_")+"downside_confirmation_"+uuid.uuid4().hex[:8]);root.mkdir(parents=True,exist_ok=False);(root/"configs").mkdir()
    shutil.copytree(gate_root,root/"reading_gate")
    def save(seed,background,visible,brain,repetition=0):
        cfg=recipe(seed,background,visible,brain=brain,repetition=repetition);path=root/"configs"/(cfg.name+".yaml");path.write_text(yaml.safe_dump(cfg.to_dict()),encoding="utf-8")
        return dict(seed=seed,background=background,visible=visible,repetition=repetition,config=path.relative_to(root).as_posix(),config_sha256=sha256(path))
    baselines=[save(s,b,v,"rules") for s in SEEDS for b,v in CELLS]
    blocks=[]
    for j,seed in enumerate(SEEDS):
        for rep in (1,2):
            shift=2*j+rep-1;cells=CELLS[shift:]+CELLS[:shift]
            blocks.append(dict(seed=seed,repetition=rep,arms=[save(seed,b,v,"A",rep) for b,v in cells]))
    paths=[BASE/name for name in read(BASE/"runs/20261104_140638_initial_news_ee0f084f/protocol.json")["source_sha256"]]
    paths += [BASE/"runs"/name for name in ("sequential_next_20261103.py","semantic_check_20261104.py","candidate_reading_20261104.py")]+[Path(__file__)]
    hashes={p.relative_to(BASE).as_posix():sha256(p) for p in paths}
    with zipfile.ZipFile(root/"prepared_source.zip","x",zipfile.ZIP_DEFLATED) as archive:
        for name in hashes:archive.write(BASE/name,name)
    shutil.copyfile(__file__,root/"driver_source.py")
    write_json(root/"protocol.json",dict(version=VERSION,status="frozen_before_markets",created_utc=datetime.now(timezone.utc).isoformat(),
        parent_revision=subprocess.check_output(["git","rev-parse","HEAD"],cwd=BASE,text=True).strip(),
        working_tree_status=subprocess.check_output(["git","status","--short"],cwd=BASE,text=True).splitlines(),
        source_sha256=hashes,source_zip_sha256=sha256(root/"prepared_source.zip"),reading_gate_sha256=sha256(root/"reading_gate/gate.json"),
        headline=HEADLINE,baselines=baselines,blocks=blocks,seeds=list(SEEDS),repetitions=2,rounds=8,event_round=1,
        primary="Visible-minus-silent first3 signed EXECUTED target shares,per actor/combined/seed/repetition/background. Partial paths eligible only after3 valid cleared rounds; full8 terminal comparisons require clean complete paths.",
        secondary="Difference of headline contrasts under skew0vs.02;requested/accepted/gross/net fill and opportunity;all8 prices/gaps/turnover/MM/inventory;both lifetime conditional passive marks and counterparts;costs/failures. No preferred trading sign.",
        gates="Passed pinned R040 explicit reading task,not proof of natural-trading understanding. All8 rule companions first,visible/silent financial files identical;initial books match across backgrounds;resources/dividends/accounting/MM/passive checks. All live initial inputs match except headline;later feedback/model draw divergence retained.",
        profile=dict(model="qwen-3.8-27b",max_tokens=8192,reasoning_effort="low",temperature=.3,timeout_seconds=180,memory_window=5,reflections=0,provider_seed=None,backend_fingerprint=None),
        limits=dict(per_arm_requests=24,per_arm_reservations=450000,campaign_requests=384,campaign_reservations=6000000,normal_decisions=256),
        failure_policy="First fatal provider/budget/output or persistent parse fallback stops WHOLE study;existing one shared identical-message transport/503 extra retry. No restart/splice/resample/new seed/delivery amendment/model or billing switch. All zeros/missing/uncleared/unknown costs retained.",
        limitations="Two exogenous histories,two independent unseeded model repetitions per cell,not four seeds or sixteen independent replications. Only downside initial-time forecasts,eight rounds,no established pre-event trend or long-run LLM facts. New clarified wording not pooled with older ambiguous studies. No isolated traits,human calibration,universal news,response-sign,reflection efficacy or intrinsic model-superiority claim. F/M controls ignore headlines by construction;equal capital does not equalize sizing."))
    write_json(root/"preparation.json",dict(protocol_sha256=sha256(root/"protocol.json")));print(root,flush=True);return root


def validate(root):
    root=Path(root);p=read(root/"protocol.json")
    assert sha256(root/"protocol.json")==read(root/"preparation.json")["protocol_sha256"]
    assert sha256(root/"prepared_source.zip")==p["source_zip_sha256"] and all(sha256(BASE/n)==h for n,h in p["source_sha256"].items()),"Source drift"
    assert sha256(root/"reading_gate/gate.json")==p["reading_gate_sha256"];verify_reading(root/"reading_gate")
    assert all(sha256(root/a["config"])==a["config_sha256"] for a in p["baselines"]+[a for b in p["blocks"] for a in b["arms"]]),"Config drift"
    return p


def baseline_gates(root,index):
    for seed in SEEDS:
        entries=[e for e in index if e["seed"]==seed];assert len(entries)==4
        paths={(e["background"],e["visible"]):root/e["run_path"] for e in entries};reference=next(iter(paths.values()))
        first=lambda path,name:[x for x in read_rows(path/name) if x["round"]=="1"]
        for path in paths.values():
            assert (path/"initial_state.csv").read_bytes()==(reference/"initial_state.csv").read_bytes()
            assert first(path,"orders.csv")==first(reference,"orders.csv") and first(path,"trades.csv")==first(reference,"trades.csv")
            assert [x["dividend"] for x in read_rows(path/"prices.csv")]==[x["dividend"] for x in read_rows(reference/"prices.csv")]
        for background in ("original","no_skew"):
            for name in base.FINANCIAL_FILES:assert (paths[background,False]/name).read_bytes()==(paths[background,True]/name).read_bytes()


def baselines(root):
    root=Path(root);p=validate(root)
    if (root/"baseline_summary.json").exists():
        assert read(root/"baseline_summary.json")["status"]=="completed";index=read(root/"baseline_runs.json")
        for e in index:base.verify_market(root/e["run_path"]);assert sha256(root/e["run_path"]/"manifest.json")==e["manifest_sha256"]
        baseline_gates(root,index);return index
    with (root/"baseline_execution.json").open("x") as stream:json.dump(dict(pid=os.getpid()),stream)
    index=[];status="failed"
    try:
        for a in p["baselines"]:
            path=Path(base.engine.run(root/a["config"],output_root=root/"baseline_runs"));ss=read(path/"summary.json");base.verify_market(path);ev=evaluate_run(path)
            assert ss["status"]=="completed" and ss["rounds"]==8 and ss["llm_usage"]["requests_made"]==0 and ss["max_cash_conservation_error"]<1e-7
            assert 0<=ev["metrics"]["mm_inventory_min"]<=ev["metrics"]["mm_inventory_max"]<=300 and all(abs(x)<1e-7 for x in ev["aggregate_active_minus_passive"].values())
            index.append({**a,"run_path":path.relative_to(root).as_posix(),"manifest_sha256":sha256(path/"manifest.json")});write_json(root/"baseline_runs.json",index)
        baseline_gates(root,index);status="completed"
    finally:write_json(root/"baseline_summary.json",dict(status=status,completed=len(index),planned=8))
    return index


def first_input_gates(root,index,seed):
    selected=[e for e in index if e["seed"]==seed];assert len(selected)==8;reference=root/selected[0]["run_path"];first=[]
    for e in selected:
        path=root/e["run_path"];assert base.resources(path)==base.resources(reference) and read(path/"personas.json")==read(reference/"personas.json")
        calls=[c for c in base.lines(path/"llm_requests.jsonl") if c["record_type"]=="model_call" and c["round"]==1 and c["json_attempt"]==c["transport_attempt"]==1]
        assert {c["agent_id"] for c in calls}==set(TARGETS)
        first.append({c["agent_id"]:c["messages"] for c in calls})
        for c in calls:
            assert c["prompt_version"]==VERSION and c["messages"][1]["content"].startswith("Round 1.")
            assert "Initialization references:" in c["messages"][1]["content"]
        background=lambda p:[x for x in read_rows(p/"orders.csv") if x["round"]=="1" and x["agent_id"] not in TARGETS]
        assert background(path)==background(reference)
    for aid in TARGETS:
        normalized=[]
        for e,messages in zip(selected,first):
            system,user=messages[aid];content=user["content"]
            if e["visible"]:assert content.count("News today: "+HEADLINE+"\n")==1;content=content.replace("News today: "+HEADLINE+"\n","",1)
            else:assert HEADLINE not in content
            normalized.append((system,content))
        assert all(x==normalized[0] for x in normalized)
    return dict(seed=seed,initial_inputs_resources_personas_backgrounds_equal_except_headline=True)


def execute(root):
    root=Path(root);p=validate(root)
    if any((x/"execution.json").exists() for x in root.parent.glob("*_downside_confirmation_*") if x.resolve()!=root.resolve()):raise ValueError("Campaign already attempted")
    if (root/"execution.json").exists():raise ValueError("Study already started")
    refs=baselines(root)
    with (root/"execution.json").open("x") as stream:json.dump(dict(pid=os.getpid(),started_utc=datetime.now(timezone.utc).isoformat()),stream)
    pacer=RequestPacer(10,60000);index=[];checks=[];status="running";failure=None
    try:
        for block in p["blocks"]:
            for a in block["arms"]:
                write_json(root/"progress.json",dict(status="running",recorded_markets=len(index),active=a))
                with disclosure():path=Path(base.engine.run(root/a["config"],output_root=root/"market_runs",request_pacer=pacer))
                ss=read(path/"summary.json");manifest=base.verify_market(path)
                manifest["research_adapter"]=dict(version=VERSION,protocol_sha256=sha256(root/"protocol.json"),reading_gate_sha256=p["reading_gate_sha256"],headline_version="one_time_expected_level_v1",driver_sha256=sha256(root/"driver_source.py"));write_json(path/"manifest.json",manifest)
                entry={**a,"run_path":path.relative_to(root).as_posix(),"manifest_sha256":sha256(path/"manifest.json"),"status":ss["status"],"rounds":ss["rounds"],"usage":ss["llm_usage"],"operational_failures":{k:ss[k] for k in ("parse_failures","api_failures","output_truncations","reflection_failures")}}
                index.append(entry);write_json(root/"runs.json",index)
                ref=root/next(e["run_path"] for e in refs if (e["seed"],e["background"],e["visible"])==(a["seed"],a["background"],a["visible"]))
                prices=read_rows(path/"prices.csv");assert base.resources(path)==base.resources(ref) and ss["max_cash_conservation_error"]<1e-7
                assert [x["dividend"] for x in prices]==[x["dividend"] for x in read_rows(ref/"prices.csv")[:len(prices)]]
                assert sum(x["usage"]["requests_made"] for x in index)<=384 and sum(x["usage"]["reserved_tokens"] for x in index)<=6000000
                if ss["status"]!="completed" or ss["rounds"]!=8 or any(entry["operational_failures"].values()):status="stopped";failure=ss["failure_type"] or "operational_fallback";break
                print(f"completed {a['seed']} rep{a['repetition']} {a['background']} visible{a['visible']}",flush=True)
            if status=="stopped":break
            if block["repetition"]==2:checks.append(first_input_gates(root,index,block["seed"]));write_json(root/"block_checks.json",checks)
        else:status="completed"
    except BaseException as exc:status="interrupted" if isinstance(exc,KeyboardInterrupt) else "failed";failure=type(exc).__name__;raise
    finally:
        summary=dict(status=status,recorded_markets=len(index),planned_markets=16,completed_markets=sum(x["status"]=="completed" and x["rounds"]==8 and not any(x["operational_failures"].values()) for x in index),completed_seed_checks=len(checks),failure_type=failure,usage={k:sum(x["usage"][k] for x in index) for k in USAGE},finished_utc=datetime.now(timezone.utc).isoformat())
        write_json(root/"summary.json",summary);write_json(root/"progress.json",dict(**summary,active=None))
    print(json.dumps(summary),flush=True);return summary


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("action",choices=("prepare","baselines","run"));parser.add_argument("--study");parser.add_argument("--output",default="runs");args=parser.parse_args()
    if args.action=="prepare":prepare(args.output)
    elif args.action=="baselines":baselines(Path(args.study))
    else:execute(Path(args.study))
