"""R040: new clarified-only reading protocol; R038 remains immutable/stopped."""
import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import uuid
import zipfile
import numpy as np
from sim.agents.llm_agent import LLMAgent
from sim.llm.client import LLMClient
from sim.llm.usage import UsageBudget
from sim.provenance import sha256, write_json
from runs import semantic_check_20261104 as prior

BASE=prior.BASE
PARENT=BASE/"runs/20261104_154111_semantics_cd0076dc"
VERSION="clarified_dividend_reading_v2_typed_fields"
FIELDS=prior.FIELDS


def read(path):return prior.read(path)


def definitions():
    cases=read(PARENT/"cases.json");out={}
    for key,case in cases.items():
        system,user=case["messages"]["clarified"]
        prefix=system["content"].split("Respond ONLY with a JSON object, no other text:\n")[0]
        requirement=("Respond ONLY with one JSON object. Required fields: "
            +", ".join(k+" (JSON number)" for k in FIELDS)
            +", reasoning (string). Numeric values must be JSON numbers, without quotation marks. "
            "Compute the values requested by the user; do not return a schema or type placeholders.")
        out[key]=dict(direction=case["direction"],actor=case["actor"],origins=case["origins"],
                      messages=[dict(role="system",content=prefix+requirement),dict(user)])
    assert len(out)==4
    return out


def classify(raw,direction):
    parsed=LLMAgent._extract_json(raw)
    try:json.dumps(parsed,allow_nan=False)
    except (ValueError,TypeError):parsed=None
    converted={};strings=[];valid=isinstance(parsed,dict)
    for key in FIELDS:
        value=parsed.get(key) if isinstance(parsed,dict) else None
        if type(value) is str and re.fullmatch(r"-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?",value):
            value=float(value);strings.append(key)
        if type(value) not in (int,float) or not math.isfinite(value):valid=False
        else:converted[key]=value
    level=.024 if direction=="up" else .016
    matches=[bool(valid and math.isclose(converted[k],level,rel_tol=1e-7,abs_tol=1e-9)) for k in FIELDS]
    return dict(parsed=parsed,valid_numeric_reading=valid,numeric_values=converted,
                extracted_string_fields=strings,strict_json_numbers=valid and not strings,
                matches_level=matches,interpretation="level" if all(matches) else "other_numeric_path" if valid else "invalid_numeric_fields")


def prepare(output="runs"):
    prior.validate(PARENT);cases=definitions();root=Path(output)/(time.strftime("%Y%m%d_%H%M%S_")+"candidate_reading_"+uuid.uuid4().hex[:8]);root.mkdir(parents=True,exist_ok=False)
    write_json(root/"cases.json",cases);shutil.copyfile(PARENT/"cases.json",root/"parent_cases.json");shutil.copyfile(__file__,root/"driver_source.py")
    paths=[BASE/name for name in read(PARENT/"protocol.json")["source_sha256"]]+[Path(__file__)]
    hashes={p.relative_to(BASE).as_posix():sha256(p) for p in paths}
    with zipfile.ZipFile(root/"source.zip","x",zipfile.ZIP_DEFLATED) as archive:
        for path in paths:archive.write(path,path.relative_to(BASE).as_posix())
    keys=sorted(cases);schedule=[dict(case=keys[(j+rep-1)%4],repetition=rep) for rep in (1,2,3) for j in range(4)]
    write_json(root/"protocol.json",dict(version=VERSION,status="frozen_before_calls",created_utc=datetime.now(timezone.utc).isoformat(),
        parent_revision=subprocess.check_output(["git","rev-parse","HEAD"],cwd=BASE,text=True).strip(),
        working_tree_status=subprocess.check_output(["git","status","--short"],cwd=BASE,text=True).splitlines(),
        parent_protocol_sha256=sha256(PARENT/"protocol.json"),parent_cases_sha256=sha256(PARENT/"cases.json"),source_sha256=hashes,
        cases_sha256=sha256(root/"cases.json"),source_zip_sha256=sha256(root/"source.zip"),schedule=schedule,profile=prior.PROFILE,
        max_tokens=8192,temperature=.3,limits=dict(max_requests=20,max_reserved_tokens=350000,max_cost_usd=0,requests_per_minute=10,input_tokens_per_minute=60000,stop_on_api_error=True),
        purpose="NEW candidate-only explicit reading check,4 persona/sign contexts x3 fresh draws,not resume/repair ofR038,not wording efficacy comparison or normal trading. Same clarified headline/user/context; only system response-field requirements changed. No financial-direction oracle.",
        scoring="Primary reading extraction accepts finite JSON numbers or canonical decimal/exponent strings; raw types/string-field conversions reported separately from strict format compliance. No expression/unit/boolean/NaN evaluation. Gate all12 delivered valid/36 intended level fields; numeric wrong/invalid cases retained,advance independent slot without repair. No claim old wording is worse.",
        failure_policy="First provider/budget/output failure stops after existing one shared identical-message transport/503 retry. No resample,automatic second candidate/model/billing substitution. Invalid delivered numeric fields remain unsuccessful/missing reading slots,not silently fixed or retried.",
        limitations="Four fixed contexts,unseeded provider draws/no backend fingerprint; explicit conditional-on-forecast task supplies prior expected mean.02. Passing is not natural-trading comprehension,market benefit,human calibration or A/B/C efficacy."))
    write_json(root/"preparation.json",dict(protocol_sha256=sha256(root/"protocol.json")));print(root,flush=True);return root


def validate(root):
    root=Path(root);p=read(root/"protocol.json")
    assert sha256(root/"protocol.json")==read(root/"preparation.json")["protocol_sha256"]
    assert sha256(root/"cases.json")==p["cases_sha256"] and sha256(root/"parent_cases.json")==p["parent_cases_sha256"]
    assert sha256(root/"source.zip")==p["source_zip_sha256"] and all(sha256(BASE/n)==h for n,h in p["source_sha256"].items()),"Source drift"
    return p


def execute(root,*,client=None,budget=None):
    root=Path(root);p=validate(root)
    if any((x/"execution.json").exists() for x in root.parent.glob("*_candidate_reading_*") if x.resolve()!=root.resolve()):raise ValueError("Candidate campaign already attempted")
    with (root/"execution.json").open("x") as stream:json.dump(dict(pid=os.getpid(),started_utc=datetime.now(timezone.utc).isoformat()),stream)
    client=client or LLMClient(**p["profile"]);budget=budget or UsageBudget(**p["limits"]);results=[];current={};status="running";failure=None
    with (root/"requests.jsonl").open("x",encoding="utf-8") as stream:
        def log(item):
            stream.write(json.dumps({**item,**current,"upstream_prompt_version":item.get("prompt_version"),"prompt_version":VERSION},allow_nan=False)+"\n");stream.flush()
        try:
            for i,item in enumerate(p["schedule"],1):
                current=dict(item);case=read(root/"cases.json")[item["case"]]
                agent=LLMAgent(f"candidate_reading_{i}",0,0,np.random.default_rng(40),params=dict(max_tokens=8192,transport_retries=1,retry_http_503=True),client=client,budget=budget,temperature=.3,log_fn=log)
                raw,_=agent._request(case["messages"],i,"candidate_reading")
                if client.last_response_metadata.get("model")!=p["profile"]["model"]:raise ValueError("unexpected_response_model")
                result={**item,**classify(raw,case["direction"])};results.append(result);write_json(root/"results.json",results)
                print(f"reading {i}/12 {item['case']}:{result['interpretation']},strict={result['strict_json_numbers']}",flush=True)
            status="completed"
        except Exception as exc:status="stopped";failure=type(exc).__name__
        finally:
            summary=dict(status=status,failure_type=failure,delivered=len(results),planned=12,valid_numeric_readings=sum(x["valid_numeric_reading"] for x in results),strict_number_replies=sum(x["strict_json_numbers"] for x in results),level_fields=sum(sum(x["matches_level"]) for x in results),
                gate_passed=len(results)==12 and all(x["valid_numeric_reading"] and all(x["matches_level"]) for x in results),usage=budget.snapshot(),finished_utc=datetime.now(timezone.utc).isoformat())
            write_json(root/"results.json",results);write_json(root/"summary.json",summary)
    write_json(root/"gate.json",dict(passed=summary["gate_passed"],protocol_sha256=sha256(root/"protocol.json"),cases_sha256=sha256(root/"cases.json"),results_sha256=sha256(root/"results.json"),summary_sha256=sha256(root/"summary.json")))
    write_json(root/"output_manifest.json",{x.name:sha256(x) for x in root.iterdir() if x.is_file() and x.name!="output_manifest.json"});print(json.dumps(summary),flush=True);return summary


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("action",choices=("prepare","run"));parser.add_argument("--study");parser.add_argument("--output",default="runs");args=parser.parse_args()
    prepare(args.output) if args.action=="prepare" else execute(args.study)
