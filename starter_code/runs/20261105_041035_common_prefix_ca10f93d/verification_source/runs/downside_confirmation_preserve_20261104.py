"""Preserve R040 explicit reading evidence and bounded R041 without pooling."""
import hashlib
import io
import json
from pathlib import Path
import zipfile
from sim.llm.client import dotenv_api_key
from sim.provenance import sha256,write_json
from runs import candidate_reading_20261104 as reading
from runs import downside_confirmation_20261104 as d

ROOT=d.BASE/"runs/20261104_161605_downside_confirmation_1be3841b"
OUTPUT=d.BASE/"runs/downside_confirmation_analysis_20261104"


def main():
    d.validate(ROOT);d.verify_reading(d.GATE)
    summary=d.read(ROOT/"summary.json");assert summary["status"] in ("completed","stopped","failed","interrupted")
    report=d.read(OUTPUT/"report.json");assert report["summary"]==summary and report["protocol_sha256"]==sha256(ROOT/"protocol.json")
    for name,digest in d.read(OUTPUT/"artifact_manifest.json").items():assert sha256(OUTPUT/name)==digest
    assert sha256(OUTPUT/"INTERPRETATION.md")==d.read(OUTPUT/"interpretation_manifest.json")["sha256"]
    for name,digest in d.read(OUTPUT/"supplement_manifest.json").items():assert sha256(OUTPUT/name)==digest
    for name,digest in d.read(OUTPUT/"figure_v2/artifact_manifest.json").items():assert sha256(OUTPUT/"figure_v2"/name)==digest
    for name,digest in d.read(d.GATE/"output_manifest.json").items():assert sha256(d.GATE/name)==digest
    assert sha256(d.GATE/"READOUT.md")==d.read(d.GATE/"readout_manifest.json")["sha256"]
    for name in ("baseline_runs.json","runs.json"):
        for e in d.read(ROOT/name):
            path=ROOT/e["run_path"];d.base.verify_market(path);assert sha256(path/"manifest.json")==e["manifest_sha256"]
    old={
        "balanced_validation_20261104_evidence.zip":"04df396a0c84cf99ac66d5a842aae3168f2462caa2852dd7c78e52b7f326bb5b",
        "initial_news_20261104_evidence.zip":"457fb1f642d759c5c7c5bfdd50d56e394cb6854b9f0395ff12c5378ca48ac669",
        "news_source10729_20261104_evidence.zip":"e3eda51c100d5eac2a7b59295e02509a691132e0df325a2019422a28d934b8c5",
        "news_execution_20261104_evidence.zip":"23fda86c514a776521b4d2359d4d2b1c61a9bb58ea943408f62491684dc47504",
        "horizon_environment_20261104_evidence.zip":"28bd727d162f6a586b2c697634318d57822f1e5d52052adc92cd9f16202cb812",
        "sequential_campaign_20261104_evidence.zip":"527bf047b71a0081b579a7530afe3311ec18ddf199dd7048f998e9ef1bd1e5de",
        "component_study_20261103_completed_evidence.zip":"89940c1eba9874b6686c9448197cf33979f9bb523fde6a8a47fd53de2b900ba9",
        "news_query_first_20261102_evidence.zip":"4ddbeca899dbe4e171468ce2de16692cdebd4e0cec4a734a24ed0dc7a3090176",
    }
    for name,digest in old.items():assert sha256(d.BASE/"runs"/name)==digest
    paths=[x for folder in (ROOT,OUTPUT,d.GATE) for x in folder.rglob("*")]
    names=("candidate_reading_20261104.py","candidate_reading_checks_20261104.py","candidate_reading_launch_20261104.json","candidate_reading_launch_20261104.stdout.log","candidate_reading_launch_20261104.stderr.log",
        "downside_confirmation_20261104.py","downside_confirmation_checks_20261104.py","downside_confirmation_analysis_20261104.py","downside_analysis_checks_20261104.py","downside_confirmation_preserve_20261104.py",
        "downside_confirmation_launch_20261104.json","downside_confirmation_launch_20261104.stdout.log","downside_confirmation_launch_20261104.stderr.log",
        "initial_news_20261104.py","initial_news_analysis_20261104.py","horizon_pilot_20261104.py","sequential_tail_20261104.py","sequential_next_20261103.py","semantic_check_20261104.py","semantic_checks_20261104.py")
    paths += [d.BASE/"runs"/name for name in names]
    repo=d.BASE.parent;paths += [repo/name for name in ("AGENTS.md","RESEARCH_DIARY.md","WORK_PLAN.tmp.md")]
    paths += [d.BASE/name for name in ("README.md","AGENT_EXPERIMENTS.md","ECONOMIC_MODEL.md","requirements.txt","tests/test_news_components.py")]
    files={x.relative_to(repo).as_posix():x.read_bytes() for x in paths if x.is_file() and "__pycache__" not in x.parts}
    secrets={value.encode() for name in ("API_KEY","BHARATCODE_API_KEY","GEMINI_API_KEY","NVIDIA_API_KEY") if (value:=dotenv_api_key(name)) and len(value)>=8};count=0
    def scan(name,data):
        nonlocal count
        assert ".env" not in Path(name).name and ".git" not in Path(name).parts and not any(v in data for v in secrets),"Secret export guard failed"
        count+=1
        if name.endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                assert archive.testzip() is None
                for member in archive.namelist():scan(member,archive.read(member))
    for name,data in files.items():scan(name,data)
    dest=d.BASE/"runs/downside_confirmation_20261104_evidence.zip";external=dest.with_name(dest.stem+"_manifest.json")
    assert not dest.exists() and not external.exists()
    manifest=dict(scope="R040 candidate-only explicit reading check and R041 separate fresh repeated downside-news markets under two MM backgrounds. Full/partial/missing paths and all signs/costs retained. No old ambiguous-wording pooling,default selection or human/model-superiority claim.",
        reading_summary=d.read(d.GATE/"summary.json"),market_summary=summary,protocol_sha256=sha256(ROOT/"protocol.json"),reading_protocol_sha256=sha256(d.GATE/"protocol.json"),
        files={n:hashlib.sha256(data).hexdigest() for n,data in files.items()},recursive_secret_scan_members=count,prior_archives_unchanged=old,
        note="Documentation snapshot before checksum/plan closure avoids circular hash. All source/actual prompts/provider settings/request logs/repetitions and gate receipt preserved. R038 unchanged; no .env or configured secrets.")
    with zipfile.ZipFile(dest,"x",zipfile.ZIP_DEFLATED) as archive:
        for name,data in files.items():archive.writestr(name,data)
        archive.writestr("EVIDENCE_MANIFEST.json",json.dumps(manifest,indent=2))
    with zipfile.ZipFile(dest) as archive:
        assert archive.testzip() is None
        for name,digest in manifest["files"].items():assert hashlib.sha256(archive.read(name)).hexdigest()==digest
    result=dict(path=dest.relative_to(repo).as_posix(),sha256=sha256(dest),bytes=dest.stat().st_size,files=len(files),recursive_secret_scan_members=count,prior_archives_unchanged=True,all_member_hashes_verified=True)
    write_json(external,result);print(json.dumps(result))


if __name__=="__main__":main()
