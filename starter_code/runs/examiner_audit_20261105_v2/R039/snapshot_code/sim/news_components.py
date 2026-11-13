"""Bounded news/A-B-C decisions on common, real recorded histories; no fills."""
import argparse
import copy
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import shutil
import time
from types import SimpleNamespace
import uuid

import numpy as np
import yaml

from sim.agents.base import Observation
from sim.agents.llm_agent import LLMAgent, PROMPT_VERSION
from sim.behaviour_run import score_choice
from sim.config import load_config, parse_config
from sim.llm.client import LLMClient
from sim.llm.usage import OutputLimitExceeded, ProviderUnavailable, RequestPacer, UsageBudget, UsageLimitExceeded
from sim.market import CallAuctionMarket
from sim.news_controls import HEADLINE
from sim.news_pilot import SEEDS, extract_probes, market_recipe
from sim.provenance import finish_manifest, sha256, start_manifest, write_json

VERSION = "common_history_news_components_v1"
CONDITIONS = ("A", "B", "C")
NEWS = {"silent": None, "positive": HEADLINE,
        "negative": "A news report forecasts a sustained 20% fall in KGP's dividend per trading session; actual future payments remain uncertain."}
REPETITIONS = (1, 2, 3)


def recipe():
    cfg = market_recipe(SEEDS[0], "control", "qwen").to_dict()
    cfg.update(name="common_history_news_components", seed=0)
    base = cfg["agents"][-1]
    cfg["agents"] = []
    for condition in CONDITIONS:
        group = copy.deepcopy(base)
        group["count"] = 1
        group["llm"].update(condition=condition, reflect_every=5 if condition == "C" else 0,
                             transport_retries=1, retry_http_503=True)
        cfg["agents"].append(group)
    cfg["llm_limits"].update(max_requests=264, max_reserved_tokens=4000000)
    return parse_config(cfg)


def observation(frame, news):
    raw = copy.deepcopy(frame["observation"])
    raw["news"] = [] if NEWS[news] is None else [NEWS[news]]
    return Observation(**raw)


def component_agent(frame, condition, *, tag="prepared", diary="", client=None, budget=None, log_fn=None):
    obs = observation(frame, "silent")
    agent = LLMAgent(f"{frame['frame_id']}:{tag}:{condition}", obs.my_cash, obs.my_shares,
        np.random.default_rng(0),
        params=dict(condition=condition, memory_window=5, reflect_every=5 if condition == "C" else 0,
                    tick=.1, max_tokens=4096, transport_retries=1, retry_http_503=True),
        persona=frame["persona"], client=client, budget=budget, log_fn=log_fn,
        temperature=.3, initial_price=obs.price_history[-1], initial_cost=obs.my_avg_cost,
        transaction_tax=0.0, price_band=.2)
    agent.memory = copy.deepcopy(frame["memory"])
    agent.diary = diary if condition == "C" else ""
    return agent


def messages(agent, obs):
    return [dict(role="system", content=agent.system_prompt("KGP")),
            dict(role="user", content=agent.user_prompt(obs))]


def frame_constraints(frame):
    obs = observation(frame, "silent")
    price = obs.price_history[-1]
    lo, hi = CallAuctionMarket().price_bounds(price)
    return dict(cash=obs.my_cash, shares=obs.my_shares, price=price,
        stock_weight=obs.my_shares * price / obs.my_wealth,
        executable_price_bounds=[lo, hi],
        market_buy_capacity=math.floor(obs.my_cash / (price * 1.2) + 1e-12),
        maximum_possible_buy_at_band_floor=math.floor(obs.my_cash / lo + 1e-12),
        sell_capacity=obs.my_shares)


def schedule(frame_ids):
    blocks = []
    for n in REPETITIONS:
        ordered = frame_ids[n-1:] + frame_ids[:n-1]
        for frame_index, fid in enumerate(ordered):
            modes = list(CONDITIONS[n-1:] + CONDITIONS[:n-1])
            names = list(NEWS)
            offset = (frame_ids.index(fid) + n - 1) % 3
            names = names[offset:] + names[:offset]
            blocks.append(dict(frame_id=fid, repetition=n,
                choices=[dict(condition=c, news=news) for c in modes for news in names]))
    return blocks


def verify_source(root):
    root = Path(root)
    manifest = json.loads((root / "manifest.json").read_text())
    if manifest["status"] != "completed":
        raise ValueError("source market is incomplete")
    for name, digest in manifest["output_sha256"].items():
        if sha256(root / name) != digest:
            raise ValueError("source output drift")
    cfg = load_config(root / "config.yaml")
    if cfg.market.tick != .1 or cfg.market.price_band != .2 or cfg.market.transaction_tax != 0:
        raise ValueError("study expects the unchanged common exchange rules")
    if cfg.reveal_fundamental or cfg.rounds != 20:
        raise ValueError("unexpected source observation design")
    return manifest


def prepare_controls(controls, output_root="runs"):
    if set(controls) != set(SEEDS):
        raise ValueError("both designated source scenarios are required")
    # Validate everything before creating a new prepared-study directory.
    frames = []; source_paths = {}
    for seed in SEEDS:
        path = Path(controls[seed]); verify_source(path)
        if load_config(path / "config.yaml").seed != seed:
            raise ValueError("source scenario seed mismatch")
        source_paths[seed] = path
        outcomes = [json.loads(s) for s in (path / "agent_outcomes.jsonl").read_text().splitlines()]
        for case in extract_probes(path, seed):
            if case["announce"]:
                continue
            history = [r["outcome"] for r in outcomes if r["agent_id"] == case["agent_id"] and r["outcome"]["round"] <= 10]
            if [r["round"] for r in history] != list(range(1, 11)) or history[-5:] != case["memory"]:
                raise ValueError("actual source histories do not match the decision frame")
            frame = {k: copy.deepcopy(v) for k, v in case.items() if k not in ("case_id", "announce", "messages")}
            frame.update(frame_id=f"s{seed}_{case['agent_id']}", reflection_windows={"5": history[:5], "10": history[5:]})
            frame["fixed_messages"] = {c: {news: messages(component_agent(frame, c), observation(frame, news))
                                               for news in NEWS} for c in ("A", "B")}
            if frame["fixed_messages"]["A"]["silent"] != case["messages"]:
                raise ValueError("source A prompt mismatch")
            frame["constraints"] = frame_constraints(frame)
            frames.append(frame)
    if len(frames) != 4:
        raise ValueError("all four designated agent frames are required")
    root = Path(output_root) / (time.strftime("%Y%m%d_%H%M%S_") + "news_components_" + uuid.uuid4().hex[:8])
    root.mkdir(parents=True, exist_ok=False)
    source_hashes = {}
    for seed, path in source_paths.items():
        target = root / "sources" / str(seed)
        shutil.copytree(path, target)
        for file in target.rglob("*"):
            if file.is_file():
                source_hashes[file.relative_to(root).as_posix()] = sha256(file)
    cfg = recipe()
    (root / "config.yaml").write_text(yaml.safe_dump(cfg.to_dict()), encoding="utf-8")
    write_json(root / "frames.json", frames)
    manifest = start_manifest(root, cfg)
    protocol = dict(version=VERSION, prompt_suite_version=PROMPT_VERSION,
        frames_sha256=sha256(root / "frames.json"), config_sha256=sha256(root / "config.yaml"),
        source_sha256=manifest["source_sha256"], source_archive_sha256=manifest["source_archive_sha256"],
        source_evidence_sha256=source_hashes, news=NEWS, schedule=schedule([f["frame_id"] for f in frames]),
        planned_decisions=108, planned_reflections=24, planned_requests=132,
        limits=cfg.to_dict()["llm_limits"],
        scope="Four reused actual A-control histories, three fresh responses per news/mode/frame; no independent held-out markets. A/B isolate derived facts; B/C adds two generated reflections on the same A-generated past. C's pre-news diary is shared across news variants within frame/repetition. This is not an endogenous C trajectory or a news-retention experiment.",
        reflection_recipe="For every frame/repetition, fresh chain: reflect actual outcomes1-5 at round5, then actual6-10 at round10 with the first diary; standard C templates/120-word retention, temperature0. All choices at round11 use actual6-10 memory; no query executes or updates it.",
        metrics="All signed requested/accepted quantities, headroom/resource reductions, possible execution-price intervals, action/quantity variability; positive/silent and negative/silent within mode; adjacent B-A and C-B contrasts; costs/failures. No directional/profit pass oracle, market effects or human-validation claims.",
        stops="One execution only. Stop on terminal provider/output/budget, parse or reflection failure, preserve partials and unknown usage; no blind restart/model swap. Caps include every HTTP retry and JSON repair.")
    write_json(root / "protocol.json", protocol)
    manifest.update(status="prepared", experiment_kind=VERSION, protocol_sha256=sha256(root / "protocol.json"),
        endpoints=[cfg.agents[0].llm.base_url],
        config_scope="Driver model/settings only; actual source seeds/accounts/personas in frames.json and sources/. No financial rounds or scenario RNG draws.")
    write_json(root / "manifest.json", manifest)
    print(f"prepared -> {root}", flush=True)
    return root


def prepare(study, output_root="runs"):
    study = Path(study)
    index = json.loads((study / "delivery_v4_query_first/completed_market_index.json").read_text())
    controls = {}
    for seed in SEEDS:
        found = [r for r in index if r["brain"] == "qwen" and r["cell"] == "control" and r["seed"] == seed]
        if len(found) != 1:
            raise ValueError("exactly one complete designated control per seed required")
        controls[seed] = study / found[0]["run_path"]
    return prepare_controls(controls, output_root)


def validate(root):
    root = Path(root); protocol = json.loads((root / "protocol.json").read_text())
    manifest = json.loads((root / "manifest.json").read_text())
    if protocol["version"] != VERSION or protocol["prompt_suite_version"] != PROMPT_VERSION or protocol["news"] != NEWS:
        raise ValueError("protocol version drift")
    if sha256(root / "protocol.json") != manifest["protocol_sha256"]:
        raise ValueError("protocol drift")
    for filename, key in (("frames.json", "frames_sha256"), ("config.yaml", "config_sha256"), ("source.zip", "source_archive_sha256")):
        if sha256(root / filename) != protocol[key]:
            raise ValueError("prepared input/config drift")
    base = Path(__file__).resolve().parents[1]
    for name, digest in protocol["source_sha256"].items():
        if sha256(base / name) != digest:
            raise ValueError("prepared source drift")
    for name, digest in protocol["source_evidence_sha256"].items():
        if sha256(root / name) != digest:
            raise ValueError("source evidence drift")
    frames = json.loads((root / "frames.json").read_text())
    if protocol["schedule"] != schedule([f["frame_id"] for f in frames]) or len(frames) != 4:
        raise ValueError("schedule drift")
    for frame in frames:
        for condition in ("A", "B"):
            for news in NEWS:
                if messages(component_agent(frame, condition), observation(frame, news)) != frame["fixed_messages"][condition][news]:
                    raise ValueError("render drift")
    return protocol, frames, manifest


def execution_interval(order, price):
    """Prices at which this accepted limit could fill; never predicts a fill."""
    if order.side == "hold" or not order.quantity:
        return None
    market = CallAuctionMarket(); lo, hi = market.price_bounds(price)
    normalized = market._normalise(order)
    if normalized.limit_price is not None:
        if normalized.side == "buy": hi = min(hi, normalized.limit_price)
        else: lo = max(lo, normalized.limit_price)
    return [] if lo > hi else [lo, hi]


def comparisons(results, frames):
    lookup = {(r["frame_id"], r["repetition"], r["condition"], r["news"]): r for r in results}
    def value(fid, n, condition, news, metric):
        row = lookup.get((fid, n, condition, news))
        return None if row is None or not row["valid_choice"] else row[metric]
    def delta(a, b): return None if a is None or b is None else a - b
    news_rows = []; mode_rows = []
    for f in frames:
        fid = f["frame_id"]
        for n in REPETITIONS:
            for condition in CONDITIONS:
                for news in ("positive", "negative"):
                    news_rows.append(dict(frame_id=fid, repetition=n, condition=condition, news=news,
                        **{metric: delta(value(fid,n,condition,news,metric), value(fid,n,condition,"silent",metric))
                           for metric in ("requested_signed_quantity", "accepted_signed_quantity")}))
            for news in NEWS:
                for a, b in (("A", "B"), ("B", "C")):
                    mode_rows.append(dict(frame_id=fid, repetition=n, news=news, contrast=f"{b}-{a}",
                        **{metric: delta(value(fid,n,b,news,metric), value(fid,n,a,news,metric))
                           for metric in ("requested_signed_quantity", "accepted_signed_quantity")}))
    return dict(news_minus_silent=news_rows, adjacent_mode_contrasts=mode_rows,
        interpretation="Fresh repeated queries conditional on four reused states, not market repetitions. Missing failures stay null; direction is not correctness. Neither orders nor possible price intervals are executions.")


def execute(root):
    root = Path(root)
    if (root / "execution.json").exists():
        raise ValueError("already started; inspect existing evidence, never restart blindly")
    protocol, frames, manifest = validate(root)
    cfg = load_config(root / "config.yaml"); llm = cfg.agents[0].llm
    client = LLMClient(model=llm.model, base_url=llm.base_url, timeout=llm.timeout_seconds,
                       reasoning_effort=llm.reasoning_effort, send_temperature=True)
    if not client.api_key:
        raise ValueError("BharatCode credential missing; no calls made")
    import os
    with (root / "execution.json").open("x") as stream:
        json.dump(dict(pid=os.getpid(), started_utc=datetime.now(timezone.utc).isoformat(),
                       protocol_sha256=sha256(root / "protocol.json")), stream)
    budget = UsageBudget(**asdict(cfg.llm_limits)); budget.pacer = RequestPacer(10, 60000)
    definitions = {f["frame_id"]: f for f in frames}
    results = []; chains = []; status = "running"; failure_type = None; current = {}
    with (root / "llm_requests.jsonl").open("w", encoding="utf-8") as stream, \
         (root / "decision_inputs.jsonl").open("w", encoding="utf-8") as inputs:
        def record(item):
            stream.write(json.dumps({**item, **current}, allow_nan=False) + "\n"); stream.flush()
        def progress():
            write_json(root / "progress.json", dict(status=status, active=current,
                completed_decisions=len(results), planned_decisions=108,
                completed_reflections=sum(len(c["steps"]) for c in chains), planned_reflections=24,
                llm_usage=budget.snapshot()))
        try:
            for block in protocol["schedule"]:
                frame = definitions[block["frame_id"]]; n = block["repetition"]
                chain = dict(frame_id=frame["frame_id"], repetition=n, steps=[])
                chains.append(chain)
                reflector = component_agent(frame, "C", tag=f"r{n}:history", client=client, budget=budget, log_fn=record)
                for step in (5, 10):
                    current = dict(frame_id=frame["frame_id"], repetition=n, operation="reflection", history_round=step)
                    progress()
                    reflector.memory = copy.deepcopy(frame["reflection_windows"][str(step)])
                    reflector.reflect_if_due(SimpleNamespace(round=step, total_rounds=20))
                    if reflector.reflection_failures:
                        status = "reflection_failure"; failure_type = "reflection_failed"; break
                    chain["steps"].append(dict(round=step, diary=reflector.diary,
                        source_rounds=[r["round"] for r in reflector.memory]))
                    write_json(root / "reflection_chains.json", chains)
                if status != "running": break
                diary = reflector.diary
                for choice in block["choices"]:
                    current = dict(frame_id=frame["frame_id"], repetition=n, operation="decision", **choice)
                    progress()
                    condition, news = choice["condition"], choice["news"]
                    agent = component_agent(frame, condition, tag=f"r{n}:{news}", diary=diary,
                                            client=client, budget=budget, log_fn=record)
                    obs = observation(frame, news); prompt = messages(agent, obs)
                    if condition in ("A", "B") and prompt != frame["fixed_messages"][condition][news]:
                        raise ValueError("decision prompt drift")
                    inputs.write(json.dumps({**current, "messages": prompt,
                        "diary": diary if condition == "C" else None}, allow_nan=False) + "\n"); inputs.flush()
                    before = budget.requests; order = agent.decide(obs)
                    results.append({**current, **score_choice(agent, order, obs),
                        "possible_execution_prices": execution_interval(order, obs.price_history[-1]),
                        "request_count": budget.requests-before})
                    write_json(root / "results.json", results)
                    progress()
                    if not results[-1]["valid_choice"]:
                        status = "parse_failure"; failure_type = "parse_failed"; break
                if status != "running": break
                print(f"block {len(chains)}/12: {frame['frame_id']} repetition{n}", flush=True)
            else: status = "completed"
        except (ProviderUnavailable, UsageLimitExceeded) as exc:
            status = "provider_error" if isinstance(exc, ProviderUnavailable) else "output_truncated" if isinstance(exc, OutputLimitExceeded) else "budget_exhausted"
            failure_type = type(exc).__name__
        except BaseException as exc:
            status = "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed"
            failure_type = type(exc).__name__
            raise
        finally:
            write_json(root / "results.json", results)
            write_json(root / "reflection_chains.json", chains)
            write_json(root / "contrasts.json", comparisons(results, frames))
            summary = dict(status=status, rounds=0, completed_decisions=len(results), planned_decisions=108,
                completed_reflections=sum(len(c["steps"]) for c in chains), planned_reflections=24,
                valid_choices=sum(r["valid_choice"] for r in results), failure_type=failure_type,
                llm_usage=budget.snapshot())
            write_json(root / "summary.json", summary); progress(); stream.flush(); inputs.flush()
            finish_manifest(root, manifest, summary)
    print(f"{status} -> {root}", flush=True)
    return root


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "run"))
    parser.add_argument("--source-study"); parser.add_argument("--study")
    parser.add_argument("--output-root", default="runs")
    args = parser.parse_args()
    if args.action == "prepare":
        if not args.source_study: parser.error("prepare requires --source-study")
        prepare(args.source_study, args.output_root)
    else:
        if not args.study: parser.error("run requires --study")
        execute(args.study)
