"""One logged native-route diagnostic after two compatibility-route HTTP 503s."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1] / "starter_code"
sys.path.insert(0, str(ROOT))
from sim.llm.client import gemini_api_key

endpoint = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent"
payload = {"contents": [{"role": "user", "parts": [{"text": "Compute 2+2. Return only a JSON object with key result."}]}],
           "generationConfig": {"maxOutputTokens": 2048, "responseMimeType": "application/json",
                                "thinkingConfig": {"thinkingLevel": "LOW"}}}
target = ROOT / "runs" / (time.strftime("%Y%m%d_%H%M%S_") + "flash38_native_access_" + uuid.uuid4().hex[:8])
target.mkdir(parents=True)
(target / "protocol.json").write_text(json.dumps({"endpoint": endpoint, "payload": payload,
    "attempt_limit": 1, "purpose": "Distinguish compatibility-route failure from native-route availability; not a behavioural result.",
    "predecessors": ["20261102_040526_flash38_probes_09b9a76b", "20261102_040700_flash38_probes_9054fea8"]}, indent=2), encoding="utf-8")
(target / "diagnostic_source.py").write_bytes(Path(__file__).read_bytes())
request = urllib.request.Request(endpoint, data=json.dumps(payload).encode(),
    headers={"Content-Type": "application/json", "x-goog-api-key": gemini_api_key()})
result = {"started_utc": datetime.now(timezone.utc).isoformat(), "model": "gemini-3.8-flash"}
try:
    with urllib.request.urlopen(request, timeout=90) as response:
        data = json.load(response)
    result.update(status="returned", response=data)
except urllib.error.HTTPError as exc:
    body = exc.read(65536)
    result.update(status="provider_error", http_status=exc.code,
                  content_type=exc.headers.get("Content-Type"),
                  error_body_bytes=len(body), error_body_sha256=hashlib.sha256(body).hexdigest())
    try:
        error = json.loads(body).get("error", {})
        if isinstance(error.get("status"), str):
            result["provider_status"] = error["status"]
    except (ValueError, AttributeError):
        pass
except Exception as exc:
    result.update(status="connection_error", error_type=type(exc).__name__)
result["finished_utc"] = datetime.now(timezone.utc).isoformat()
(target / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
print("Artifact:", target)
print(json.dumps(result, indent=2))
