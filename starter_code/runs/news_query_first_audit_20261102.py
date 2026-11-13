"""Read-only provenance/delivery audit; never sends a model request."""
from collections import Counter, defaultdict
import json
from pathlib import Path
import shutil
import zipfile

from sim.llm.client import dotenv_api_key
from sim.provenance import sha256, write_json
from runs.news_query_first_analysis_20261102 import STUDY, OUTPUT, verify_manifest


def audit():
    phase=STUDY/"delivery_v4_query_first"
    plan=json.loads((phase/"plan.json").read_text())
    status=json.loads((phase/"summary.json").read_text()) if (phase/"summary.json").exists() else {"status":"in_progress"}
    index=[]
    for root in (STUDY,STUDY/"continuation_1",STUDY/"recovery_transport_v3",phase):
        index+=json.loads((root/"runs.json").read_text())
    roots=[STUDY/r["run_path"] for r in index]
    roots += [p for p in phase.glob("probes_seed_*/same_state_probes") if (p/"summary.json").exists()]
    calls=[];decisions=[];groups=defaultdict(list);usage=Counter();errors=[];returned_models=Counter()
    for root in roots:
        verify_manifest(root)
        summary=json.loads((root/"summary.json").read_text())
        requests=[json.loads(s) for s in (root/"llm_requests.jsonl").read_text().splitlines()]
        run_calls=[r for r in requests if r["record_type"]=="model_call"]
        assert len(run_calls)==summary["llm_usage"]["requests_made"],root
        assert len({r["call_id"] for r in run_calls})==len(run_calls),root
        for key in ("requests_made","reserved_tokens","provider_reported_tokens","unknown_usage_requests","failed_requests","blocked_requests"):
            usage[key]+=summary["llm_usage"][key]
        for call in run_calls:
            calls.append(call)
            groups[(str(root),call.get("request_group_id",call["call_id"]))].append(call)
            if call["status"]=="error":
                errors.append(dict(run=root.relative_to(STUDY).as_posix(),**{k:call.get(k) for k in
                    ("call_id","error_type","http_status","transport_diagnostics","retry_category","retry_wait_seconds","transport_retry_planned")}))
            else:returned_models[call.get("response_metadata",{}).get("model","unreported")]+=1
        decision_path=root/"llm_calls.jsonl"
        if decision_path.exists():
            decisions += [json.loads(s) for s in decision_path.read_text().splitlines() if json.loads(s)["record_type"]=="decision"]
    retries=[]
    for (run,group),rows in groups.items():
        assert len(rows)<=2,(run,group)
        if len(rows)==2:
            assert rows[0]["status"]=="error" and rows[0].get("transport_retry_planned")
            assert rows[1]["transport_attempt"]==2
            for key in ("messages","temperature","max_tokens","json_mode","reasoning_effort"):
                assert rows[0][key]==rows[1][key],(run,group,key)
            retries.append(dict(run=Path(run).relative_to(STUDY).as_posix(),group=group,
                kind=rows[1]["attempt_kind"],recovered=rows[1]["status"]=="returned"))
    assert len(calls)==usage["requests_made"]
    assert sum(r["status"]=="error" for r in calls)==usage["failed_requests"]
    assert sum(r["usage"]["total_tokens"] for r in calls if r.get("usage") and r["usage"].get("source")=="provider")==usage["provider_reported_tokens"]
    assert usage["requests_made"]<=688 and usage["reserved_tokens"]<=9000000
    assert usage["requests_made"]<=619 and usage["reserved_tokens"]<=8055022
    source_root=Path(__file__).resolve().parents[1]
    for name,digest in plan["source_sha256"].items():assert sha256(source_root/name)==digest,name
    assert sha256(STUDY/"study.json")==plan["original_study_sha256"]
    assert sha256(phase/"prepared_source.zip")==plan["source_archive_sha256"]
    assert sha256(phase/"driver_source.py")==plan["driver_sha256"]
    for item in plan["schedule"]:assert sha256(phase/item["config"])==item["config_sha256"]
    # Read credential VALUES only into memory, never emit them or scan .env itself.
    secrets={v.encode() for name in ("API_KEY","BHARATCODE_API_KEY","GEMINI_API_KEY","NVIDIA_API_KEY")
             if (v:=dotenv_api_key(name)) and len(v)>=8}
    checked=0
    for root in roots:
        for file in root.rglob("*"):
            if not file.is_file():continue
            assert file.name!=".env"
            if file.suffix==".zip":
                with zipfile.ZipFile(file) as archive:
                    for name in archive.namelist():
                        assert not name.endswith("/.env") and name!=".env"
                        assert not any(secret in archive.read(name) for secret in secrets),"Secret found in archived artifact"
                        checked+=1
            else:
                assert not any(secret in file.read_bytes() for secret in secrets),"Secret found in artifact"
                checked+=1
    report=dict(status=status,scope="Finalized arms/subsets only; active arms excluded while study in progress.",
        finalized_market_runs=len(index),finalized_probe_subsets=len(roots)-len(index),
        usage=dict(usage),actual_model_calls=len(calls),returned_models=dict(returned_models),
        attempt_kinds=dict(Counter(r.get("attempt_kind","legacy_initial") for r in calls)),
        errors=errors,retries=retries,
        decision_records=len(decisions),decision_failures=dict(Counter(r["failure_type"] for r in decisions if r["failure_type"])),
        quantity_reductions=sum("quantity" in r.get("parsed",{}).get("validation_note","").lower() for r in decisions),
        manifest_output_and_archived_source_hashes_verified=True,current_phase_source_unchanged=True,
        same_messages_and_sampling_parameters_for_delivery_retries=True,
        original_global_caps_and_amended_phase_caps_respected=True,
        secret_value_scan_passed=True,scanned_file_or_archive_member_count=checked,
        plan_sha256=sha256(phase/"plan.json"),audit_source_sha256=sha256(Path(__file__)))
    write_json(OUTPUT/"delivery_audit.json",report)
    shutil.copyfile(Path(__file__),OUTPUT/"audit_source.py")
    write_json(OUTPUT/"artifact_hashes.json",{p.name:sha256(p) for p in OUTPUT.iterdir() if p.is_file() and p.name!="artifact_hashes.json"})
    print(json.dumps(report,indent=2))


if __name__=="__main__":audit()
