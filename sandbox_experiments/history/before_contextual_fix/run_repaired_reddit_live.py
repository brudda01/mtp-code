"""
Repaired Matched Live Reddit Sentiment Experiment:
Scientifically Identified Matched Pair (Silent Control vs. Active WallStreetBets Feed).
Scale: 16 Rounds x 2 Conditions = 32 Rounds (192 Live LLM Decisions).
Directly addresses Findings #5, #6, #9, #12, #13, #14, #16 in AUDIT_REPORT.md:
- Matched Control condition (Forum Silent) vs Intervention (Reddit Active).
- Decoupled RNG (exact identical dividend realization).
- Strict parser with explicit failure status (never disguise API drops as HOLD).
- Accurate phase shading aligned to post delivery rounds.
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

SEED = 88
TOTAL_ROUNDS = 16
RESULTS_DIR = "sandbox_experiments/results_repaired_reddit"

# Realistic Demographic Personas
PERSONAS = [
    {
        "name": "Vikram_Student", "age": 23, "occupation": "engineering student",
        "cash": 2000.0, "shares": 10, "risk_tolerance": "high", "strategy_inclination": "speculative",
        "backstory": "You trade on your phone with tight savings. You are easily swayed by online trading hype."
    },
    {
        "name": "Arjun_Marketer", "age": 27, "occupation": "startup marketer",
        "cash": 5000.0, "shares": 25, "risk_tolerance": "high", "strategy_inclination": "momentum",
        "backstory": "You look for trending consumer sentiment and viral retail momentum."
    },
    {
        "name": "Meera_Teacher", "age": 34, "occupation": "school teacher",
        "cash": 8000.0, "shares": 40, "risk_tolerance": "low", "strategy_inclination": "fundamentalist",
        "backstory": "You save carefully from your teaching salary. Financial uncertainty terrifies you."
    },
    {
        "name": "Sana_Owner", "age": 42, "occupation": "restaurant owner",
        "cash": 20000.0, "shares": 100, "risk_tolerance": "medium", "strategy_inclination": "growth",
        "backstory": "You understand business cash flows and look to capitalize on retail overreactions."
    },
    {
        "name": "Lakshmi_Pharmacist", "age": 48, "occupation": "retail pharmacist",
        "cash": 25000.0, "shares": 125, "risk_tolerance": "medium", "strategy_inclination": "dividend_yield",
        "backstory": "You care about stable dividends and capital preservation."
    },
    {
        "name": "Prakash_Retiree", "age": 58, "occupation": "retired bank officer",
        "cash": 50000.0, "shares": 250, "risk_tolerance": "low", "strategy_inclination": "capital_preservation",
        "backstory": "Decades in commercial banking made you cynical of social media stock tips."
    }
]

# Reddit Feed with Rigorously Annotated Delivery Rounds
REDDIT_POSTS_SCHEDULE = {
    4: ["r/WallStreetBets: Hearing whispers of big institutional accumulation. Smart money is quietly loading shares."],
    7: ["r/WallStreetBets: WE ARE GOING TO THE MOON! Massive short squeeze brewing. Retail army buy and HOLD! 🚀🚀🚀"],
    8: ["r/WallStreetBets: DIAMOND HANDS ONLY! Do not sell a single share. Hedgies are panicking! 💎🙌"],
    9: ["r/WallStreetBets: Trending #1 across all platforms. $150 IS NOT A MEME! BUY BUY BUY!"],
    10: ["r/WallStreetBets: CRITICAL ALERT: WHALES ARE DUMPING! Volume spiking, bids disappearing! Is this a rug pull?!"],
    11: ["r/WallStreetBets: RUG PULL CONFIRMED! CEO selling personal stake! GET OUT WHILE YOU CAN!"],
    12: ["r/WallStreetBets: Bloodbath. Margin calls triggered everywhere. Everyone who held is completely wiped out."]
}

def get_phase_name(rnd: int) -> str:
    if rnd <= 3:
        return "Quiet Baseline"
    elif rnd <= 6:
        return "Subreddit Rumor"
    elif rnd <= 9:
        return "Meme Pump (FOMO)"
    elif rnd <= 12:
        return "Panic Dump (Crash)"
    else:
        return "Post-Crash Stagnation"

def run_reddit_market(use_forum: bool, client: RepairedResilientClient) -> Dict[str, Any]:
    cond_name = "REDDIT_FEED_ACTIVE" if use_forum else "FORUM_SILENT_CONTROL"
    print(f"\n=======================================================")
    print(f" LAUNCHING LIVE MARKET: {cond_name}")
    print(f"=======================================================")

    asset = DecoupledAsset(seed=SEED + 100)
    auction = CallAuction(seed=SEED + 200)
    rule_rng = np.random.default_rng(SEED + 300)

    accounts: Dict[str, RepairedMarginAgent] = {}
    mm = RepairedMarginAgent("MarketMaker", cash=100000.0, shares=300, rng=rule_rng, allow_short=False)
    accounts["MarketMaker"] = mm

    f1 = RepairedMarginFundamentalist("Fund_1", cash=30000.0, shares=0, rng=rule_rng, allow_short=True, max_trade_size=10)
    accounts["Fund_1"] = f1

    llm_traders: List[RepairedLLMTrader] = []
    for p in PERSONAS:
        t = RepairedLLMTrader(
            agent_id=p["name"],
            cash=p["cash"],
            shares=p["shares"],
            rng=rule_rng,
            persona=p,
            client=client,
            allow_short=True
        )
        accounts[p["name"]] = t
        llm_traders.append(t)

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
        phase = get_phase_name(rnd)

        posts = REDDIT_POSTS_SCHEDULE.get(rnd, []) if use_forum else []
        post_str = f" | Post: \"{posts[0][:40]}...\"" if posts else ""
        print(f"\n--- Round {rnd:02d}/{TOTAL_ROUNDS} [{phase}] | Price=${curr_p:.2f}{post_str} ---")

        for aid, a in accounts.items():
            accounts_log.append({
                "condition": cond_name, "round": rnd, "agent": aid,
                "cash": round(a.cash, 2), "shares": a.shares,
                "wealth": round(a.wealth(curr_p), 2), "avg_cost": round(a.avg_cost, 2)
            })

        round_orders: List[Order] = []

        # Market Maker quotes
        mm_bid = Order("MarketMaker", "buy", 10, round(curr_p - 1.0, 2))
        mm_ask = Order("MarketMaker", "sell", 10, round(curr_p + 1.0, 2))
        round_orders.extend([mm_bid, mm_ask])

        # Fundamentalist order
        obs_fund = Observation(
            round=rnd, total_rounds=TOTAL_ROUNDS, price_history=price_history, volume_history=volume_history,
            last_dividend=last_div, risk_free_rate=0.0002, fundamental_hint=100.0,
            bbs_posts=[], order_book=[], cash=0, shares=0, locked_collateral=0, wealth=0, peer_trades=[]
        )
        fo = f1.decide(obs_fund)
        if fo.side != 'hold':
            round_orders.append(fo)

        # LLM decisions
        for t in llm_traders:
            obs_llm = Observation(
                round=rnd, total_rounds=TOTAL_ROUNDS, price_history=price_history, volume_history=volume_history,
                last_dividend=last_div, risk_free_rate=0.0002, fundamental_hint=100.0,
                bbs_posts=posts, order_book=[], cash=t.cash, shares=t.shares,
                locked_collateral=t.get_required_collateral(curr_p), wealth=t.wealth(curr_p), peer_trades=[]
            )
            order = t.decide(obs_llm)
            orders_log.append({
                "condition": cond_name, "round": rnd, "phase": phase, "agent": t.agent_id,
                "side": order.side, "requested_qty": order.quantity, "validated_qty": order.quantity,
                "limit_price": order.limit_price, "reasoning": order.reasoning,
                "status": order.status, "model_status": t.last_status,
                "forum_post": posts[0] if posts else "None"
            })
            if order.side != 'hold' and order.quantity > 0:
                round_orders.append(order)
            print(f"   [{t.agent_id:18s}]: {order.side.upper():4s} {order.quantity:2d} sh @ {str(order.limit_price):>6s} | {order.reasoning[:45]}")
            time.sleep(1.0)

        # Clearing & Settlement
        clearing_p, vol, trades = auction.match(rnd, round_orders, curr_p)
        executed_trades = atomic_settle(trades, accounts)

        for a in accounts.values():
            a.pay_dividend(div)
            a.pay_risk_free_interest(0.0002)

        price_history.append(clearing_p)
        volume_history.append(vol)

        market_log.append({
            "round": rnd, "phase": phase, "price": clearing_p, "volume": vol,
            "dividend": round(div, 4), "trades_count": len(executed_trades)
        })

        net_shares = sum(a.shares for a in accounts.values())
        assert net_shares == initial_total_shares, f"Share leak: {net_shares} vs {initial_total_shares}"
        print(f"   => Cleared at ${clearing_p:.2f} | Volume: {vol:2d} shares")

    return {
        "condition": cond_name,
        "market_log": market_log,
        "orders_log": orders_log,
        "accounts_log": accounts_log,
        "prices": price_history[1:],
        "volumes": volume_history[1:],
        "dividends": dividends_history
    }

def main():
    os.makedirs(RESULTS_DIR, exist_ok=True)
    client = RepairedResilientClient()

    t_start = time.time()
    res_silent = run_reddit_market(use_forum=False, client=client)
    res_reddit = run_reddit_market(use_forum=True, client=client)
    total_time = round(time.time() - t_start, 1)

    print("\n=======================================================")
    print(" SAVING REPAIRED REDDIT EXPERIMENT ARTIFACTS")
    print("=======================================================")

    # 1. Market Comparison CSV
    comp_path = os.path.join(RESULTS_DIR, "market_comparison.csv")
    with open(comp_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["round", "phase", "price_silent", "vol_silent", "price_reddit", "vol_reddit", "dividend"])
        for r in range(TOTAL_ROUNDS):
            writer.writerow([
                r + 1, get_phase_name(r + 1),
                res_silent["prices"][r], res_silent["volumes"][r],
                res_reddit["prices"][r], res_reddit["volumes"][r],
                round(res_silent["dividends"][r], 4)
            ])

    # 2. Orders Ledger CSV
    orders_path = os.path.join(RESULTS_DIR, "orders_ledger.csv")
    all_orders = res_silent["orders_log"] + res_reddit["orders_log"]
    with open(orders_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "condition", "round", "phase", "agent", "side", "requested_qty", "validated_qty",
            "limit_price", "reasoning", "status", "model_status", "forum_post"
        ])
        writer.writeheader()
        writer.writerows(all_orders)

    # 3. Accounts History CSV
    accounts_path = os.path.join(RESULTS_DIR, "accounts_history.csv")
    all_accounts = res_silent["accounts_log"] + res_reddit["accounts_log"]
    with open(accounts_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "condition", "round", "agent", "cash", "shares", "wealth", "avg_cost"
        ])
        writer.writeheader()
        writer.writerows(all_accounts)

    # 4. Provenance Manifest JSON
    prov_path = os.path.join(RESULTS_DIR, "provenance_manifest.json")
    prov_data = {
        "experiment": "Repaired Matched Reddit Social Contagion",
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
        "dividends_identical": (res_silent["dividends"] == res_reddit["dividends"]),
        "peak_price_silent": max(res_silent["prices"]),
        "peak_price_reddit": max(res_reddit["prices"]),
        "trough_price_silent": min(res_silent["prices"]),
        "trough_price_reddit": min(res_reddit["prices"])
    }
    with open(prov_path, "w", encoding="utf-8") as f:
        json.dump(prov_data, f, indent=2)

    # 5. High-Resolution Comparative Plot with Rigorous Phase Shading
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True, gridspec_kw={'height_ratios': [2.5, 1.2]})
    rounds_x = list(range(1, TOTAL_ROUNDS + 1))

    # Phase Shading matching exact schedule
    ax1.axvspan(3.5, 6.5, color='#fff3cd', alpha=0.4, label='Subreddit Rumor (R4-R6)')
    ax1.axvspan(6.5, 9.5, color='#d4edda', alpha=0.5, label='Meme Pump / FOMO (R7-R9)')
    ax1.axvspan(9.5, 12.5, color='#f8d7da', alpha=0.5, label='Panic Dump / Rug Pull (R10-R12)')
    ax1.axvspan(12.5, 16.5, color='#e2e3e5', alpha=0.3, label='Post-Crash Hangover (R13-R16)')

    ax1.axhline(100.0, color='gray', linestyle='--', linewidth=1.5, label='Fundamental Anchor ($F=100$)')
    ax1.plot(rounds_x, res_silent["prices"], color='#6c757d', marker='o', linewidth=2.5, label='Silent Control Market (No Forum)')
    ax1.plot(rounds_x, res_reddit["prices"], color='#ff4500', marker='^', linewidth=3.0, label='Reddit Intervention Market (Active Feed)')
    ax1.set_ylabel('Clearing Price ($)', fontsize=12, fontweight='bold')
    ax1.set_title('Social Sentiment Contagion: Matched Control vs. WallStreetBets Hype Cycle', fontsize=14, fontweight='bold')
    ax1.grid(True, alpha=0.3)
    ax1.legend(loc='upper left', frameon=True, fontsize=9)

    ax2.bar([x - 0.2 for x in rounds_x], res_silent["volumes"], width=0.4, color='#6c757d', label='Vol: Silent Control')
    ax2.bar([x + 0.2 for x in rounds_x], res_reddit["volumes"], width=0.4, color='#ff4500', label='Vol: Reddit Intervention')
    ax2.set_xlabel('Round Number', fontsize=12, fontweight='bold')
    ax2.set_ylabel('Volume (Shares)', fontsize=11, fontweight='bold')
    ax2.grid(True, alpha=0.3)
    ax2.legend(loc='upper left', frameon=True, fontsize=9)

    plt.tight_layout()
    chart_path = os.path.join(RESULTS_DIR, "reddit_sentiment_repaired_chart.png")
    plt.savefig(chart_path, dpi=300)
    plt.close()

    print(f"\nCompleted in {total_time}s.")
    print(f"Chart saved to: {chart_path}")
    print(f"Provenance saved to: {prov_path}")

if __name__ == "__main__":
    main()
