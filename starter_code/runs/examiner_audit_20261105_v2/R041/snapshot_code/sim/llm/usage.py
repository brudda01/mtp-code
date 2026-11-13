"""Thread-safe pilot request limits and explicit, conservative cost estimates.

Reservations are never refunded: failed/ambiguous requests may still be billed.
UTF-8 byte counts plus overhead are a screening estimate, not a provider tokenizer
or a guarantee about a provider's final bill. Use provider account limits too.
"""
import json
import threading
import time
from collections import deque


class UsageLimitExceeded(RuntimeError):
    """A request was blocked before calling the model."""


class OutputLimitExceeded(UsageLimitExceeded):
    """A recorded model response reached its output cap; do not repeat that cap."""


class ProviderUnavailable(RuntimeError):
    """A recorded provider error stopped a fail-fast pilot."""


class RequestPacer:
    """Shared, evenly spaced requests and rolling input-estimate reservations.

    Estimates use the budget's byte-based count, not a provider tokenizer. This
    limits this process only; other programs using the same project share quota.
    """
    def __init__(self, requests_per_minute=None, input_tokens_per_minute=None,
                 *, clock=time.monotonic, sleep=time.sleep):
        self.requests_per_minute = requests_per_minute
        self.input_tokens_per_minute = input_tokens_per_minute
        self.clock, self.sleep = clock, sleep
        self._next_request = 0.0
        self._recent = deque()
        self._lock = threading.Lock()

    def acquire(self, input_estimate):
        if self.input_tokens_per_minute is not None and input_estimate > self.input_tokens_per_minute:
            raise UsageLimitExceeded("single input exceeds per-minute input reservation limit")
        started = self.clock()
        while True:
            with self._lock:
                now = self.clock()
                while self._recent and self._recent[0][0] <= now - 60:
                    self._recent.popleft()
                delay = max(0.0, self._next_request - now)
                if self.input_tokens_per_minute is not None:
                    excess = sum(n for _, n in self._recent) + input_estimate - self.input_tokens_per_minute
                    for stamp, count in self._recent:
                        if excess <= 0:
                            break
                        delay = max(delay, stamp + 60 - now)
                        excess -= count
                if delay <= 1e-9:
                    if self.requests_per_minute:
                        self._next_request = now + 60 / self.requests_per_minute
                    if self.input_tokens_per_minute is not None:
                        self._recent.append((now, input_estimate))
                    return max(0.0, now - started)
            self.sleep(min(delay, 1.0))


class UsageBudget:
    def __init__(self, max_requests=10000, max_reserved_tokens=20000000, max_cost_usd=None,
                 requests_per_minute=None, input_tokens_per_minute=None, stop_on_api_error=False):
        self.max_requests = max_requests
        self.max_reserved_tokens = max_reserved_tokens
        self.max_cost_usd = max_cost_usd
        self.stop_on_api_error = stop_on_api_error
        self._provider_stopped = False
        self.pacer = RequestPacer(requests_per_minute, input_tokens_per_minute)
        self.requests = self.reserved_tokens = self.rejections = 0
        self.reserved_cost_usd = 0.0
        self.provider_tokens = self.estimated_tokens = self.unknown_usage_requests = 0
        self.failed_requests = 0
        self.observed_cost_estimate_usd = 0.0
        self._lock = threading.Lock()

    def reserve(self, messages, max_output_tokens, input_price, output_price):
        input_tokens = len(json.dumps(messages, ensure_ascii=False).encode("utf-8")) + 256
        tokens = input_tokens + max_output_tokens
        cost = (input_tokens * input_price + max_output_tokens * output_price) / 1e6
        with self._lock:
            if self._provider_stopped:
                self.rejections += 1
                raise ProviderUnavailable("an earlier provider error stopped this pilot")
            reason = None
            if self.requests + 1 > self.max_requests:
                reason = "request limit"
            elif self.pacer.input_tokens_per_minute is not None and input_tokens > self.pacer.input_tokens_per_minute:
                reason = "single input exceeds per-minute input reservation limit"
            elif max(self.reserved_tokens, self.provider_tokens + self.estimated_tokens) + tokens > self.max_reserved_tokens:
                reason = "token reservation limit"
            elif self.max_cost_usd is not None and max(
                    self.reserved_cost_usd, self.observed_cost_estimate_usd) + cost > self.max_cost_usd + 1e-12:
                reason = "declared-price cost reservation limit"
            if reason:
                self.rejections += 1
                raise UsageLimitExceeded(reason)
            self.requests += 1
            self.reserved_tokens += tokens
            self.reserved_cost_usd += cost
            return {"reservation_id": self.requests, "input_token_estimate": input_tokens,
                    "max_output_tokens": max_output_tokens, "reserved_cost_usd": cost}

    def stop_for_provider_error(self):
        if self.stop_on_api_error:
            with self._lock:
                self._provider_stopped = True

    def ensure_provider_available(self):
        with self._lock:
            if self._provider_stopped:
                raise ProviderUnavailable("an earlier provider error stopped this pilot")

    def record(self, usage, success, input_price, output_price):
        with self._lock:
            if not success:
                self.failed_requests += 1
            if usage is None:
                self.unknown_usage_requests += 1
                return None
            tokens = usage["total_tokens"]
            if usage["source"] == "provider":
                self.provider_tokens += tokens
            else:
                self.estimated_tokens += tokens
            cost = (usage["prompt_tokens"] * input_price +
                    usage["completion_tokens"] * output_price) / 1e6
            self.observed_cost_estimate_usd += cost
            return cost

    def snapshot(self):
        with self._lock:
            return {"requests_made": self.requests, "max_requests": self.max_requests,
                    "reserved_tokens": self.reserved_tokens,
                    "max_reserved_tokens": self.max_reserved_tokens,
                    "reserved_cost_usd": self.reserved_cost_usd,
                    "max_cost_usd": self.max_cost_usd,
                    "provider_reported_tokens": self.provider_tokens,
                    "estimated_mock_tokens": self.estimated_tokens,
                    "unknown_usage_requests": self.unknown_usage_requests,
                    "failed_requests": self.failed_requests,
                    "observed_cost_estimate_usd": self.observed_cost_estimate_usd,
                    "blocked_requests": self.rejections,
                    "requests_per_minute": self.pacer.requests_per_minute,
                    "input_tokens_per_minute": self.pacer.input_tokens_per_minute,
                    "stop_on_api_error": self.stop_on_api_error,
                    "provider_stopped": self._provider_stopped,
                    "reservation_method": "utf8_bytes_plus_256_and_max_output_no_refunds"}
