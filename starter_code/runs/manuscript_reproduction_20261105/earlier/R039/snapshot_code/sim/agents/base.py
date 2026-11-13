"""Portfolio bookkeeping and a pluggable decide(obs) interface.

Single orders remain supported; liquidity providers may return one quote per side.
"""
from __future__ import annotations
from dataclasses import dataclass
import math
from numbers import Integral, Real
import numpy as np
from sim.market import Order, Trade


@dataclass
class Observation:
    round: int
    total_rounds: int
    price_history: list
    last_volume: int
    last_dividend: float
    risk_free_rate: float
    fundamental_hint: float | None
    news: list
    bbs_posts: list
    my_cash: float
    my_shares: int
    my_avg_cost: float
    my_wealth: float
    my_recent_trades: list
    round_unit: str = "trading_session"


class Agent:
    def __init__(self, agent_id: str, cash: float, shares: int,
                 rng: np.random.Generator, params: dict | None = None, *,
                 initial_price=100.0, initial_cost=None,
                 transaction_tax=0.0, price_band=0.2):
        self.agent_id = agent_id
        self.cash = float(cash)
        self.shares = int(shares)
        if (not math.isfinite(self.cash) or self.cash < 0 or
                isinstance(shares, bool) or not isinstance(shares, Integral) or shares < 0):
            raise ValueError("initial cash/shares must be nonnegative and finite")
        basis = initial_price if initial_cost is None else initial_cost
        if not math.isfinite(basis) or basis < 0:
            raise ValueError("initial share cost must be finite and nonnegative")
        if not 0 <= transaction_tax < 1 or not 0 <= price_band < 1:
            raise ValueError("invalid tax or price band")
        self.avg_cost = float(basis) if self.shares else 0.0
        self.transaction_tax = transaction_tax
        self.price_band = price_band
        self.rng = rng
        self.params = params or {}
        self.recent_trades: list[str] = []

    # -- portfolio bookkeeping ------------------------------------------------
    def _add_shares(self, q: int, price: float):
        if q > 0:
            tot = self.avg_cost * self.shares + price * q
            self.shares += q
            self.avg_cost = tot / self.shares if self.shares else 0.0
        else:
            self.shares += q
            if self.shares == 0:
                self.avg_cost = 0.0

    def record_trade(self, t: Trade, is_buyer: bool):
        verb = "bought" if is_buyer else "sold"
        self.recent_trades.append(
            f"r{t.round}: {verb} {t.quantity} @ {t.price:.2f}")
        self.recent_trades = self.recent_trades[-5:]

    def pay_dividend(self, d: float, r: float):
        """Pay closing shares and post-settlement cash, without intra-round compounding."""
        if not math.isfinite(d) or d < 0 or not math.isfinite(r) or r < 0:
            raise ValueError("cash-flow inputs must be finite and nonnegative")
        dividend_income, interest_income = self.shares * d, self.cash * r
        new_cash = self.cash + dividend_income + interest_income
        if not math.isfinite(new_cash):
            raise ValueError("cash-flow update would overflow the account")
        self.cash = new_cash
        return dividend_income, interest_income

    def wealth(self, price: float) -> float:
        return self.cash + self.shares * price

    # -- brain ---------------------------------------------------------------
    def decide(self, obs: Observation) -> Order | list[Order]:  # pragma: no cover
        raise NotImplementedError

    def validate_orders(self, decisions, last_price):
        """Reserve aggregate cash/shares for at most one buy and one sell quote.

        Separate reservations prevent unreceived sale proceeds from funding buys.
        Two-sided quoting is supported; an agent may not cross its own quotes.
        """
        orders = [decisions] if isinstance(decisions, Order) else decisions
        if not isinstance(orders, list) or not orders or not all(isinstance(o, Order) for o in orders):
            raise ValueError("decide must return an Order or a nonempty list of Orders")
        remaining_cash, remaining_shares = self.cash, self.shares
        checked, seen = [], set()
        for order in orders:
            if order.agent_id != self.agent_id:
                raise ValueError("order agent ID differs from its submitting agent")
            if order.side in ("buy", "sell"):
                if order.side in seen:
                    raise ValueError("only one quote per side per agent is supported")
                seen.add(order.side)
            order = self.validate(order, last_price)
            requested = order.quantity
            if order.side == "buy":
                ceiling = last_price * (1 + self.price_band)
                reference = min(order.limit_price, ceiling) if order.limit_price is not None else ceiling
                unit_cost = reference * (1 + self.transaction_tax)
                order.quantity = min(order.quantity, math.floor(remaining_cash / unit_cost + 1e-12))
                remaining_cash -= order.quantity * unit_cost
            elif order.side == "sell":
                order.quantity = min(order.quantity, remaining_shares)
                remaining_shares -= order.quantity
            if order.quantity != requested:
                order.validation_note = "quantity_reduced_to_reserved_resources"
            if order.quantity == 0:
                order.side = "hold"
            checked.append(order)
        buys = [o for o in checked if o.side == "buy"]
        sells = [o for o in checked if o.side == "sell"]
        if buys and sells and (buys[0].limit_price is None or sells[0].limit_price is None or
                               buys[0].limit_price >= sells[0].limit_price):
            raise ValueError("an agent's buy and sell quotes must not cross")
        return checked

    def validate(self, order: Order, last_price: float) -> Order:
        """Scale feasible quantities; turn invalid inputs into an auditable HOLD.

        Reserve buys at their maximum execution price including transaction tax.
        The engine rechecks all orders, including orders from rule agents.
        """
        def hold(note):
            order.side, order.quantity, order.limit_price = "hold", 0, None
            order.validation_note = note
            return order

        if order.side not in ("buy", "sell", "hold"):
            return hold("invalid_side")
        if (isinstance(order.quantity, bool) or
                not isinstance(order.quantity, Integral) or order.quantity < 0):
            return hold("invalid_quantity")
        if order.limit_price is not None and (
                isinstance(order.limit_price, bool) or
                not isinstance(order.limit_price, Real) or
                not math.isfinite(order.limit_price) or order.limit_price <= 0):
            return hold("invalid_limit_price")
        if order.side == "hold":
            return hold(order.validation_note)
        if not math.isfinite(last_price) or last_price <= 0:
            raise ValueError("last price must be finite and positive")
        requested = order.quantity
        if order.side == "sell":
            order.quantity = max(0, min(order.quantity, self.shares))
        elif order.side == "buy":
            ceiling = last_price * (1 + self.price_band)
            ref = min(order.limit_price, ceiling) if order.limit_price is not None else ceiling
            afford = math.floor(self.cash / (ref * (1 + self.transaction_tax)) + 1e-12)
            order.quantity = max(0, min(order.quantity, afford))
        order.quantity = int(order.quantity)
        if order.quantity != requested:
            order.validation_note = "quantity_reduced_to_resources"
        if order.quantity == 0:
            order.side = "hold"
        return order
