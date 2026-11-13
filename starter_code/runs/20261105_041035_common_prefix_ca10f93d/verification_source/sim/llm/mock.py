"""Deterministic mock LLM: same interface as the real client, zero cost.
Parses the price history embedded in the prompt and answers with a simple
persona-flavoured heuristic in valid JSON. Used for tests and free dev runs."""
from __future__ import annotations
import hashlib, json, re


class MockLLMClient:
    def __init__(self, **kwargs):
        self.total_tokens = 0
        self.total_cost = 0.0
        self.last_usage = None
        self.last_response_metadata = {"model": "deterministic_mock_v2"}

    def _finish(self, text, response):
        prompt, completion = max(1, len(text) // 4), max(1, len(response) // 4)
        self.last_usage = {"prompt_tokens": prompt, "completion_tokens": completion,
                           "total_tokens": prompt + completion, "source": "estimated_mock"}
        self.total_tokens += prompt + completion
        return response

    def chat(self, messages: list[dict], temperature: float = 0.7,
             max_tokens: int = 300, json_mode: bool = True) -> str:
        text = "\n".join(m["content"] for m in messages)
        if not json_mode:
            return self._finish(text, "Observed: This is a mock-only reflection. "
                                "Beliefs: No economic judgment. Plan: Continue the software test.")
        nums = re.findall(r"prices.*?:\s*\[([^\]]*)\]", text, re.S)
        hist = []
        if nums:
            hist = [float(x) for x in re.findall(r"[-\d.]+", nums[0])][-6:]
        h = int(hashlib.md5(text.encode()).hexdigest(), 16)
        p = hist[-1] if hist else 100.0
        trend = (hist[-1] - hist[0]) / hist[0] if len(hist) > 1 else 0.0
        style = h % 3  # pseudo-persona from prompt hash
        if style == 0:      # contrarian-ish
            side = "sell" if trend > 0.01 else ("buy" if trend < -0.01 else "hold")
        elif style == 1:    # momentum-ish
            side = "buy" if trend > 0.005 else ("sell" if trend < -0.005 else "hold")
        else:               # value-ish around 100
            side = "buy" if p < 97 else ("sell" if p > 103 else "hold")
        qty = 1 + (h >> 8) % 8
        limit = round(p * (1 + ((h >> 16) % 41 - 20) / 1000.0), 2)
        if side == "hold":
            qty, limit = 0, None
        return self._finish(text, json.dumps({"action": side, "quantity": qty,
                           "limit_price": limit,
                           "reasoning": f"mock style {style}, trend {trend:+.2%}"}))
