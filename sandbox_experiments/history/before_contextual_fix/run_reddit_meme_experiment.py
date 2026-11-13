"""Live Reddit Meme-Stock Experiment in Sandbox.

16 Rounds, 6 Canonical LLM Personas (DeepSeek v4.1 Flash via Goedel Machines).
Features:
- Realistic Demographic Wealth Heterogeneity.
- Short-Selling Allowed with Margin Collateral.
- 4-Phase Reddit Hype Cycle via obs.bbs_posts.
- Automated 2-panel chart generation (Price bubble + Agent actions).

Completely isolated in sandbox_experiments/ - does NOT touch thesis/ or starter_code/.
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
    """Robust client with automatic retry on 429/502/503."""
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
                    # If model put text in reasoning_content when content is null
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


class SandboxLLMAgent(MarginAgent):
    """LLM agent with full demographic persona and Reddit forum visibility."""
    def __init__(self, aid, cash, shares, rng, persona, client, **kwargs):
        super().__init__(aid, cash, shares, rng, **kwargs)
        self.persona = persona
        self.client = client
        self.last_reasoning = ""

    def decide(self, obs: Observation) -> Order:
        system_prompt = (
            f"You are {self.persona['name']}, a {self.persona['age']}-year-old {self.persona['occupation']}. "
            f"Risk profile: {self.persona['risk_tolerance']}; Style: {self.persona['strategy_inclination']}. "
            f"{self.persona.get('backstory', '')} "
            f"Exchange rules: Uniform call auction. Price tick 0.1; allowable price band ±20% of previous price. "
            f"Short-selling IS ALLOWED if backed by cash margin. Cash earns interest; stock pays dividends. "
            f"Respond ONLY with a JSON object: "
            f'{{"action": "buy"|"sell"|"hold", "quantity": <int>, "limit_price": <number or null>, "reasoning": "<1-2 sentences>"}}'
        )

        bbs_text = f"Social Forum (Reddit / Twitter):\n" + "\n".join(obs.bbs_posts) + "\n" if obs.bbs_posts else "Social Forum: [No trending posts]\n"
        
        user_prompt = (
            f"Round {obs.round}/{obs.total_rounds}. Recent auction closing prices: {obs.price_history[-10:]}\n"
            f"Last volume: {obs.last_volume}, Dividend: {obs.last_dividend:.3f}, Risk-free rate: {obs.risk_free_rate}\n"
            f"{bbs_text}"
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
            # Clean possible markdown fence
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


# 2. Define the Reddit Social Media Schedule across 16 Rounds
FORUM_SCHEDULE = {
    1: [],
    2: [],
    3: [],
    4: ["[r/WallStreetBets] Anyone noticing $KGP? Super low float, heavily shorted by institutional bots... 👀"],
    5: [
        "[r/WallStreetBets] 🚀🚀 $KGP TO THE MOON! Short squeeze starting! Institutions are trapped!",
        "[r/WallStreetBets] BUY AND HOLD! Do not sell a single share! Squeeze them dry! 💎🙌"
    ],
    6: [
        "[r/WallStreetBets] 🔥 SQUEEZE IN PROGRESS! Buy at market! Target is $140!",
        "[Twitter/X] #SqueezeKGP trending #1 worldwide! Retail army uniting!"
    ],
    7: [
        "[r/WallStreetBets] 🚀🚀 WE ARE BREAKING THE ALGORITHMS! Keep buying! $150 next!",
        "[r/WallStreetBets] If you sell now, you are weak hands! Diamond hands only! 💎🙌"
    ],
    8: [
        "[r/WallStreetBets] Hold the line! Hedgies are bleeding millions per day!",
        "[Twitter/X] Volume soaring on $KGP. Retail buying frenzy continues!"
    ],
    9: [
        "[r/WallStreetBets] 🚨 WHALES ARE DUMPING! Big institutional sell walls appearing at 115!",
        "[Twitter/X] Insiders taking profit on $KGP. Momentum slowing down."
    ],
    10: [
        "[r/WallStreetBets] 🚨 EMERGENCY: IT WAS A RUG PULL! Market maker dumping inventory! RUN!",
        "[Twitter/X] $KGP crashing! Cut losses and sell now!"
    ],
    11: [
        "[r/WallStreetBets] I lost everything... Sell at any price to salvage cash! 📉😭",
        "[Twitter/X] Retail panic selling on $KGP."
    ],
    12: [
        "[r/WallStreetBets] Squeeze is officially dead. Bagholders convention... 💀"
    ],
    13: [],
    14: [],
    15: [],
    16: []
}


def run_meme_experiment():
    print("=" * 70)
    print("LAUNCHING LIVE REDDIT MEME-STOCK EXPERIMENT (16 ROUNDS, 6 LLMs)")
    print("Model: deepseek/deepseek-v4.1-flash | Goedel Machines API")
    print("=" * 70)

    results_dir = Path(__file__).resolve().parent / "results"
    results_dir.mkdir(parents=True, exist_ok=True)

    rng = np.random.default_rng(2026)
    client = SandboxLLMClient(API_KEY)
    
    asset_cfg = {"dividend": {"mean": 0.02, "relative_noise": 0.2}, "risk_free": 0.0002}
    asset = Asset(asset_cfg, rng)
    market = CallAuctionMarket(tick=0.1, price_band=0.2, transaction_tax=0.0, rng=rng)

    # Demographic Wealth Profile for all 6 personas
    persona_configs = [
        {"name": "Vikram_Student", "cash": 2000.0, "shares": 10, "lib_idx": 4},   # Vikram Bose
        {"name": "Arjun_Marketer",  "cash": 5000.0, "shares": 25, "lib_idx": 1},   # Arjun Malhotra
        {"name": "Meera_Teacher",   "cash": 8000.0, "shares": 40, "lib_idx": 0},   # Meera Iyer
        {"name": "Sana_Owner",      "cash": 20000.0, "shares": 100, "lib_idx": 3}, # Sana Sheikh
        {"name": "Lakshmi_Pharma",  "cash": 25000.0, "shares": 125, "lib_idx": 5}, # Lakshmi Nair
        {"name": "Prakash_Retiree", "cash": 50000.0, "shares": 250, "lib_idx": 2}, # Prakash Rao
    ]

    agents = {}
    # 1. Market Maker & Institutions
    agents["MM_001"] = MarketMakerAgent("MM_001", 50000.0, 200, rng, params={"spread": 0.02, "inventory_limit": 500})
    agents["Fund_001"] = MarginFundamentalist("Fund_001", 30000.0, 150, rng, allow_short=True, params={"aggressiveness": 0.6})
    agents["Fund_002"] = MarginFundamentalist("Fund_002", 30000.0, 150, rng, allow_short=True, params={"aggressiveness": 0.6})
    agents["Mom_001"] = MomentumAgent("Mom_001", 20000.0, 100, rng, params={"aggressiveness": 0.7, "window": 3})
    agents["ZI_001"] = ZeroIntelligenceAgent("ZI_001", 10000.0, 50, rng)

    # 2. The 6 LLM Traders
    for p in persona_configs:
        persona_data = dict(LIBRARY[p["lib_idx"]])
        persona_data["name"] = p["name"]
        agents[p["name"]] = SandboxLLMAgent(
            p["name"], p["cash"], p["shares"], rng,
            persona=persona_data, client=client, allow_short=True
        )

    initial_shares = sum(a.shares for a in agents.values())
    initial_cash = math.fsum(a.cash for a in agents.values())

    prices = [100.0]
    volumes = []
    agent_shares_trace = {aid: [a.shares] for aid, a in agents.items() if isinstance(a, SandboxLLMAgent)}
    agent_cash_trace = {aid: [a.cash] for aid, a in agents.items() if isinstance(a, SandboxLLMAgent)}
    all_orders_log = []

    executor = ThreadPoolExecutor(max_workers=2)

    for rnd in range(1, 17):
        prev_price = prices[-1]
        asset.open_round(rnd)
        posts = FORUM_SCHEDULE.get(rnd, [])
        
        obs_common = dict(
            round=rnd, total_rounds=16,
            price_history=prices[-15:], last_volume=volumes[-1] if volumes else 0,
            last_dividend=0.02, risk_free_rate=0.0002, fundamental_hint=100.0,
            news=[], bbs_posts=posts, round_unit="session"
        )

        # 1. Collect LLM decisions concurrently with pacer
        llm_list = [a for a in agents.values() if isinstance(a, SandboxLLMAgent)]
        rule_list = [a for a in agents.values() if not isinstance(a, SandboxLLMAgent)]

        def get_obs(a):
            return Observation(**obs_common, my_cash=a.cash, my_shares=a.shares,
                               my_avg_cost=a.avg_cost, my_wealth=a.wealth(prev_price),
                               my_recent_trades=list(a.recent_trades))

        llm_decisions = list(executor.map(lambda a: a.decide(get_obs(a)), llm_list))
        rule_decisions = [a.decide(get_obs(a)) for a in rule_list]

        # 2. Validate and collect all orders
        orders = []
        for a, dec in zip(llm_list + rule_list, llm_decisions + rule_decisions):
            checked = a.validate_orders(dec, prev_price)
            orders.extend(checked)
            for o in checked:
                if isinstance(a, SandboxLLMAgent):
                    all_orders_log.append({
                        "round": rnd, "agent": o.agent_id, "side": o.side,
                        "qty": o.quantity, "limit": o.limit_price, "reasoning": a.last_reasoning
                    })

        # 3. Clear call auction
        clearing_price, trades, unmatched = market.clear(orders, prev_price, rnd)
        settle_with_short(trades, agents, market)

        # 4. Dividends & Interest
        div = asset.draw_dividend()
        for a in agents.values():
            a.pay_dividend(div, asset.risk_free)

        prices.append(clearing_price)
        cur_vol = sum(t.quantity for t in trades)
        volumes.append(cur_vol)

        for aid in agent_shares_trace:
            agent_shares_trace[aid].append(agents[aid].shares)
            agent_cash_trace[aid].append(agents[aid].cash)

        # Phase description
        if rnd <= 4:
            phase = "Quiet Baseline"
        elif rnd <= 9:
            phase = "🚀 REDDIT PUMP"
        elif rnd <= 13:
            phase = "🚨 PANIC DUMP"
        else:
            phase = "Aftermath"

        llm_summary = ", ".join(f"{o['agent'][:6]}:{o['side'].upper()}{o['qty']}" for o in all_orders_log if o['round'] == rnd)
        print(f"Round {rnd:02d} [{phase:14s}] P: {clearing_price:6.2f} | Vol: {cur_vol:3d} | LLMs: {llm_summary}")

    executor.shutdown()

    # Final Audits
    final_shares = sum(a.shares for a in agents.values())
    assert final_shares == initial_shares, f"Share leak: {final_shares} != {initial_shares}"
    print("\nConservation checks passed: Zero share leakage!")

    # Save CSVs
    import csv
    with open(results_dir / "reddit_orders.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["round", "agent", "side", "qty", "limit", "reasoning"])
        w.writeheader()
        w.writerows(all_orders_log)

    with open(results_dir / "reddit_market.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["round", "price", "volume"])
        for r in range(1, 17):
            w.writerow([r, prices[r], volumes[r-1]])

    # Generate Publication Plot
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 8), sharex=True, dpi=300)

    rounds_x = list(range(0, 17))
    ax1.plot(rounds_x, prices, color="#1f77b4", linewidth=2.5, marker="o", label="Auction Clearing Price")
    ax1.axhline(100.0, color="gray", linestyle="--", linewidth=1.5, label="Fundamental Reference (F=100)")
    ax1.axvspan(4.5, 9.5, color="green", alpha=0.12, label="Reddit Hype Pump Phase")
    ax1.axvspan(9.5, 13.5, color="red", alpha=0.12, label="Panic Dump Phase")
    ax1.set_ylabel("Stock Price ($)", fontsize=12, fontweight="bold")
    ax1.set_title("Autonomous LLM Reaction to Social Media Hype (Reddit / WallStreetBets)", fontsize=14, fontweight="bold")
    ax1.grid(True, linestyle=":", alpha=0.6)
    ax1.legend(loc="upper left")

    colors = {"Vikram_Student": "#d62728", "Arjun_Marketer": "#ff7f0e", "Meera_Teacher": "#2ca02c",
              "Sana_Owner": "#9467bd", "Lakshmi_Pharma": "#8c564b", "Prakash_Retiree": "#17becf"}

    for aid in agent_shares_trace:
        ax2.plot(rounds_x, agent_shares_trace[aid], label=aid, color=colors.get(aid), linewidth=2, marker="s", markersize=4)

    ax2.axvspan(4.5, 9.5, color="green", alpha=0.08)
    ax2.axvspan(9.5, 13.5, color="red", alpha=0.08)
    ax2.set_xlabel("Trading Session (Round)", fontsize=12, fontweight="bold")
    ax2.set_ylabel("Shares Held", fontsize=12, fontweight="bold")
    ax2.set_title("Agent Portfolio Holdings over Time (FOMO vs. Liquidations)", fontsize=12, fontweight="bold")
    ax2.grid(True, linestyle=":", alpha=0.6)
    ax2.legend(loc="upper left", ncol=2)

    plt.tight_layout()
    chart_path = results_dir / "reddit_meme_bubble_chart.png"
    plt.savefig(chart_path)
    plt.close()

    print(f"\nSUCCESS! Chart saved to: {chart_path}")
    print("=" * 70)


if __name__ == "__main__":
    run_meme_experiment()
