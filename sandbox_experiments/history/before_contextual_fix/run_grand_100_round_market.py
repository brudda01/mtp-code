"""
Grand 100-Round Market Simulation with 12 Heterogeneous LLM Personas.
Scale: 100 Rounds x 12 LLMs = 1,200 Decisions (+ 8 Rule Agents).
Strictly isolated in sandbox_experiments/
"""
import os
import json
import time
import math
import random
import urllib.request
import concurrent.futures
from dataclasses import dataclass
from typing import List, Dict, Any, Optional

# Load environment credentials safely
ENV = {}
with open("starter_code/.env") as f:
    for line in f:
        if "=" in line and not line.startswith("#"):
            k, v = line.strip().split("=", 1)
            ENV[k] = v.strip("\"'")
API_KEY = ENV.get("GODEL_MACHINES_API_KEY") or ENV.get("API_KEY")
MODEL = "deepseek/deepseek-v4.1-flash"
BASE_URL = "https://api.goedelmachines.com/v1"

# 12 Handcrafted Heterogeneous Personas spanning students to high-net-worth investors
PERSONAS_12 = [
    {
        "name": "Vikram_Student",
        "age": 23,
        "occupation": "engineering student",
        "cash": 2000.0,
        "shares": 10,
        "risk": "high",
        "horizon": "short",
        "strategy": "speculative_momentum",
        "backstory": "You trade on your phone with tight savings. You love high-growth rallies and fear missing out."
    },
    {
        "name": "Rohan_DayTrader",
        "age": 25,
        "occupation": "crypto & options trader",
        "cash": 4000.0,
        "shares": 15,
        "risk": "extreme_high",
        "horizon": "ultra_short",
        "strategy": "breakout_hunter",
        "backstory": "You scalp fast moves. You buy aggressive breakouts and dump immediately if momentum stalls."
    },
    {
        "name": "Arjun_Marketer",
        "age": 27,
        "occupation": "startup marketer",
        "cash": 6000.0,
        "shares": 25,
        "risk": "high",
        "horizon": "short",
        "strategy": "momentum_chaser",
        "backstory": "You believe you can spot consumer and social trends ahead of the crowd. You trust market hype."
    },
    {
        "name": "Rohit_QuantDev",
        "age": 31,
        "occupation": "software engineer",
        "cash": 9000.0,
        "shares": 35,
        "risk": "medium",
        "horizon": "medium",
        "strategy": "algorithmic_trend",
        "backstory": "You look at numerical trends and moving averages. You dislike irrational emotional swings."
    },
    {
        "name": "Meera_Teacher",
        "age": 34,
        "occupation": "high school teacher",
        "cash": 12000.0,
        "shares": 50,
        "risk": "low",
        "horizon": "long",
        "strategy": "loss_averse_saver",
        "backstory": "You save every rupee from your teaching salary. Losing capital is deeply painful to you."
    },
    {
        "name": "Kavita_Lawyer",
        "age": 39,
        "occupation": "corporate lawyer",
        "cash": 16000.0,
        "shares": 70,
        "risk": "medium_low",
        "horizon": "medium_long",
        "strategy": "analytical_contrarian",
        "backstory": "You scrutinize valuation contracts and earnings reports. You are skeptical of rapid unbacked price rises."
    },
    {
        "name": "Sana_Owner",
        "age": 42,
        "occupation": "restaurant owner",
        "cash": 22000.0,
        "shares": 90,
        "risk": "medium",
        "horizon": "medium",
        "strategy": "growth_accumulating",
        "backstory": "You run a busy restaurant and reinvest profits. You believe in reinvesting aggressively in expanding businesses."
    },
    {
        "name": "Lakshmi_Pharmacist",
        "age": 48,
        "occupation": "retail pharmacist",
        "cash": 26000.0,
        "shares": 110,
        "risk": "medium",
        "horizon": "long",
        "strategy": "dividend_harvester",
        "backstory": "You rely on steady, predictable returns and dividends. You prefer stable cash-generating companies."
    },
    {
        "name": "Ananya_Director",
        "age": 52,
        "occupation": "non-profit director",
        "cash": 32000.0,
        "shares": 130,
        "risk": "low",
        "horizon": "long",
        "strategy": "ethical_fundamentalist",
        "backstory": "You value prudence, long-term stability, and fair pricing. You avoid speculative gambles."
    },
    {
        "name": "Devendra_Builder",
        "age": 45,
        "occupation": "real-estate developer",
        "cash": 40000.0,
        "shares": 160,
        "risk": "medium_high",
        "horizon": "medium",
        "strategy": "value_opportunist",
        "backstory": "You buy hard assets when they are cheap and sell when overextended. You understand cash flow cycles."
    },
    {
        "name": "Prakash_Retiree",
        "age": 58,
        "occupation": "retired bank officer",
        "cash": 55000.0,
        "shares": 220,
        "risk": "low",
        "horizon": "long",
        "strategy": "capital_preservation",
        "backstory": "Four decades in banking taught you that valuation matters above all. You protect your retirement nest egg."
    },
    {
        "name": "Vijay_AngelInvestor",
        "age": 62,
        "occupation": "angel investor & industrialist",
        "cash": 80000.0,
        "shares": 300,
        "risk": "medium",
        "horizon": "ultra_long",
        "strategy": "institutional_liquidity",
        "backstory": "You manage substantial family capital. You provide liquidity during panics and trim during euphoria."
    }
]

print("Personas defined:", len(PERSONAS_12))
