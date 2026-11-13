"""Rule-based agents. Params use the same attribute vocabulary as parametric
(ODE-style) agents: aggressiveness, risk_aversion, horizon, activity_prob."""
from __future__ import annotations
from collections import deque
from sim.agents.base import Agent, Observation
from sim.market import Order


class ZeroIntelligenceAgent(Agent):
    """Gode & Sunder (1993): random orders under budget constraint."""
    def decide(self, obs: Observation) -> Order:
        if self.rng.random() > self.params.get("activity_prob", 0.8):
            return Order(self.agent_id, "hold", round=obs.round)
        p = obs.price_history[-1]
        side = "buy" if self.rng.random() < 0.5 else "sell"
        limit = p * self.rng.uniform(0.9, 1.1)
        qty = int(self.rng.integers(1, 11))
        return self.validate(Order(self.agent_id, side, qty, limit, obs.round,
                                   "random (ZI)"), p)


class FundamentalistAgent(Agent):
    """Demand ~ k*(F - P): the ODE-agent analogue. Trades toward fundamental."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.dividend_window = self.params.get("dividend_window", 1)
        if type(self.dividend_window) is not int or self.dividend_window < 1:
            raise ValueError("dividend_window must be a positive integer")
        self._past_dividends = deque(maxlen=self.dividend_window)
        self._last_observed_round = 0

    def decide(self, obs: Observation) -> Order:
        # Round 1's initial reference is not an executed payout. Thereafter,
        # observe each previous payout once, including if decide is repeated.
        if obs.round > self._last_observed_round:
            if obs.round > 1:
                self._past_dividends.append(obs.last_dividend)
            self._last_observed_round = obs.round
        estimate = (sum(self._past_dividends) / len(self._past_dividends)
                    if self.dividend_window > 1 and self._past_dividends else obs.last_dividend)
        p = obs.price_history[-1]
        f = obs.fundamental_hint if obs.fundamental_hint is not None else \
            estimate / max(obs.risk_free_rate, 1e-9)
        delta = self.params.get("delta", 0.05)
        k = self.params.get("aggressiveness", 0.5)
        mis = (f - p) / max(p, 1e-9)
        if abs(mis) < delta:
            return Order(self.agent_id, "hold", round=obs.round)
        qty = max(1, int(abs(mis) * k * 100))
        if mis > 0:
            return self.validate(Order(self.agent_id, "buy", qty,
                                       p * (1 + min(0.05, mis / 2)), obs.round,
                                       f"underpriced vs F={f:.1f}"), p)
        return self.validate(Order(self.agent_id, "sell", qty,
                                   p * (1 + max(-0.05, mis / 2)), obs.round,
                                   f"overpriced vs F={f:.1f}"), p)


class MomentumAgent(Agent):
    """Extrapolates recent trend (chartist, Brock–Hommes style)."""
    def decide(self, obs: Observation) -> Order:
        w = self.params.get("window", 5)
        hist = obs.price_history
        if len(hist) <= w:
            return Order(self.agent_id, "hold", round=obs.round)
        p, trend = hist[-1], (hist[-1] - hist[-1 - w]) / hist[-1 - w]
        k = self.params.get("aggressiveness", 0.5)
        if abs(trend) < 0.005:
            return Order(self.agent_id, "hold", round=obs.round)
        qty = max(1, int(abs(trend) * k * 200))
        if trend > 0:
            return self.validate(Order(self.agent_id, "buy", qty, p * 1.02,
                                       obs.round, f"uptrend {trend:+.1%}"), p)
        return self.validate(Order(self.agent_id, "sell", qty, p * 0.98,
                                   obs.round, f"downtrend {trend:+.1%}"), p)


class MarketMakerAgent(Agent):
    """Two-sided quotes with finite cash and a hard share inventory cap.

    spread is a half-spread; inventory_skew shifts the quote center downward
    above inventory_target and upward below it. It does not guarantee a fill.
    """
    def decide(self, obs: Observation) -> list[Order]:
        p = obs.price_history[-1]
        s = self.params.get("spread", 0.02)
        inv_limit = self.params.get("inventory_limit", 200)
        qty = self.params.get("quote_size", 10)
        target = self.params.get("inventory_target", inv_limit // 2)
        skew = self.params.get("inventory_skew", 0.02)
        pressure = max(-1.0, min(1.0, (self.shares - target) / max(1, inv_limit)))
        center = p * (1 - skew * pressure)
        orders = []
        buy_qty = min(qty, max(0, inv_limit - self.shares))
        sell_qty = min(qty, self.shares)
        if buy_qty:
            orders.append(Order(self.agent_id, "buy", buy_qty, center * (1 - s), obs.round, "MM bid"))
        if sell_qty:
            orders.append(Order(self.agent_id, "sell", sell_qty, center * (1 + s), obs.round, "MM ask"))
        return self.validate_orders(orders or [Order(self.agent_id, "hold", round=obs.round)], p)


RULE_AGENTS = {
    "zero_intelligence": ZeroIntelligenceAgent,
    "fundamentalist": FundamentalistAgent,
    "momentum": MomentumAgent,
    "market_maker": MarketMakerAgent,
}
