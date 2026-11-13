"""Preserve R032 once, including the saved background inputs it reanalyses."""
import hashlib
import importlib.metadata
import io
import json
from pathlib import Path
import platform
import subprocess
import zipfile
from sim.llm.client import dotenv_api_key
from sim.provenance import sha256,write_json
from sim.sequential_markets import verify_market
from runs.horizon_pilot_20261104 import BASE,read,validate

ROOT=BASE/"runs/20261104_045742_horizon_pilot_2617baf7"
OUTPUT=BASE/"runs/horizon_analysis_v2_20261104"
REFERENCE=BASE/"runs/realism_review_20261104"


def main():
    p=validate(ROOT);summary=read(ROOT/"summary.json");report=read(OUTPUT/"report.json")
    assert report["summary"]==summary and report["protocol_sha256"]==sha256(ROOT/"protocol.json")
    assert summary["status"] in ("completed","completed_with_missing","stopped","failed","interrupted")
    destination=BASE/"runs/horizon_environment_20261104_evidence.zip"
    external=destination.with_name(destination.stem+"_manifest.json")
    assert not destination.exists() and not external.exists(),"Existing evidence is immutable"
    paths=list(ROOT.rglob("*"))+list(OUTPUT.rglob("*"))+list(REFERENCE.rglob("*"))+list((BASE/"runs/horizon_analysis_20261104").rglob("*"))
    for folder in (OUTPUT,REFERENCE,BASE/"runs/horizon_analysis_20261104"):
        for name,digest in read(folder/"artifact_manifest.json").items():assert sha256(folder/name)==digest
    interpretation=read(OUTPUT/"interpretation_manifest.json")
    assert sha256(OUTPUT/"INTERPRETATION.md")==interpretation["interpretation_sha256"]
    assert sha256(OUTPUT/"report.json")==interpretation["v2_report_sha256"]==interpretation["v1_report_sha256"]
    addendum=read(REFERENCE/"reference_addendum_manifest.json")
    assert sha256(REFERENCE/addendum["path"])==addendum["sha256"]
    for entry in read(ROOT/"baseline_runs.json")+read(ROOT/"runs.json"):
        raw=ROOT/entry["run_path"];verify_market(raw)
        assert sha256(raw/"manifest.json")==entry["manifest_sha256"]
    saved=read(REFERENCE/"report.json")
    for entry in saved["records"]:
        raw=BASE/entry["run_path"];verify_market(raw)
        assert sha256(raw/"manifest.json")==entry["manifest_sha256"]
        paths+=list(raw.rglob("*"))
    for name,digest in saved["source_indexes"].items():
        path=BASE/name;assert sha256(path)==digest;paths.append(path)
    paths += [BASE/"runs"/name for name in ("horizon_pilot_20261104.py","horizon_checks_20261104.py","horizon_analysis_20261104.py","horizon_preserve_20261104.py","realism_review_20261104.py","sequential_tail_20261104.py","horizon_launch_20261104.json","horizon_launch_20261104.stdout.log","horizon_launch_20261104.stderr.log")]
    paths += [BASE/name for name in ("README.md","AGENT_EXPERIMENTS.md","ECONOMIC_MODEL.md","requirements.txt")]
    paths += [BASE/"tests/test_news_components.py"]
    repo=BASE.parent;paths += [repo/name for name in ("AGENTS.md","RESEARCH_DIARY.md","WORK_PLAN.tmp.md")]
    files={x.relative_to(repo).as_posix():x.read_bytes() for x in paths if x.is_file() and "__pycache__" not in x.parts}
    secrets={v.encode() for n in ("API_KEY","BHARATCODE_API_KEY","GEMINI_API_KEY","NVIDIA_API_KEY") if (v:=dotenv_api_key(n)) and len(v)>=8}
    scanned=0
    def scan(name,data):
        nonlocal scanned
        assert ".env" not in Path(name).name and ".git" not in Path(name).parts
        assert not any(s in data for s in secrets),"Secret scan failed; no export"
        scanned+=1
        if name.endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                assert z.testzip() is None
                for n in z.namelist():scan(n,z.read(n))
    for n,data in files.items():scan(n,data)
    old_bundles={"news_query_first_20261102_evidence.zip":"4ddbeca899dbe4e171468ce2de16692cdebd4e0cec4a734a24ed0dc7a3090176",
        "component_study_20261103_completed_evidence.zip":"89940c1eba9874b6686c9448197cf33979f9bb523fde6a8a47fd53de2b900ba9",
        "sequential_campaign_20261104_evidence.zip":"527bf047b71a0081b579a7530afe3311ec18ddf199dd7048f998e9ef1bd1e5de"}
    for n,d in old_bundles.items():assert sha256(BASE/"runs"/n)==d
    manifest=dict(scope="R032 frozen horizon pilot and reference/environment synthesis. Includes all actual new rule/live attempts, frozen unattempted slots if any, all15 reused long-rule input paths, actual prompts/costs/missing outputs. Does not claim reused inputs are new repeats.",
        protocol_sha256=sha256(ROOT/"protocol.json"),status=summary,files={n:hashlib.sha256(data).hexdigest() for n,data in files.items()},recursive_secret_scan_members=scanned,prior_bundles_unchanged=old_bundles,
        parent_revision=subprocess.check_output(["git","rev-parse","HEAD"],cwd=BASE,text=True).strip(),working_tree_status=subprocess.check_output(["git","status","--short"],cwd=BASE,text=True).splitlines(),
        analysis_environment=dict(python=platform.python_version(),libraries={n:importlib.metadata.version(n) for n in ("numpy","PyYAML","matplotlib")}),
        note="Documentation snapshots precede the diary entry recording the final bundle checksum. No .env or secrets included. Base sim source is in each frozen source archive; research adapter and analysis sources preserved separately.")
    with zipfile.ZipFile(destination,"x",zipfile.ZIP_DEFLATED) as z:
        for name,data in files.items():z.writestr(name,data)
        z.writestr("EVIDENCE_MANIFEST.json",json.dumps(manifest,indent=2))
    with zipfile.ZipFile(destination) as z:
        assert z.testzip() is None
        for n,d in manifest["files"].items():assert hashlib.sha256(z.read(n)).hexdigest()==d
    result=dict(path=destination.relative_to(repo).as_posix(),sha256=sha256(destination),bytes=destination.stat().st_size,files=len(files),recursive_secret_scan_members=scanned,zip_and_member_hash_checks=True,prior_bundles_unchanged=True)
    write_json(external,result);print(json.dumps(result))


if __name__=="__main__":main()
