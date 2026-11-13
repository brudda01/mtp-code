"""Standalone Sandbox Engine for Prototype Testing.

Features:
1. Wealth Heterogeneity (Demographic endowments: student, teacher, restaurant owner, retiree).
2. Short-Selling with Margin Collateral (Testing Miller 1977 overvaluation hypothesis).
3. Forum Posts / Bulletin Board Feed (Testing social sentiment and meme-stock hype).

This file lives exclusively in sandbox_experiments/ and does NOT alter starter_code/ or thesis/.
"""
from __future__ import annotations

import math
from numbers import Integral, Real
from dataclasses import dataclass, replace
import numpy as np

# Import core structures from starter_code
import sys
from pathlib import Path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "starter_code"))

from sim.market import Order, Trade, CallAuctionMarket
from sim.assets import Asset
from sim.agents.base import Observation, Agent
from sim.agents.rule_agents import ZeroIntelligenceAgent, FundamentalistAgent, MomentumAgent, MarketMakerAgent


class MarginAgent(Agent):
    """An agent that can short-sell shares using cash as margin collateral.
    
    Margin requirement: 150% of notional short value (100% principal + 50% maintenance buffer).
    If shares < 0, agent is short. When dividend is paid, short seller PAYS the dividend.
    """
    def __init__(self, agent_id, cash, shares, rng, params=None, *,
                 initial_price=100.0, initial_cost=None, transaction_tax=0.0,
                 price_band=0.2, allow_short=True, margin_ratio=1.5):
        super().__init__(agent_id, cash, shares, rng, params=params,
                         initial_price=initial_price, initial_cost=initial_cost,
                         transaction_tax=transaction_tax, price_band=price_band)
        self.allow_short = allow_short
        self.margin_ratio = margin_ratio

    def _add_shares(self, q: int, price: float):
        """Handle both long additions and short positions."""
        old_shares = self.shares
        self.shares += q
        if self.shares > 0:
            if old_shares >= 0:
                tot = self.avg_cost * old_shares + price * q
                self.avg_cost = tot / self.shares if self.shares else 0.0
            else:
                # Covered short position into net long
                self.avg_cost = price
        elif self.shares < 0:
            if old_shares <= 0:
                # Added to short position
                tot = self.avg_cost * abs(old_shares) + price * abs(q)
                self.avg_cost = tot / abs(self.shares)
            else:
                # Flipped from long to net short
                self.avg_cost = price
        else:
            self.avg_cost = 0.0

    def pay_dividend(self, d: float, r: float):
        """If short (shares < 0), agent PAYS dividend. Cash earns risk-free interest."""
        dividend_income = self.shares * d  # Negative if shares < 0
        interest_income = max(0.0, self.cash) * r
        self.cash += dividend_income + interest_income
        return dividend_income, interest_income

    def wealth(self, price: float) -> float:
        """Net equity = cash + shares * price (shares * price is negative debt if short)."""
        return self.cash + self.shares * price

    def validate_orders(self, decisions, last_price):
        orders = [decisions] if isinstance(decisions, Order) else decisions
        remaining_cash = self.cash
        ceiling = last_price * (1 + self.price_band)
        checked = []
        
        for order in orders:
            requested = order.quantity
            if order.side == "buy":
                ref = min(order.limit_price, ceiling) if order.limit_price is not None else ceiling
                unit_cost = ref * (1 + self.transaction_tax)
                max_buy = math.floor(max(0.0, remaining_cash) / unit_cost + 1e-12)
                order.quantity = min(order.quantity, max_buy)
                remaining_cash -= order.quantity * unit_cost
            elif order.side == "sell":
                if self.allow_short:
                    # Can sell long shares + short sell up to cash margin
                    long_sellable = max(0, self.shares)
                    short_part = max(0, order.quantity - long_sellable)
                    unit_margin = ceiling * self.margin_ratio
                    max_short = math.floor(max(0.0, remaining_cash) / unit_margin + 1e-12)
                    allowed_short = min(short_part, max_short)
                    order.quantity = min(order.quantity, long_sellable + allowed_short)
                    remaining_cash -= allowed_short * unit_margin
                else:
                    order.quantity = min(order.quantity, max(0, self.shares))
            
            if order.quantity != requested:
                order.validation_note = "quantity_adjusted_by_margin_or_shares"
            if order.quantity == 0:
                order.side = "hold"
            checked.append(order)
        return checked


class MarginFundamentalist(FundamentalistAgent, MarginAgent):
    """Fundamentalist that actively short-sells when stock is heavily overpriced."""
    def __init__(self, *args, allow_short=True, **kwargs):
        super().__init__(*args, **kwargs)
        self.allow_short = allow_short
        self.margin_ratio = 1.5


def settle_with_short(trades, agents, market):
    """Settlement supporting short-sellers with cash/share conservation."""
    trades = list(trades)
    spending = {aid: 0.0 for aid in agents}
    cash_changes = {aid: [] for aid in agents}
    total_cash = math.fsum(a.cash for a in agents.values()) + market.tax_collected
    total_shares = sum(a.shares for a in agents.values())
    taxes = []

    for trade in trades:
        gross = trade.quantity * trade.price
        tax = gross * market.transaction_tax
        spending[trade.buyer_id] += gross + tax
        cash_changes[trade.buyer_id].append(-gross - tax)
        cash_changes[trade.seller_id].append(gross - tax)
        taxes.append(2 * tax)

    # Perform asset transfers
    for trade in trades:
        buyer = agents[trade.buyer_id]
        seller = agents[trade.seller_id]
        buyer._add_shares(trade.quantity, trade.price * (1 + market.transaction_tax))
        seller._add_shares(-trade.quantity, trade.price)
        buyer.record_trade(trade, is_buyer=True)
        seller.record_trade(trade, is_buyer=False)

    for aid, agent in agents.items():
        agent.cash = agent.cash + math.fsum(cash_changes[aid])
    
    market.tax_collected += math.fsum(taxes)
    cash_after = math.fsum(a.cash for a in agents.values()) + market.tax_collected
    
    # Conservation checks
    shares_after = sum(a.shares for a in agents.values())
    assert shares_after == total_shares, f"Share leak: {shares_after} != {total_shares}"
    assert math.isclose(cash_after, total_cash, rel_tol=1e-12, abs_tol=1e-7), f"Cash leak: {cash_after} != {total_cash}"
