"""Seal the separate failed R033 and retrospective R034 without altering either."""
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
from runs.news_auctions_20261104 import BASE,read,validate,verify_market

ROOT=BASE/"runs/20261104_055619_news_auctions_a2e319da"
ANALYSIS=BASE/"runs/news_auction_analysis_20261104"
OFFLINE=BASE/"runs/retrospective_execution_20261104"

def main():
    validate(ROOT);s=read(ROOT/"summary.json");assert s["status"]=="stopped" and s["completed_auctions"]==0
    dest=BASE/"runs/news_execution_20261104_evidence.zip";external=dest.with_name(dest.stem+"_manifest.json")
    assert not dest.exists() and not external.exists(),"Prior evidence must stay immutable"
    folders=[ROOT,ANALYSIS,OFFLINE];paths=[]
    for e in read(ROOT/"source_runs.json"):
        verify_market(ROOT/e["run_path"]);assert sha256(ROOT/e["run_path"]/"manifest.json")==e["manifest_sha256"]
    protocol=read(OFFLINE/"protocol.json")
    for name,digest in protocol["source_and_code_sha256"].items():
        x=BASE/name;assert sha256(x)==digest;paths.append(x)
    assert sha256(BASE/"runs/retrospective_execution_20261104.py")==protocol["analysis_sha256"]
    for name in ("20261103_023441_news_components_da6bdf79","20261103_172911_components_continue_f62a08f1","20261103_174525_components_tail_90002a97"):verify_market(BASE/"runs"/name)
    for folder in (ANALYSIS,OFFLINE,OFFLINE/"depth_sensitivity"):
        for name,digest in read(folder/"artifact_manifest.json").items():assert sha256(folder/name)==digest
    manual=read(OFFLINE/"interpretation_manifest.json");assert sha256(OFFLINE/"INTERPRETATION.md")==manual["interpretation_sha256"]
    assert sha256(OFFLINE/"INTERPRETATION_v1.md")==manual["prior_interpretation_sha256"]
    assert read(OFFLINE/"wealth_identity_check.json")["passed"]
    old={"component_study_20261103_completed_evidence.zip":"89940c1eba9874b6686c9448197cf33979f9bb523fde6a8a47fd53de2b900ba9","horizon_environment_20261104_evidence.zip":"28bd727d162f6a586b2c697634318d57822f1e5d52052adc92cd9f16202cb812","sequential_campaign_20261104_evidence.zip":"527bf047b71a0081b579a7530afe3311ec18ddf199dd7048f998e9ef1bd1e5de"}
    for name,digest in old.items():assert sha256(BASE/"runs"/name)==digest
    for folder in folders:paths+=list(folder.rglob("*"))
    paths += [BASE/"runs"/name for name in ("news_auctions_20261104.py","news_auction_checks_20261104.py","news_auction_analysis_20261104.py","retrospective_execution_20261104.py","execution_depth_20261104.py","news_execution_preserve_20261104.py","horizon_pilot_20261104.py","sequential_tail_20261104.py","sequential_next_20261103.py","news_auction_launch_20261104.json","news_auction_launch_20261104.stdout.log","news_auction_launch_20261104.stderr.log")]
    paths += [BASE/name for name in ("README.md","AGENT_EXPERIMENTS.md","ECONOMIC_MODEL.md","requirements.txt","tests/test_news_components.py")]
    repo=BASE.parent;paths += [repo/name for name in ("AGENTS.md","RESEARCH_DIARY.md","WORK_PLAN.tmp.md")]
    files={p.relative_to(repo).as_posix():p.read_bytes() for p in paths if p.is_file() and "__pycache__" not in p.parts}
    secrets={v.encode() for n in ("API_KEY","BHARATCODE_API_KEY","GEMINI_API_KEY","NVIDIA_API_KEY") if (v:=dotenv_api_key(n)) and len(v)>=8};count=0
    def scan(name,data):
        nonlocal count
        assert ".env" not in Path(name).name and ".git" not in Path(name).parts and not any(s in data for s in secrets),"Secret/file export guard failed"
        count+=1
        if name.endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                assert z.testzip() is None
                for n in z.namelist():scan(n,z.read(n))
    for name,data in files.items():scan(name,data)
    manifest=dict(scope="R033 FAILED before source round1 completed: no new behavioural result. R034 DISTINCT retrospective36-A-reply one-focal execution extension and one post-hoc current-MM-depth sensitivity: zero new replies. Reused raw component histories/results retained, not new replications.",
        source_status=s,retrospective_audit=read(OFFLINE/"report.json")["audit"],files={n:hashlib.sha256(data).hexdigest() for n,data in files.items()},recursive_secret_scan_members=count,prior_bundles_unchanged=old,
        parent_revision=subprocess.check_output(["git","rev-parse","HEAD"],cwd=BASE,text=True).strip(),working_tree_status=subprocess.check_output(["git","status","--short"],cwd=BASE,text=True).splitlines(),environment=dict(python=platform.python_version(),libraries={n:importlib.metadata.version(n) for n in ("numpy","PyYAML","matplotlib")}),
        note="Documentation snapshots precede final archive checksum/plan closure. Old C failure and all signs remain; original interpretation count-error draft/manifest preserved with explicit correction. No .env/keys.")
    with zipfile.ZipFile(dest,"x",zipfile.ZIP_DEFLATED) as z:
        for n,data in files.items():z.writestr(n,data)
        z.writestr("EVIDENCE_MANIFEST.json",json.dumps(manifest,indent=2))
    with zipfile.ZipFile(dest) as z:
        assert z.testzip() is None
        for n,d in manifest["files"].items():assert hashlib.sha256(z.read(n)).hexdigest()==d
    result=dict(path=dest.relative_to(repo).as_posix(),sha256=sha256(dest),bytes=dest.stat().st_size,files=len(files),recursive_secret_scan_members=count,zip_member_hashes_checked=True,prior_bundles_unchanged=True)
    write_json(external,result);print(json.dumps(result))

if __name__=="__main__":main()
