"""Seal the terminal first-seed gate once; no API calls or raw-run mutations."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import zipfile

from sim.llm.client import dotenv_api_key
from sim.provenance import sha256,write_json
from sim.sequential_markets import validate
from runs.sequential_analysis_20261103 import ROOT,OUTPUT,analyze


def main():
    base=ROOT.parents[1];repo=base.parent
    summary=json.loads((ROOT/"block_4103/summary.json").read_text())
    assert summary["status"] in ("completed","stopped","failed","interrupted")
    assert not any((ROOT/f"block_{seed}/execution.json").exists() for seed in (5209,6317))
    validate(ROOT);analyze()
    destination=base/"runs/sequential_gate_20261103_evidence.zip"
    external=destination.with_name(destination.stem+"_manifest.json")
    assert not destination.exists() and not external.exists(),"Existing evidence is immutable"
    paths=list(ROOT.rglob("*"))+list(OUTPUT.rglob("*"))
    paths+=list((base/"runs/sequential_launch_20261103").rglob("*"))
    paths+=[base/"runs"/name for name in ("sequential_analysis_20261103.py","sequential_progress_20261103.py","sequential_preserve_20261103.py")]
    paths+=[base/"sim/sequential_markets.py",base/"tests/test_sequential_markets.py",base/"README.md",base/"AGENT_EXPERIMENTS.md"]
    paths+=sorted((base/"tests").rglob("*.py"))
    paths+=[p for p in (base/"requirements.txt",base/"pyproject.toml") if p.exists()]
    paths+=[repo/name for name in ("AGENTS.md","RESEARCH_DIARY.md","WORK_PLAN.tmp.md")]
    files={p.relative_to(repo).as_posix():p.read_bytes() for p in paths if p.is_file()}
    secrets={v.encode() for n in ("API_KEY","BHARATCODE_API_KEY","GEMINI_API_KEY","NVIDIA_API_KEY") if (v:=dotenv_api_key(n)) and len(v)>=8}
    scanned=0
    def scan(name,data):
        nonlocal scanned
        assert ".env" not in Path(name).name and ".git" not in Path(name).parts
        assert not any(value in data for value in secrets),"Secret scan failed; no evidence export"
        scanned+=1
        if name.endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                assert archive.testzip() is None
                for entry in archive.namelist():scan(entry,archive.read(entry))
    for name,data in files.items():scan(name,data)
    original_bundles={
        "news_query_first_20261102_evidence.zip":"4ddbeca899dbe4e171468ce2de16692cdebd4e0cec4a734a24ed0dc7a3090176",
        "component_study_20261103_completed_evidence.zip":"89940c1eba9874b6686c9448197cf33979f9bb523fde6a8a47fd53de2b900ba9"}
    for name,digest in original_bundles.items():assert sha256(base/"runs"/name)==digest
    manifest=dict(scope="R028 terminal first seed only, nine completed zero-API rule companions; six other live arms remain unrun.",
        block_summary=summary,protocol_sha256=sha256(ROOT/"protocol.json"),
        parent_revision=subprocess.check_output(["git","rev-parse","HEAD"],cwd=base,text=True).strip(),
        working_tree_status=subprocess.check_output(["git","status","--short"],cwd=base,text=True).splitlines(),
        files={name:hashlib.sha256(data).hexdigest() for name,data in files.items()},
        recursive_secret_scan_members=scanned,prior_evidence_unchanged=original_bundles,
        note="Documentation snapshots precede the diary entry recording this bundle checksum; no secrets or .env included.")
    with zipfile.ZipFile(destination,"x",zipfile.ZIP_DEFLATED) as archive:
        for name,data in files.items():archive.writestr(name,data)
        archive.writestr("EVIDENCE_MANIFEST.json",json.dumps(manifest,indent=2))
    with zipfile.ZipFile(destination) as archive:
        assert archive.testzip() is None
        for name,digest in manifest["files"].items():assert hashlib.sha256(archive.read(name)).hexdigest()==digest
    result=dict(path=destination.relative_to(repo).as_posix(),sha256=sha256(destination),bytes=destination.stat().st_size,
        files=len(files),recursive_secret_scan_members=scanned,zip_and_member_hash_checks=True,prior_bundles_unchanged=True)
    write_json(external,result);print(json.dumps(result))


if __name__=="__main__":main()
