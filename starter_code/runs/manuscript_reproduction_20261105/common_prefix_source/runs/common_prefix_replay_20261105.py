"""Standalone isolated replay of clean R047 continuations;network denied."""
import argparse
import contextlib
import hashlib
import io
import json
from pathlib import Path
import socket
import sys
from unittest.mock import patch


def main():
    parser=argparse.ArgumentParser()
    for name in ('source','study','output','result'):parser.add_argument('--'+name,required=True)
    args=parser.parse_args();source=Path(args.source).resolve();root=Path(args.study).resolve();out=Path(args.output).resolve()
    workspace=Path(__file__).resolve().parents[2]
    sys.path=[str(source)]+[p for p in sys.path if not Path(p or '.').resolve().is_relative_to(workspace)]
    blocked=[]
    def deny(*args,**kwargs):blocked.append(True);raise RuntimeError('Network denied in R047 verification')
    socket.socket.connect=deny;socket.socket.connect_ex=deny;socket.create_connection=deny
    from runs import common_prefix_20261105 as d
    from sim.news_controls import FINANCIAL_FILES
    from sim.config import load_config
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    d.validate(root);index=d.read(root/'runs.json');records=[];partial=[]
    class NoDelay:
        def __init__(self,rpm,tpm):self.requests_per_minute=rpm;self.input_tokens_per_minute=tpm
        def acquire(self,estimate):return 0
    class Replay:
        tape=[];cursor=0
        def __init__(self,model,base_url,reasoning_effort=None,send_temperature=True,**kwargs):
            self.model=model;self.base_url=base_url;self.reasoning_effort=reasoning_effort;self.send_temperature=send_temperature
            self.total_tokens=0;self.last_usage=None;self.last_response_metadata={};self.last_error_metadata={}
        def chat(self,messages,temperature,max_tokens,json_mode):
            call=type(self).tape[type(self).cursor]
            assert messages==call['messages'] and call['status']=='returned'
            assert temperature==call['temperature'] and max_tokens==call['max_tokens'] and json_mode==call['json_mode'] and self.reasoning_effort==call['reasoning_effort']
            assert call['response_metadata']['model']==self.model
            type(self).cursor+=1;self.last_usage=call['usage'];self.last_response_metadata=call['response_metadata']
            self.total_tokens+=(self.last_usage or {}).get('total_tokens',0)
            return call['raw']
    for arm in index:
        original=root/arm['run_path'];d.prior.base.verify_market(original)
        assert sha(original/'manifest.json')==arm['manifest_sha256']
        if arm['status']!='completed' or arm['rounds']!=12 or any(arm['operational_failures'].values()):
            partial.append(arm['run_path']);continue
        Replay.tape=[c for c in d.lines(original/'llm_requests.jsonl') if c['record_type']=='model_call'];Replay.cursor=0
        # Exact final tapes can include an identical-message successful retry.
        # Error attempts require explicit exception replay;do not silently drop.
        if any(c['status']!='returned' for c in Replay.tape):
            partial.append(dict(run=arm['run_path'],reason='Recovered error attempt requires exception-aware tape replay;raw evidence retained.'));continue
        cfg=load_config(original/'config.yaml')
        with patch.object(d.prior.base.engine,'LLMClient',Replay),d.context(root/'prefixes'/arm['prefix_id']) as state,contextlib.redirect_stdout(io.StringIO()):
            replay=Path(d.prior.base.engine.run(original/'config.yaml',output_root=out,request_pacer=NoDelay(cfg.llm_limits.requests_per_minute,cfg.llm_limits.input_tokens_per_minute)))
        assert Replay.cursor==len(Replay.tape) and state['prefix_requests']==10 and state['first_live_gate']
        matched={name:sha(replay/name)==sha(original/name) for name in FINANCIAL_FILES};assert all(matched.values()),matched
        marker=dict(kind='OFFLINE_R047_VERIFICATION',new_http_requests=0,warning='Replayed usage metadata is historical,not new provider usage or independent decisions.')
        (replay/'VERIFICATION_REPLAY.json').write_text(json.dumps(marker,indent=2)+'\n')
        records.append(dict(original=arm['run_path'],replay=str(replay),fresh_tape_replies=len(Replay.tape),cached_prefix=10,financial_files=matched))
    result=dict(status='passed',verified_clean_paths=len(records),records=records,not_replayed=partial,network_attempts=len(blocked),
        scope='Recorded-reply verification only. Partial/affected/recovered-error paths retained but not silently reclassified as successful replays.')
    Path(args.result).write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(dict(verified=len(records),not_replayed=len(partial),network_attempts=len(blocked))))


if __name__=='__main__':main()
