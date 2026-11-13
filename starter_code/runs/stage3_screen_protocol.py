"""Prespecified engineering screen; no tuning or live provider calls.

Run from starter_code with PYTHONPATH pointing at starter_code if needed.
All conditions are saved. This script also preserves its own protocol copy.
"""
import contextlib
import copy
import csv
import hashlib
import io
import json
from pathlib import Path
import statistics

import numpy as np
import pandas as pd
import yaml

from sim.engine import run
from sim.metrics import acf


def rows(path):
    with path.open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def run_quiet(config):
    with contextlib.redirect_stdout(io.StringIO()):
        return Path(run(config))


report = {"purpose": "Exploratory rule-only mechanism sensitivity and mock A/B/C plumbing",
          "not_evidence_of": ["human realism", "live LLM behaviour", "optimal market calibration"],
          "seeds": [101, 202, 303], "rounds": 1000,
          "predeclared_factors": {"inventory_skew": [0.02, 0.0],
                                 "momentum_windows": ["5x5", "2x3+2x5+1x10"]},
          "baseline_changed": False, "rule_runs": [], "mock_runs": []}
scratch = Path("../.tmp")
scratch.mkdir(exist_ok=True)
base = yaml.safe_load(Path("configs/baseline_rules.yaml").read_text(encoding="utf-8"))
environment_reference = {}
initial_reference = {}
for seed in report["seeds"]:
    for skew in (0.02, 0.0):
        for varied in (False, True):
            cfg = copy.deepcopy(base)
            cfg["seed"] = seed
            label = ("skew" if skew else "no_skew") + ("_varied" if varied else "_common")
            cfg["name"] = f"screen_{label}_{seed}"
            cfg["agents"][0]["params"]["inventory_skew"] = skew
            if varied:
                original = cfg["agents"].pop()
                for count, window in ((2, 3), (2, 5), (1, 10)):
                    group = copy.deepcopy(original)
                    group["count"], group["params"]["window"] = count, window
                    cfg["agents"].append(group)
            config_path = scratch / "screen_config.yaml"
            config_path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
            output = run_quiet(config_path)
            prices = pd.read_csv(output / "prices.csv")
            summary = json.loads((output / "summary.json").read_text())
            assert summary["status"] == "completed"
            dividends = prices["dividend"].to_numpy()
            initial = (output / "initial_state.csv").read_bytes()
            if seed in environment_reference:
                np.testing.assert_array_equal(dividends, environment_reference[seed])
                assert initial == initial_reference[seed]
            else:
                environment_reference[seed] = dividends
                initial_reference[seed] = initial
            p = prices["price"].to_numpy(float)
            returns = np.diff(np.log(p))
            absolute = np.abs(returns)
            trades = rows(output / "trades.csv")
            volume = sum(int(t["quantity"]) for t in trades)
            maker_volume = sum(int(t["quantity"]) for t in trades
                               if t["buyer_id"].startswith("mark") or t["seller_id"].startswith("mark"))
            values = {"acf_returns_lag1": float(acf(returns, 10)[1]),
                      "acf_abs_returns_lag1": float(acf(absolute, 10)[1]),
                      "mean_abs_mispricing": float(np.mean(np.abs(p - 100) / 100)),
                      "volume_absret_spearman": float(pd.Series(prices["volume"].to_numpy()[1:]).corr(
                          pd.Series(absolute), method="spearman")),
                      "zero_volume_fraction": summary["zero_volume_fraction"],
                      "market_maker_quantity_fraction": maker_volume / volume if volume else None,
                      "mean_turnover_per_round": volume / summary["total_shares"] / len(prices)}
            report["rule_runs"].append({"run_id": output.name, "condition": label, "seed": seed,
                                        "metrics": values, "manifest_sha256": hashlib.sha256(
                                            (output / "manifest.json").read_bytes()).hexdigest()})
report["matched_checks"] = {"initial_resources_and_ids_identical_within_seed": True,
                             "dividend_paths_identical_within_seed": True}
for label in sorted({r["condition"] for r in report["rule_runs"]}):
    selected = [r["metrics"] for r in report["rule_runs"] if r["condition"] == label]
    report.setdefault("rule_summary", {})[label] = {
        key: {"mean": statistics.mean(r[key] for r in selected),
              "sample_std": statistics.stdev(r[key] for r in selected)}
        for key in selected[0]}

mock_outputs = {}
for condition in ("a", "b", "c"):
    output = run_quiet(Path("configs") / f"pilot_{condition}_mock.yaml")
    mock_outputs[condition] = output
    summary = json.loads((output / "summary.json").read_text())
    assert summary["status"] == "completed"
    requests = [json.loads(line) for line in (output / "llm_requests.jsonl").read_text().splitlines()]
    report["mock_runs"].append({"condition": condition.upper(), "run_id": output.name,
                                "rounds": summary["rounds"], "usage": summary["llm_usage"],
                                "reflection_calls": sum(r["call_type"] == "reflection" for r in requests)})
for filename in ("initial_state.csv", "personas.json"):
    assert len({(p / filename).read_bytes() for p in mock_outputs.values()}) == 1
paths = [pd.read_csv(p / "prices.csv") for p in mock_outputs.values()]
for path in paths[1:]:
    np.testing.assert_array_equal(paths[0]["dividend"], path["dividend"])
assert rows(mock_outputs["b"] / "prices.csv")[:5] == rows(mock_outputs["c"] / "prices.csv")[:5]
report["mock_matching"] = {"initial_accounts_personas_dividends_identical": True,
                            "B_C_equal_before_first_reflection": True}
out = Path("runs/stage3_checks_20261102.json")
out.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
Path("runs/stage3_screen_protocol.py").write_text(Path(__file__).read_text(encoding="utf-8"), encoding="utf-8")
print(json.dumps({"report": str(out), "rule_summary": report["rule_summary"],
                  "mock_runs": report["mock_runs"], "matching": report["matched_checks"]}, indent=2))
