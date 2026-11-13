"""Comparable A/B/C traders: raw facts, derived facts, optional reflection.

Executed outcomes are authoritative Python records. Reflection is a model's
fallible interpretation; it never edits those records or the portfolio.
"""
from __future__ import annotations

import json
import math
import re
import ssl
import time
from urllib.error import HTTPError, URLError

from sim.agents.base import Agent, Observation
from sim.market import Order
from sim.llm.client import retry_after_metadata
from sim.llm.usage import OutputLimitExceeded, ProviderUnavailable, UsageBudget, UsageLimitExceeded

PROMPT_VERSION = "comparable_agents_v2_disclosed_rules"
CONDITION_VERSIONS = {"A": "simple_A_v2", "B": "facts_B_v2", "C": "reflection_C_v2"}
TRANSPORT_POLICY_VERSION = "budgeted_delivery_v2_optional_503"

MARKET_RULES_TEMPLATE = """Exchange rules (common to every trader): price tick {tick}; fractional price band {band}; transaction tax rate {tax} on each side of an executed trade.
Let P be the last closing price. Execution prices must be tick multiples within [P*(1-band), P*(1+band)].
Buy limits round DOWN to the tick; sell limits round UP. A limit outside the executable band may remain unfilled.
Cash reservation is deliberately conservative and uses RAW prices BEFORE tick rounding:
U=P*(1+band). For a market buy (limit_price null), reserve q*U*(1+tax).
For a limit buy at submitted L, reserve q*min(L,U)*(1+tax).
The maximum accepted buy quantity is floor(cash / reserved_cost_per_share); the maximum sell quantity is your current shares.
Oversized quantities are reduced, or become HOLD if zero shares are affordable/available. Execution may be partial or absent even for an accepted order.
On a fill at price p, a buyer pays q*p*(1+tax) and a seller receives q*p*(1-tax).
Sale proceeds and new dividends/interest cannot fund orders in the same auction. An order request or acceptance is not an executed trade."""


def market_rules_prompt(tick, band, tax):
    return MARKET_RULES_TEMPLATE.format(tick=tick, band=band, tax=tax)

SYSTEM_TEMPLATE = """You are {name}, a {age}-year-old {occupation} trading stocks with your personal savings.
Profile: risk tolerance {risk}; style {style}; horizon {horizon}. {backstory} {biases}
You trade shares of {ticker} on a simulated exchange. Each round is one {round_unit}.
The exchange batches all orders and clears at one price. No short selling, no borrowing:
you can only sell shares you own and spend cash you have. limit_price is in currency units
(e.g. 101.5), or null to accept the clearing price.
{market_rules}
After the auction, holders receive the dividend; remaining cash earns interest.
The interest rate quoted below is per round. Dividend income earns interest from the next round.
The stock continues beyond the recorded episode; shares do not expire at its end.
End-of-run wealth includes the shares valued at the last auction price.
Respond ONLY with a JSON object, no other text:
{{"action": "buy"|"sell"|"hold", "quantity": <int >= 0>, "limit_price": <number or null>, "reasoning": "<1-2 sentences in character>"}}"""

USER_TEMPLATE = """Round {rnd}/{total}. Recent auction closing prices (old to new): {hist}
Previous round: volume {vol}, dividend paid {div} per share. Risk-free rate: {r} per round.
{news}{bbs}{fund}Your account: cash {cash}, shares {shares} (avg cost {avg}), total wealth {wealth}.
Your recent trades: {trades}
Your recent verified outcomes: {memory}
{facts}{diary}Decide your order for today. Remember: JSON only."""

REFLECTION_TEMPLATE = """You are {name}, reflecting on your own trading experience.
Your stable profile: risk {risk}; style {style}; horizon {horizon}. {biases}
Use only the verified records below for facts. Distinguish Observations, Beliefs,
and Plan. An order request is not an executed trade. Do not invent fills, future
events, or unavailable fundamentals. You may revise beliefs; do not rewrite the
facts or your stable profile. Write under 120 words in first person."""


class LLMAgent(Agent):
    def __init__(self, agent_id, cash, shares, rng, params=None,
                 persona=None, client=None, temperature=0.7, log_fn=None,
                 initial_price=100.0, initial_cost=None, transaction_tax=0.0,
                 price_band=0.2, budget=None, input_price=0.0, output_price=0.0):
        super().__init__(agent_id, cash, shares, rng, params,
                         initial_price=initial_price, initial_cost=initial_cost,
                         transaction_tax=transaction_tax, price_band=price_band)
        self.persona = persona or {}
        self.client = client
        self.temperature = temperature
        self.condition = self.params.get("condition", "C" if self.params.get("reflect_every", 0) else "A")
        if self.condition not in CONDITION_VERSIONS:
            raise ValueError("condition must be A, B, or C")
        self.memory_window = self.params.get("memory_window", 10)
        self.reflect_every = self.params.get("reflect_every", 10 if self.condition == "C" else 0)
        if self.condition != "C" and self.reflect_every:
            raise ValueError("only condition C reflects")
        if self.memory_window < 1 or (self.condition == "C" and not 0 < self.reflect_every <= self.memory_window):
            raise ValueError("invalid memory/reflection window")
        self.budget = budget if budget is not None else UsageBudget()
        self.input_price, self.output_price = input_price, output_price
        self.diary = ""
        self.memory = []
        self.log_fn = log_fn or (lambda record: None)
        self.parse_failures = self.api_failures = self.reflection_failures = 0
        self.output_truncations = 0
        self.transport_retry_limit = self.params.get("transport_retries", 0)
        if type(self.transport_retry_limit) is not int or self.transport_retry_limit not in (0, 1):
            raise ValueError("transport_retries must be 0 or 1")
        self.transport_retries = self.json_repairs = 0
        self.retry_http_503 = self.params.get("retry_http_503", False)
        if type(self.retry_http_503) is not bool or (self.retry_http_503 and self.transport_retry_limit != 1):
            raise ValueError("retry_http_503 requires transport_retries: 1")
        self.server_retries = 0
        self.last_intent = None
        self._last_reflected_round = 0

    def system_prompt(self, ticker):
        p = self.persona
        return SYSTEM_TEMPLATE.format(
            name=p.get("name", self.agent_id), age=p.get("age", 35),
            occupation=p.get("occupation", "professional"),
            risk=p.get("risk_tolerance", "medium"),
            style=p.get("strategy_inclination", "balanced"),
            horizon=p.get("horizon", "medium"), backstory=p.get("backstory", ""),
            biases=p.get("bias_clauses", ""), ticker=ticker,
            market_rules=market_rules_prompt(self.params.get("tick", 0.1), self.price_band, self.transaction_tax),
            round_unit=self.params.get("round_unit", "trading_session").replace("_", " "))

    def factual_summary(self, obs):
        price = obs.price_history[-1]
        lookback = min(5, len(obs.price_history) - 1)
        result = {
            "price_change_lookback_rounds": lookback,
            "price_change_pct": None if not lookback else 100 * (price / obs.price_history[-1-lookback] - 1),
            "stock_weight_pct": None if obs.my_wealth <= 0 else 100 * obs.my_shares * price / obs.my_wealth,
            "unrealized_gain_loss_amount": obs.my_shares * (price - obs.my_avg_cost),
            "previous_dividend_yield_pct": 100 * obs.last_dividend / price,
            "cash_interest_pct_per_round": 100 * obs.risk_free_rate}
        if obs.fundamental_hint is not None and obs.fundamental_hint > 0:
            result["price_gap_vs_disclosed_value_pct"] = 100 * (price / obs.fundamental_hint - 1)
        if self.memory:
            result["last_executed_buy_quantity"] = self.memory[-1]["executed_buy_quantity"]
            result["last_executed_sell_quantity"] = self.memory[-1]["executed_sell_quantity"]
        return result

    def user_prompt(self, obs):
        news = f"News today: {'; '.join(obs.news)}\n" if obs.news else ""
        bbs = f"Forum posts: {' | '.join(obs.bbs_posts)}\n" if obs.bbs_posts else ""
        fund = f"Analyst fair-value estimate: {obs.fundamental_hint:.8g}\n" if obs.fundamental_hint is not None else ""
        facts = ""
        if self.condition in ("B", "C"):
            facts = ("Computed facts (derived from the same observations, no recommendation): "
                     + json.dumps(self.factual_summary(obs), allow_nan=False) + "\n")
        diary = f"Your reflection (beliefs may be wrong): {self.diary}\n" if self.condition == "C" and self.diary else ""
        return USER_TEMPLATE.format(
            rnd=obs.round, total=obs.total_rounds, hist=obs.price_history,
            vol=obs.last_volume, div=obs.last_dividend, r=obs.risk_free_rate,
            news=news, bbs=bbs, fund=fund, cash=obs.my_cash, shares=obs.my_shares,
            avg=obs.my_avg_cost, wealth=obs.my_wealth,
            trades="; ".join(obs.my_recent_trades) or "none",
            memory=json.dumps(self.memory, allow_nan=False), facts=facts, diary=diary)

    @staticmethod
    def _extract_json(text):
        if not isinstance(text, str):
            return None
        fence = chr(96) * 3
        for candidate in (text, re.sub("^" + fence + "(json)?|" + fence + "$", "", text.strip(), flags=re.M),
                          text[text.find("{"): text.rfind("}") + 1]):
            try:
                result = json.loads(candidate)
                if isinstance(result, dict):
                    return result
            except (ValueError, TypeError):
                continue
        return None

    def _request(self, messages, rnd, kind, attempt=1, *, temperature=None, json_mode=True):
        retry_category = None
        for transport_attempt in range(1, self.transport_retry_limit + 2):
            raw, meta = self._request_once(messages, rnd, kind, attempt,
                temperature=temperature, json_mode=json_mode, transport_attempt=transport_attempt,
                allow_transport_retry=transport_attempt <= self.transport_retry_limit, retry_category=retry_category)
            if not meta.get("transport_retry_planned"):
                return raw, meta
            # Shared pacing is applied again after a separately budgeted retry.
            retry_category = meta["retry_category"]
            time.sleep(meta["retry_wait_seconds"])

    def _request_once(self, messages, rnd, kind, attempt=1, *, temperature=None, json_mode=True,
                      transport_attempt=1, allow_transport_retry=False, retry_category=None):
        group_id = f"{self.agent_id}:{rnd}:{kind}:{attempt}"
        meta = {"call_id": group_id if transport_attempt == 1 else group_id + f":transport{transport_attempt}",
                "request_group_id": group_id, "json_attempt": attempt,
                "transport_attempt": transport_attempt, "transport_policy_version": TRANSPORT_POLICY_VERSION,
                "attempt_kind": ("server_retry" if retry_category == "server_503" else "transport_retry") if transport_attempt > 1 else "json_repair" if kind == "decision" and attempt > 1 else "initial",
                "messages": [dict(m) for m in messages], "call_type": kind,
                "temperature": self.temperature if temperature is None else temperature,
                "max_tokens": self.params.get("max_tokens", 300), "json_mode": json_mode,
                "reasoning_effort": getattr(self.client, "reasoning_effort", None),
                "input_usd_per_million": self.input_price, "output_usd_per_million": self.output_price}
        meta["temperature_sent"] = meta["temperature"] if getattr(self.client, "send_temperature", True) else None
        started = time.perf_counter()
        try:
            meta["reservation"] = self.budget.reserve(
                messages, meta["max_tokens"], self.input_price, self.output_price)
            meta["pacing_wait_seconds"] = self.budget.pacer.acquire(
                meta["reservation"]["input_token_estimate"])
            self.budget.ensure_provider_available()
        except (UsageLimitExceeded, ProviderUnavailable) as exc:
            self.log_fn({"record_type": "request_blocked", "agent_id": self.agent_id,
                         "round": rnd, "condition": self.condition,
                         "prompt_version": CONDITION_VERSIONS[self.condition],
                         "call_type": kind, "reason": str(exc), "attempts": [meta]})
            raise
        request_started = time.perf_counter()
        if transport_attempt > 1:
            if retry_category == "server_503":
                self.server_retries += 1
            else:
                self.transport_retries += 1
        elif kind == "decision" and attempt > 1:
            self.json_repairs += 1
        if hasattr(self.client, "last_usage"):
            self.client.last_usage = None
        raw = None
        try:
            raw = self.client.chat(messages, temperature=meta["temperature"],
                                   max_tokens=meta["max_tokens"], json_mode=json_mode)
            meta["status"] = "returned"
        except Exception as exc:
            meta["status"], meta["error_type"] = "error", type(exc).__name__
            reason = getattr(exc, "reason", None)
            meta["transport_diagnostics"] = {"reason_type": type(reason).__name__ if reason is not None else None}
            for name in ("errno", "winerror"):
                code = getattr(reason, name, getattr(exc, name, None))
                if type(code) is int:
                    meta["transport_diagnostics"][name] = code
            eligible = (not isinstance(exc, HTTPError)
                        and isinstance(exc, (URLError, TimeoutError, ConnectionError))
                        and not isinstance(exc, ssl.SSLCertVerificationError)
                        and not isinstance(reason, ssl.SSLCertVerificationError))
            category = "transport"
            delay = 2
            if isinstance(exc, HTTPError) and exc.code == 503 and self.retry_http_503:
                header = retry_after_metadata(exc.headers)
                meta["retry_after"] = header
                provider_error = getattr(self.client, "last_error_metadata", {})
                quota_or_auth = (bool(provider_error.get("quota_violations")) or
                    str(provider_error.get("provider_status", "")).upper() in
                    ("RESOURCE_EXHAUSTED", "UNAUTHENTICATED", "PERMISSION_DENIED"))
                eligible = (not quota_or_auth and (not header["retry_after_present"] or
                    (header["retry_after_valid"] and header["retry_after_seconds"] <= 60)))
                category = "server_503"
                delay = max(10, header.get("retry_after_seconds") or 0)
            meta["transport_retry_planned"] = bool(allow_transport_retry and eligible)
            if meta["transport_retry_planned"]:
                meta.update(retry_category=category, retry_wait_seconds=delay)
            if not meta["transport_retry_planned"]:
                self.budget.stop_for_provider_error()
            if isinstance(getattr(exc, "code", None), int):
                meta["http_status"] = exc.code
        meta["latency_seconds"] = time.perf_counter() - started
        meta["provider_latency_seconds"] = time.perf_counter() - request_started
        meta["raw"] = raw
        meta["usage"] = getattr(self.client, "last_usage", None)
        meta["response_metadata"] = dict(getattr(self.client, "last_response_metadata", {}))
        if meta["status"] == "error":
            meta["provider_error"] = dict(getattr(self.client, "last_error_metadata", {}))
        meta["observed_cost_estimate_usd"] = self.budget.record(
            meta["usage"], meta["status"] == "returned", self.input_price, self.output_price)
        # Persist each response immediately, even if a later repair is blocked
        # or the surrounding decision/round never finishes.
        self.log_fn({"record_type": "model_call", "agent_id": self.agent_id,
                     "round": rnd, "condition": self.condition,
                     "prompt_version": CONDITION_VERSIONS[self.condition], **meta})
        if meta["response_metadata"].get("finish_reason") == "length":
            self.output_truncations += 1
            if self.budget.stop_on_api_error:
                raise OutputLimitExceeded("provider output cap exhausted; partial reply preserved; no same-cap retry")
        if meta["status"] == "error" and self.budget.stop_on_api_error and not meta.get("transport_retry_planned"):
            self.api_failures += 1
            raise ProviderUnavailable("provider request failed" +
                                      (f" (HTTP {meta['http_status']})" if "http_status" in meta else ""))
        return raw, meta

    @staticmethod
    def _attempt_refs(attempts):
        return [{k: v for k, v in attempt.items() if k not in ("messages", "raw")}
                for attempt in attempts]

    def decide(self, obs):
        messages = [{"role": "system", "content": self.system_prompt(self.params.get("ticker", "KGP"))},
                    {"role": "user", "content": self.user_prompt(obs)}]
        order, raw, failure = None, "", None
        attempts = []
        self.last_intent = None
        for attempt in range(1, 3):
            raw, call = self._request(messages, obs.round, "decision", attempt)
            attempts.append(call)
            if call["status"] == "error":
                self.api_failures += 1
                failure = "api_failed"
                break
            if call["response_metadata"].get("finish_reason") == "length":
                failure = "output_truncated"
                break
            parsed = self._extract_json(raw)
            error = "response must be a JSON object with buy, sell, or hold action"
            if parsed and parsed.get("action") in ("buy", "sell", "hold"):
                try:
                    qty = parsed.get("quantity")
                    if type(qty) is not int or qty < 0:
                        raise ValueError("quantity must be a nonnegative integer")
                    limit = parsed.get("limit_price")
                    if limit is not None:
                        if type(limit) not in (int, float) or not math.isfinite(limit) or limit <= 0:
                            raise ValueError("limit_price must be positive and finite, or null")
                        limit = float(limit)
                    order = Order(self.agent_id, parsed["action"], qty, limit, obs.round,
                                  str(parsed.get("reasoning", ""))[:400])
                    self.last_intent = dict(order.__dict__)
                    break
                except (TypeError, ValueError) as exc:
                    error = str(exc)
            call["validation_error"] = error
            messages.extend([{"role": "assistant", "content": raw if isinstance(raw, str) else str(raw)},
                             {"role": "user", "content": f"Your reply was invalid: {error}. Reply with ONLY the JSON object."}])
        if order is None:
            if failure is None:
                self.parse_failures += 1
                failure = "parse_failed"
            order = Order(self.agent_id, "hold", round=obs.round, reasoning=failure)
            self.last_intent = dict(order.__dict__)
        order = self.validate(order, obs.price_history[-1])
        self.log_fn({"record_type": "decision", "call_type": "decision",
                     "agent_id": self.agent_id, "round": obs.round,
                     "condition": self.condition, "prompt_version": CONDITION_VERSIONS[self.condition],
                     "system_prompt": messages[0]["content"], "prompt": messages[1]["content"],
                     "raw": raw, "intent": self.last_intent, "parsed": dict(order.__dict__),
                     "attempts": self._attempt_refs(attempts), "failure_type": failure})
        return order

    def end_round(self, obs, order, price, *, fills=(), dividend_income=0.0,
                  interest_income=0.0, opening_wealth=None, reflect=True):
        own_fills = []
        for trade in fills:
            if trade.buyer_id == self.agent_id:
                own_fills.append({"side": "buy", "quantity": trade.quantity, "price": trade.price})
            elif trade.seller_id == self.agent_id:
                own_fills.append({"side": "sell", "quantity": trade.quantity, "price": trade.price})
        outcome = {"round": obs.round, "price": price,
                   "requested_order": dict(self.last_intent or order.__dict__),
                   "accepted_order": dict(order.__dict__),
                   "executed_buy_quantity": sum(t["quantity"] for t in own_fills if t["side"] == "buy"),
                   "executed_sell_quantity": sum(t["quantity"] for t in own_fills if t["side"] == "sell"),
                   "fills": own_fills, "cash": self.cash, "shares": self.shares,
                   "avg_cost": self.avg_cost, "wealth": self.wealth(price),
                   "dividend_income": dividend_income, "interest_income": interest_income,
                   "wealth_change": None if opening_wealth is None else self.wealth(price) - opening_wealth,
                   "news": list(obs.news)}
        self.memory.append(outcome)
        self.memory = self.memory[-self.memory_window:]
        self.log_fn({"record_type": "outcome", "agent_id": self.agent_id,
                     "round": obs.round, "condition": self.condition, "outcome": outcome})
        if reflect:
            self.reflect_if_due(obs)

    def reflect_if_due(self, obs):
        if (self.condition != "C" or obs.round >= obs.total_rounds or obs.round <= self._last_reflected_round or
                obs.round <= 0 or obs.round % self.reflect_every):
            return
        self._last_reflected_round = obs.round
        p = self.persona
        messages = [{"role": "system", "content": REFLECTION_TEMPLATE.format(
            name=p.get("name", self.agent_id), risk=p.get("risk_tolerance", "medium"),
            style=p.get("strategy_inclination", "balanced"), horizon=p.get("horizon", "medium"),
            biases=p.get("bias_clauses", ""))},
            {"role": "user", "content": "Previous reflection (fallible): " + (self.diary or "none") +
             "\nVerified recent outcomes: " + json.dumps(self.memory, allow_nan=False)}]
        raw, meta = self._request(messages, obs.round, "reflection", temperature=0.0, json_mode=False)
        failed = (meta["status"] == "error" or not isinstance(raw, str) or not raw.strip() or
                  meta["response_metadata"].get("finish_reason") in ("length", "content_filter"))
        if failed:
            self.reflection_failures += 1
        else:
            self.diary = " ".join(raw.split()[:120])
        self.log_fn({"record_type": "reflection", "call_type": "reflection",
                     "agent_id": self.agent_id, "round": obs.round,
                     "condition": self.condition, "prompt_version": CONDITION_VERSIONS[self.condition],
                     "attempts": self._attempt_refs([meta]), "raw": raw, "diary": self.diary,
                     "failure_type": "reflection_failed" if failed else None})
