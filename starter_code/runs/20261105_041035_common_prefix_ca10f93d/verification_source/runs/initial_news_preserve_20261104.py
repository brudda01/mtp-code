"""Preserve the bounded R036 campaign, including negative/missing evidence."""
import hashlib
import importlib.metadata
import io
import json
from pathlib import Path
import platform
import subprocess
import zipfile
from sim.llm.client import dotenv_api_key
from sim.provenance import sha256, write_json
from runs import initial_news_20261104 as d

ROOT = d.BASE / "runs/20261104_140638_initial_news_ee0f084f"
OUTPUT = d.BASE / "runs/initial_news_analysis_20261104"


def main():
    d.validate(ROOT)
    summary = d.read(ROOT / "summary.json")
    assert summary["status"] in ("completed", "stopped", "failed", "interrupted")
    report = d.read(OUTPUT / "report.json")
    assert report["summary"] == summary
    assert report["protocol_sha256"] == sha256(ROOT / "protocol.json")
    dest = d.BASE / "runs/initial_news_20261104_evidence.zip"
    external = dest.with_name(dest.stem + "_manifest.json")
    assert not dest.exists() and not external.exists()
    for name, digest in d.read(OUTPUT / "artifact_manifest.json").items():
        assert sha256(OUTPUT / name) == digest
    interpretation = OUTPUT / "interpretation_manifest.json"
    if interpretation.exists():
        supplemental = d.read(interpretation)
        assert sha256(OUTPUT / "INTERPRETATION.md") == supplemental["sha256"]
        assert sha256(OUTPUT / "semantic_examples.json") == supplemental["semantic_examples_sha256"]
    for name in ("baseline_runs.json", "runs.json"):
        for entry in d.read(ROOT / name):
            path = ROOT / entry["run_path"]
            d.verify_market(path)
            assert sha256(path / "manifest.json") == entry["manifest_sha256"]
    old = {
        "news_source10729_20261104_evidence.zip": "e3eda51c100d5eac2a7b59295e02509a691132e0df325a2019422a28d934b8c5",
        "news_execution_20261104_evidence.zip": "23fda86c514a776521b4d2359d4d2b1c61a9bb58ea943408f62491684dc47504",
        "horizon_environment_20261104_evidence.zip": "28bd727d162f6a586b2c697634318d57822f1e5d52052adc92cd9f16202cb812",
        "sequential_campaign_20261104_evidence.zip": "527bf047b71a0081b579a7530afe3311ec18ddf199dd7048f998e9ef1bd1e5de",
        "component_study_20261103_completed_evidence.zip": "89940c1eba9874b6686c9448197cf33979f9bb523fde6a8a47fd53de2b900ba9",
        "news_query_first_20261102_evidence.zip": "4ddbeca899dbe4e171468ce2de16692cdebd4e0cec4a734a24ed0dc7a3090176",
    }
    for name, digest in old.items():
        assert sha256(d.BASE / "runs" / name) == digest
    paths = [x for folder in (ROOT, OUTPUT) for x in folder.rglob("*")]
    paths += [d.BASE / "runs" / name for name in (
        "initial_news_20261104.py", "initial_news_checks_20261104.py",
        "initial_news_analysis_20261104.py", "initial_news_analysis_checks_20261104.py",
        "initial_news_preserve_20261104.py", "horizon_pilot_20261104.py",
        "sequential_tail_20261104.py", "sequential_next_20261103.py",
        "initial_news_launch_20261104.json", "initial_news_launch_20261104.stdout.log",
        "initial_news_launch_20261104.stderr.log",
    )]
    paths += [d.BASE / name for name in (
        "README.md", "AGENT_EXPERIMENTS.md", "ECONOMIC_MODEL.md",
        "requirements.txt", "tests/test_news_components.py",
    )]
    repo = d.BASE.parent
    paths += [repo / name for name in ("AGENTS.md", "RESEARCH_DIARY.md", "WORK_PLAN.tmp.md")]
    files = {x.relative_to(repo).as_posix(): x.read_bytes()
             for x in paths if x.is_file() and "__pycache__" not in x.parts}
    secrets = {value.encode() for name in ("API_KEY", "BHARATCODE_API_KEY", "GEMINI_API_KEY", "NVIDIA_API_KEY")
               if (value := dotenv_api_key(name)) and len(value) >= 8}
    count = 0

    def scan(name, data):
        nonlocal count
        assert ".env" not in Path(name).name and ".git" not in Path(name).parts
        assert not any(secret in data for secret in secrets), "Secret export guard failed"
        count += 1
        if name.endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                assert archive.testzip() is None
                for member in archive.namelist():
                    scan(member, archive.read(member))

    for name, data in files.items():
        scan(name, data)
    manifest = dict(
        scope="R036 sequential initial-state controls only; same-resource rule companions, all scheduled live conditions and all failures/missing endpoints retained. Two fresh scenarios, one unseeded model path per cell. No selected restart, pooling with older prompts or production default change.",
        summary=summary, protocol_sha256=sha256(ROOT / "protocol.json"),
        files={name: hashlib.sha256(data).hexdigest() for name, data in files.items()},
        recursive_secret_scan_members=count, prior_archives_unchanged=old,
        parent_revision=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=d.BASE, text=True).strip(),
        working_tree_status=subprocess.check_output(["git", "status", "--short"], cwd=d.BASE, text=True).splitlines(),
        environment=dict(python=platform.python_version(), libraries={name: importlib.metadata.version(name) for name in ("numpy", "PyYAML", "matplotlib")}),
        note="Documentation snapshot before checksum/plan closure, avoiding a circular archive hash. Original evidence archives remain separate and hash-verified. No .env or keys.",
    )
    with zipfile.ZipFile(dest, "x", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
        archive.writestr("EVIDENCE_MANIFEST.json", json.dumps(manifest, indent=2))
    with zipfile.ZipFile(dest) as archive:
        assert archive.testzip() is None
        for name, digest in manifest["files"].items():
            assert hashlib.sha256(archive.read(name)).hexdigest() == digest
    result = dict(path=dest.relative_to(repo).as_posix(), sha256=sha256(dest),
                  bytes=dest.stat().st_size, files=len(files), recursive_secret_scan_members=count,
                  zip_member_hashes_checked=True, prior_archives_unchanged=True)
    write_json(external, result)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
