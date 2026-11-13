"""Preserve R035 and immutable R033 ancestry without merging their outcomes."""
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
from runs import news_source10729_20261104 as d

ROOT=d.BASE/"runs/20261104_065011_news_source10729_09bd4875"
OUTPUT=d.BASE/"runs/news_source10729_analysis_20261104"

def main():
    p=d.validate(ROOT);summary=d.read(ROOT/"summary.json");assert summary["status"] in ("completed_phase_schedule","stopped","failed","interrupted")
    report=d.read(OUTPUT/"report.json");assert report["summary"]==summary and report["protocol_sha256"]==sha256(ROOT/"protocol.json")
    dest=d.BASE/"runs/news_source10729_20261104_evidence.zip";external=dest.with_name(dest.stem+"_manifest.json");assert not dest.exists() and not external.exists()
    for name,digest in d.read(OUTPUT/"artifact_manifest.json").items():assert sha256(OUTPUT/name)==digest
    if (OUTPUT/"interpretation_manifest.json").exists():assert sha256(OUTPUT/"INTERPRETATION.md")==d.read(OUTPUT/"interpretation_manifest.json")["sha256"]
    for e in d.read(ROOT/"source_runs.json"):
        d.parent.verify_market(ROOT/e["run_path"]);assert sha256(ROOT/e["run_path"]/"manifest.json")==e["manifest_sha256"]
    if (ROOT/"queries").exists():d.parent.verify_market(ROOT/"queries")
    old={"news_execution_20261104_evidence.zip":"23fda86c514a776521b4d2359d4d2b1c61a9bb58ea943408f62491684dc47504","component_study_20261103_completed_evidence.zip":"89940c1eba9874b6686c9448197cf33979f9bb523fde6a8a47fd53de2b900ba9","horizon_environment_20261104_evidence.zip":"28bd727d162f6a586b2c697634318d57822f1e5d52052adc92cd9f16202cb812"}
    for name,digest in old.items():assert sha256(d.BASE/"runs"/name)==digest
    paths=[x for folder in (ROOT,OUTPUT,d.PARENT) for x in folder.rglob("*")]
    paths += [d.BASE/"runs"/name for name in ("news_source10729_20261104.py","news_source10729_checks_20261104.py","news_source10729_analysis_20261104.py","news_source10729_preserve_20261104.py","news_auctions_20261104.py","horizon_pilot_20261104.py","sequential_tail_20261104.py","sequential_next_20261103.py","news_source10729_launch_20261104.json","news_source10729_launch_20261104.stdout.log","news_source10729_launch_20261104.stderr.log")]
    paths += [d.BASE/name for name in ("README.md","AGENT_EXPERIMENTS.md","ECONOMIC_MODEL.md","requirements.txt","tests/test_news_components.py")]
    repo=d.BASE.parent;paths += [repo/name for name in ("AGENTS.md","RESEARCH_DIARY.md","WORK_PLAN.tmp.md")]
    files={x.relative_to(repo).as_posix():x.read_bytes() for x in paths if x.is_file() and "__pycache__" not in x.parts}
    secrets={v.encode() for n in ("API_KEY","BHARATCODE_API_KEY","GEMINI_API_KEY","NVIDIA_API_KEY") if (v:=dotenv_api_key(n)) and len(v)>=8};count=0
    def scan(name,data):
        nonlocal count
        assert ".env" not in Path(name).name and ".git" not in Path(name).parts and not any(s in data for s in secrets),"Secret export guard failed"
        count+=1
        if name.endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                assert z.testzip() is None
                for n in z.namelist():scan(n,z.read(n))
    for n,data in files.items():scan(n,data)
    manifest=dict(scope="R035 only originally unattempted10729 source under explicit pre-call independent-source amendment. R033 failed9623 retained separately and missing; no retrospective R034 reply substituted or new seed. Conditional pilot, not completed two-history study.",
        summary=summary,phase_protocol_sha256=sha256(ROOT/"protocol.json"),parent_protocol_sha256=p["parent_protocol_sha256"],files={n:hashlib.sha256(data).hexdigest() for n,data in files.items()},recursive_secret_scan_members=count,prior_archives_unchanged=old,
        parent_revision=subprocess.check_output(["git","rev-parse","HEAD"],cwd=d.BASE,text=True).strip(),working_tree_status=subprocess.check_output(["git","status","--short"],cwd=d.BASE,text=True).splitlines(),environment=dict(python=platform.python_version(),libraries={n:importlib.metadata.version(n) for n in ("numpy","PyYAML","matplotlib")} ),note="Documentation snapshot before checksum/plan closure; all missing/negative results retained. No .env or secrets.")
    with zipfile.ZipFile(dest,"x",zipfile.ZIP_DEFLATED) as z:
        for n,data in files.items():z.writestr(n,data)
        z.writestr("EVIDENCE_MANIFEST.json",json.dumps(manifest,indent=2))
    with zipfile.ZipFile(dest) as z:
        assert z.testzip() is None
        for n,h in manifest["files"].items():assert hashlib.sha256(z.read(n)).hexdigest()==h
    result=dict(path=dest.relative_to(repo).as_posix(),sha256=sha256(dest),bytes=dest.stat().st_size,files=len(files),recursive_secret_scan_members=count,zip_member_hashes_checked=True,prior_archives_unchanged=True)
    write_json(external,result);print(json.dumps(result))

if __name__=="__main__":main()
