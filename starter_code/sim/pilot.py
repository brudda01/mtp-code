"""A bounded first live diagnostic, deliberately separate from headline research.

Protocol is saved before any generation. Model replies and independent repeats
are never cached or reused. Keys are scoped to the explicitly configured provider.
Run probes first; inspect them before invoking the micro-market phase.
"""
from dataclasses import asdict, replace
import argparse
import json
from pathlib import Path
import time
import uuid

import numpy as np
import yaml

from sim.agents.base import Observation
from sim.agents.llm_agent import LLMAgent, PROMPT_VERSION
from sim.config import parse_config
from sim.engine import run
from sim.llm.client import LLMClient
from sim.llm.usage import ProviderUnavailable, RequestPacer, UsageBudget, UsageLimitExceeded
from sim.provenance import finish_manifest, start_manifest, write_json

MODEL = "qwen-3.8-27b"
ENDPOINT = "https://bharatcode.ai/api/model/v1"
PROTOCOL_VERSION = "first_live_diagnostic_v5_qwen_disclosed_rules"
# Student-included tokens have no incremental per-token price. This excludes any
# subscription charge and does not assert remaining allowance or provider RPM.
INPUT_PRICE, OUTPUT_PRICE = 0.0, 0.0
RPM, INPUT_TPM = 10, 60000
MAX_TOKENS, TEMPERATURE, REASONING_EFFORT = 2048, 0.3, "low"
TIMEOUT = 180
PERSONA = dict(name="Pilot Trader", age=35, occupation="professional",
               risk_tolerance="medium", strategy_inclination="balanced", horizon="medium",
               backstory="You invest your savings in stocks and cash.", bias_clauses="")


def market_recipe(condition, seed):
    raw = yaml.safe_load((Path(__file__).resolve().parents[1] / "configs/pilot_a_mock.yaml").read_text())
    raw.update(name=f"qwen_{condition.lower()}_s{seed}", seed=seed, rounds=4,
               execution={"max_workers": 1}, llm_limits={
                   "max_requests": 12, "max_reserved_tokens": 100000, "max_cost_usd": 0,
                   "requests_per_minute": RPM, "input_tokens_per_minute": INPUT_TPM,
                   "stop_on_api_error": True})
    group = raw["agents"][-1]
    group["count"] = 2
    group["llm"] = dict(provider="openai_compatible", model=MODEL, base_url=ENDPOINT,
                        condition=condition, memory_window=2,
                        reflect_every=2 if condition == "C" else 0,
                        max_tokens=MAX_TOKENS, temperature=TEMPERATURE, timeout_seconds=TIMEOUT,
                        reasoning_effort=REASONING_EFFORT,
                        send_temperature=True,
                        input_usd_per_million=INPUT_PRICE, output_usd_per_million=OUTPUT_PRICE)
    return parse_config(raw)


def probe_cases():
    base = Observation(6, 20, [100.0]*6, 10, 0.02, 0.0002, None,
                       [], [], 10000, 100, 100, 20000, [])
    result = []
    for repetition in (1, 2):
        for variant, hint in (("value_100", 100), ("value_120", 120)):
            result.append(dict(family="disclosed_value", variant=variant, repetition=repetition,
                               condition="A", observation=asdict(replace(base, fundamental_hint=hint)), persona=PERSONA))
        for variant, news in (("no_news", []), ("positive_headline", [
                "A newspaper reports that KGP's future dividends may rise by 20%; this is unverified."])):
            result.append(dict(family="headline_only", variant=variant, repetition=repetition,
                               condition="A", observation=asdict(replace(base, news=news)), persona=PERSONA))
        for risk in ("low", "high"):
            obs = replace(base, price_history=[100, 102, 104, 106, 108, 110], my_wealth=21000)
            result.append(dict(family="risk_trait", variant=risk, repetition=repetition,
                               condition="A", observation=asdict(obs), persona={**PERSONA, "risk_tolerance": risk}))
    for condition in ("A", "B"):
        for variant, cash in (("little_cash_no_shares", 10), ("empty_account", 0)):
            obs = replace(base, my_cash=cash, my_shares=0, my_avg_cost=0, my_wealth=cash,
                          fundamental_hint=120)
            result.append(dict(family="constraints", variant=variant, repetition=1,
                               condition=condition, observation=asdict(obs), persona=PERSONA))
    # Mix family/variant order in advance, independently of any reply. Two calls
    # in a pair remain independent; order is retained for drift interpretation.
    rng = np.random.default_rng(704)
    return [result[i] for i in rng.permutation(len(result))]


def probes(output_root="runs"):
    cfg = market_recipe("A", 704)
    raw = cfg.to_dict()
    raw["llm_limits"].update(max_requests=24, max_cost_usd=0)
    cfg = parse_config(raw)
    target = Path(output_root) / (time.strftime("%Y%m%d_%H%M%S_") + "qwen_probes_" + uuid.uuid4().hex[:8])
    target.mkdir(parents=True)
    (target / "config.yaml").write_text(yaml.safe_dump(cfg.to_dict()), encoding="utf-8")
    protocol = dict(version=PROTOCOL_VERSION, question="Does the live model support a useful bounded pilot?",
                    probe_cases=probe_cases(), arithmetic_repetitions=2,
                    arithmetic_expected={"price_change_pct": 10, "interest_income": 2,
                                         "dividend_income": 2, "maximum_affordable_shares": 96},
                    market_conditions=[{"seed": seed, "condition": condition} for seed in (704, 905) for condition in "ABC"],
                    limits="At most 24 probe attempts + six runs of at most 12 = 96; 700000 byte-based token reservations. Zero incremental student token price; no subscription/upgrade purchased.",
                    model_change="User selected BharatCode Qwen student access after Gemini access failures. Preserve earlier Lite/Gemini artifacts separately; not an isolated model-size ablation.",
                    sampling="Requested temperature 0.3 decisions/probes, 0 reflections; low reasoning effort, output cap 2048. Provider RNG/seed and effective sampling implementation are not exposed.",
                    interpretation="Diagnostic only; independent replies, two repeats per paired probe, no population or long-run realism claim.",
                    price_source="https://bharatcode.ai/build", billing_tier="User-reported verified student benefit, 10M tokens/day; no per-token billing in this included allowance. Remaining allowance not independently verified.",
                    quota_basis="Chosen 10 RPM / 60000 byte-based input estimates per minute; actual RPM/queue limit unknown. 180-second timeout, no hidden retries, stop on provider errors or truncated output.")
    write_json(target / "protocol.json", protocol)
    manifest = start_manifest(target, cfg)
    manifest.update(experiment_kind="fixed_observation_probes", protocol_version=PROTOCOL_VERSION, endpoints=[ENDPOINT])
    write_json(target / "manifest.json", manifest)
    budget = UsageBudget(**asdict(cfg.llm_limits))
    client = LLMClient(model=MODEL, base_url=ENDPOINT, timeout=TIMEOUT,
                       reasoning_effort=REASONING_EFFORT, send_temperature=True)
    completed, status, error_type = 0, "running", None
    results = []
    with (target / "llm_requests.jsonl").open("w", encoding="utf-8") as log:
        def record(item):
            log.write(json.dumps(item, allow_nan=False) + "\n")
            log.flush()

        def trader(case_id, condition="A", persona=None, cash=10000, shares=100):
            return LLMAgent(case_id, cash, shares, np.random.default_rng(704),
                            params={"condition": condition, "memory_window": 2, "max_tokens": MAX_TOKENS,
                                    "tick": cfg.market.tick},
                            persona=persona or PERSONA, client=client, temperature=TEMPERATURE,
                            budget=budget, input_price=INPUT_PRICE, output_price=OUTPUT_PRICE, log_fn=record,
                            transaction_tax=cfg.market.transaction_tax, price_band=cfg.market.price_band)
        try:
            # Arithmetic is an objective task, deliberately separate from free
            # economic choices. No expected buy/sell answer is supplied to agents.
            for repetition in (1, 2):
                agent = trader(f"arithmetic_{repetition}")
                messages = [{"role": "system", "content": "Compute the requested quantities. Return only one JSON object with the requested keys."},
                            {"role": "user", "content": "Prices changed from 100 to 110. Cash is 10000, shares 100, last price 110. Per-round cash interest rate is 0.0002; dividend is 0.02 per share. A limit buy costs at most 104 per share with no tax or other fees. Compute price_change_pct, interest_income, dividend_income, maximum_affordable_shares (whole shares)."}]
                raw_reply, meta = agent._request(messages, 0, "arithmetic")
                results.append(dict(case_id=agent.agent_id, family="arithmetic", repetition=repetition,
                                    parsed=agent._extract_json(raw_reply), status=meta["status"]))
                completed += 1
                print(f"probe {completed}/18 arithmetic", flush=True)
            for i, case in enumerate(protocol["probe_cases"]):
                obs = Observation(**case["observation"])
                case_id = f"p{i:02d}_{case['family']}_{case['variant']}_r{case['repetition']}"
                agent = trader(case_id, case["condition"], case["persona"], obs.my_cash, obs.my_shares)
                order = agent.decide(obs)
                results.append(dict(case_id=case_id, family=case["family"], variant=case["variant"],
                                    repetition=case["repetition"], condition=case["condition"],
                                    requested=agent.last_intent, accepted=asdict(order),
                                    parse_failures=agent.parse_failures, api_failures=agent.api_failures))
                completed += 1
                print(f"probe {completed}/18 {case['family']} {case['variant']}", flush=True)
            status = "completed"
        except (ProviderUnavailable, UsageLimitExceeded) as exc:
            status = "provider_error" if isinstance(exc, ProviderUnavailable) else "budget_exhausted"
            error_type = type(exc).__name__
        except BaseException as exc:
            status, error_type = "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed", type(exc).__name__
            raise
        finally:
            write_json(target / "results.json", results)
            summary = dict(status=status, rounds=0, completed_probes=completed, planned_probes=18,
                           failure_type=error_type, llm_usage=budget.snapshot())
            write_json(target / "summary.json", summary)
            finish_manifest(target, manifest, summary)
    print(f"{status} -> {target}", flush=True)
    return target


def markets(probe_dir):
    probe_dir = Path(probe_dir)
    if json.loads((probe_dir / "summary.json").read_text())["status"] != "completed":
        raise ValueError("successful probes are required before micro-market trials")
    probe_manifest = json.loads((probe_dir / "manifest.json").read_text())
    if (probe_manifest["models"][0]["configured_model"] != MODEL or
            probe_manifest.get("prompt_suite_version") != PROMPT_VERSION or
            json.loads((probe_dir / "protocol.json").read_text())["version"] != PROTOCOL_VERSION):
        raise ValueError("probe model/protocol must match the current pilot; do not mix model batches")
    pacer = RequestPacer(RPM, INPUT_TPM)
    outputs = []
    # Seed-specific condition order is fixed, so elapsed provider drift does not
    # always put reflection last. It does not establish provider stationarity.
    protocol = {"version": PROTOCOL_VERSION, "runs": [
        {"seed": seed, "condition": condition} for seed, order in ((704, "ABC"), (905, "CBA")) for condition in order]}
    write_json(probe_dir / "market_schedule.json", protocol)
    for item in protocol["runs"]:
        cfg = market_recipe(item["condition"], item["seed"])
        config = probe_dir / f"market_{item['condition']}_{item['seed']}.yaml"
        config.write_text(yaml.safe_dump(cfg.to_dict()), encoding="utf-8")
        path = Path(run(config, output_root=probe_dir.parent, request_pacer=pacer))
        summary = json.loads((path / "summary.json").read_text())
        outputs.append({**item, "run_id": path.name, "status": summary["status"]})
        write_json(probe_dir / "market_runs.json", outputs)
        if summary["status"] != "completed" or summary["parse_failures"]:
            break
    return outputs


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("probes", "markets"))
    parser.add_argument("--probe-dir")
    args = parser.parse_args()
    if args.phase == "probes":
        probes()
    elif args.probe_dir:
        markets(args.probe_dir)
    else:
        parser.error("markets requires --probe-dir")
