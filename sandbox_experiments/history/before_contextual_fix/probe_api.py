import urllib.request
import json
from pathlib import Path

env_lines = Path("starter_code/.env").read_text(encoding="utf-8").splitlines()
key = None
for l in env_lines:
    if l.startswith("GODEL_MACHINES_API_KEY="):
        key = l.split("=", 1)[1].strip().strip('"').strip("'")
        break

if not key:
    print("No key found.")
    exit(1)

req = urllib.request.Request(
    "https://api.goedelmachines.com/v1/chat/completions",
    data=json.dumps({
        "model": "deepseek/deepseek-v4.1-flash",
        "messages": [{"role": "user", "content": "Respond only with OK"}],
        "max_tokens": 10
    }).encode("utf-8"),
    headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {key}"
    }
)

try:
    with urllib.request.urlopen(req, timeout=15) as resp:
        print("Status code:", resp.status)
        data = json.loads(resp.read().decode("utf-8"))
        print("Data:", data)
except urllib.error.HTTPError as e:
    print("HTTP Error:", e.code, e.reason)
    print("Body:", e.read().decode("utf-8", errors="ignore"))
except Exception as e:
    print("Error:", type(e).__name__, str(e))
