"""Bounded execution/action scoring for frozen matched trait-state inputs."""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import time
import uuid

import numpy as np
import yaml

from sim.agents.base import Observation
from sim.agents.llm_agent import LLMAgent, PROMPT_VERSION
from sim.config import parse_config
from sim.llm.client import LLMClient
from sim.llm.usage import OutputLimitExceeded, ProviderUnavailable, UsageBudget, UsageLimitExceeded
from sim.provenance import finish_manifest, sha256, start_manifest, write_json

VERSION = "matched_trait_actions_v1"
PROFILE = dict(model="qwen-3.8-27b", base_url="https://bharatcode.ai/api/model/v1",
               temperature=.3, reasoning_effort="low", max_tokens=4096, timeout_seconds=180)


def recipe():
    return parse_config(dict(name="behaviour_qwen", seed=0, rounds=1,
        llm_limits=dict(max_requests=96,max_reserved_tokens=1000000,max_cost_usd=0,
                        requests_per_minute=10,input_tokens_per_minute=60000,stop_on_api_error=True),
        agents=[dict(type="llm",llm=dict(provider="openai_compatible",condition="A",memory_window=5,
                                       input_usd_per_million=0,output_usd_per_million=0,**PROFILE))]))


def scenario_agent(case, client=None, budget=None, log_fn=None):
    obs=Observation(**case["observation"])
    return LLMAgent(case["case_id"],obs.my_cash,obs.my_shares,np.random.default_rng(0),
                    params=dict(condition="A",memory_window=5,max_tokens=4096,tick=.1),
                    persona=case["persona"],client=client,budget=budget,log_fn=log_fn,
                    temperature=.3,initial_price=obs.price_history[-1],initial_cost=obs.my_avg_cost)


def validate_battery(battery):
    if battery.get("version") != "matched_trait_states_v1" or battery.get("prompt_suite_version") != PROMPT_VERSION:
        raise ValueError("battery/prompt version mismatch; no calls made")
    proposed=battery["proposed_profile"]
    for key in ("model","temperature","reasoning_effort","max_tokens","timeout_seconds"):
        if proposed.get(key) != PROFILE[key]:
            raise ValueError("frozen model profile mismatch; no calls made")
    definitions={c["case_id"]:c for c in battery["cases"]}
    if len(definitions)!=16 or len(battery["cases"])!=16 or len(battery["schedule"])!=48:
        raise ValueError("expected the full frozen 16-case/48-decision battery")
    expected={(case_id,n) for case_id in definitions for n in (1,2,3)}
    schedule={(s["case_id"],s["repetition"]) for s in battery["schedule"]}
    if schedule != expected or len(schedule)!=48:
        raise ValueError("schedule has duplicates or missing cases")
    for case in definitions.values():
        agent=scenario_agent(case)
        rendered=[dict(role="system",content=agent.system_prompt("KGP")),
                  dict(role="user",content=agent.user_prompt(Observation(**case["observation"])))]
        digest=hashlib.sha256(json.dumps(case["messages"],sort_keys=True).encode()).hexdigest()
        if rendered!=case["messages"] or digest!=case["messages_sha256"]:
            raise ValueError("frozen input/render drift; no calls made")
    return definitions


def signed_quantity(order):
    return order["quantity"] * (1 if order["side"]=="buy" else -1 if order["side"]=="sell" else 0)


def score_choice(agent, order, obs):
    valid=not (agent.parse_failures or agent.api_failures or agent.output_truncations)
    intent=agent.last_intent
    accepted=asdict(order)
    requested=signed_quantity(intent) if valid else None
    delivered=signed_quantity(accepted) if valid else None
    # These are desired notional changes at the current mark, not executions
    # or a forecast of portfolio weights after price impact and settlement.
    notional=lambda q:None if q is None or obs.my_wealth<=0 else q*obs.price_history[-1]/obs.my_wealth
    return dict(valid_choice=valid,intent=intent,accepted=accepted,
                requested_signed_quantity=requested,accepted_signed_quantity=delivered,
                requested_notional_over_current_wealth=notional(requested),
                accepted_notional_over_current_wealth=notional(delivered),
                accepted_sell_quantity=None if not valid else accepted["quantity"] if accepted["side"]=="sell" else 0,
                resource_reduced=None if not valid else accepted["validation_note"]=="quantity_reduced_to_resources",
                parse_failures=agent.parse_failures,api_failures=agent.api_failures,
                output_truncations=agent.output_truncations,executions=None)


def contrasts(results, definitions):
    """Predeclared contrasts; missing/failed choices stay null, never HOLD zero."""
    indexed={(r["case_id"],r["repetition"]):r for r in results}
    def value(case_id,n,metric):
        row=indexed.get((case_id,n))
        return None if row is None or not row["valid_choice"] else row[metric]
    def difference(a,b):
        return None if a is None or b is None else a-b
    risk=[]
    basis=[]
    for n in (1,2,3):
        for context in ("rising","falling"):
            for wording in ("label","description"):
                low=f"risk_{context}_{wording}_low";high=f"risk_{context}_{wording}_high"
                risk.append(dict(repetition=n,context=context,wording=wording,
                    high_minus_low_requested=difference(value(high,n,"requested_signed_quantity"),value(low,n,"requested_signed_quantity")),
                    high_minus_low_accepted=difference(value(high,n,"accepted_signed_quantity"),value(low,n,"accepted_signed_quantity"))))
        for wording in ("pain","weight"):
            amounts={}
            for trait in ("neutral","loss_sensitive"):
                amounts[trait]=difference(value(f"basis_{wording}_gain_{trait}",n,"accepted_sell_quantity"),
                                         value(f"basis_{wording}_loss_{trait}",n,"accepted_sell_quantity"))
            basis.append(dict(repetition=n,wording=wording,gain_minus_loss_sell_quantity=amounts,
                              trait_by_basis_sell_interaction=difference(amounts["loss_sensitive"],amounts["neutral"])))
    return dict(version=VERSION,risk=risk,gain_loss=basis,
                interpretation="Positive risk contrast means greater requested/accepted stock exposure for high-risk wording. Positive sell interaction means the gain-minus-loss selling contrast is larger with the loss-sensitive clause. No direction is a correctness oracle; no simulated fills, human-validation or independent-market inference.")


def run_battery(battery_dir, output_root="runs", *, output_dir=None):
    battery_path=Path(battery_dir)/"battery.json"
    battery=json.loads(battery_path.read_text())
    definitions=validate_battery(battery)
    cfg=recipe();llm=cfg.agents[0].llm
    client=LLMClient(model=llm.model,base_url=llm.base_url,timeout=llm.timeout_seconds,
                     reasoning_effort=llm.reasoning_effort,send_temperature=True)
    if not client.api_key:
        raise ValueError("BharatCode credential missing; no calls made")
    target=Path(output_dir) if output_dir else Path(output_root)/(time.strftime("%Y%m%d_%H%M%S_")+"behaviour_qwen_"+uuid.uuid4().hex[:8])
    target.mkdir(parents=True,exist_ok=False)
    (target/"config.yaml").write_text(yaml.safe_dump(cfg.to_dict()),encoding="utf-8")
    (target/"battery.json").write_bytes(battery_path.read_bytes())
    manifest=start_manifest(target,cfg)
    manifest.update(experiment_kind="fixed_matched_trait_states",action_scoring_version=VERSION,
                    battery_sha256=sha256(battery_path),endpoints=[llm.base_url],
                    access_basis="user-reported student-included tokens; zero marginal price, remaining quota unknown",
                    config_scope="Driver/profile settings only; exact per-case accounts/personas/messages in battery.json",
                    random_stream_scheme="fixed_synthetic_states_and_schedule;no_market_rng;provider_sampling_unseeded",
                    sampling_note="Fresh requests, temperature .3/low effort/4096 cap. Model RNG/served weights unpinned. Repetition labels do not make different synthetic states independent market replications.",
                    scoring_note="Signed requested/accepted quantities and gain-loss sell interaction; parse failures excluded from preferences, retained for reliability; no action/profit oracle or auction fills.")
    write_json(target/"manifest.json",manifest)
    budget=UsageBudget(**asdict(cfg.llm_limits))
    results=[];status="running";failure_type=None;current={}
    write_json(target/"results.json",results)
    with (target/"llm_requests.jsonl").open("w",encoding="utf-8") as stream:
        def record(item):
            stream.write(json.dumps({**item,**current},allow_nan=False)+"\n");stream.flush()
        try:
            for item in battery["schedule"]:
                case=definitions[item["case_id"]]
                current={**item,"family":case["family"],"factors":case["factors"]}
                before=budget.requests
                agent=scenario_agent(case,client,budget,record)
                agent.agent_id=f"{case['case_id']}:r{item['repetition']}"
                obs=Observation(**case["observation"])
                order=agent.decide(obs)
                results.append({**current,**score_choice(agent,order,obs),
                                "request_count":budget.requests-before,"repaired":budget.requests-before>1})
                write_json(target/"results.json",results)
                write_json(target/"progress.json",dict(completed=len(results),planned=48,llm_usage=budget.snapshot()))
                print(f"decision {len(results)}/48 {case['case_id']} rep {item['repetition']}",flush=True)
            status="completed"
        except OutputLimitExceeded as exc:
            status,failure_type="output_truncated",type(exc).__name__
        except (ProviderUnavailable,UsageLimitExceeded) as exc:
            status="provider_error" if isinstance(exc,ProviderUnavailable) else "budget_exhausted"
            failure_type=type(exc).__name__
        except BaseException as exc:
            status,failure_type=("interrupted" if isinstance(exc,KeyboardInterrupt) else "failed"),type(exc).__name__
            raise
        finally:
            write_json(target/"results.json",results)
            write_json(target/"contrasts.json",contrasts(results,definitions))
            summary=dict(status=status,rounds=0,completed_decisions=len(results),planned_decisions=48,
                         valid_choices=sum(r["valid_choice"] for r in results),
                         failure_type=failure_type,llm_usage=budget.snapshot())
            write_json(target/"summary.json",summary)
            stream.flush()
            finish_manifest(target,manifest,summary)
    print(f"{status} -> {target}",flush=True)
    return target


if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--battery",required=True)
    parser.add_argument("--output-root",default="runs")
    parser.add_argument("--output-dir")
    args=parser.parse_args()
    run_battery(args.battery,args.output_root,output_dir=args.output_dir)
