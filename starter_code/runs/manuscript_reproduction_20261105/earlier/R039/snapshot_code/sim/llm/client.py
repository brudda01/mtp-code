"""Minimal OpenAI-compatible HTTP client, one HTTP attempt per recorded call.

No automatic retry is hidden from the shared request budget. Invalid model JSON
may trigger the agent's separately recorded corrective request. Credentials are
read from environment/constructor and never returned in call metadata.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
import re
from urllib.parse import urlparse
import urllib.error
import urllib.request


def dotenv_api_key(name, env_path=None):
    """Read one named credential as data; never execute dotenv or mutate env."""
    if os.environ.get(name, "").strip():
        return os.environ[name].strip()
    path = Path(env_path) if env_path is not None else Path(__file__).resolve().parents[2] / ".env"
    if not path.is_file():
        return ""
    value = ""
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        match = re.match(r"^\s*(?:export\s+)?" + re.escape(name) + r"\s*=\s*(.*?)\s*$", line)
        if match:
            value = match.group(1).strip()
            if value.startswith(("'", '"')):
                quote = value[0]
                end = value.find(quote, 1)
                if end < 0 or value[end+1:].strip().split("#", 1)[0].strip():
                    raise ValueError(name + " has invalid dotenv quoting")
                value = value[1:end]
            else:
                value = re.sub(r"\s+#.*$", "", value).strip()
    if any(c.isspace() for c in value):
        raise ValueError(name + " must not contain whitespace")
    return value


def gemini_api_key(env_path=None):
    return dotenv_api_key("GEMINI_API_KEY", env_path)


def bharatcode_api_key(env_path=None):
    return dotenv_api_key("BHARATCODE_API_KEY", env_path) or dotenv_api_key("API_KEY", env_path)


def retry_after_metadata(headers, now=None):
    """Parse only the standard delay/date; never retain arbitrary header text."""
    raw = (headers or {}).get("Retry-After")
    if raw is None:
        return {"retry_after_present": False}
    delay = None
    try:
        if isinstance(raw, str) and re.fullmatch(r"\d+", raw.strip()):
            delay = float(raw.strip())
        elif isinstance(raw, str):
            date = parsedate_to_datetime(raw)
            if date.tzinfo is not None:
                delay = max(0.0, (date - (now or datetime.now(timezone.utc))).total_seconds())
    except (ValueError, TypeError, OverflowError):
        pass
    if delay is not None and not (0 <= delay < float("inf")):
        delay = None
    return {"retry_after_present": True, "retry_after_valid": delay is not None,
            "retry_after_seconds": delay}


def _error_metadata(exc):
    """Keep structured quota information, never raw provider error messages."""
    result = {"http_status": exc.code}
    result.update(retry_after_metadata(exc.headers))
    request_id = (exc.headers or {}).get("x-request-id")
    if isinstance(request_id, str):
        result["request_id"] = request_id
    try:
        error = json.loads(exc.read(65536)).get("error", {})
        if isinstance(error.get("status"), str):
            result["provider_status"] = error["status"]
        for detail in error.get("details", []):
            if not isinstance(detail, dict):
                continue
            if str(detail.get("@type", "")).endswith("QuotaFailure"):
                violations = []
                for violation in detail.get("violations", []):
                    item = {k: violation[k] for k in ("quotaMetric", "quotaId", "quotaValue")
                            if isinstance(violation.get(k), (str, int, float))}
                    item["dimensions"] = {k: v for k, v in violation.get("quotaDimensions", {}).items()
                                           if k in ("model", "location") and isinstance(v, str)}
                    violations.append(item)
                result["quota_violations"] = violations
            delay = detail.get("retryDelay")
            if isinstance(delay, str) and re.fullmatch(r"[0-9.]+s", delay):
                result["retry_delay_seconds"] = float(delay[:-1])
    except (ValueError, TypeError, AttributeError, OSError):
        pass
    return result


class LLMClient:
    def __init__(self, model="gpt-4o-mini", base_url=None, api_key=None, timeout=30,
                 reasoning_effort=None, send_temperature=True, **kwargs):
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.send_temperature = send_temperature
        self.base_url = (base_url or os.environ.get(
            "LLM_BASE_URL", "https://api.openai.com/v1")).rstrip("/")
        parsed = urlparse(self.base_url)
        if (parsed.scheme not in ("http", "https") or not parsed.netloc or
                parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise ValueError("base URL must be HTTP(S), without embedded credentials/query/fragment")
        self.api_key = api_key or ""
        if not self.api_key and parsed.scheme == "https" and parsed.port in (None, 443):
            if parsed.hostname == "generativelanguage.googleapis.com":
                self.api_key = gemini_api_key()
            elif parsed.hostname == "bharatcode.ai" and parsed.path.rstrip("/") == "/api/model/v1":
                self.api_key = bharatcode_api_key()
            elif parsed.hostname == "integrate.api.nvidia.com" and parsed.path.rstrip("/") == "/v1":
                self.api_key = dotenv_api_key("NVIDIA_API_KEY")
        if not self.api_key:
            self.api_key = os.environ.get("LLM_API_KEY", "")
        self.timeout = timeout
        self.total_tokens = 0
        self.total_cost = 0.0  # Declared-price estimates are recorded by UsageBudget.
        self.last_usage = None
        self.last_response_metadata = {}
        self.last_error_metadata = {}

    def chat(self, messages, temperature=0.7, max_tokens=300, json_mode=True, retries=1):
        if retries != 1:
            raise ValueError("hidden retries are disabled; record and budget each new request")
        self.last_usage = None
        self.last_response_metadata = {}
        self.last_error_metadata = {}
        body = {"model": self.model, "messages": messages, "max_tokens": max_tokens}
        if self.send_temperature:
            body["temperature"] = temperature
        if self.reasoning_effort is not None:
            body["reasoning_effort"] = self.reasoning_effort
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(self.base_url + "/chat/completions",
                                         data=json.dumps(body).encode(), headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                request_id = (getattr(response, "headers", {}) or {}).get("x-request-id")
                data = json.loads(response.read())
        except urllib.error.HTTPError as exc:
            self.last_error_metadata = _error_metadata(exc)
            raise
        usage = data.get("usage", {})
        if (isinstance(usage, dict) and all(type(usage.get(k)) is int and usage[k] >= 0
                for k in ("prompt_tokens", "completion_tokens"))):
            total = usage["prompt_tokens"] + usage["completion_tokens"]
            reported = usage.get("total_tokens", total)
            if type(reported) is int and reported >= total:
                self.last_usage = {"prompt_tokens": usage["prompt_tokens"],
                                   "completion_tokens": usage["completion_tokens"],
                                   "total_tokens": reported, "source": "provider"}
                details = usage.get("completion_tokens_details", {})
                if isinstance(details, dict) and type(details.get("reasoning_tokens")) is int and details["reasoning_tokens"] >= 0:
                    self.last_usage["reasoning_tokens"] = details["reasoning_tokens"]
                self.total_tokens += reported
        self.last_response_metadata = {
            k: data[k] for k in ("model", "system_fingerprint") if isinstance(data.get(k), str)}
        if isinstance(request_id, str):
            self.last_response_metadata["request_id"] = request_id
        choice = data["choices"][0]
        if isinstance(choice.get("finish_reason"), str):
            self.last_response_metadata["finish_reason"] = choice["finish_reason"]
        content = choice["message"]["content"]
        if not isinstance(content, str):
            raise ValueError("provider returned non-text message content")
        return content
