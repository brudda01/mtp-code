"""R058 budgeted 429 backoff. _request_once derived from frozen LLMAgent;
only retry classification/eligibility changes. Prompt/choice/economic code unchanged.
Every HTTP attempt passes the existing shared budget, pacer and raw request log.
"""
import math
import re
import ssl
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError, URLError
from sim.agents.llm_agent import CONDITION_VERSIONS
from sim.llm.client import retry_after_metadata
from sim.llm.usage import OutputLimitExceeded, ProviderUnavailable, UsageLimitExceeded
from research.goedel_cohort import CappedAgent

TRANSPORT_POLICY_VERSION = 'budgeted_delivery_R058_retryafter_plus1_v1'
MAX_429_RETRIES = 10


def parse_retry_after(headers, now=None):
    raw = (headers or {}).get('Retry-After')
    delay = None
    if isinstance(raw, str):
        raw = raw.strip()
        try:
            if re.fullmatch(r'[0-9]+(?:\.[0-9]+)?', raw):
                delay = float(raw)
            else:
                date = parsedate_to_datetime(raw)
                if date.tzinfo is not None:
                    delay = max(0., (date - (now or datetime.now(timezone.utc))).total_seconds())
        except (ValueError, TypeError, OverflowError):
            pass
    valid = delay is not None and math.isfinite(delay) and delay >= 0
    return dict(retry_after_present=raw is not None, retry_after_valid=valid,
                retry_after_seconds=delay if valid else None)


class BackoffAgent(CappedAgent):
    def _request(self, messages, rnd, kind, attempt=1, *, temperature=None, json_mode=True):
        category = None
        self._rate_retries_used = self._ordinary_retries_used = 0
        number = 0
        while True:
            number += 1
            raw, meta = self._request_once(messages, rnd, kind, attempt,
                temperature=temperature, json_mode=json_mode, transport_attempt=number,
                allow_transport_retry=True, retry_category=category)
            if not meta.get('transport_retry_planned'):
                return raw, meta
            category = meta['retry_category']
            if category == 'rate_limit_429':self._rate_retries_used += 1
            else:self._ordinary_retries_used += 1
            time.sleep(meta['retry_wait_seconds'])

    def _request_once(self, messages, rnd, kind, attempt=1, *, temperature=None, json_mode=True,
                      transport_attempt=1, allow_transport_retry=False, retry_category=None):
        group_id = f"{self.agent_id}:{rnd}:{kind}:{attempt}"
        meta = {"call_id": group_id if transport_attempt == 1 else group_id + f":transport{transport_attempt}",
                "request_group_id": group_id, "json_attempt": attempt,
                "transport_attempt": transport_attempt, "transport_policy_version": TRANSPORT_POLICY_VERSION,
                "attempt_kind": ("rate_limit_retry" if retry_category == "rate_limit_429" else "server_retry" if retry_category == "server_503" else "transport_retry") if transport_attempt > 1 else "json_repair" if kind == "decision" and attempt > 1 else "initial",
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
            if isinstance(exc, HTTPError) and exc.code == 429:
                header = parse_retry_after(exc.headers)
                meta["retry_after"] = header
                category = "rate_limit_429"
                eligible = self._rate_retries_used < MAX_429_RETRIES
                # Invalid/missing Retry-After: bounded exponential fallback plus buffer.
                delay = (header["retry_after_seconds"] if header["retry_after_valid"]
                         else min(60, 2 ** (self._rate_retries_used + 1))) + 1
            elif eligible:
                eligible = self._ordinary_retries_used < self.transport_retry_limit
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

