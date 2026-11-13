"""Isolated source-snapshot replay. Network denied; original replies never resampled."""
import argparse
import contextlib
import hashlib
import io
import json
from pathlib import Path
import socket
import sys
from unittest.mock import patch

parser=argparse.ArgumentParser()
for option in ('source','study','index','output','result','adapter'):parser.add_argument('--'+option,required=True)
args=parser.parse_args()
source=Path(args.source).resolve();root=Path(args.study).resolve();out=Path(args.output).resolve()
workspace=Path(__file__).resolve().parents[2]
sys.path=[str(source)]+[p for p in sys.path if not Path(p or '.').resolve().is_relative_to(workspace)]
network_attempts=[]
def denied(*args,**kwargs):
    network_attempts.append('blocked');raise RuntimeError('Network forbidden in verification replay')
socket.socket.connect=denied
socket.socket.connect_ex=denied
socket.create_connection=denied
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
result=dict(status='running',kind='Recorded-output verification,not fresh model replication',network_attempts=0,markets=[])


class NoDelay:
    def __init__(self,rpm,tpm):self.requests_per_minute=rpm;self.input_tokens_per_minute=tpm
    def acquire(self,estimate):return 0


class ReplayClient:
    tape=[];cursor=0
    def __init__(self,model,base_url,reasoning_effort=None,send_temperature=True,**kwargs):
        self.model=model;self.base_url=base_url;self.reasoning_effort=reasoning_effort
        self.send_temperature=send_temperature;self.total_tokens=0;self.last_usage=None
        self.last_response_metadata={};self.last_error_metadata={}
    def chat(self,messages,temperature,max_tokens,json_mode):
        call=type(self).tape[type(self).cursor]
        assert messages==call['messages'],'Exact request messages differ'
        for actual,expected in [(temperature,call['temperature']), (max_tokens,call['max_tokens']),
            (json_mode,call['json_mode']), (self.reasoning_effort,call['reasoning_effort'])]:assert actual==expected
        assert call['status']=='returned' and call['response_metadata']['model']==self.model
        type(self).cursor+=1
        self.last_usage=call['usage'];self.last_response_metadata=call['response_metadata']
        self.total_tokens+=(self.last_usage or {}).get('total_tokens',0)
        return call['raw']


try:
    import sim.engine as engine
    from sim.config import load_config
    from sim.news_controls import FINANCIAL_FILES
    if args.adapter=='quiet':
        from runs.quiet_components_20261105 import disclosure
    elif args.adapter=='downside':
        from runs.downside_confirmation_20261104 import disclosure
    else:disclosure=contextlib.nullcontext
    for name,module in list(sys.modules.items()):
        if name=='sim' or name.startswith(('sim.','runs.')):
            if getattr(module,'__file__',None):assert Path(module.__file__).resolve().is_relative_to(source),name
    index=json.loads(Path(args.index).read_text())
    if isinstance(index,dict):index=index['runs']
    for entry in index:
        original=root/entry['run_path'];manifest=json.loads((original/'manifest.json').read_text())
        assert sha(original/'manifest.json')==entry['manifest_sha256']
        for name,digest in manifest['source_sha256'].items():assert sha(source/name)==digest,name
        for name,digest in manifest['output_sha256'].items():assert sha(original/name)==digest,name
        ReplayClient.tape=[json.loads(line) for line in (original/'llm_requests.jsonl').read_text().splitlines()
            if json.loads(line)['record_type']=='model_call']
        ReplayClient.cursor=0;cfg=load_config(original/'config.yaml')
        for group in cfg.agents:
            if group.llm:
                assert cfg.execution.max_workers==1
        with patch.object(engine,'LLMClient',ReplayClient),disclosure(),contextlib.redirect_stdout(io.StringIO()):
            replay=Path(engine.run(original/'config.yaml',output_root=out,
                request_pacer=NoDelay(cfg.llm_limits.requests_per_minute,cfg.llm_limits.input_tokens_per_minute)))
        assert ReplayClient.cursor==len(ReplayClient.tape)
        matched={name:sha(replay/name)==sha(original/name) for name in FINANCIAL_FILES}
        assert all(matched.values()),matched
        summary=json.loads((replay/'summary.json').read_text());assert summary['status']=='completed'
        # Outcome/diary contents are regenerated through the actual agent/engine,
        # not copied into the new financial files.
        result['markets'].append(dict(original_run=entry['run_path'],replay_run=str(replay),
            rounds=summary['rounds'],recorded_calls_consumed=ReplayClient.cursor,
            exact_financial_files=matched,source_snapshot_matches=True))
    result['status']='passed'
except BaseException as exc:
    result.update(status='failed',error_type=type(exc).__name__,error=str(exc))
finally:
    result['network_attempts']=len(network_attempts)
    Path(args.result).write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(dict(status=result['status'],markets=len(result['markets']),network_attempts=len(network_attempts),error=result.get('error'))))
if result['status']!='passed':sys.exit(1)
