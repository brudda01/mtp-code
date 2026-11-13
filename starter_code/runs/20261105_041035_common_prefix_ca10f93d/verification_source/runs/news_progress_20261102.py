"""Read-only live-study monitor; counts delivered records, not in-flight usage."""
import json
from pathlib import Path
import yaml

STUDY=Path(__file__).resolve().parent/"20261102_202946_news_pilot_786a0370"
ROOT=(STUDY/"delivery_v4_query_first" if (STUDY/"delivery_v4_query_first/execution.json").exists()
      else STUDY/"recovery_transport_v3" if (STUDY/"recovery_transport_v3/execution.json").exists()
      else STUDY/"continuation_1" if (STUDY/"continuation_1/execution.json").exists() else STUDY)
def read_json(path,default):
    try:return json.loads(path.read_text())
    except (FileNotFoundError,json.JSONDecodeError):return default
progress=read_json(ROOT/"progress.json",{})
runs=read_json(STUDY/"runs.json",[])
for phase in (STUDY/"continuation_1",STUDY/"recovery_transport_v3",STUDY/"delivery_v4_query_first"):
    if phase==ROOT or (phase/"summary.json").exists():runs+=read_json(phase/"runs.json",[])
active=progress.get("active")
result=dict(status=progress.get("status"),completed_rule_arms=sum(r["brain"]=="rules" and r["status"]=="completed" for r in runs),
            completed_live_arms=sum(r["brain"]=="qwen" and r["status"]=="completed" for r in runs),active=active)
if active and "config" in active:
    cfg=yaml.safe_load((ROOT/active["config"]).read_text())
    candidates=list((ROOT/"market_runs").glob("*_"+cfg["name"]+"_*"))
    if candidates:
        market=max(candidates,key=lambda p:p.stat().st_mtime)
        calls=[]
        try:
            for line in (market/"llm_requests.jsonl").read_text().splitlines():
                try:
                    row=json.loads(line)
                    if row["record_type"]=="model_call":calls.append(row)
                except json.JSONDecodeError:pass
        except FileNotFoundError:pass
        result.update(active_run=market.name,returned_attempts_in_active_arm=len(calls),
            active_api_errors=sum(r.get("status")=="error" for r in calls),
            active_transport_retry_attempts=sum(r.get("attempt_kind")=="transport_retry" for r in calls))
        try:result["logged_financial_rounds"]=max(0,len((market/"prices.csv").read_text().splitlines())-1)
        except FileNotFoundError:pass
if active and active.get("phase")=="same_state_probes":
    probe_root=ROOT/("probes_seed_"+str(active["seed"])) if "seed" in active else ROOT
    result["probe_progress"]=read_json(probe_root/"same_state_probes/progress.json",{})
result["final_summary"]=read_json(ROOT/"summary.json",None)
print(json.dumps(result))
