"""Offline recorded-output reproduction;never starts a live model campaign.

Run from the repo: python thesis/reproduce_saved.py --output starter_code/runs/NEW
Requires the indexed experiment trees and recorded numpy/PyYAML environment.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

REPO = Path(__file__).resolve().parent.parent
BASE = REPO / "starter_code"
STUDY = BASE / "runs/20261105_041035_common_prefix_ca10f93d"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(output):
    out = Path(output).resolve()
    if not out.is_relative_to((BASE / "runs").resolve()):
        raise ValueError("Output must be a new directory inside starter_code/runs")
    # Never overwrite or resume either evidence or an earlier reproduction.
    out.mkdir(exist_ok=False)
    shutil.copyfile(__file__, out / "reproduction_driver.py")
    result = dict(status="running", scope="Recorded-output reproduction,not fresh model draws or independent implementation",
                  new_api_requests=0, fresh_model_samples=0, live_campaigns_started=0)
    environment = {k: v for k, v in os.environ.items() if k != "API_KEY" and not k.endswith("_API_KEY")}

    def run(label, command, cwd):
        process = subprocess.run(command, cwd=cwd, env=environment, capture_output=True, text=True)
        (out / (label + ".stdout.log")).write_text(process.stdout, encoding="utf-8")
        (out / (label + ".stderr.log")).write_text(process.stderr, encoding="utf-8")
        if process.returncode:
            raise RuntimeError(f"{label} failed;preserved logs in {out}")

    try:
        run("writing_checks", [sys.executable, str(REPO / "thesis/verify_writing.py")], REPO)
        # Existing frozen audit records the original missing-helper failure,
        # then supplies only its explicitly archived R041 dependency.
        run("earlier", [sys.executable, "-m", "runs.examiner_audit_20261105", "--output", str(out / "earlier")], BASE)
        earlier = read(out / "earlier/replay_report.json")
        markets = [m for s in earlier["studies"] for m in s.get("supplemented_result", s["original_bundle_result"])["markets"]]
        assert len(markets) == 42 and all(all(m["exact_financial_files"].values()) for m in markets)
        assert all(s.get("supplemented_result", s["original_bundle_result"])["network_attempts"] == 0 for s in earlier["studies"])
        result["earlier"] = dict(paths=42, financial_csvs=294, network_attempts=0)

        code = out / "common_prefix_source"
        code.mkdir()
        protocol = read(STUDY / "protocol.json")
        source = STUDY / "prepared_source.zip"
        assert sha(source) == protocol["source_archive_sha256"]
        with zipfile.ZipFile(source) as archive:
            expected = protocol["source_sha256"]
            assert set(archive.namelist()) == set(expected)
            for name in archive.namelist():
                target = (code / name).resolve()
                if not target.is_relative_to(code.resolve()) or not name.endswith(".py"):
                    raise ValueError("Invalid source member")
                data = archive.read(name)
                assert hashlib.sha256(data).hexdigest() == expected[name]
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
        run("common_prefix", [sys.executable, str(code / "runs/common_prefix_replay_20261105.py"),
                              "--source", str(code), "--study", str(STUDY),
                              "--output", str(out / "common_prefix_replays"),
                              "--result", str(out / "common_prefix_report.json")], code)
        common = read(out / "common_prefix_report.json")
        assert common["verified_clean_paths"] == 23 and len(common["not_replayed"]) == 1
        assert common["network_attempts"] == 0 and all(all(m["financial_files"].values()) for m in common["records"])
        result.update(status="passed", common_prefix=dict(paths=23, financial_csvs=161, network_attempts=0,
                                                          explicit_exclusions=common["not_replayed"]),
                      inputs=dict(r047_protocol_sha256=sha(STUDY / "protocol.json"), r047_source_zip_sha256=sha(source)),
                      limitation="Same-environment saved-response replay;no independent machine,provider repeatability or human-market validation.")
    except BaseException as exc:
        result.update(status="failed", error_type=type(exc).__name__, error=str(exc))
        raise
    finally:
        (out / "summary.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    main(parser.parse_args().output)
