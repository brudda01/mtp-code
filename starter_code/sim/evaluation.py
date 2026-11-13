"""Read-only accounting comparisons and compact market diagnostics.

Passive accounts hold initial shares and receive the same realized payments.
Prices are held fixed for this accounting comparison; it is not an equilibrium
simulation of what prices would become if active traders stopped trading.
"""
import csv
import json
from pathlib import Path

import numpy as np
import yaml


def read_rows(path):
    with Path(path).open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def passive_cash_path(cash, shares, dividends, rate):
    result = []
    for dividend in dividends:
        cash = cash * (1 + rate) + shares * dividend
        result.append(cash)
    return result


def dependence(values):
    x = np.asarray(values, dtype=float)
    x = x - x.mean()
    denominator = float(x @ x)
    return None if denominator == 0 or len(x) < 2 else float(x[:-1] @ x[1:] / denominator)


def evaluate_run(run_dir):
    """Return JSON-compatible results without changing any archived run file."""
    root = Path(run_dir)
    cfg = yaml.safe_load((root / "config.yaml").read_text(encoding="utf-8"))
    summary = json.loads((root / "summary.json").read_text())
    prices = read_rows(root / "prices.csv")
    if not prices:
        raise ValueError("evaluation requires at least one completed financial round")
    rounds = [int(row["round"]) for row in prices]
    if rounds != list(range(1, len(prices) + 1)) or len(prices) != summary["rounds"]:
        raise ValueError("price rows must match the completed financial horizon")
    initial = read_rows(root / "initial_state.csv")
    states = read_rows(root / "agents_state.csv")
    final = {row["agent_id"]: row for row in states if int(row["round"]) == rounds[-1]}
    if set(final) != {row["agent_id"] for row in initial}:
        raise ValueError("final accounts do not match initial accounts")
    price, benchmark = float(prices[-1]["price"]), float(prices[-1]["fundamental"])
    dividends = [float(row["dividend"]) for row in prices]
    rate = cfg["asset"]["risk_free"]
    accounts = []
    for start in initial:
        aid = start["agent_id"]
        end = final[aid]
        initial_cash, initial_shares = float(start["cash"]), int(start["shares"])
        initial_wealth = float(start["wealth"])
        passive_cash = passive_cash_path(initial_cash, initial_shares, dividends, rate)[-1]
        marks = {}
        for name, mark in (("auction", price), ("regime_benchmark", benchmark)):
            active = float(end["cash"]) + int(end["shares"]) * mark
            passive = passive_cash + initial_shares * mark
            marks[name] = dict(active_wealth=active, passive_wealth=passive,
                               active_minus_passive=active - passive,
                               active_return=None if initial_wealth == 0 else active / initial_wealth - 1,
                               passive_return=None if initial_wealth == 0 else passive / initial_wealth - 1,
                               excess_return=None if initial_wealth == 0 else (active-passive)/initial_wealth)
        accounts.append(dict(agent_id=aid, type=start["type"], initial_market_wealth=initial_wealth,
                             passive_cash=passive_cash, passive_shares=initial_shares, marks=marks))
    liquidity = read_rows(root / "liquidity.csv")
    volume = np.array([float(row["volume"]) for row in prices])
    if [int(row["round"]) for row in liquidity] != rounds:
        raise ValueError("liquidity rows must match price rounds")
    p = np.array([float(row["price"]) for row in prices])
    f = np.array([float(row["fundamental"]) for row in prices])
    # Include the first auction's change from its configured initial price.
    returns = np.diff(np.log(np.r_[cfg["asset"]["initial_price"], p]))
    total_shares = sum(int(row["shares"]) for row in initial)
    total_cash = sum(float(row["cash"]) for row in initial)
    total_volume = float(volume.sum())
    maker_states = [row for row in states if row["type"] == "MarketMakerAgent"]
    metrics = dict(rounds=len(prices), return_observations=len(returns),
                   mean_absolute_relative_gap=float(np.abs(p/f-1).mean()),
                   acf_returns_lag1=dependence(returns), acf_absolute_returns_lag1=dependence(np.abs(returns)),
                   zero_volume_fraction=float((volume == 0).mean()),
                   turnover_per_round=None if total_shares == 0 else total_volume/(total_shares*len(prices)),
                   volume_weighted_mm_share=None if total_volume == 0 else sum(
                       float(row["market_maker_volume_fraction"] or 0)*v for row,v in zip(liquidity,volume))/total_volume,
                   mean_fill_rate=float(np.mean([float(row["fill_rate"]) for row in liquidity])),
                   band_hit_fraction=float(np.mean([row["at_price_band"] in ("True","1") for row in liquidity])),
                   mm_inventory_min=min((int(row["shares"]) for row in maker_states), default=None),
                   mm_inventory_max=max((int(row["shares"]) for row in maker_states), default=None),
                   aggregate_cash_growth=None if total_cash == 0 else sum(float(row["cash"]) for row in final.values())/total_cash-1,
                   max_share_concentration=None if total_shares == 0 else max(int(row["shares"]) for row in states)/total_shares)
    return dict(version="conditional_passive_evaluation_v1", status=summary["status"],
                interpretation="Conditional realized-price-path accounting, not an equilibrium no-trading counterfactual or risk-adjusted alpha. Returns use initial market wealth for both terminal marks.",
                metrics=metrics, accounts=accounts,
                aggregate_active_minus_passive={mark:sum(a["marks"][mark]["active_minus_passive"] for a in accounts)
                                               for mark in ("auction","regime_benchmark")})
