"""Explicit linked continuation of the frozen R025 query study; no policy edits."""
import argparse
import copy
from dataclasses import asdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import time
from types import SimpleNamespace
import uuid

import yaml

from sim.behaviour_run import score_choice
from sim.config import load_config, parse_config
from sim.llm.client import LLMClient
from sim.llm.usage import OutputLimitExceeded, ProviderUnavailable, RequestPacer, UsageBudget, UsageLimitExceeded
from sim.news_components import (comparisons, component_agent, execution_interval,
                                 messages, observation, validate as validate_parent)
from sim.provenance import finish_manifest, sha256, start_manifest, write_json

VERSION = "common_history_components_linked_continuation_v1"


def key(row):
    return row["frame_id"], row["repetition"], row["condition"], row["news"]


def pending_blocks(protocol, results, chains):
    if any(not r["valid_choice"] for r in results):
        raise ValueError("failed parsed choices require a separately reviewed design")
    done = {key(r) for r in results}
    if len(done) != len(results):
        raise ValueError("duplicate completed choices")
    scheduled = {(b["frame_id"], b["repetition"], c["condition"], c["news"])
                 for b in protocol["schedule"] for c in b["choices"]}
    if not done <= scheduled:
        raise ValueError("unexpected completed choice")
    chain_map = {(c["frame_id"], c["repetition"]): c for c in chains}
    if len(chain_map) != len(chains):
        raise ValueError("duplicate reflection chains")
    blocks = []
    for block in protocol["schedule"]:
        choices = [c for c in block["choices"] if (block["frame_id"], block["repetition"], c["condition"], c["news"]) not in done]
        if not choices: continue
        chain = chain_map.get((block["frame_id"], block["repetition"]))
        if chain is not None and [s["round"] for s in chain["steps"]] != [5, 10]:
            raise ValueError("partial reflection chain needs an explicit separate continuation")
        blocks.append(dict(frame_id=block["frame_id"], repetition=block["repetition"], choices=choices,
                           inherited_chain=copy.deepcopy(chain)))
    return blocks


def prepare(parent, output_root="runs"):
    parent = Path(parent).resolve()
    protocol, frames, parent_manifest = validate_parent(parent)
    summary = json.loads((parent / "summary.json").read_text())
    if summary["status"] != "provider_error":
        raise ValueError("this controller only continues the stopped provider-error study")
    for name, digest in parent_manifest["output_sha256"].items():
        if sha256(parent / name) != digest: raise ValueError("sealed parent output drift")
    results = json.loads((parent / "results.json").read_text())
    chains = json.loads((parent / "reflection_chains.json").read_text())
    blocks = pending_blocks(protocol, results, chains)
    if not blocks: raise ValueError("no pending work")
    cfg = load_config(parent / "config.yaml").to_dict()
    prior = summary["llm_usage"]
    for name, used in (("max_requests", "requests_made"), ("max_reserved_tokens", "reserved_tokens")):
        cfg["llm_limits"][name] -= prior[used]
        if cfg["llm_limits"][name] <= 0: raise ValueError("original allowance exhausted")
    cfg = parse_config(cfg)
    root = Path(output_root) / (time.strftime("%Y%m%d_%H%M%S_") + "components_continue_" + uuid.uuid4().hex[:8])
    root.mkdir(parents=True, exist_ok=False)
    (root / "config.yaml").write_text(yaml.safe_dump(cfg.to_dict()), encoding="utf-8")
    shutil.copyfile(parent / "frames.json", root / "frames.json")
    manifest = start_manifest(root, cfg)
    parent_files = {name: sha256(parent / name) for name in parent_manifest["output_sha256"]}
    parent_files["manifest.json"] = sha256(parent / "manifest.json")
    plan = dict(version=VERSION, parent=str(parent), parent_files_sha256=parent_files,
        parent_protocol_sha256=sha256(parent / "protocol.json"), source_sha256=manifest["source_sha256"],
        source_archive_sha256=manifest["source_archive_sha256"], config_sha256=sha256(root / "config.yaml"),
        frames_sha256=sha256(root / "frames.json"), blocks=blocks, prior_usage=prior,
        prior_completed_decisions=len(results), prior_completed_reflections=summary["completed_reflections"],
        planned_decisions=sum(len(b["choices"]) for b in blocks),
        planned_reflections=2*sum(b["inherited_chain"] is None for b in blocks),
        decision="Explicit user-authorized linked continuation; skip completed choices, preserve existing diary, original schedule/profile/caps. One execution, terminal failure stops, no automatic further restart. No endogenous C trajectory or new market state.")
    write_json(root / "plan.json", plan)
    manifest.update(status="prepared", experiment_kind=VERSION, plan_sha256=sha256(root / "plan.json"),
        endpoints=[cfg.agents[0].llm.base_url],
        config_scope="Remaining driver allowance only; actual observations/personas/source scenarios in frames.json and sealed parent. Prior usage is retained, not reset.")
    write_json(root / "manifest.json", manifest)
    print(f"prepared -> {root}", flush=True)
    return root


def validate(root):
    root = Path(root); plan = json.loads((root / "plan.json").read_text())
    manifest = json.loads((root / "manifest.json").read_text())
    if plan["version"] != VERSION or sha256(root / "plan.json") != manifest["plan_sha256"]:
        raise ValueError("continuation plan drift")
    parent = Path(plan["parent"])
    protocol, frames, _ = validate_parent(parent)
    for name, digest in plan["parent_files_sha256"].items():
        if sha256(parent / name) != digest: raise ValueError("sealed parent drift")
    for name, field in (("config.yaml", "config_sha256"), ("frames.json", "frames_sha256"), ("source.zip", "source_archive_sha256")):
        if sha256(root / name) != plan[field]: raise ValueError("continuation input drift")
    base = Path(__file__).resolve().parents[1]
    for name, digest in plan["source_sha256"].items():
        if sha256(base / name) != digest: raise ValueError("continuation source drift")
    expected = pending_blocks(protocol, json.loads((parent / "results.json").read_text()),
                              json.loads((parent / "reflection_chains.json").read_text()))
    if expected != plan["blocks"]: raise ValueError("pending schedule or diary drift")
    return plan, frames, manifest


def execute(root):
    root = Path(root)
    if (root / "execution.json").exists(): raise ValueError("already started; inspect existing evidence")
    plan, frames, manifest = validate(root)
    cfg = load_config(root / "config.yaml"); llm = cfg.agents[0].llm
    client = LLMClient(model=llm.model, base_url=llm.base_url, timeout=llm.timeout_seconds,
                       reasoning_effort=llm.reasoning_effort, send_temperature=True)
    if not client.api_key: raise ValueError("BharatCode credential missing; no calls made")
    with (root / "execution.json").open("x") as stream:
        json.dump(dict(pid=os.getpid(), started_utc=datetime.now(timezone.utc).isoformat(),
                       plan_sha256=sha256(root / "plan.json")), stream)
    budget = UsageBudget(**asdict(cfg.llm_limits)); budget.pacer = RequestPacer(10, 60000)
    definitions = {f["frame_id"]: f for f in frames}
    results = []; chains = []; status = "running"; failure_type = None; current = {}
    inherited = [copy.deepcopy(b["inherited_chain"]) for b in plan["blocks"] if b["inherited_chain"] is not None]
    for c in inherited: c["inherited"] = True
    chains.extend(inherited)
    def new_reflections(): return sum(len(c["steps"]) for c in chains if not c.get("inherited"))
    with (root / "llm_requests.jsonl").open("w", encoding="utf-8") as stream, \
         (root / "decision_inputs.jsonl").open("w", encoding="utf-8") as inputs:
        def record(item):
            stream.write(json.dumps({**item, **current}, allow_nan=False)+"\n"); stream.flush()
        def progress():
            write_json(root / "progress.json", dict(status=status, active=current if status=="running" else None,
                completed_decisions=len(results), planned_decisions=plan["planned_decisions"],
                completed_reflections=new_reflections(), planned_reflections=plan["planned_reflections"],
                cumulative_decisions=plan["prior_completed_decisions"]+len(results),
                cumulative_reflections=plan["prior_completed_reflections"]+new_reflections(), llm_usage=budget.snapshot()))
        try:
            for block in plan["blocks"]:
                frame = definitions[block["frame_id"]]; n = block["repetition"]
                if block["inherited_chain"] is not None:
                    diary = block["inherited_chain"]["steps"][-1]["diary"]
                else:
                    chain = dict(frame_id=frame["frame_id"], repetition=n, steps=[]); chains.append(chain)
                    reflector = component_agent(frame, "C", tag=f"continuation1:r{n}:history", client=client, budget=budget, log_fn=record)
                    for step in (5, 10):
                        current = dict(frame_id=frame["frame_id"], repetition=n, operation="reflection", history_round=step)
                        progress(); reflector.memory = copy.deepcopy(frame["reflection_windows"][str(step)])
                        reflector.reflect_if_due(SimpleNamespace(round=step, total_rounds=20))
                        if reflector.reflection_failures:
                            status="reflection_failure"; failure_type="reflection_failed"; break
                        chain["steps"].append(dict(round=step, diary=reflector.diary,
                            source_rounds=[r["round"] for r in reflector.memory]))
                        write_json(root / "reflection_chains.json", chains)
                    if status!="running": break
                    diary = reflector.diary
                write_json(root / "reflection_chains.json", chains)
                for choice in block["choices"]:
                    current = dict(frame_id=frame["frame_id"], repetition=n, operation="decision", **choice)
                    progress(); condition, news = choice["condition"], choice["news"]
                    agent = component_agent(frame, condition, tag=f"continuation1:r{n}:{news}", diary=diary,
                                            client=client, budget=budget, log_fn=record)
                    obs = observation(frame, news); prompt = messages(agent, obs)
                    if condition in ("A","B") and prompt!=frame["fixed_messages"][condition][news]:
                        raise ValueError("decision prompt drift")
                    inputs.write(json.dumps({**current,"messages":prompt,"diary":diary if condition=="C" else None},allow_nan=False)+"\n"); inputs.flush()
                    before=budget.requests; order=agent.decide(obs)
                    results.append({**current,**score_choice(agent,order,obs),
                        "possible_execution_prices":execution_interval(order,obs.price_history[-1]),"request_count":budget.requests-before})
                    write_json(root / "results.json",results); progress()
                    if not results[-1]["valid_choice"]:
                        status="parse_failure"; failure_type="parse_failed"; break
                if status!="running": break
                print(f"continued block {block['frame_id']} repetition{n}; {len(results)}/{plan['planned_decisions']} new choices",flush=True)
            else: status="completed"
        except (ProviderUnavailable, UsageLimitExceeded) as exc:
            status="provider_error" if isinstance(exc,ProviderUnavailable) else "output_truncated" if isinstance(exc,OutputLimitExceeded) else "budget_exhausted"
            failure_type=type(exc).__name__
        except BaseException as exc:
            status="interrupted" if isinstance(exc,KeyboardInterrupt) else "failed"; failure_type=type(exc).__name__
            raise
        finally:
            write_json(root / "results.json",results); write_json(root / "reflection_chains.json",chains)
            original=json.loads((Path(plan["parent"]) / "results.json").read_text())
            write_json(root / "combined_contrasts.json",comparisons(original+results,frames))
            summary=dict(status=status,rounds=0,completed_decisions=len(results),planned_decisions=plan["planned_decisions"],
                completed_reflections=new_reflections(),planned_reflections=plan["planned_reflections"],
                inherited_reflection_steps=sum(len(c["steps"]) for c in inherited),
                cumulative_decisions=plan["prior_completed_decisions"]+len(results),
                cumulative_reflections=plan["prior_completed_reflections"]+new_reflections(),
                failure_type=failure_type,llm_usage=budget.snapshot())
            write_json(root / "summary.json",summary); progress(); stream.flush(); inputs.flush()
            finish_manifest(root,manifest,summary)
    print(f"{status} -> {root}",flush=True)
    return root


if __name__=="__main__":
    parser=argparse.ArgumentParser(); parser.add_argument("action",choices=("prepare","run"))
    parser.add_argument("--parent"); parser.add_argument("--study"); parser.add_argument("--output-root",default="runs")
    args=parser.parse_args()
    if args.action=="prepare":
        if not args.parent: parser.error("prepare requires --parent")
        prepare(args.parent,args.output_root)
    else:
        if not args.study: parser.error("run requires --study")
        execute(args.study)
