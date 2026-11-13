"""Read-only R029 status; logged usage excludes a request still in flight."""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent/"20261103_195320_sequential_next_fd0fc07c"
BLOCK=ROOT/"block_5209"


def read(path,default):
    try:return json.loads(path.read_text())
    except (FileNotFoundError,json.JSONDecodeError):return default


p=read(BLOCK/"progress.json",{});result=dict(p)
if p.get("active"):
    paths=list((BLOCK/"market_runs").glob("*_sequential_"+p["active"]["mode"]+"_combined_s5209_r24_*"))
    if paths:
        run=max(paths,key=lambda p:p.stat().st_mtime);calls=[]
        try:
            for line in (run/"llm_requests.jsonl").read_text().splitlines():
                try:
                    r=json.loads(line)
                    if r["record_type"]=="model_call":calls.append(r)
                except json.JSONDecodeError:pass
        except FileNotFoundError:pass
        result.update(run=run.name,logged_http_attempts=len(calls),errors=sum(r.get("status")=="error" for r in calls),
            capped_replies=sum(r.get("response_metadata",{}).get("finish_reason")=="length" for r in calls))
        try:result["financial_rounds"]=max(0,len((run/"prices.csv").read_text().splitlines())-1)
        except FileNotFoundError:pass
result["final_summary"]=read(BLOCK/"summary.json",None)
print(json.dumps(result))
