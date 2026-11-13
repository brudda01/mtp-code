"""Descriptive audit of the first live pilot; not a significance analysis."""
import csv
import hashlib
import json
from pathlib import Path
import zipfile
import yaml

SCRIPT = Path(__file__).resolve()
ROOT = SCRIPT.parents[1] if SCRIPT.parent.name == "runs" else SCRIPT.parents[1] / "starter_code"
PROBE = ROOT / "runs/20261102_034741_live_probes_73582e3f"


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def rows(path):
    with path.open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def lines(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def audit(path):
    manifest = read_json(path / "manifest.json")
    for name, digest in manifest["output_sha256"].items():
        assert hashlib.sha256((path/name).read_bytes()).hexdigest() == digest, (path.name, name)
    with zipfile.ZipFile(path/"source.zip") as archive:
        for name, digest in manifest["source_sha256"].items():
            assert hashlib.sha256(archive.read(name)).hexdigest() == digest, (path.name, name)
    return {"manifest_sha256": hashlib.sha256((path/"manifest.json").read_bytes()).hexdigest(),
            "source_sha256": manifest["source_sha256"], "parent_revision": manifest["parent_revision"],
            "prompt_suite_version": manifest["prompt_suite_version"], "models": manifest["models"]}


def signed(order):
    return order["quantity"] * {"buy": 1, "sell": -1, "hold": 0}[order["side"]]


def main():
    probe_results = read_json(PROBE/"results.json")
    expected = read_json(PROBE/"protocol.json")["arithmetic_expected"]
    arithmetic = [r for r in probe_results if r["family"] == "arithmetic"]
    constraints = [r for r in probe_results if r["family"] == "constraints"]
    pair_specs = {"disclosed_value": ("value_100", "value_120"),
                  "headline_only": ("no_news", "positive_headline"), "risk_trait": ("low", "high")}
    pairs = []
    for family, variants in pair_specs.items():
        for repetition in (1, 2):
            matched = [next(r for r in probe_results if r["family"] == family and
                            r["variant"] == variant and r["repetition"] == repetition) for variant in variants]
            pairs.append({"family": family, "repetition": repetition,
                          "variants": variants, "requested_signed_quantities": [signed(r["requested"]) for r in matched],
                          "requested_limit_prices": [r["requested"]["limit_price"] for r in matched],
                          "case_ids": [r["case_id"] for r in matched]})
    schedule = read_json(PROBE/"market_runs.json")
    output = {"analysis_kind": "descriptive exploratory diagnostic, not confirmatory inference",
              "analysis_script_sha256": hashlib.sha256(SCRIPT.read_bytes()).hexdigest(),
              "protocol_sha256": hashlib.sha256((PROBE/"protocol.json").read_bytes()).hexdigest(),
              "market_schedule_sha256": hashlib.sha256((PROBE/"market_schedule.json").read_bytes()).hexdigest(),
              "market_runs_index_sha256": hashlib.sha256((PROBE/"market_runs.json").read_bytes()).hexdigest(),
              "probe_run_id": PROBE.name, "probe_audit": audit(PROBE),
              "arithmetic_correct_fields": sum(isinstance(r["parsed"], dict) and
                 type(r["parsed"].get(key)) in (int, float) and abs(r["parsed"][key]-value) < 1e-8
                 for r in arithmetic for key,value in expected.items()),
              "arithmetic_total_fields": len(arithmetic)*len(expected),
              "constraint_cases": len(constraints),
              "constraint_nonzero_orders": sum(r["requested"]["side"] != "hold" and r["requested"]["quantity"] > 0 for r in constraints),
              "paired_probe_actions": pairs, "market_runs": [], "matched_checks": []}
    all_usage = [read_json(PROBE/"summary.json")["llm_usage"]]
    all_calls = [r for r in lines(PROBE/"llm_requests.jsonl") if r.get("record_type") == "model_call"]
    for item in schedule:
        path = PROBE.parent/item["run_id"]
        summary = read_json(path/"summary.json")
        calls = lines(path/"llm_calls.jsonl")
        decisions = [r for r in calls if r.get("record_type") == "decision"]
        reflections = [r for r in calls if r.get("record_type") == "reflection"]
        states = rows(path/"agents_state.csv")
        initial_state = rows(path/"initial_state.csv")
        opening = {(1,r["agent_id"]):r for r in initial_state}
        opening.update({(int(r["round"])+1,r["agent_id"]):r for r in states})
        prices = rows(path/"prices.csv")
        recipe = yaml.safe_load((path/"config.yaml").read_text())
        previous_price = {1: recipe["asset"]["initial_price"]}
        previous_price.update({int(r["round"])+1:float(r["price"]) for r in prices})
        definitely_over_cash = []
        for r in decisions:
            intent = r["intent"]
            cash = float(opening[(r["round"],r["agent_id"])]["cash"])
            cheapest_band_price = previous_price[r["round"]]*(1-recipe["market"]["price_band"])
            if intent["side"] == "buy" and intent["quantity"]*cheapest_band_price*(1+recipe["market"]["transaction_tax"]) > cash+1e-6:
                definitely_over_cash.append({"round": r["round"], "agent_id": r["agent_id"], "cash": cash,
                                            "requested_quantity": intent["quantity"], "lower_band_price": cheapest_band_price})
        final = [r for r in states if r["round"] == str(summary["rounds"]) and r["type"] == "LLMAgent"]
        output["market_runs"].append({**item, "audit": audit(path), "completed_rounds": summary["rounds"],
              "parse_failures": summary["parse_failures"], "api_failures": summary["api_failures"],
              "reflection_failures": summary["reflection_failures"],
              "requested_action_counts": {side: sum(r["intent"]["side"] == side and
                  (side == "hold" or r["intent"]["quantity"] > 0) for r in decisions) for side in ("buy", "sell", "hold")},
              "requested_quantity_reductions": sum(r["intent"]["quantity"] != r["parsed"]["quantity"] for r in decisions),
              "buys_unaffordable_even_at_lower_band": definitely_over_cash,
              "adjusted_decisions": [{"agent_id": r["agent_id"], "round": r["round"],
                      "requested": r["intent"], "accepted": r["parsed"]} for r in decisions
                      if r["intent"]["quantity"] != r["parsed"]["quantity"]],
              "executed_llm_quantity": sum(r["outcome"]["executed_buy_quantity"]+r["outcome"]["executed_sell_quantity"] for r in lines(path/"agent_outcomes.jsonl")),
              "final_llm_accounts": final, "final_price": summary["final_price"],
              "cash_conservation_error": summary["max_cash_conservation_error"],
              "reflection_count": len(reflections), "usage": summary["llm_usage"]})
        all_usage.append(summary["llm_usage"])
        all_calls.extend(r for r in lines(path/"llm_requests.jsonl") if r.get("record_type") == "model_call")
    for seed in (704,905):
        matched = [PROBE.parent/r["run_id"] for r in schedule if r["seed"] == seed]
        if len(matched) != 3:
            output["matched_checks"].append({"seed": seed, "status": "incomplete"})
            continue
        initial = [p.joinpath("initial_state.csv").read_bytes() for p in matched]
        personas = [read_json(p/"personas.json") for p in matched]
        dividends = [[r["dividend"] for r in rows(p/"prices.csv")] for p in matched]
        output["matched_checks"].append({"seed": seed, "initial_accounts_equal": initial[0] == initial[1] == initial[2],
                                         "personas_equal": personas[0] == personas[1] == personas[2],
                                         "dividends_equal": dividends[0] == dividends[1] == dividends[2]})
    output["usage_totals"] = {key: sum(u[key] for u in all_usage) for key in (
          "requests_made", "provider_reported_tokens", "reserved_tokens", "reserved_cost_usd",
          "observed_cost_estimate_usd", "failed_requests", "unknown_usage_requests", "blocked_requests")}
    output["returned_models"] = sorted({r["response_metadata"].get("model", "unknown") for r in all_calls})
    output["market_source_identical"] = all(r["audit"]["source_sha256"] == output["market_runs"][0]["audit"]["source_sha256"] for r in output["market_runs"])
    output["finish_reasons"] = {reason: sum(r["response_metadata"].get("finish_reason") == reason for r in all_calls)
                                for reason in sorted({str(r["response_metadata"].get("finish_reason")) for r in all_calls})}
    output["billing_note"] = "Estimates apply published paid rates, not actual invoices or proof of a charge. Account tier is unknown."
    output["model_status"] = "Lite preliminary batch superseded by user-selected 3.8 Flash; three complete markets, not six."
    output["interrupted_run"] = "20261102_035925_live_c_s905_ed83224d"
    output["interruption_record"] = read_json(PROBE.parent/output["interrupted_run"]/"interruption.json")
    output["usage_totals_scope"] = "Completed probes plus three completed markets only; partial Lite run is excluded."
    target = ROOT/"runs/lite_preliminary_diagnostic_20261102.json"
    target.write_text(json.dumps(output, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({key: value for key,value in output.items() if key not in ("probe_audit", "market_runs")}, indent=2))
    for run in output["market_runs"]:
        print(json.dumps({k:run[k] for k in ("run_id", "condition", "seed", "completed_rounds", "requested_action_counts",
                                            "executed_llm_quantity", "reflection_count", "final_price", "cash_conservation_error")}))


if __name__ == "__main__":
    main()
