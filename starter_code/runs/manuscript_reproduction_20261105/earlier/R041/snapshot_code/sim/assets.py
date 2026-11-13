"""Per-round cash flows and explicit stationary-regime valuation benchmarks.

In iid_permanent, d_t = mean_t * U(1-noise, 1+noise). All regime shifts are
permanent. mean_t/r is a risk-neutral stationary-regime benchmark, assuming
no anticipation of future unannounced events, no risk premium, and no tax.

legacy_ar1 retains the old clipped AR process and its approximate mean/r
benchmark, including temporary effects. It is not the new research baseline.
"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
import math

import numpy as np


class Asset:
    def __init__(self, cfg, rng: np.random.Generator, news_events=None):
        cfg = asdict(cfg) if is_dataclass(cfg) else cfg
        self.rng = rng
        d = cfg.get("dividend", {})
        inferred = "legacy_ar1" if set(d) & {"rho", "sigma"} else "iid_permanent"
        self.model = cfg.get("model", inferred)
        if self.model not in ("iid_permanent", "legacy_ar1"):
            raise ValueError("unsupported asset model")
        self.ticker = cfg.get("ticker", "KGP")
        self.dbar_base = d.get("mean", 1.0 if self.model == "legacy_ar1" else 0.02)
        self.risk_free = cfg.get("risk_free", 0.01 if self.model == "legacy_ar1" else 0.0002)
        if not math.isfinite(self.risk_free) or self.risk_free <= 0:
            raise ValueError("risk_free must be finite and positive")
        if not math.isfinite(self.dbar_base) or self.dbar_base <= 0:
            raise ValueError("dividend mean must be finite and positive")
        if self.model == "legacy_ar1":
            self.rho, self.sigma = d.get("rho", 0.6), d.get("sigma", 0.3)
            if not -1 < self.rho < 1 or not math.isfinite(self.sigma) or self.sigma < 0:
                raise ValueError("invalid legacy dividend parameters")
        else:
            self.relative_noise = d.get("relative_noise", 0.2)
            if not 0 <= self.relative_noise <= 1:
                raise ValueError("relative_noise must lie in [0, 1]")
        events = cfg.get("news", []) if news_events is None else news_events
        self.news_events = [dict(asdict(e) if is_dataclass(e) else e) for e in (events or [])]
        for event in self.news_events:
            if type(event.get("announce", True)) is not bool:
                raise ValueError("event announce must be true or false")
            headline = event.get("headline")
            if event.get("announce", True) or headline is not None:
                if not isinstance(headline, str) or not headline.strip():
                    raise ValueError("announced events require a nonempty headline; hidden labels must be nonempty if supplied")
        self.last_dividend = self.dbar_base
        self.active_effects = []
        self.round_events = []  # Researcher audit only; never part of observations.
        self.round = self._paid_round = 0

    def dbar(self, rnd):
        multiplier = 1.0
        for effect in self.active_effects:
            until = effect["until_round"]
            if until is None or rnd < until:
                multiplier *= effect["mult"]
        return self.dbar_base * multiplier

    def fundamental(self, rnd):
        return self.dbar(rnd) / self.risk_free

    @property
    def benchmark_kind(self):
        return ("stationary_regime_risk_neutral" if self.model == "iid_permanent"
                else "legacy_perpetuity_approximation")

    def open_round(self, rnd):
        """Apply events and return public headlines only, before the dividend draw."""
        if rnd != self.round + 1 or self._paid_round != self.round:
            raise ValueError("rounds must open sequentially after the preceding payout")
        self.round = rnd
        headlines = []
        self.round_events = []
        for event_index, event in enumerate(self.news_events):
            if event["round"] == rnd:
                mean_before = self.dbar(rnd)
                announce = event.get("announce", True)
                if announce:
                    headlines.append(event["headline"])
                effect = event.get("effect")
                if effect:
                    duration = effect.get("duration")
                    if self.model == "iid_permanent" and duration is not None:
                        raise ValueError("iid_permanent does not support temporary shocks")
                    self.active_effects.append({
                        "mult": effect.get("dbar_mult", 1.0),
                        "until_round": None if duration is None else rnd + duration})
                self.round_events.append({
                    "round": rnd, "event_index": event_index, "announce": announce,
                    "configured_headline": event.get("headline"),
                    "public_headline": event.get("headline") if announce else None,
                    "effect": effect, "dividend_mean_before": mean_before,
                    "dividend_mean_after": self.dbar(rnd),
                    "regime_benchmark_before": mean_before / self.risk_free,
                    "regime_benchmark_after": self.fundamental(rnd),
                    "audit_scope": "researcher_only; state at round open, before decisions and current payout"})
        return headlines

    def draw_dividend(self):
        """Draw once after the auction; closing holders receive this payout."""
        if self.round == self._paid_round:
            raise ValueError("open a new round before drawing another dividend")
        mean = self.dbar(self.round)
        if self.model == "iid_permanent":
            dividend = mean * (1 + self.rng.uniform(-self.relative_noise, self.relative_noise))
        else:
            dividend = max(0.0, mean + self.rho * (self.last_dividend - mean)
                           + self.sigma * self.rng.normal())
        if not math.isfinite(dividend) or dividend < 0:
            raise ValueError("dividend process produced an invalid payout")
        self.last_dividend = float(dividend)
        self._paid_round = self.round
        return self.last_dividend

    def step(self, rnd):
        """Compatibility helper: open a round and immediately draw its payout."""
        headlines = self.open_round(rnd)
        return self.draw_dividend(), headlines
