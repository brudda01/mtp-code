"""Audit a failed-prefix/explicit-tail continuation without pooling new cases."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import zipfile

from capability_analysis_20261102 import analyze,read


def protected_functions(path):
    with zipfile.ZipFile(path/"source.zip") as archive:
        tree=ast.parse(archive.read("sim/capability_check.py"))
    wanted={"scenario_agent","cases","memory_fixture","grade_objective","recipe"}
    return {node.name:ast.dump(node,include_attributes=False) for node in tree.body
            if isinstance(node,ast.FunctionDef) and node.name in wanted}


def complete(parent,tail,output):
    a,b=analyze(parent),analyze(tail)
    original,continuation=read(parent/"battery.json"),read(tail/"battery.json")
    link=continuation["continuation"]
    assert link["parent_run_id"]==parent.name
    assert link["parent_battery_sha256"]==a["battery_sha256"]
    assert original["cases"]==continuation["cases"]
    assert original["version"]==continuation["version"]
    assert original["prompt_suite_version"]==continuation["prompt_suite_version"]
    assert a["settings"]==b["settings"]
    assert protected_functions(parent)==protected_functions(tail)
    differences={name for name,digest in a["source_sha256"].items() if b["source_sha256"].get(name)!=digest}
    assert differences <= {"sim/capability_check.py"},differences
    first,last=read(parent/"results.json"),read(tail/"results.json")
    assert link["completed_prefix_length"]==len(first)
    key=lambda row:(row["case_id"],row["repetition"])
    assert list(map(key,first))==list(map(key,original["schedule"][:len(first)]))
    assert continuation["schedule"]==original["schedule"][len(first):]
    joined=first+last
    assert list(map(key,joined))==list(map(key,original["schedule"]))
    assert len({key(row) for row in joined})==len(joined)
    assert b["status"]=="completed"
    objective=[r for r in joined if r["kind"]=="objective"]
    orders=[r for r in joined if r["kind"]=="order"]
    pairs=[]
    for family,ids in {"news":("control","headline"),"risk":("risk_low","risk_high"),"value":("value_75","value_90")}.items():
        for n in range(1,original["repetitions"]+1):
            rows=[next(r for r in joined if r["case_id"]==name and r["repetition"]==n) for name in ids]
            signed=[r["intent"]["quantity"]*{"buy":1,"sell":-1,"hold":0}[r["intent"]["side"]] for r in rows]
            pairs.append(dict(family=family,repetition=n,cases=ids,signed_quantities=signed,limits=[r["intent"]["limit_price"] for r in rows]))
    totals={k:a["usage"][k]+b["usage"][k] for k in ("requests_made","provider_reported_tokens","reserved_tokens","failed_requests","unknown_usage_requests")}
    assert totals["requests_made"]<=54
    assert totals["reserved_tokens"]<=400000
    report=dict(analysis_kind="Descriptive Qwen qualification completed via explicitly linked continuation",
        analysis_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        original_battery_sha256=a["battery_sha256"],completed_checks=len(joined),planned_checks=len(original["schedule"]),
        settings=a["settings"],prompt_suite_version=a["prompt_suite_version"],
        parent_run=parent.name,continuation_run=tail.name,
        parent_audit=a,continuation_audit=b,
        source_difference=list(differences),protected_case_rendering_fixture_grading_and_profile_functions_equal=True,
        objective_checks=len(objective),objective_all_correct=sum(r["all_correct"] for r in objective),
        objective_fields=sum(len(r["correct_fields"]) for r in objective),objective_correct_fields=sum(sum(r["correct_fields"].values()) for r in objective),
        valid_order_checks=sum(r["parse_failures"]==0 for r in orders),order_checks=len(orders),
        reservation_compliant_orders=sum(r["resource_compliant"] is True for r in orders),
        repaired_order_checks=sum(r["repaired"] for r in orders),
        usage_totals=totals,case_results=joined,paired_choices=pairs,
        exclusions="The earlier externally interrupted 13-check prefix 20261102_053929_capability_qwen_6cdca7bd is preserved and excluded. No answer was selected from that run.",
        limitations="The main run had a provider TimeoutError after 34 checks, including measured elapsed 5161 seconds despite configured 180-second I/O timeout. Host/runtime suspension cannot be separated from provider delay. The eight-case tail ran later. Do not use this run to rank inference latency or claim a model-size/human-realism effect. Unknown failed-request usage is not reconstructed.")
    output.write_text(json.dumps(report,indent=2,allow_nan=False),encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k not in ("parent_audit","continuation_audit","case_results","settings")},indent=2))


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("parent")
    parser.add_argument("continuation")
    parser.add_argument("--output",required=True)
    args=parser.parse_args()
    complete(Path(args.parent),Path(args.continuation),Path(args.output))
