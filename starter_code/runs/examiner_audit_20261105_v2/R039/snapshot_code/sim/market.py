"""Uniform-price auction with price priority and seeded integer pro-rata fills.

Buy limits round down, sell limits up. Bands restrict execution prices without
changing willingness to trade. Equal-price ties do not favor earlier agent IDs.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_EVEN
import math
from numbers import Integral

import numpy as np


@dataclass
class Order:
    agent_id: str
    side: str
    quantity: int = 0
    limit_price: float | None = None
    round: int = 0
    reasoning: str = ""
    validation_note: str = ""


@dataclass
class Trade:
    round: int
    buyer_id: str
    seller_id: str
    quantity: int
    price: float


class CallAuctionMarket:
    def __init__(self, tick=0.1, price_band=0.2, transaction_tax=0.0, rng=None):
        if not math.isfinite(tick) or tick <= 0:
            raise ValueError("tick must be finite and positive")
        if not math.isfinite(price_band) or not 0 <= price_band < 1:
            raise ValueError("price_band must be in [0, 1)")
        if not math.isfinite(transaction_tax) or not 0 <= transaction_tax < 1:
            raise ValueError("transaction_tax must be in [0, 1)")
        self.tick = tick
        self.price_band = price_band
        self.transaction_tax = transaction_tax
        self.tax_collected = 0.0
        self.rng = rng if rng is not None else np.random.default_rng(0)

    def _round_tick(self, price, rounding=ROUND_HALF_EVEN):
        tick = Decimal(str(self.tick))
        ticks = (Decimal(str(price)) / tick).to_integral_value(rounding=rounding)
        return float(ticks * tick)

    def price_bounds(self, prev_price):
        if not math.isfinite(prev_price) or prev_price <= 0:
            raise ValueError("previous price must be finite and positive")
        previous = Decimal(str(prev_price))
        band = Decimal(str(self.price_band))
        return (self._round_tick(previous * (1 - band), ROUND_CEILING),
                self._round_tick(previous * (1 + band), ROUND_FLOOR))

    def _normalise(self, order):
        if order.side not in ("buy", "sell", "hold"):
            raise ValueError("unknown order side")
        if (isinstance(order.quantity, bool) or
                not isinstance(order.quantity, Integral) or order.quantity < 0):
            raise ValueError("order quantity must be a nonnegative integer")
        if order.limit_price is None:
            return order
        if (isinstance(order.limit_price, bool) or
                not math.isfinite(order.limit_price) or order.limit_price <= 0):
            raise ValueError("limit price must be finite and positive")
        rounding = ROUND_FLOOR if order.side == "buy" else ROUND_CEILING
        return replace(order, limit_price=self._round_tick(order.limit_price, rounding))

    def _fill(self, orders, total, is_buy):
        def priority(order):
            if order.limit_price is None:
                return -math.inf
            return -order.limit_price if is_buy else order.limit_price

        ordered = sorted(orders, key=lambda o: (priority(o), o.agent_id))
        groups = {}
        for order in ordered:
            groups.setdefault(priority(order), []).append(order)
        fills = []
        for group in groups.values():
            if total == 0:
                break
            quantity = sum(o.quantity for o in group)
            if quantity <= total:
                fills.extend((o, int(o.quantity)) for o in group)
                total -= quantity
                continue
            # Exact integer arithmetic; leftovers go to largest remainders.
            allocation = [divmod(int(o.quantity) * total, quantity) for o in group]
            assigned = [q for q, _ in allocation]
            leftover = total - sum(assigned)
            if leftover:
                tie_breaks = self.rng.random(len(group))
                ranks = sorted(range(len(group)),
                               key=lambda i: (-allocation[i][1], tie_breaks[i]))
                for i in ranks[:leftover]:
                    assigned[i] += 1
            fills.extend((o, q) for o, q in zip(group, assigned) if q)
            total = 0
        return fills

    def clear(self, orders, prev_price, rnd):
        lo, hi = self.price_bounds(prev_price)
        active = [self._normalise(o) for o in orders]
        buys = [o for o in active if o.side == "buy" and o.quantity > 0]
        sells = [o for o in active if o.side == "sell" and o.quantity > 0]
        unmatched = sum(o.quantity for o in buys + sells)
        if not buys or not sells or lo > hi or hi <= 0:
            return prev_price, [], unmatched
        candidates = {lo, hi, min(max(self._round_tick(prev_price), lo), hi)}
        candidates.update(o.limit_price for o in buys + sells
                          if o.limit_price is not None and lo <= o.limit_price <= hi)
        candidates = sorted(p for p in candidates if p > 0)

        def willing(order, price, is_buy):
            return order.limit_price is None or (
                order.limit_price >= price if is_buy else order.limit_price <= price)

        def volume(price):
            demand = sum(o.quantity for o in buys if willing(o, price, True))
            supply = sum(o.quantity for o in sells if willing(o, price, False))
            return min(demand, supply)

        # Residual symmetric price ties choose the lower price, explicitly.
        price = min(candidates, key=lambda p: (-volume(p), abs(p - prev_price), p))
        matched = volume(price)
        if matched == 0:
            return prev_price, [], unmatched
        bfills = self._fill([o for o in buys if willing(o, price, True)], matched, True)
        sfills = self._fill([o for o in sells if willing(o, price, False)], matched, False)
        trades = []
        bi = si = 0
        bleft, sleft = bfills[0][1], sfills[0][1]
        while bi < len(bfills) and si < len(sfills):
            buyer, seller = bfills[bi][0], sfills[si][0]
            quantity = min(bleft, sleft)
            if buyer.agent_id == seller.agent_id:
                raise ValueError("crossing orders from the same agent are not allowed")
            trades.append(Trade(rnd, buyer.agent_id, seller.agent_id, quantity, price))
            bleft -= quantity
            sleft -= quantity
            if bleft == 0:
                bi += 1
                if bi < len(bfills):
                    bleft = bfills[bi][1]
            if sleft == 0:
                si += 1
                if si < len(sfills):
                    sleft = sfills[si][1]
        return price, trades, unmatched - 2 * matched

    def quote_statistics(self, orders):
        """Submitted limit quotes before clearing; a batch may have crossed quotes.

        This is a quote snapshot, not a continuous-book effective spread. Market
        orders contribute to volume/fill rate but do not define a limit quote.
        """
        active = [self._normalise(o) for o in orders if o.quantity > 0 and o.side != "hold"]
        bids = [o.limit_price for o in active if o.side == "buy" and o.limit_price is not None]
        asks = [o.limit_price for o in active if o.side == "sell" and o.limit_price is not None]
        best_bid, best_ask = max(bids, default=None), min(asks, default=None)
        return {"best_bid": best_bid, "best_ask": best_ask,
                "quoted_spread": None if best_bid is None or best_ask is None else best_ask - best_bid,
                "submitted_quantity": sum(o.quantity for o in active)}


def settle(trades, agents, market):
    """Preflight a batch; reserve resources from pre-auction portfolios.

    Unreceived proceeds cannot finance buys, nor can unreceived shares be sold.
    Buyer transaction tax is included in acquisition cost.
    """
    trades = list(trades)
    spending = {aid: 0.0 for aid in agents}
    selling = {aid: 0 for aid in agents}
    cash_changes = {aid: [] for aid in agents}
    total_cash = math.fsum(a.cash for a in agents.values()) + market.tax_collected
    total_shares = sum(a.shares for a in agents.values())
    taxes = []
    for trade in trades:
        if trade.buyer_id not in agents or trade.seller_id not in agents:
            raise ValueError("trade refers to an unknown agent")
        if trade.buyer_id == trade.seller_id:
            raise ValueError("self trades are not allowed")
        if (isinstance(trade.quantity, bool) or
                not isinstance(trade.quantity, Integral) or trade.quantity <= 0 or
                not math.isfinite(trade.price) or trade.price <= 0):
            raise ValueError("trade quantity/price is invalid")
        gross = trade.quantity * trade.price
        tax = gross * market.transaction_tax
        spending[trade.buyer_id] += gross + tax
        selling[trade.seller_id] += trade.quantity
        cash_changes[trade.buyer_id].append(-gross - tax)
        cash_changes[trade.seller_id].append(gross - tax)
        taxes.append(2 * tax)
    for aid, agent in agents.items():
        if spending[aid] > agent.cash + 1e-8 or selling[aid] > agent.shares:
            raise ValueError(f"settlement would exceed {aid}'s cash or shares")
    for trade in trades:
        buyer, seller = agents[trade.buyer_id], agents[trade.seller_id]
        buyer._add_shares(trade.quantity, trade.price * (1 + market.transaction_tax))
        seller._add_shares(-trade.quantity, trade.price)
        buyer.record_trade(trade, is_buyer=True)
        seller.record_trade(trade, is_buyer=False)
    for aid, agent in agents.items():
        agent.cash = max(0.0, agent.cash + math.fsum(cash_changes[aid]))
    market.tax_collected += math.fsum(taxes)
    cash_after = math.fsum(a.cash for a in agents.values()) + market.tax_collected
    if (sum(a.shares for a in agents.values()) != total_shares or
            not math.isclose(cash_after, total_cash, rel_tol=1e-12, abs_tol=1e-7)):
        raise RuntimeError("settlement conservation invariant failed")
