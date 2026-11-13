"""
Resilient LLM Client with Request Ledger and Provenance Tracking.
Directly addresses Findings #5, #6, #10, #14 in AUDIT_REPORT.md.
"""
from __future__ import annotations

import os
import time
import json
import urllib.request
import urllib.error
from typing import List, Dict, Any, Optional

def load_credentials():
    env = {}
    env_path = "starter_code/.env"
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                if "=" in line and not line.startswith("#"):
                    k, v = line.strip().split("=", 1)
                    env[k] = v.strip("\"'")
    key = env.get("GODEL_MACHINES_API_KEY") or env.get("API_KEY")
    if not key:
        raise ValueError("Missing GODEL_MACHINES_API_KEY or API_KEY in starter_code/.env")
    return key

class RepairedResilientClient:
    def __init__(self, api_key: Optional[str] = None,
                 model: str = "deepseek/deepseek-v4.1-flash",
                 base_url: str = "https://api.goedelmachines.com/v1"):
        self.api_key = api_key or load_credentials()
        self.model = model
        self.base_url = base_url
        self.request_ledger: List[Dict[str, Any]] = []
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_http_requests = 0
        self.total_errors = 0

    def complete(self, messages: List[Dict[str, str]],
                 temperature: float = 0.3,
                 max_tokens: int = 1024,
                 timeout: int = 30) -> str:
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"}
        }
        data = json.dumps(body).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        req = urllib.request.Request(f"{self.base_url}/chat/completions", data=data, headers=headers)

        for attempt in range(6):
            t0 = time.time()
            self.total_http_requests += 1
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    latency = round(time.time() - t0, 3)
                    raw_bytes = resp.read()
                    res_json = json.loads(raw_bytes.decode("utf-8"))
                    
                    choice = res_json["choices"][0]
                    content = choice["message"].get("content")
                    if not content and "reasoning_content" in choice["message"]:
                        content = choice["message"]["reasoning_content"]

                    usage = res_json.get("usage", {})
                    p_tok = usage.get("prompt_tokens", 0)
                    c_tok = usage.get("completion_tokens", 0)
                    self.total_prompt_tokens += p_tok
                    self.total_completion_tokens += c_tok

                    self.request_ledger.append({
                        "timestamp": time.time(),
                        "attempt": attempt + 1,
                        "status_code": 200,
                        "latency_s": latency,
                        "model": res_json.get("model", self.model),
                        "finish_reason": choice.get("finish_reason", "stop"),
                        "prompt_tokens": p_tok,
                        "completion_tokens": c_tok
                    })
                    return content or ""

            except urllib.error.HTTPError as e:
                latency = round(time.time() - t0, 3)
                self.total_errors += 1
                retry_after = e.headers.get("Retry-After") if e.headers else None
                wait = int(retry_after) + 2 if (retry_after and retry_after.isdigit()) else (3 * (attempt + 1))
                
                self.request_ledger.append({
                    "timestamp": time.time(),
                    "attempt": attempt + 1,
                    "status_code": e.code,
                    "latency_s": latency,
                    "error": str(e),
                    "retry_after_wait": wait
                })
                print(f"   [API {e.code}: waiting {wait}s on attempt {attempt+1}/6...]")
                time.sleep(wait)

            except Exception as e:
                latency = round(time.time() - t0, 3)
                self.total_errors += 1
                wait = 3 * (attempt + 1)
                self.request_ledger.append({
                    "timestamp": time.time(),
                    "attempt": attempt + 1,
                    "status_code": "EXCEPTION",
                    "latency_s": latency,
                    "error": str(e),
                    "wait": wait
                })
                print(f"   [Transport error: {str(e)[:50]} - waiting {wait}s...]")
                time.sleep(wait)

        raise RuntimeError(f"Exhausted 6 retries to {self.base_url}")
