"""Live Short-Sale Comparison Experiment: Short-Sale Ban vs. Short-Sale Allowed.

Testing Miller (1977) Overvaluation Hypothesis with Live DeepSeek LLMs.
Two Matched Markets (15 Rounds Each):
- Market 1: No Short-Selling (Baseline).
- Market 2: Short-Selling Allowed with Cash Margin Collateral (Intervention).

Isolated in sandbox_experiments/results_short_sale_comparison/
"""
import sys
import os
import math
import json
import time
import urllib.request
import urllib.error
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "starter_code"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from prototype_engine import (
    MarginAgent, MarginFundamentalist, settle_with_short,
    CallAuctionMarket, Asset, Observation, Order, Trade,
    MomentumAgent, ZeroIntelligenceAgent, MarketMakerAgent
)
from sim.agents.personas import LIBRARY

# 1. Load API Key
env_lines = (REPO_ROOT / "starter_code/.env").read_text(encoding="utf-8").splitlines()
API_KEY = None
for l in env_lines:
    if l.startswith("GODEL_MACHINES_API_KEY="):
        API_KEY = l.split("=", 1)[1].strip().strip('"').strip("'")
        break

if not API_KEY:
    raise RuntimeError("GODEL_MACHINES_API_KEY not found in starter_code/.env")

BASE_URL = "https://api.goedelmachines.com/v1"
MODEL = "deepseek/deepseek-v4.1-flash"


class SandboxLLMClient:
    def __init__(self, api_key, model=MODEL, base_url=BASE_URL):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url

    def complete(self, messages, temperature=0.3, max_tokens=1024):
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"}
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        req = urllib.request.Request(f"{self.base_url}/chat/completions",
                                     data=json.dumps(body).encode("utf-8"),
                                     headers=headers)
        
        for attempt in range(5):
            try:
                with urllib.request.urlopen(req, timeout=25) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    choice = data["choices"][0]
                    content = choice["message"].get("content")
                    if not content and "reasoning_content" in choice["message"]:
                        content = choice["message"]["reasoning_content"]
                    return content
            except urllib.error.HTTPError as e:
                if e.code in (429, 502, 503):
                    wait = 3 * (attempt + 1)
                    print(f" [API {e.code}: waiting {wait}s...]")
                    time.sleep(wait)
                else:
                    print(f" [API Error {e.code}]: {e.read().decode('utf-8', errors='ignore')}")
                    break
            except Exception as e:
                print(f" [Network Error: {e}, waiting 2s...]")
                time.sleep(2)
        return '{"action": "hold", "quantity": 0, "limit_price": null, "reasoning": "API fallback"}'


class LiveLLMTrader(MarginAgent):
    def __init__(self, aid, cash, shares, rng, persona, client, allow_short=False, **kwargs):
        super().__init__(aid, cash, shares, rng, allow_short=allow_short, **kwargs)
        self.persona = persona
        self.client = client
        self.last_reasoning = ""

    def decide(self, obs: Observation) -> Order:
        short_rule = "Short-selling IS ALLOWED if backed by cash margin collateral." if self.allow_short else "NO SHORT-SELLING: You can only sell shares you currently own."
        
        system_prompt = (
            f"You are {self.persona['name']}, a {self.persona['age']}-year-old {self.persona['occupation']}. "
            f"Risk profile: {self.persona['risk_tolerance']}; Style: {self.persona['strategy_inclination']}. "
            f"{self.persona.get('backstory', '')} "
            f"Exchange rules: Uniform call auction. Price tick 0.1; allowable price band ±20% of previous price. "
            f"{short_rule} Cash earns interest; stock pays dividends. "
            f"Respond ONLY with a JSON object: "
            f'{{"action": "buy"|"sell"|"hold", "quantity": <int>, "limit_price": <number or null>, "reasoning": "<1-2 sentences>"}}'
        )

        user_prompt = (
            f"Round {obs.round}/{obs.total_rounds}. Recent auction closing prices: {obs.price_history[-10:]}\n"
            f"Last volume: {obs.last_volume}, Dividend: {obs.last_dividend:.3f}, Risk-free rate: {obs.risk_free_rate}\n"
            f"Your Account: Cash ${self.cash:.2f}, Shares {self.shares}, Wealth ${self.wealth(obs.price_history[-1]):.2f}\n"
            f"Your recent trades: {self.recent_trades[-3:]}\n"
            f"Decide your order for this round. Remember: JSON only."
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        raw = self.client.complete(messages, temperature=0.3)
        try:
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            parsed = json.loads(cleaned)
            action = str(parsed.get("action", "hold")).lower().strip()
            if action not in ("buy", "sell", "hold"):
                action = "hold"
            qty = max(0, int(parsed.get("quantity", 0)))
            limit = parsed.get("limit_price")
            limit = float(limit) if limit is not None and math.isfinite(float(limit)) and float(limit) > 0 else None
            reasoning = str(parsed.get("reasoning", ""))
            self.last_reasoning = reasoning
            return Order(self.agent_id, action, qty, limit, round=obs.round, reasoning=reasoning)
        except Exception as e:
            self.last_reasoning = f"Parse fallback: {e}"
            return Order(self.agent_id, "hold", 0, None, round=obs.round, reasoning=self.last_reasoning)


def run_single_live_market(allow_short=False, label="No_Short", seed=30841):
    print("\n" + "=" * 65)
    print(f"RUNNING LIVE MARKET: {label.upper()} (allow_short={allow_short})")
    print("=" * 65)

    rng = np.random.default_rng(seed)
    client = SandboxLLMClient(API_KEY)
    
    asset_cfg = {"dividend": {"mean": 0.02, "relative_noise": 0.2}, "risk_free": 0.0002}
    asset = Asset(asset_cfg, rng)
    market = CallAuctionMarket(tick=0.1, price_band=0.2, transaction_tax=0.0, rng=rng)

    # Demographic Wealth Profile
    persona_configs = [
        {"name": "Vikram_Student", "cash": 2000.0, "shares": 10, "lib_idx": 4},
        {"name": "Arjun_Marketer",  "cash": 5000.0, "shares": 25, "lib_idx": 1},
        {"name": "Meera_Teacher",   "cash": 8000.0, "shares": 40, "lib_idx": 0},
        {"name": "Sana_Owner",      "cash": 20000.0, "shares": 100, "lib_idx": 3},
        {"name": "Lakshmi_Pharma",  "cash": 25000.0, "shares": 125, "lib_idx": 5},
        {"name": "Prakash_Retiree", "cash": 50000.0, "shares": 250, "lib_idx": 2},
    ]

    agents = {}
    agents["MM_001"] = MarketMakerAgent("MM_001", 50000.0, 200, rng, params={"spread": 0.02, "inventory_limit": 500})
    agents["Fund_001"] = MarginFundamentalist("Fund_001", 30000.0, 150, rng, allow_short=allow_short, params={"aggressiveness": 0.6})
    agents["Fund_002"] = MarginFundamentalist("Fund_002", 30000.0, 150, rng, allow_short=allow_short, params={"aggressiveness": 0.6})
    agents["Mom_001"] = MomentumAgent("Mom_001", 20000.0, 100, rng, params={"aggressiveness": 0.7, "window": 3})
    agents["Mom_002"] = MomentumAgent("Mom_002", 20000.0, 100, rng, params={"aggressiveness": 0.7, "window": 3})
    agents["ZI_001"] = ZeroIntelligenceAgent("ZI_001", 10000.0, 50, rng)
    agents["ZI_002"] = ZeroIntelligenceAgent("ZI_002", 10000.0, 50, rng)

    for p in persona_configs:
        p_data = dict(LIBRARY[p["lib_idx"]])
        p_data["name"] = p["name"]
        agents[p["name"]] = LiveLLMTrader(
            p["name"], p["cash"], p["shares"], rng,
            persona=p_data, client=client, allow_short=allow_short
        )

    initial_shares = sum(a.shares for a in agents.values())
    prices = [100.0]
    volumes = []
    short_shares_trace = [0]
    all_orders = []

    executor = ThreadPoolExecutor(max_workers=2)

    for rnd in range(1, 16):
        prev_price = prices[-1]
        asset.open_round(rnd)

        obs_common = dict(
            round=rnd, total_rounds=15,
            price_history=prices[-15:], last_volume=volumes[-1] if volumes else 0,
            last_dividend=0.02, risk_free_rate=0.0002, fundamental_hint=100.0,
            news=[], bbs_posts=[], round_unit="session"
        )

        llm_list = [a for a in agents.values() if isinstance(a, LiveLLMTrader)]
        rule_list = [a for a in agents.values() if not isinstance(a, LiveLLMTrader)]

        def get_obs(a):
            return Observation(**obs_common, my_cash=a.cash, my_shares=a.shares,
                               my_avg_cost=a.avg_cost, my_wealth=a.wealth(prev_price),
                               my_recent_trades=list(a.recent_trades))

        llm_decs = list(executor.map(lambda a: a.decide(get_obs(a)), llm_list))
        rule_decs = [a.decide(get_obs(a)) for a in rule_list]

        orders = []
        for a, dec in zip(llm_list + rule_list, llm_decs + rule_decs):
            checked = a.validate_orders(dec, prev_price)
            orders.extend(checked)
            for o in checked:
                if isinstance(a, LiveLLMTrader):
                    all_orders.append({
                        "round": rnd, "agent": o.agent_id, "side": o.side,
                        "qty": o.quantity, "limit": o.limit_price, "reasoning": a.last_reasoning
                    })

        clearing_price, trades, unmatched = market.clear(orders, prev_price, rnd)
        settle_with_short(trades, agents, market)

        div = asset.draw_dividend()
        for a in agents.values():
            a.pay_dividend(div, asset.risk_free)

        prices.append(clearing_price)
        cur_vol = sum(t.quantity for t in trades)
        volumes.append(cur_vol)

        cur_short = sum(abs(a.shares) for a in agents.values() if a.shares < 0)
        short_shares_trace.append(cur_short)

        llm_str = ", ".join(f"{o['agent'][:6]}:{o['side'].upper()}{o['qty']}" for o in all_orders if o['round'] == rnd)
        print(f"Round {rnd:02d} | Price: {clearing_price:6.2f} | Vol: {cur_vol:3d} | Short: {cur_short:2d} | LLMs: {llm_str}")

    executor.shutdown()

    final_shares = sum(a.shares for a in agents.values())
    assert final_shares == initial_shares, f"Share leak: {final_shares} != {initial_shares}"
    print(f"Audit passed: {initial_shares} shares conserved!")

    return {
        "prices": prices,
        "volumes": volumes,
        "short_shares": short_shares_trace,
        "orders": all_orders,
        "mean_price": np.mean(prices[1:]),
        "mean_gap": np.mean(np.abs(np.array(prices[1:]) - 100.0)),
        "max_price": max(prices),
        "total_volume": sum(volumes),
        "final_cash": {aid: round(a.cash, 2) for aid, a in agents.items() if isinstance(a, LiveLLMTrader)},
        "final_shares": {aid: a.shares for aid, a in agents.items() if isinstance(a, LiveLLMTrader)}
    }


def main():
    out_dir = Path(__file__).resolve().parent / "results_short_sale_comparison"
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Run Market 1: No Short-Selling (Baseline)
    res_banned = run_single_live_market(allow_short=False, label="Short_Sale_BANNED")

    # 2. Run Market 2: Short-Selling Allowed (Intervention)
    res_allowed = run_single_live_market(allow_short=True, label="Short_Sale_ALLOWED")

    print("\n" + "=" * 70)
    print("LIVE COMPARATIVE EXPERIMENT SUMMARY (MILLER 1977 VALIDATION)")
    print("=" * 70)
    print(f"Baseline (Short-Sale Banned)    -> Mean Price: {res_banned['mean_price']:.2f} | Peak: {res_banned['max_price']:.2f} | Mean Gap: {res_banned['mean_gap']:.2f}%")
    print(f"Intervention (Short Allowed)    -> Mean Price: {res_allowed['mean_price']:.2f} | Peak: {res_allowed['max_price']:.2f} | Mean Gap: {res_allowed['mean_gap']:.2f}%")
    gap_diff = res_banned['mean_gap'] - res_allowed['mean_gap']
    print(f"Valuation Improvement (Error Reduction): {gap_diff:+.2f} percentage points")
    print("=" * 70)

    # Save Output CSVs
    import csv
    with open(out_dir / "market_comparison.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["round", "price_no_short", "vol_no_short", "price_short_allowed", "vol_short_allowed", "short_interest"])
        for r in range(1, 16):
            w.writerow([r, res_banned["prices"][r], res_banned["volumes"][r-1],
                        res_allowed["prices"][r], res_allowed["volumes"][r-1],
                        res_allowed["short_shares"][r]])

    # Generate Publication Chart
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 8), sharex=True, dpi=300)
    rounds_x = list(range(0, 16))

    ax1.plot(rounds_x, res_banned["prices"], color="#d62728", linewidth=2.5, marker="o", label="Market 1: Short-Sale Banned (Baseline)")
    ax1.plot(rounds_x, res_allowed["prices"], color="#2ca02c", linewidth=2.5, marker="s", label="Market 2: Short-Sale Allowed (Miller 1977)")
    ax1.axhline(100.0, color="black", linestyle="--", linewidth=1.5, label="Risk-Neutral Reference (F=100)")
    ax1.set_ylabel("Stock Price ($)", fontsize=12, fontweight="bold")
    ax1.set_title("Live DeepSeek Market: Testing Miller (1977) Short-Sale Overvaluation", fontsize=14, fontweight="bold")
    ax1.grid(True, linestyle=":", alpha=0.6)
    ax1.legend(loc="upper left")

    ax2.bar(np.array(rounds_x[1:]) - 0.15, res_banned["volumes"], width=0.3, color="#d62728", alpha=0.6, label="Volume (No Short)")
    ax2.bar(np.array(rounds_x[1:]) + 0.15, res_allowed["volumes"], width=0.3, color="#2ca02c", alpha=0.6, label="Volume (Short Allowed)")
    ax2.plot(rounds_x[1:], res_allowed["short_shares"][1:], color="purple", linewidth=2, marker="^", label="Total Short Interest (Shares)")
    ax2.set_xlabel("Trading Session (Round)", fontsize=12, fontweight="bold")
    ax2.set_ylabel("Shares", fontsize=12, fontweight="bold")
    ax2.set_title("Trading Volume and Active Short Interest over Time", fontsize=12, fontweight="bold")
    ax2.grid(True, linestyle=":", alpha=0.6)
    ax2.legend(loc="upper left")

    plt.tight_layout()
    chart_path = out_dir / "short_sale_vs_ban_chart.png"
    plt.savefig(chart_path)
    plt.close()

    print(f"\nComparative chart successfully saved to: {chart_path}\n")


if __name__ == "__main__":
    main()
