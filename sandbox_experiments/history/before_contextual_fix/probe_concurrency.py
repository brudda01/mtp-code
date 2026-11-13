import urllib.request, json, time, os, concurrent.futures

env = {}
with open("starter_code/.env") as f:
    for line in f:
        if "=" in line and not line.startswith("#"):
            k, v = line.strip().split("=", 1)
            env[k] = v.strip("\"'")
key = env.get("GODEL_MACHINES_API_KEY") or env.get("API_KEY")

def call_one(i):
    t0 = time.time()
    body = {
        "model": "deepseek/deepseek-v4.1-flash",
        "messages": [{"role": "user", "content": f"Hello agent {i}, respond with JSON {{\"agent\": {i}, \"status\": \"ready\"}}"}],
        "max_tokens": 30,
        "response_format": {"type": "json_object"}
    }
    req = urllib.request.Request(
        "https://api.goedelmachines.com/v1/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"}
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        res = json.loads(r.read())
        return i, round(time.time() - t0, 2), res["choices"][0]["message"]["content"]

t_start = time.time()
with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
    futs = [ex.submit(call_one, i) for i in range(6)]
    for f in concurrent.futures.as_completed(futs):
        print(f.result())
print(f"Total time for 6 concurrent calls: {round(time.time() - t_start, 2)}s")
