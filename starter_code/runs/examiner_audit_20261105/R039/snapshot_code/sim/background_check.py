"""Bounded hidden-value background screen and equal-resource slot templates."""
import contextlib
import io
import json
from pathlib import Path
import time
import uuid

import yaml

from sim.config import parse_config
from sim.engine import run
from sim.evaluation import evaluate_run, read_rows
from sim.provenance import sha256, write_json

ROOT = Path(__file__).resolve().parents[1]
SEEDS = (317, 628, 939)
CELLS = {"original": (.02, 1), "average5": (.02, 5),
         "no_skew": (0, 1), "no_skew_average5": (0, 5)}


def slot_recipe(seed, *, brain="rules", rounds=600, skew=.02, dividend_window=1):
    """Slots 0..11 are unchanged; slots 12/13 switch brain, never endowments."""
    raw = yaml.safe_load((ROOT / "configs/pilot_a_mock.yaml").read_text())
    raw.update(name=f"background_{brain}_w{dividend_window}_k{int(skew*1000)}", seed=seed,
               rounds=rounds, reveal_fundamental=False, news=[], execution={"max_workers":1},
               llm_limits={"max_requests":0 if brain == "rules" else 4*rounds,
                           "max_reserved_tokens":0 if brain == "rules" else 1000000,
                           "max_cost_usd":0})
    raw["agents"][0]["params"]["inventory_skew"] = skew
    raw["agents"][2]["params"]["dividend_window"] = dividend_window
    raw["agents"][-1]["count"] = 2
    if brain == "rules":
        raw["agents"][-1:] = [
            {"type":"fundamentalist", "count":1, "cash":10000, "shares":100,
             "params":{"delta":.03,"aggressiveness":.5,"dividend_window":dividend_window}},
            {"type":"momentum", "count":1, "cash":10000, "shares":100,
             "params":{"window":5,"aggressiveness":.5}}]
    elif brain == "mock":
        raw["agents"][-1]["llm"].update(condition="A", memory_window=5,
                                       reflect_every=0, temperature=.3)
    else:
        raise ValueError("background templates support rules or offline mock only")
    return parse_config(raw)


def check(output_root="runs"):
    root = Path(output_root) / (time.strftime("%Y%m%d_%H%M%S_")+"background_screen_"+uuid.uuid4().hex[:8])
    root.mkdir(parents=True)
    (root / "configs").mkdir()
    (root / "driver_source.py").write_bytes(Path(__file__).read_bytes())
    protocol = dict(version="background_screen_v1", status="frozen_before_runs", seeds=SEEDS,
                    rounds=600, cells={c:dict(mm_skew=k,dividend_window=w) for c,(k,w) in CELLS.items()},
                    population="14 fixed slots: MM1/ZI4/F3/M4 background, F1/M1 replacement slots",
                    resources=dict(cash=160000,shares=1450), reveal_fundamental=False, news=[],
                    purpose="Exploratory mechanisms/sensitivity across price, dependence, liquidity and conditional passive performance; no default selection or empirical-realism pass score.",
                    passive_note="Conditional same-price-path accounting; no equilibrium response to removing trading.",
                    return_convention="All 600 regular-time log price changes, including first auction versus initial price; zero returns retained.",
                    pairing="Same seed/resources/environment/agent RNG positions; financial outcomes may differ endogenously.")
    write_json(root / "protocol.json", protocol)
    # Reviewable equal-slot mock template. This is not a live LLM comparator run.
    (root / "configs/matched_mock_template.yaml").write_text(
        yaml.safe_dump(slot_recipe(SEEDS[0], brain="mock").to_dict()), encoding="utf-8")
    index, results = [], []
    for seed in SEEDS:
        shared_dividends = shared_initial = None
        for cell, (skew, window) in CELLS.items():
            cfg = slot_recipe(seed, skew=skew, dividend_window=window)
            path = root / "configs" / f"{cell}_{seed}.yaml"
            path.write_text(yaml.safe_dump(cfg.to_dict()), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                market = Path(run(path, output_root=root / "market_runs"))
            summary = json.loads((market / "summary.json").read_text())
            assert summary["status"] == "completed" and summary["rounds"] == 600
            assert summary["llm_usage"]["requests_made"] == 0
            assert summary["max_cash_conservation_error"] < 1e-7
            dividends = [row["dividend"] for row in read_rows(market / "prices.csv")]
            initial = (market / "initial_state.csv").read_bytes()
            if shared_dividends is None:
                shared_dividends, shared_initial = dividends, initial
            assert dividends == shared_dividends and initial == shared_initial
            evaluation = evaluate_run(market)
            # In this closed-share, zero-tax market, aggregate excess over passive
            # accounting should cancel; trading reallocates income/wealth.
            assert all(abs(v) < 1e-7 for v in evaluation["aggregate_active_minus_passive"].values())
            assert evaluation["metrics"]["mm_inventory_min"] >= 0
            assert evaluation["metrics"]["mm_inventory_max"] <= 300
            evaluation_path = root / f"evaluation_{cell}_{seed}.json"
            write_json(evaluation_path, evaluation)
            index.append(dict(seed=seed,cell=cell,run_path=market.relative_to(root).as_posix(),
                              manifest_sha256=sha256(market / "manifest.json"),
                              evaluation=evaluation_path.name,evaluation_sha256=sha256(evaluation_path)))
            results.append(dict(seed=seed,cell=cell,**evaluation["metrics"]))
            write_json(root / "runs.json", index)
            print(f"completed {cell} / seed {seed}", flush=True)
    contrasts=[]
    for seed in SEEDS:
        by_cell={r["cell"]:r for r in results if r["seed"] == seed}
        for estimator in ("original","average5"):
            other="no_skew" if estimator == "original" else "no_skew_average5"
            contrasts.append(dict(seed=seed,factor="remove_skew",at=estimator,
                delta={m:by_cell[other][m]-by_cell[estimator][m] for m in
                       ("mean_absolute_relative_gap","turnover_per_round","acf_returns_lag1")}))
        for skew, a, b in ((.02,"original","average5"),(0,"no_skew","no_skew_average5")):
            contrasts.append(dict(seed=seed,factor="average5",at_skew=skew,
                delta={m:by_cell[b][m]-by_cell[a][m] for m in
                       ("mean_absolute_relative_gap","turnover_per_round","acf_returns_lag1")}))
    write_json(root / "report.json",dict(status="completed_exploratory_screen",protocol=protocol,
        runs=index,results=results,paired_contrasts=contrasts,
        checks=dict(same_dividend_paths=True,same_initial_states=True,zero_api_requests=True,
                    aggregate_passive_excess_cancels=True,finite_mm_inventory=True)))
    print(f"saved screen -> {root}", flush=True)
    return root


if __name__ == "__main__":
    check()
