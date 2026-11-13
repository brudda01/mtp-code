"""
Repaired Matched Live Comparison: Short-Sale Ban vs. Short-Sale Allowed.
Scale: 15 Rounds x 2 Matched Markets = 30 Rounds (180 Live LLM Decisions).
Features:
- Decoupled RNG streams (exact identical dividend realization).
- Persistent maintenance collateral and atomic settlement.
- Active fundamentalist short-selling under Market 2.
- Full provenance, per-account sheets, and orders ledger.
"""
from __future__ import annotations

import os
import sys
import csv
import json
import time
import math
from typing import List, Dict, Any, Tuple
import numpy as np
import matplotlib.pyplot as plt

from repaired_engine import (
    RepairedMarginAgent,
    RepairedMarginFundamentalist,
    Order,
    Trade,
    Observation,
    atomic_settle
)
from repaired_market_sim import DecoupledAsset, CallAuction
from repaired_llm_trader import RepairedLLMTrader
from repaired_client import RepairedResilientClient

SEED = 42
TOTAL_ROUNDS = 15
RESULTS_DIR = "sandbox_experiments/results_repaired_short_sale"

# Canonical 6 Heterogeneous Demographics
PERSONAS = [
    {
        "name": "Vikram_Student", "age": 23, "occupation": "engineering student",
        "cash": 2000.0, "shares": 10, "risk_tolerance": "high", "strategy_inclination": "speculative",
        "backstory": "You trade on tight student savings. You seek quick gains and fear missing out."
    },
    {
        "name": "Arjun_Marketer", "age": 27, "occupation": "startup marketer",
        "cash": 5000.0, "shares": 25, "risk_tolerance": "high", "strategy_inclination": "momentum",
        "backstory": "You believe you can spot trends and consumer hype before anyone else."
    },
    {
        "name": "Meera_Teacher", "age": 34, "occupation": "school teacher",
        "cash": 8000.0, "shares": 40, "risk_tolerance": "low", "strategy_inclination": "fundamentalist",
        "backstory": "You save carefully from a modest salary. Losing hard-earned money is deeply painful to you."
    },
    {
        "name": "Sana_Owner", "age": 42, "occupation": "restaurant owner",
        "cash": 20000.0, "shares": 100, "risk_tolerance": "medium", "strategy_inclination": "growth",
        "backstory": "You reinvest business cash into expanding equity and productive assets."
    },
    {
        "name": "Lakshmi_Pharmacist", "age": 48, "occupation": "retail pharmacist",
        "cash": 25000.0, "shares": 125, "risk_tolerance": "medium", "strategy_inclination": "dividend_yield",
        "backstory": "You focus on steady dividend payouts and long-term capital preservation."
    },
    {
        "name": "Prakash_Retiree", "age": 58, "occupation": "retired bank officer",
        "cash": 50000.0, "shares": 250, "risk_tolerance": "low", "strategy_inclination": "capital_preservation",
        "backstory": "Decades in commercial banking taught you that valuation matters above all."
    }
]

def run_single_market(allow_short: bool, client: RepairedResilientClient) -> Dict[str, Any]:
    cond_name = "SHORT_ALLOWED" if allow_short else "SHORT_BANNED"
    print(f"\n=======================================================")
    print(f" LAUNCHING LIVE MARKET: {cond_name} (allow_short={allow_short})")
    print(f"=======================================================")

    # 3 Decoupled RNG Streams (guarantees identical dividends and tie-breaks across conditions)
    asset = DecoupledAsset(seed=SEED + 100)
    auction = CallAuction(seed=SEED + 200)
    rule_rng = np.random.default_rng(SEED + 300)

    # Initialize Accounts
    accounts: Dict[str, RepairedMarginAgent] = {}

    # 1. Market Maker (Liquidity anchor)
    mm = RepairedMarginAgent("MarketMaker", cash=100000.0, shares=300, rng=rule_rng, allow_short=False)
    accounts["MarketMaker"] = mm

    # 2. Fundamentalist Rule Traders (Active disciplinary traders)
    f1 = RepairedMarginFundamentalist("Fund_1", cash=30000.0, shares=0, rng=rule_rng, allow_short=allow_short, max_trade_size=10)
    f2 = RepairedMarginFundamentalist("Fund_2", cash=30000.0, shares=0, rng=rule_rng, allow_short=allow_short, max_trade_size=10)
    accounts["Fund_1"] = f1
    accounts["Fund_2"] = f2

    # 3. 6 DeepSeek LLM Traders
    llm_traders: List[RepairedLLMTrader] = []
    for p in PERSONAS:
        t = RepairedLLMTrader(
            agent_id=p["name"],
            cash=p["cash"],
            shares=p["shares"],
            rng=rule_rng,
            persona=p,
            client=client,
            allow_short=allow_short
        )
        accounts[p["name"]] = t
        llm_traders.append(t)

    initial_total_cash = sum(a.cash for a in accounts.values())
    initial_total_shares = sum(a.shares for a in accounts.values())

    market_log = []
    orders_log = []
    accounts_log = []

    price_history = [100.0]
    volume_history = [0]
    dividends_history = []

    for rnd in range(1, TOTAL_ROUNDS + 1):
        curr_p = price_history[-1]
        div = asset.draw_dividend()
        dividends_history.append(div)
        last_div = dividends_history[-2] if len(dividends_history) > 1 else 0.02

        print(f"\n--- Round {rnd:02d}/{TOTAL_ROUNDS} [{cond_name}] | Price=${curr_p:.2f} | Div=${div:.3f} ---")

        # Snapshot opening accounts
        for aid, a in accounts.items():
            req_collat = a.get_required_collateral(curr_p)
            accounts_log.append({
                "condition": cond_name, "round": rnd, "agent": aid,
                "cash": round(a.cash, 2), "shares": a.shares,
                "locked_margin": round(req_collat, 2),
                "wealth": round(a.wealth(curr_p), 2),
                "avg_cost": round(a.avg_cost, 2)
            })

        round_orders: List[Order] = []

        # 1. Market Maker Quotes (spread of 2.0 around current price)
        mm_bid = Order("MarketMaker", "buy", 10, round(curr_p - 1.0, 2))
        mm_ask = Order("MarketMaker", "sell", 10, round(curr_p + 1.0, 2))
        round_orders.extend([mm_bid, mm_ask])

        # 2. Fundamentalist Decisions
        obs_fund = Observation(
            round=rnd, total_rounds=TOTAL_ROUNDS, price_history=price_history, volume_history=volume_history,
            last_dividend=last_div, risk_free_rate=0.0002, fundamental_hint=100.0,
            bbs_posts=[], order_book=[], cash=0, shares=0, locked_collateral=0, wealth=0, peer_trades=[]
        )
        for fund in [f1, f2]:
            fo = fund.decide(obs_fund)
            if fo.side != 'hold':
                round_orders.append(fo)
                orders_log.append({
                    "condition": cond_name, "round": rnd, "agent": fund.agent_id,
                    "side": fo.side, "requested_qty": fo.quantity, "validated_qty": fo.quantity,
                    "limit_price": fo.limit_price, "reasoning": fo.reasoning,
                    "status": fo.status, "model_status": "rule_based"
                })

        # 3. Live LLM Decisions (Sequential with polite rate-limiting)
        for t in llm_traders:
            obs_llm = Observation(
                round=rnd, total_rounds=TOTAL_ROUNDS, price_history=price_history, volume_history=volume_history,
                last_dividend=last_div, risk_free_rate=0.0002, fundamental_hint=100.0,
                bbs_posts=[], order_book=[], cash=t.cash, shares=t.shares,
                locked_collateral=t.get_required_collateral(curr_p), wealth=t.wealth(curr_p), peer_trades=[]
            )
            order = t.decide(obs_llm)
            orders_log.append({
                "condition": cond_name, "round": rnd, "agent": t.agent_id,
                "side": order.side, "requested_qty": order.quantity, "validated_qty": order.quantity,
                "limit_price": order.limit_price, "reasoning": order.reasoning,
                "status": order.status, "model_status": t.last_status
            })
            if order.side != 'hold' and order.quantity > 0:
                round_orders.append(order)
            print(f"   [{t.agent_id:18s}]: {order.side.upper():4s} {order.quantity:2d} sh @ limit {str(order.limit_price):>6s} | {order.reasoning[:40]}")
            time.sleep(1.0)  # Gentle pacing

        # 4. Auction Matching
        clearing_p, vol, trades = auction.match(rnd, round_orders, curr_p)

        # 5. Atomic Settlement
        executed_trades = atomic_settle(trades, accounts)

        # 6. Dividends & Cash Interest
        for a in accounts.values():
            a.pay_dividend(div)
            a.pay_risk_free_interest(0.0002)

        # Metric Logging
        price_history.append(clearing_p)
        volume_history.append(vol)
        curr_short_int = sum(abs(a.shares) for a in accounts.values() if a.shares < 0)

        market_log.append({
            "round": rnd, "price": clearing_p, "volume": vol,
            "short_interest": curr_short_int, "dividend": round(div, 4),
            "trades_count": len(executed_trades)
        })

        # Strict conservation audit
        net_shares = sum(a.shares for a in accounts.values())
        assert net_shares == initial_total_shares, f"Share leak in round {rnd}: {net_shares} vs {initial_total_shares}"

        print(f"   => Cleared at ${clearing_p:.2f} | Volume: {vol:2d} shares | Short Interest: {curr_short_int:2d} shares")

    return {
        "condition": cond_name,
        "market_log": market_log,
        "orders_log": orders_log,
        "accounts_log": accounts_log,
        "prices": price_history[1:],
        "volumes": volume_history[1:],
        "dividends": dividends_history,
        "short_interest": [m["short_interest"] for m in market_log]
    }

def main():
    os.makedirs(RESULTS_DIR, exist_ok=True)
    client = RepairedResilientClient()

    t_start = time.time()
    res_banned = run_single_market(allow_short=False, client=client)
    res_allowed = run_single_market(allow_short=True, client=client)
    total_time = round(time.time() - t_start, 1)

    print("\n=======================================================")
    print(" SAVING AUDITED PROVENANCE ARTIFACTS")
    print("=======================================================")

    # 1. Market Comparison CSV
    comp_path = os.path.join(RESULTS_DIR, "market_comparison.csv")
    with open(comp_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "round", "price_no_short", "vol_no_short", "short_int_no_short",
            "price_short_allowed", "vol_short_allowed", "short_int_short_allowed", "dividend"
        ])
        for r in range(TOTAL_ROUNDS):
            writer.writerow([
                r + 1,
                res_banned["prices"][r], res_banned["volumes"][r], res_banned["short_interest"][r],
                res_allowed["prices"][r], res_allowed["volumes"][r], res_allowed["short_interest"][r],
                round(res_banned["dividends"][r], 4)
            ])

    # 2. Combined Orders Ledger CSV
    orders_path = os.path.join(RESULTS_DIR, "orders_ledger.csv")
    all_orders = res_banned["orders_log"] + res_allowed["orders_log"]
    with open(orders_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "condition", "round", "agent", "side", "requested_qty", "validated_qty",
            "limit_price", "reasoning", "status", "model_status"
        ])
        writer.writeheader()
        writer.writerows(all_orders)

    # 3. Combined Accounts History CSV
    accounts_path = os.path.join(RESULTS_DIR, "accounts_history.csv")
    all_accounts = res_banned["accounts_log"] + res_allowed["accounts_log"]
    with open(accounts_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "condition", "round", "agent", "cash", "shares", "locked_margin", "wealth", "avg_cost"
        ])
        writer.writeheader()
        writer.writerows(all_accounts)

    # 4. Provenance Manifest JSON
    prov_path = os.path.join(RESULTS_DIR, "provenance_manifest.json")
    prov_data = {
        "experiment": "Repaired Short-Sale Comparison",
        "timestamp": time.time(),
        "total_runtime_s": total_time,
        "model": client.model,
        "base_url": client.base_url,
        "total_http_requests": client.total_http_requests,
        "total_errors": client.total_errors,
        "total_prompt_tokens": client.total_prompt_tokens,
        "total_completion_tokens": client.total_completion_tokens,
        "seed": SEED,
        "rounds_per_condition": TOTAL_ROUNDS,
        "dividends_identical": (res_banned["dividends"] == res_allowed["dividends"]),
        "max_short_interest_banned": max(res_banned["short_interest"]),
        "max_short_interest_allowed": max(res_allowed["short_interest"]),
        "mean_absolute_gap_banned": float(np.mean([abs(p - 100) for p in res_banned["prices"]])),
        "mean_absolute_gap_allowed": float(np.mean([abs(p - 100) for p in res_allowed["prices"]]))
    }
    with open(prov_path, "w", encoding="utf-8") as f:
        json.dump(prov_data, f, indent=2)

    # 5. High-Resolution Comparative Chart
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 8), sharex=True, gridspec_kw={'height_ratios': [2.5, 1.2]})

    rounds_x = list(range(1, TOTAL_ROUNDS + 1))
    ax1.axhline(100.0, color='gray', linestyle='--', linewidth=1.5, label='Fundamental Anchor ($F=100$)')
    ax1.plot(rounds_x, res_banned["prices"], color='#d9534f', marker='o', linewidth=2.5, label=f'Short-Sale Banned (Mean Gap: {prov_data["mean_absolute_gap_banned"]:.2f}%)')
    ax1.plot(rounds_x, res_allowed["prices"], color='#0275d8', marker='s', linewidth=2.5, label=f'Short-Sale Allowed (Mean Gap: {prov_data["mean_absolute_gap_allowed"]:.2f}%)')
    ax1.set_ylabel('Clearing Price ($)', fontsize=12, fontweight='bold')
    ax1.set_title('Miller (1977) Overvaluation Test: Repaired Margin & Decoupled RNG', fontsize=14, fontweight='bold')
    ax1.grid(True, alpha=0.3)
    ax1.legend(loc='upper right', frameon=True, fontsize=10)

    ax2.bar([x - 0.2 for x in rounds_x], res_banned["short_interest"], width=0.4, color='#d9534f', label='Short Int: Banned')
    ax2.bar([x + 0.2 for x in rounds_x], res_allowed["short_interest"], width=0.4, color='#0275d8', label='Short Int: Allowed')
    ax2.set_xlabel('Round Number', fontsize=12, fontweight='bold')
    ax2.set_ylabel('Short Interest (Shares)', fontsize=11, fontweight='bold')
    ax2.grid(True, alpha=0.3)
    ax2.legend(loc='upper right', frameon=True, fontsize=10)

    plt.tight_layout()
    chart_path = os.path.join(RESULTS_DIR, "short_sale_vs_ban_repaired_chart.png")
    plt.savefig(chart_path, dpi=300)
    plt.close()

    print(f"\nCompleted in {total_time}s.")
    print(f"Chart saved to: {chart_path}")
    print(f"Provenance saved to: {prov_path}")

if __name__ == "__main__":
    main()
