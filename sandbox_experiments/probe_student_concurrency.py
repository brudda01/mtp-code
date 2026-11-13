import sys
sys.dont_write_bytecode = True
from pathlib import Path
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "starter_code"))

import time
import json
import urllib.request
import concurrent.futures
from sim.llm.client import dotenv_api_key

key = dotenv_api_key('GODEL_MACHINES_API_KEY')
print("Testing 4 concurrent requests under Student Pass...")

def send_one(i):
    t0 = time.time()
    body = {
        "model": "deepseek/deepseek-v4.1-flash",
        "messages": [{"role": "user", "content": f"Student probe {i}: return JSON {{\"agent_id\": {i}, \"status\": \"ready\"}}"}],
        "max_tokens": 50,
        "response_format": {"type": "json_object"}
    }
    req = urllib.request.Request(
        "https://api.goedelmachines.com/v1/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        res = json.loads(resp.read().decode("utf-8"))
        latency = round(time.time() - t0, 3)
        return i, resp.status, latency, res["choices"][0]["message"]["content"]

t_start = time.time()
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
    futures = [ex.submit(send_one, i) for i in range(4)]
    for f in concurrent.futures.as_completed(futures):
        i, status, latency, content = f.result()
        print(f" Request {i}: HTTP {status} in {latency}s -> {content}")

total_time = round(time.time() - t_start, 3)
print(f"Total elapsed for 4 concurrent requests: {total_time}s")
