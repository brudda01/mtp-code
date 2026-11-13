"""Preserve R038 stopped probe and independent completed R039, without pooling."""
import hashlib
import io
import json
from pathlib import Path
import zipfile
from sim.llm.client import dotenv_api_key
from sim.provenance import sha256, write_json
from sim.sequential_markets import verify_market
from runs import semantic_check_20261104 as s
from runs import market_validation_20261104 as m


def main():
    sr=s.BASE/"runs/20261104_154111_semantics_cd0076dc";mr=s.BASE/"runs/20261104_154730_market_validation_fff53e3b"
    s.validate(sr);m.validate(mr)
    assert s.read(sr/"summary.json")["status"]=="stopped" and m.read(mr/"summary.json")["status"]=="completed"
    for root in (sr,mr):
        for name,digest in s.read(root/"output_manifest.json").items():assert sha256(root/name)==digest
    assert sha256(sr/"READOUT.md")==s.read(sr/"reading_supplement_manifest.json")["readout_sha256"]
    for name,digest in s.read(mr/"supplement/artifact_manifest.json").items():assert sha256(mr/"supplement"/name)==digest
    assert sha256(mr/"supplement/INTERPRETATION.md")==s.read(mr/"supplement/interpretation_manifest.json")["sha256"]
    for entry in s.read(mr/"runs.json"):
        path=mr/entry["run_path"];verify_market(path);assert sha256(path/"manifest.json")==entry["manifest_sha256"]
    old={
        "initial_news_20261104_evidence.zip":"457fb1f642d759c5c7c5bfdd50d56e394cb6854b9f0395ff12c5378ca48ac669",
        "news_source10729_20261104_evidence.zip":"e3eda51c100d5eac2a7b59295e02509a691132e0df325a2019422a28d934b8c5",
        "news_execution_20261104_evidence.zip":"23fda86c514a776521b4d2359d4d2b1c61a9bb58ea943408f62491684dc47504",
        "horizon_environment_20261104_evidence.zip":"28bd727d162f6a586b2c697634318d57822f1e5d52052adc92cd9f16202cb812",
        "sequential_campaign_20261104_evidence.zip":"527bf047b71a0081b579a7530afe3311ec18ddf199dd7048f998e9ef1bd1e5de",
        "component_study_20261103_completed_evidence.zip":"89940c1eba9874b6686c9448197cf33979f9bb523fde6a8a47fd53de2b900ba9",
        "news_query_first_20261102_evidence.zip":"4ddbeca899dbe4e171468ce2de16692cdebd4e0cec4a734a24ed0dc7a3090176",
    }
    for name,digest in old.items():assert sha256(s.BASE/"runs"/name)==digest
    paths=[p for root in (sr,mr) for p in root.rglob("*")]
    paths += [s.BASE/"runs"/name for name in (
        "semantic_check_20261104.py","semantic_checks_20261104.py","semantic_launch_20261104.json",
        "semantic_launch_20261104.stdout.log","semantic_launch_20261104.stderr.log",
        "market_validation_20261104.py","market_validation_checks_20261104.py",
        "market_validation_supplement_20261104.py","balanced_validation_preserve_20261104.py")]
    repo=s.BASE.parent
    paths += [repo/name for name in ("AGENTS.md","RESEARCH_DIARY.md","WORK_PLAN.tmp.md")]
    paths += [s.BASE/name for name in ("README.md","AGENT_EXPERIMENTS.md","ECONOMIC_MODEL.md","requirements.txt")]
    files={p.relative_to(repo).as_posix():p.read_bytes() for p in paths if p.is_file() and "__pycache__" not in p.parts}
    secrets={v.encode() for key in ("API_KEY","BHARATCODE_API_KEY","GEMINI_API_KEY","NVIDIA_API_KEY") if (v:=dotenv_api_key(key)) and len(v)>=8};count=0
    def scan(name,data):
        nonlocal count
        assert ".env" not in Path(name).name and ".git" not in Path(name).parts and not any(value in data for value in secrets),"Secret export guard failed"
        count+=1
        if name.endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                assert archive.testzip() is None
                for member in archive.namelist():scan(member,archive.read(member))
    for name,data in files.items():scan(name,data)
    dest=s.BASE/"runs/balanced_validation_20261104_evidence.zip";external=dest.with_name(dest.stem+"_manifest.json")
    assert not dest.exists() and not external.exists()
    manifest=dict(scope="R038 strict-format stop with0 clarified replies retained separately from independent R039 four-pair rule confirmation and one frozen-window empirical total-return diagnostic. No pooled semantic/market efficacy claim, no default/A/B/C change.",
        semantic_summary=s.read(sr/"summary.json"),market_summary=s.read(mr/"summary.json"),
        semantic_protocol_sha256=sha256(sr/"protocol.json"),market_protocol_sha256=sha256(mr/"protocol.json"),
        files={name:hashlib.sha256(data).hexdigest() for name,data in files.items()},recursive_secret_scan_members=count,prior_archives_unchanged=old,
        note="Raw French source snapshot and fixed600 selected dates preserved; public download never used LLM credentials. Documentation snapshot before checksum/plan closure to avoid circular hashes. No .env or configured secret values.")
    with zipfile.ZipFile(dest,"x",zipfile.ZIP_DEFLATED) as archive:
        for name,data in files.items():archive.writestr(name,data)
        archive.writestr("EVIDENCE_MANIFEST.json",json.dumps(manifest,indent=2))
    with zipfile.ZipFile(dest) as archive:
        assert archive.testzip() is None
        for name,digest in manifest["files"].items():assert hashlib.sha256(archive.read(name)).hexdigest()==digest
    result=dict(path=dest.relative_to(repo).as_posix(),sha256=sha256(dest),bytes=dest.stat().st_size,files=len(files),recursive_secret_scan_members=count,prior_archives_unchanged=True,all_member_hashes_verified=True)
    write_json(external,result);print(json.dumps(result))


if __name__=="__main__":main()
