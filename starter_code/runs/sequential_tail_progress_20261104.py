"""Read-only R030 monitor; logged counts exclude any request still in flight."""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent/"20261104_034344_sequential_tail_f50a2cdd"


def read(path,default):
    try:return json.loads(path.read_text())
    except (FileNotFoundError,json.JSONDecodeError):return default


p=read(ROOT/"progress.json",{});result=dict(p)
if p.get("active"):
    a=p["active"];result["active"]={k:a[k] for k in ("seed","mode")}
    paths=list((ROOT/"market_runs").glob(f"*_sequential_{a['mode']}_combined_s{a['seed']}_r24_*"))
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
result["final_summary"]=read(ROOT/"summary.json",None)
print(json.dumps(result))
