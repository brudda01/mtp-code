"""Recover an interrupted worker from exact recorded deliveries; buy no duplicate replies."""
import json
import time
from pathlib import Path
from urllib.error import HTTPError
from unittest.mock import patch
import yaml
from research import goedel_cohort as g
from research.goedel_backoff3 import BackoffAgent
from sim.llm.usage import RequestPacer

OLD=g.BASE/'runs/goedel_seed2_backoff_20261109'
ROOT=g.BASE/'runs/goedel_seed2_detached_20261109'
class RecordedThenLive(g.GoedelClient):
    cursor=0
    tape=[]
    def chat(self,messages,temperature=.3,max_tokens=2048,json_mode=True,retries=1):
        if type(self).cursor>=len(self.tape):
            return super().chat(messages,temperature,max_tokens,json_mode,retries)
        i=type(self).cursor;x=self.tape[i]
        expected=dict(model=g.MODEL,messages=messages,temperature=temperature,max_tokens=max_tokens,chat_template_kwargs={'thinking':False},stream=False)
        assert x['request']==expected,('Recorded prefix request mismatch',i)
        type(self).cursor+=1
        self.last_usage=None;self.last_response_metadata={};self.last_error_metadata={}
        with (ROOT/'replayed_prefix.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps({'index':i,'historical_not_fresh':True,'request_matches':True})+'\n')
        if 'error' in x:
            self.last_error_metadata=x['error']
            headers={'Retry-After':str(x['error'].get('retry_after_seconds') or 2)}
            raise HTTPError(g.URL,x['error']['http_status'],'Recorded historical error',headers,None)
        d=x['response'];u=d['usage'];self.last_usage=dict(prompt_tokens=u['prompt_tokens'],completion_tokens=u['completion_tokens'],total_tokens=u['total_tokens'],source='provider')
        self.total_tokens+=u['total_tokens'];c=d['choices'][0]
        self.last_response_metadata=dict(model=d['model'],finish_reason=c['finish_reason'])
        return c['message']['content']


def main():
    auth=g.read(g.BASE.parent/'DATA_COLLECTION_AUTHORIZATION.json')
    assert auth['status']=='active_detached_seed31991_continuation'
    assert not (OLD/'summary.json').exists()
    g.validate(OLD)
    ROOT.mkdir(exist_ok=False)
    (ROOT/'config.yaml').write_bytes((OLD/'config.yaml').read_bytes())
    (ROOT/'prefix_transport.jsonl').write_bytes((OLD/'provider_transport.jsonl').read_bytes())
    RecordedThenLive.tape=[json.loads(l) for l in (ROOT/'prefix_transport.jsonl').read_text().splitlines()]
    assert sum('response' in x for x in RecordedThenLive.tape)==27
    protocol=g.read(OLD/'protocol.json')
    for k in ('source_sha256','source_zip_sha256','created_utc','working_tree_status'):protocol.pop(k,None)
    protocol.update(version='R058_interruption_exact_prefix_continuation_plus3_v1',
        config_sha256=g.digest(ROOT/'config.yaml'),
        recovery='Unified worker terminated on user interruption after27saved decisions/38HTTP records. New detached worker replays exact wire prefix with message assertions,then new provider calls only. Replay usage is historical,not fresh. Prior root retained. Any unlogged in-flight attempt at interruption cannot be excluded. Fresh429wait=Retry-After+3. No new scenario or model change.',
        prefix_sha256=g.digest(ROOT/'prefix_transport.jsonl'),historical_prefix_decisions=27,historical_prefix_http_records=len(RecordedThenLive.tape))
    protocol['inputs_sha256'].update({p.relative_to(g.BASE).as_posix():g.digest(p) for p in OLD.rglob('*') if p.is_file()})
    g.freeze(ROOT,protocol,['research/goedel_backoff3.py','research/goedel_detached_continuation.py'])
    original_pace=RequestPacer.acquire
    original_sleep=time.sleep
    def pace(pacer,*args,**kwargs):
        if RecordedThenLive.cursor<len(RecordedThenLive.tape):return 0
        return original_pace(pacer,*args,**kwargs)
    def sleep(seconds):
        if RecordedThenLive.cursor>=len(RecordedThenLive.tape):original_sleep(seconds)
    # Cached deliveries require neither provider pacing nor historical wall-clock waits.
    # Actual live requests retain the original pacer and Retry-After+3 sleep.
    with patch.object(g,'CappedAgent',BackoffAgent),patch.object(g,'GoedelClient',RecordedThenLive),patch.object(RequestPacer,'acquire',pace),patch.object(time,'sleep',sleep):g.execute(ROOT)
    assert RecordedThenLive.cursor==len(RecordedThenLive.tape)
    fresh=[json.loads(l) for l in (ROOT/'provider_transport.jsonl').read_text().splitlines()]
    g.write(ROOT/'delivery_origin.json',dict(historical_prefix_http_records=len(RecordedThenLive.tape),historical_prefix_decisions=27,
        fresh_http_attempts=len(fresh),fresh_delivered_decisions=sum('response' in x for x in fresh),
        note='summary usage includes historical replay metadata. Only provider_transport.jsonl in this root represents new HTTP attempts. Prefix metadata must not be counted twice.'))
    g.write(ROOT/'output_manifest.json',{p.relative_to(ROOT).as_posix():g.digest(p) for p in ROOT.rglob('*') if p.is_file() and p.name!='output_manifest.json'})


if __name__=='__main__':main()
