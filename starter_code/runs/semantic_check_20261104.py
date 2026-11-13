"""R038: one frozen old/new dividend reading check; never places orders."""
import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import time
import uuid
import zipfile
import numpy as np
from sim.agents.llm_agent import LLMAgent
from sim.llm.client import LLMClient
from sim.llm.usage import UsageBudget
from sim.news_controls import HEADLINE
from sim.provenance import sha256, write_json

BASE = Path(__file__).resolve().parents[1]
SOURCE = BASE / "runs/initial_news_analysis_20261104/semantic_examples.json"
VERSION = "dividend_level_reading_v1"
FIELDS = tuple(f"expected_dividend_session_{k}" for k in (1, 5, 10))
PROFILE = dict(model="qwen-3.8-27b", base_url="https://bharatcode.ai/api/model/v1",
               reasoning_effort="low", timeout=180, send_temperature=True)


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def headline(direction):
    change = "increase" if direction == "up" else "decrease"
    return (f"A news report forecasts a one-time 20% {change} in KGP's expected dividend per share, "
            "starting this trading session. The forecast is that the expected dividend will remain "
            "at this new level in later sessions. Actual future payments remain uncertain.")


def definitions():
    unique = {}
    for example in read(SOURCE)["examples"]:
        direction = example["cell"].split("_")[0]
        key = example["agent_id"] + "_" + direction
        if key in unique:
            assert example["messages"] == unique[key]["original_messages"]
            unique[key]["origins"].append(dict(seed=example["seed"], run=example["source_run"]))
            continue
        unique[key] = dict(direction=direction, actor=example["agent_id"],
                           original_messages=example["messages"], origins=[dict(seed=example["seed"], run=example["source_run"])])
    assert len(unique) == 4 and all(len(x["origins"]) == 2 for x in unique.values())
    for key, case in unique.items():
        messages = case["original_messages"]
        marker = "Respond ONLY with a JSON object, no other text:\n"
        assert messages[0]["content"].count(marker) == 1
        schema = {**{field: "<number>" for field in FIELDS}, "reasoning": "<one or two sentences>"}
        system = messages[0]["content"].split(marker)[0] + marker + json.dumps(schema)
        ending = "Decide your order for today. Remember: JSON only."
        assert messages[1]["content"].endswith(ending)
        task = ("Reading check only. For this calculation, use 0.02 as the expected dividend per share "
                "immediately before the report. Conditional on the report's forecast being accurate, "
                "what expected dividends does it imply in trading sessions 1, 5, and 10 after the report? "
                "Session 1 is this session. Report expected levels, not realized random payments. "
                "Return the requested JSON fields.")
        user = messages[1]["content"][:-len(ending)] + task
        old = HEADLINE if case["direction"] == "up" else HEADLINE.replace("20% rise", "20% fall")
        assert user.count(old) == 1
        case["messages"] = {
            "original": [dict(role="system", content=system), dict(role="user", content=user)],
            "clarified": [dict(role="system", content=system), dict(role="user", content=user.replace(old, headline(case["direction"]), 1))],
        }
    return unique


def classify(raw, direction):
    value = LLMAgent._extract_json(raw)
    try:
        json.dumps(value, allow_nan=False)
    except (ValueError, TypeError):
        value = None
    if not isinstance(value, dict) or any(type(value.get(k)) not in (int, float) or not math.isfinite(value[k]) for k in FIELDS):
        return dict(valid=False, parsed=value, interpretation="malformed", matches_level=[False]*3)
    factor = 1.2 if direction == "up" else .8
    near = lambda a, b: math.isclose(a, b, rel_tol=1e-7, abs_tol=1e-9)
    level = [near(value[k], .02*factor) for k in FIELDS]
    growth = [near(value[k], .02*factor**n) for k, n in zip(FIELDS, (1, 5, 10))]
    return dict(valid=True, parsed=value, interpretation="level" if all(level) else "repeated_growth" if all(growth) else "other_numeric_path", matches_level=level)


def prepare(output="runs"):
    cases = definitions()
    schedule = []
    keys = sorted(cases)
    for rep in (1, 2, 3):
        for j in range(4):
            key = keys[(j+rep-1) % 4]
            for wording in (("original", "clarified") if (j+rep) % 2 else ("clarified", "original")):
                schedule.append(dict(case=key, wording=wording, repetition=rep))
    root = Path(output) / (time.strftime("%Y%m%d_%H%M%S_") + "semantics_" + uuid.uuid4().hex[:8])
    root.mkdir(parents=True, exist_ok=False)
    sources = [*sorted((BASE/"sim").rglob("*.py")), Path(__file__)]
    hashes = {p.relative_to(BASE).as_posix(): sha256(p) for p in sources}
    with zipfile.ZipFile(root/"source.zip", "x", zipfile.ZIP_DEFLATED) as archive:
        for p in sources:
            archive.write(p, p.relative_to(BASE).as_posix())
    shutil.copyfile(__file__, root/"driver_source.py")
    shutil.copyfile(SOURCE, root/"original_source_examples.json")
    write_json(root/"cases.json", cases)
    protocol = dict(version=VERSION, status="frozen_before_requests", created_utc=datetime.now(timezone.utc).isoformat(),
                    parent_revision=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=BASE, text=True).strip(),
                    working_tree_status=subprocess.check_output(["git", "status", "--short"], cwd=BASE, text=True).splitlines(),
                    source_sha256=hashes, source_zip_sha256=sha256(root/"source.zip"), source_examples_sha256=sha256(SOURCE),
                    cases_sha256=sha256(root/"cases.json"), schedule=schedule, profile=PROFILE,
                    max_tokens=8192, temperature=.3, repetitions=3, limits=dict(max_requests=40,max_reserved_tokens=700000,max_cost_usd=0,requests_per_minute=10,input_tokens_per_minute=60000,stop_on_api_error=True),
                    interpretation="Four unique initial persona/sign contexts from eight original messages, not eight independent states. Explicit reading task replaces trading response instructions and supplies previous EXPECTED mean .02. Conditional-on-forecast arithmetic is not natural trading or human validation. Old repeated-growth reading is compatible with ambiguous wording. No preferred action/profit oracle or statistical efficacy claim.",
                    gate="All12 clarified replies and36 finite numeric fields match intended one-time level. No requirement old is worse. Failures/missing retained; no automatic new wording or qualification. Passing is not evidence of improved market outcomes.",
                    failures="First provider/budget/output or malformed numeric reply stops this semantic batch. Existing one shared identical-message transport/503 extra attempt. Valid but different numeric paths recorded without retry; no response selection/model switch/billing.")
    write_json(root/"protocol.json", protocol)
    write_json(root/"preparation.json", dict(protocol_sha256=sha256(root/"protocol.json")))
    print(root, flush=True)
    return root


def validate(root):
    p = read(root/"protocol.json")
    assert sha256(root/"protocol.json") == read(root/"preparation.json")["protocol_sha256"]
    assert sha256(root/"cases.json") == p["cases_sha256"] and sha256(root/"source.zip") == p["source_zip_sha256"]
    assert sha256(root/"original_source_examples.json") == p["source_examples_sha256"]
    assert all(sha256(BASE/name) == digest for name, digest in p["source_sha256"].items()), "Source drift"
    return p


def execute(root, *, client=None, budget=None):
    root = Path(root); p = validate(root)
    if any((x/"execution.json").exists() for x in root.parent.glob("*_semantics_*") if x.resolve()!=root.resolve()):
        raise ValueError("This semantic campaign version was already attempted")
    with (root/"execution.json").open("x") as stream:
        json.dump(dict(pid=os.getpid(), started_utc=datetime.now(timezone.utc).isoformat()), stream)
    client = client or LLMClient(**p["profile"])
    budget = budget or UsageBudget(**p["limits"])
    results = []; status = "running"; failure = None; current = {}
    with (root/"requests.jsonl").open("x", encoding="utf-8") as stream:
        def log(item):
            stream.write(json.dumps({**item, **current, "upstream_prompt_version":item.get("prompt_version"), "prompt_version":VERSION}, allow_nan=False)+"\n"); stream.flush()
        try:
            for number, item in enumerate(p["schedule"], 1):
                current = dict(item); case = read(root/"cases.json")[item["case"]]
                agent = LLMAgent(f"reading_{number}", 0, 0, np.random.default_rng(38),
                                 params=dict(max_tokens=8192, transport_retries=1, retry_http_503=True),
                                 client=client, budget=budget, temperature=.3, log_fn=log)
                raw, _ = agent._request(case["messages"][item["wording"]], number, "semantic_comprehension")
                if client.last_response_metadata.get("model") != p["profile"]["model"]:
                    raise ValueError("unexpected_response_model")
                result = {**item, **classify(raw, case["direction"])}; results.append(result)
                write_json(root/"results.json", results)
                print(f"reading {number}/24 {item['case']} {item['wording']}: {result['interpretation']}", flush=True)
                if not result["valid"]:
                    status = "stopped"; failure = "malformed_numeric_reply"; break
            else:
                status = "completed"
        except Exception as exc:
            status = "stopped"; failure = type(exc).__name__
        finally:
            clarified = [x for x in results if x["wording"] == "clarified"]
            summary = dict(status=status, failure_type=failure, completed=len(results), planned=24,
                           clarified_replies=len(clarified), clarified_level_fields=sum(sum(x["matches_level"]) for x in clarified),
                           clarified_gate=len(clarified)==12 and all(all(x["matches_level"]) for x in clarified),
                           usage=budget.snapshot(), finished_utc=datetime.now(timezone.utc).isoformat())
            write_json(root/"results.json", results); write_json(root/"summary.json", summary)
    write_json(root/"output_manifest.json", {x.name:sha256(x) for x in root.iterdir() if x.is_file() and x.name != "output_manifest.json"})
    print(json.dumps(summary), flush=True)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("action", choices=("prepare", "run")); parser.add_argument("--study"); parser.add_argument("--output", default="runs"); args = parser.parse_args()
    prepare(args.output) if args.action == "prepare" else execute(args.study)
