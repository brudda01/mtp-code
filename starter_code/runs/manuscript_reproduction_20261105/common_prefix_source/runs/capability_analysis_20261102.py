"""Descriptive analysis; refuse cross-battery or access-smoke pooling."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import zipfile


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def analyze(path):
    manifest=read(path/"manifest.json")
    assert manifest["experiment_kind"]=="fixed_capability_check","not a comparison run"
    for name,digest in manifest["output_sha256"].items():
        assert hashlib.sha256((path/name).read_bytes()).hexdigest()==digest,(path.name,name)
    with zipfile.ZipFile(path/"source.zip") as archive:
        for name,digest in manifest["source_sha256"].items():
            assert hashlib.sha256(archive.read(name)).hexdigest()==digest,(path.name,name)
    battery=read(path/"battery.json")
    digest=hashlib.sha256((path/"battery.json").read_bytes()).hexdigest()
    assert digest==manifest["battery_sha256"]
    definitions={c["case_id"]:c for c in battery["cases"]}
    results=read(path/"results.json")
    records=[json.loads(x) for x in (path/"llm_requests.jsonl").read_text().splitlines()]
    calls=[r for r in records if r.get("record_type")=="model_call"]
    for r in calls:
        if r["call_id"].endswith(":1"):
            assert r["messages"]==definitions[r["case_id"]]["messages"],(path.name,r["case_id"],"prompt drift")
    objective=[r for r in results if r["kind"]=="objective"]
    orders=[r for r in results if r["kind"]=="order"]
    cases={}
    for case_id,case in definitions.items():
        rows=sorted([r for r in results if r["case_id"]==case_id],key=lambda r:r["repetition"])
        cases[case_id]=dict(kind=case["kind"],family=case["family"],repetitions=rows)
    pairs=[]
    for family,ids in {"news":("control","headline"),"risk":("risk_low","risk_high"),
                       "value":("value_75","value_90")}.items():
        for n in range(1,battery["repetitions"]+1):
            rows=[next((r for r in results if r["case_id"]==name and r["repetition"]==n),None) for name in ids]
            if any(r is None for r in rows):continue
            signed=[r["intent"]["quantity"]*{"buy":1,"sell":-1,"hold":0}[r["intent"]["side"]] for r in rows]
            pairs.append(dict(family=family,repetition=n,cases=ids,signed_quantities=signed,
                              limits=[r["intent"]["limit_price"] for r in rows],delta_signed_quantity=signed[1]-signed[0]))
    result=dict(run_id=path.name,status=read(path/"summary.json")["status"],battery_sha256=digest,
        configured_model=manifest["models"][0]["configured_model"],actual_models=sorted({r["response_metadata"].get("model","unknown") for r in calls}),
        parent_revision=manifest["parent_revision"],prompt_suite_version=manifest["prompt_suite_version"],
        source_sha256=manifest["source_sha256"],manifest_sha256=hashlib.sha256((path/"manifest.json").read_bytes()).hexdigest(),
        settings=manifest["models"],completed_checks=len(results),planned_checks=len(battery["schedule"]),
        objective_all_fields_correct=sum(r["all_correct"] for r in objective),objective_checks=len(objective),
        objective_fields_correct=sum(sum(r["correct_fields"].values()) for r in objective),objective_fields=sum(len(r["correct_fields"]) for r in objective),
        valid_order_checks=sum(r["parse_failures"]==0 for r in orders),order_checks=len(orders),
        reservation_compliant_orders=sum(r["resource_compliant"] is True for r in orders),
        repaired_order_checks=sum(r["repaired"] for r in orders),
        provider_request_errors=sum(r["status"]=="error" for r in calls),
        mean_provider_seconds=statistics.mean(r["provider_latency_seconds"] for r in calls) if calls else None,
        reported_reasoning_tokens=sum((r.get("usage") or {}).get("reasoning_tokens",0) for r in calls),
        reasoning_detail_calls=sum("reasoning_tokens" in (r.get("usage") or {}) for r in calls),
        usage=read(path/"summary.json")["llm_usage"],cases=cases,paired_choices=pairs,
        scoring_note="Objective scores use the frozen strict tolerance; inspect rounding/formatting cases separately before judging competence. Orders have no directional or profit oracle. A HOLD is resource-compliant but not an arithmetic pass.")
    return result


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("runs",nargs="+")
    parser.add_argument("--output",required=True)
    args=parser.parse_args()
    rows=[analyze(Path(p)) for p in args.runs]
    assert len({r["battery_sha256"] for r in rows})==1,"cannot compare different batteries"
    report=dict(analysis_kind="Small served-model diagnostic; no significance, causal model-size or human-realism claim",
        analysis_script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),runs=rows,
        selection_note="Inspect factual/task correctness, reservation compliance, faithful memory, reliability and usage by family. Do not select a model because reflection profits improve or headline reactions have a preferred sign.")
    Path(args.output).write_text(json.dumps(report,indent=2,allow_nan=False),encoding="utf-8")
    for r in rows:
        print(json.dumps({k:v for k,v in r.items() if k not in ("cases","source_sha256","paired_choices","settings")},indent=2))
