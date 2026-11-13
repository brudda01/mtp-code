"""Small run manifests and source snapshots for auditable pilot experiments."""
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import subprocess
import zipfile

from sim.agents.llm_agent import (CONDITION_VERSIONS, MARKET_RULES_TEMPLATE, PROMPT_VERSION, TRANSPORT_POLICY_VERSION,
                                  REFLECTION_TEMPLATE, SYSTEM_TEMPLATE, USER_TEMPLATE)


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def start_manifest(run_dir, cfg):
    run_dir = Path(run_dir)
    source = Path(__file__).resolve().parent
    source_files = sorted(source.rglob("*.py"))
    with zipfile.ZipFile(run_dir / "source.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for path in source_files:
            archive.write(path, "sim/" + path.relative_to(source).as_posix())
    try:
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source,
                                           text=True, stderr=subprocess.DEVNULL).strip()
        dirty = subprocess.check_output(["git", "status", "--short"], cwd=source,
                                        text=True, stderr=subprocess.DEVNULL).splitlines()
    except (OSError, subprocess.CalledProcessError):
        revision, dirty = None, None
    templates = {"system": SYSTEM_TEMPLATE, "user": USER_TEMPLATE,
                 "reflection": REFLECTION_TEMPLATE, "market_rules": MARKET_RULES_TEMPLATE}
    manifest = {"manifest_version": 1, "status": "running",
                "started_utc": datetime.now(timezone.utc).isoformat(),
                "python": platform.python_version(),
                "libraries": {name: importlib.metadata.version(name) for name in ("numpy", "PyYAML")},
                "parent_revision": revision, "working_tree_status": dirty,
                "source_sha256": {"sim/" + p.relative_to(source).as_posix(): sha256(p) for p in source_files},
                "source_archive_sha256": sha256(run_dir / "source.zip"),
                "normalized_config_sha256": sha256(run_dir / "config.yaml"),
                "prompt_suite_version": PROMPT_VERSION, "condition_versions": CONDITION_VERSIONS,
                "transport_policy_version": TRANSPORT_POLICY_VERSION,
                "prompt_templates_sha256": hashlib.sha256(
                    json.dumps(templates, sort_keys=True).encode()).hexdigest(),
                "seed": cfg.seed, "conditions": [g.llm.condition for g in cfg.agents if g.llm],
                "random_stream_scheme": "seedsequence_v1:environment,population,personas,allocation",
                "models": [{"provider": g.llm.provider, "configured_model": g.llm.model,
                            "condition": g.llm.condition, "temperature": g.llm.temperature,
                            "reflect_every": g.llm.reflect_every, "memory_window": g.llm.memory_window,
                            "max_tokens": g.llm.max_tokens, "timeout_seconds": g.llm.timeout_seconds,
                            "reasoning_effort": g.llm.reasoning_effort,
                            "send_temperature": g.llm.send_temperature,
                            "transport_retries": g.llm.transport_retries,
                            "retry_http_503": g.llm.retry_http_503,
                            "input_usd_per_million": g.llm.input_usd_per_million,
                            "output_usd_per_million": g.llm.output_usd_per_million}
                           for g in cfg.agents if g.llm],
                "usage_limits": cfg.to_dict()["llm_limits"],
                "reproducibility_note": "Seeds fix simulator randomness, not provider sampling. "
                    "Every response is logged; independent live repetitions must not reuse responses."}
    write_json(run_dir / "manifest.json", manifest)
    return manifest


def finish_manifest(run_dir, manifest, summary):
    run_dir = Path(run_dir)
    manifest.update(status=summary["status"], completed_rounds=summary["rounds"],
                    finished_utc=datetime.now(timezone.utc).isoformat(), usage=summary["llm_usage"])
    manifest["output_sha256"] = {p.name: sha256(p) for p in sorted(run_dir.iterdir())
                                  if p.is_file() and p.name != "manifest.json"}
    write_json(run_dir / "manifest.json", manifest)
