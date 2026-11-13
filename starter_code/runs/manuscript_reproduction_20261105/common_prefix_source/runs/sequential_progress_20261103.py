"""Read-only R028 gate monitor; excludes in-flight usage from logged counts."""
import json
from pathlib import Path
import yaml

ROOT=Path(__file__).resolve().parent/"20261103_183126_sequential_markets_bb927356"
BLOCK=ROOT/"block_4103"

def read(path,default):
    try:return json.loads(path.read_text())
    except (FileNotFoundError,json.JSONDecodeError):return default

p=read(BLOCK/"progress.json",{})
result=dict(status=p.get("status"),completed_markets=p.get("completed_markets"),active=p.get("active"))
if p.get("active"):
    cfg=yaml.safe_load((ROOT/p["active"]["config"]).read_text())
    paths=list((BLOCK/"market_runs").glob("*_"+cfg["name"]+"_*"))
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
if result["final_summary"] is not None:
    result["recorded_markets"]=result["final_summary"]["recorded_markets"]
    result["completed_markets"]=result["final_summary"]["completed_markets"]
    result["count_note"]="Terminal summary distinguishes completed from merely recorded/partial arms; raw progress counts records."
print(json.dumps(result))
