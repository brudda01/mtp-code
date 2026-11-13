"""Freeze and run a small, model-neutral diagnostic before larger experiments.

Objective tasks have numeric oracles. Discretionary order choices have no
profitable-action oracle; resource compliance and responses are reported apart.
The later challenger receives the exact same first-attempt messages, not newly
rendered scenarios or a selected subset. No model's replies are reused.
"""
from dataclasses import asdict, replace
import argparse
import hashlib
import json
from pathlib import Path
import time
import uuid

import numpy as np
import yaml

from sim.agents.base import Agent, Observation
from sim.agents.llm_agent import LLMAgent, PROMPT_VERSION, market_rules_prompt
from sim.config import parse_config
from sim.llm.client import LLMClient
from sim.llm.usage import ProviderUnavailable, UsageBudget, UsageLimitExceeded
from sim.market import CallAuctionMarket, Order, settle
from sim.pilot import PERSONA
from sim.provenance import finish_manifest, start_manifest, write_json

BATTERY_VERSION = "fresh_capability_v1_disclosed_rules"
SETUP_SEED = 1103
REPETITIONS = 3
MAX_TOKENS = 4096
BACKENDS = {
    "qwen": {"model": "qwen-3.8-27b", "base_url": "https://bharatcode.ai/api/model/v1",
             "reasoning_effort": "low", "access_basis": "user-reported included student tokens"},
    "deepseek": {"model": "deepseek-ai/deepseek-v4.1-flash", "base_url": "https://integrate.api.nvidia.com/v1",
                 "reasoning_effort": None, "access_basis": "catalog free prototype endpoint; account access unverified"}}


def memory_fixture():
    """Synthetic record generated through real validation/auction/settlement."""
    trader = LLMAgent("memory_agent", 720, 80, np.random.default_rng(SETUP_SEED),
                      params={"tick": 0.25}, initial_price=75)
    seller = Agent("fixture_seller", 1000, 3, np.random.default_rng(2), initial_price=75)
    obs = Observation(1, 24, [75.0], 0, .03, .0004, None, [], [], 720, 80, 75, 6720, [])
    request = Order(trader.agent_id, "buy", 12, 75.25, 1, "Requested twelve shares.")
    trader.last_intent = asdict(request)
    accepted = trader.validate(replace(request), 75)
    market = CallAuctionMarket(tick=.25, rng=np.random.default_rng(SETUP_SEED))
    price, fills, _ = market.clear([accepted, Order(seller.agent_id, "sell", 3, 75.25, 1)], 75, 1)
    settle(fills, {trader.agent_id:trader, seller.agent_id:seller}, market)
    div_income, interest_income = trader.pay_dividend(.03, .0004)
    trader.end_round(obs, accepted, price, fills=fills, dividend_income=div_income,
                     interest_income=interest_income, opening_wealth=6720, reflect=False)
    return trader.memory[-1]


def scenario_agent(case, client=None, budget=None, log_fn=None):
    obs = Observation(**case["observation"])
    rules = case["rules"]
    return LLMAgent("check", obs.my_cash, obs.my_shares, np.random.default_rng(SETUP_SEED),
        params={"condition":case["condition"], "memory_window":2, "tick":rules["tick"], "max_tokens":MAX_TOKENS},
        persona=case["persona"], initial_price=obs.price_history[-1], initial_cost=obs.my_avg_cost,
        transaction_tax=rules["tax"], price_band=rules["band"], client=client,
        temperature=.3, budget=budget, log_fn=log_fn)


def cases():
    base = Observation(7, 24, [75.0]*7, 12, .03, .0004, None, [], [], 9000, 120, 75, 18000, [])
    rules = {"tick":.25,"band":.1,"tax":.02}
    result = []

    def order_case(name, family, obs, condition="A", persona=None):
        case_rules = dict(rules) if family == "resources" else {"tick":.1,"band":.2,"tax":0.0}
        case = dict(case_id=name, family=family, kind="order", condition=condition,
                    observation=asdict(obs), persona=persona or dict(PERSONA), rules=case_rules)
        agent = scenario_agent(case)
        case["messages"] = [{"role":"system","content":agent.system_prompt("KGP")},
                            {"role":"user","content":agent.user_prompt(obs)}]
        result.append(case)

    for condition in "AB":
        for name,cash in (("empty",0),("tight_cash",75.10)):
            order_case(f"{name}_{condition}","resources",replace(base,my_cash=cash,my_shares=0,
                       my_avg_cost=0,my_wealth=cash,fundamental_hint=90),condition)
    for name,news in (("control",[]),("headline",["A local newspaper reports that KGP's future dividends may increase 25%; this report is unverified."])):
        order_case(name,"news",replace(base,news=news))
    for risk in ("low","high"):
        order_case("risk_"+risk,"risk_trait",replace(base,price_history=[74,75,76,77,78,79,80],my_wealth=18600),
                   persona={**PERSONA,"risk_tolerance":risk})
    for name,hint in (("value_75",75),("value_90",90)):
        order_case(name,"disclosed_value",replace(base,fundamental_hint=hint))

    def task(name, family, market_rules, question, expected):
        result.append(dict(case_id=name, family=family, kind="objective", expected=expected,
            messages=[{"role":"system","content":"You are auditing a synthetic trading scenario. Use the stated exchange rules and records. Return ONLY a JSON object with the requested keys.\n"+market_rules},
                      {"role":"user","content":question}]))

    task("raw_market_reserve","mechanics",market_rules_prompt(.1,.2,0),
         "Last price P=100.1, cash=120.11, shares=0. For a MARKET buy with null limit, compute raw_upper_price, tick_execution_upper_price, maximum_buy_quantity under the exchange reservation rule.",
         {"raw_upper_price":120.12,"tick_execution_upper_price":120.1,"maximum_buy_quantity":0})
    task("taxed_raw_limit","mechanics",market_rules_prompt(.25,.1,.02),
         "Last price P=75, cash=153.24. A limit buy submits L=75.12. Compute reserved_cost_per_share, rounded_buy_limit, maximum_buy_quantity. Reservation precedes tick rounding.",
         {"reserved_cost_per_share":76.6224,"rounded_buy_limit":75.0,"maximum_buy_quantity":1})
    task("cashflow_units","cashflows",market_rules_prompt(.25,.1,.02),
         "No trades occur. Closing cash before income is 9000, shares=120, price=75. Cash interest is 0.0004 per round; the dividend paid is 0.03 per share. New dividend income earns interest only next round. Compute interest_income, dividend_income, closing_cash, dividend_yield_pct, cash_interest_pct_per_round.",
         {"interest_income":3.6,"dividend_income":3.6,"closing_cash":9007.2,"dividend_yield_pct":.04,"cash_interest_pct_per_round":.04})
    fixture = memory_fixture()
    task("executions_not_requests","verified_memory",market_rules_prompt(.25,.2,0),
         "This synthetic record is generated by the simulator's actual validation, auction and settlement. Read actual executions separately from intent/acceptance. Report requested_quantity, accepted_quantity, executed_buy_quantity, current_shares, closing_cash, dividend_income, interest_income. Record: "+json.dumps(fixture,allow_nan=False),
         {"requested_quantity":12,"accepted_quantity":9,"executed_buy_quantity":3,"current_shares":83,
          "closing_cash":496.9377,"dividend_income":2.49,"interest_income":.1977})
    return result


def prepare(output_root="runs"):
    path = Path(output_root)/(time.strftime("%Y%m%d_%H%M%S_")+"capability_battery_"+uuid.uuid4().hex[:8])
    path.mkdir(parents=True)
    definitions = cases()
    rng = np.random.default_rng(SETUP_SEED)
    schedule = [{"case_id":case["case_id"],"repetition":n} for n in range(1,REPETITIONS+1) for case in definitions]
    schedule = [schedule[i] for i in rng.permutation(len(schedule))]
    write_json(path/"battery.json",dict(version=BATTERY_VERSION,prompt_suite_version=PROMPT_VERSION,
        setup_seed=SETUP_SEED,repetitions=REPETITIONS,cases=definitions,schedule=schedule,
        scoring="Numeric fields use absolute/relative tolerance 1e-7. Order choices have no directional/profit oracle; evaluate disclosed reservation compliance separately.",
        limitations="Small diagnostic; fresh values but the same research families as prior pilots. Not a controlled historical before/after or human-validation study.",
        challenger="Reuse exact first-attempt messages and full schedule. Record backend defaults, output caps, repairs, failures and unknown usage. A truncated run is not evidence of model weakness."))
    print(f"frozen battery -> {path}",flush=True)
    return path


def recipe(backend):
    profile = BACKENDS[backend]
    return parse_config({"name":"capability_"+backend,"seed":SETUP_SEED,"rounds":1,
        "llm_limits":{"max_requests":54,"max_reserved_tokens":400000,"max_cost_usd":0,
                      "requests_per_minute":10,"input_tokens_per_minute":60000,"stop_on_api_error":True},
        "agents":[{"type":"llm","llm":{"provider":"openai_compatible","model":profile["model"],
            "base_url":profile["base_url"],"condition":"A","temperature":.3,"max_tokens":MAX_TOKENS,
            "timeout_seconds":180,"reasoning_effort":profile["reasoning_effort"],
            "input_usd_per_million":0,"output_usd_per_million":0}}]})


def grade_objective(raw, expected):
    parsed = LLMAgent._extract_json(raw)
    try:
        json.dumps(parsed,allow_nan=False)
    except (ValueError,TypeError):
        parsed = None
    scores = {key: isinstance(parsed,dict) and type(parsed.get(key)) in (int,float)
              and bool(np.isclose(parsed[key],value,atol=1e-7,rtol=1e-7)) for key,value in expected.items()}
    return dict(parsed=parsed,correct_fields=scores,all_correct=all(scores.values()))


def run_battery(battery_dir, backend, output_root="runs", *, max_requests=None, max_reserved_tokens=None):
    battery_dir = Path(battery_dir)
    battery_path = battery_dir/"battery.json"
    battery = json.loads(battery_path.read_text())
    if battery["version"] != BATTERY_VERSION or battery["prompt_suite_version"] != PROMPT_VERSION:
        raise ValueError("battery/prompt version changed; preserve this battery and prepare a new one")
    definitions = {case["case_id"]:case for case in battery["cases"]}
    for case in definitions.values():
        if case["kind"] == "order":
            agent = scenario_agent(case)
            rendered = [{"role":"system","content":agent.system_prompt("KGP")},
                        {"role":"user","content":agent.user_prompt(Observation(**case["observation"]))}]
            if rendered != case["messages"]:
                raise ValueError("frozen prompts no longer match rendering; no calls made")
    cfg = recipe(backend)
    if max_requests is not None or max_reserved_tokens is not None:
        raw_cfg = cfg.to_dict()
        if max_requests is not None:
            raw_cfg["llm_limits"]["max_requests"] = max_requests
        if max_reserved_tokens is not None:
            raw_cfg["llm_limits"]["max_reserved_tokens"] = max_reserved_tokens
        cfg = parse_config(raw_cfg)
    llm = cfg.agents[0].llm
    client = LLMClient(model=llm.model,base_url=llm.base_url,timeout=llm.timeout_seconds,reasoning_effort=llm.reasoning_effort)
    if not client.api_key:
        raise ValueError("provider credential missing; configure it locally before running")
    target = Path(output_root)/(time.strftime("%Y%m%d_%H%M%S_")+"capability_"+backend+"_"+uuid.uuid4().hex[:8])
    target.mkdir(parents=True)
    (target/"config.yaml").write_text(yaml.safe_dump(cfg.to_dict()),encoding="utf-8")
    (target/"battery.json").write_bytes(battery_path.read_bytes())
    manifest = start_manifest(target,cfg)
    manifest.update(experiment_kind="fixed_capability_check",battery_sha256=hashlib.sha256(battery_path.read_bytes()).hexdigest(),
                    endpoints=[llm.base_url],access_basis=BACKENDS[backend]["access_basis"],
                    conditions=["A","B"],config_scope="Driver/provider settings only; per-case account, persona and rules are in battery.json. Objective tasks are not A/B market experiments.",
                    random_stream_scheme="numpy_default_rng_v1:fixed_scenario_order_and_synthetic_fixture;model_unseeded",
                    sampling_note="Requested temperature .3 on both models; Qwen low effort versus unverified NVIDIA provider default. Output cap 4096; no claim of equal hidden reasoning compute.")
    if "continuation" in battery:
        manifest["continuation"] = battery["continuation"]
    write_json(target/"manifest.json",manifest)
    budget = UsageBudget(**asdict(cfg.llm_limits))
    results, status, failure_type = [], "running", None
    with (target/"llm_requests.jsonl").open("w",encoding="utf-8") as log:
        current = {}
        def record(item):
            log.write(json.dumps({**item,**current},allow_nan=False)+"\n")
            log.flush()
        try:
            for item in battery["schedule"]:
                current = dict(item)
                case = definitions[item["case_id"]]
                current.update(case_kind=case["kind"],case_family=case["family"])
                if case["kind"] == "order":
                    agent = scenario_agent(case,client,budget,record)
                    agent.agent_id = f"{item['case_id']}:r{item['repetition']}"
                    order = agent.decide(Observation(**case["observation"]))
                    outcome = dict(intent=agent.last_intent,accepted=asdict(order),
                        resource_compliant=None if agent.parse_failures else agent.last_intent["quantity"] == order.quantity,
                        parse_failures=agent.parse_failures, repaired=budget.requests > sum(r["request_count"] for r in results)+1)
                else:
                    agent = LLMAgent(f"{item['case_id']}:r{item['repetition']}",0,0,np.random.default_rng(SETUP_SEED),
                                     params={"max_tokens":MAX_TOKENS},client=client,budget=budget,
                                     temperature=.3,log_fn=record)
                    raw, meta = agent._request(case["messages"],item["repetition"],"objective")
                    outcome = grade_objective(raw,case["expected"])
                count_before = sum(r["request_count"] for r in results)
                results.append({**item,"kind":case["kind"],"family":case["family"],
                                "request_count":budget.requests-count_before,**outcome})
                write_json(target/"results.json",results)
                print(f"check {len(results)}/{len(battery['schedule'])} {case['case_id']} rep {item['repetition']}",flush=True)
            status = "completed"
        except (ProviderUnavailable,UsageLimitExceeded) as exc:
            status = "provider_error" if isinstance(exc,ProviderUnavailable) else "budget_exhausted"
            failure_type = type(exc).__name__
        except BaseException as exc:
            status,failure_type = "interrupted" if isinstance(exc,KeyboardInterrupt) else "failed",type(exc).__name__
            raise
        finally:
            write_json(target/"results.json",results)
            summary = dict(status=status,rounds=0,completed_checks=len(results),planned_checks=len(battery["schedule"]),
                           failure_type=failure_type,llm_usage=budget.snapshot())
            write_json(target/"summary.json",summary)
            finish_manifest(target,manifest,summary)
    print(f"{status} -> {target}",flush=True)
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action",choices=("prepare","qwen","deepseek"))
    parser.add_argument("--battery")
    parser.add_argument("--max-requests",type=int)
    parser.add_argument("--max-reserved-tokens",type=int)
    args = parser.parse_args()
    if args.action == "prepare":
        prepare()
    else:
        frozen = Path(args.battery) if args.battery else prepare()
        run_battery(frozen,args.action,max_requests=args.max_requests,max_reserved_tokens=args.max_reserved_tokens)
