"""R047: common actual prefix, repeated B/C continuations, no simulator edits."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import csv
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import time
import uuid
import zipfile
import yaml
from sim.config import load_config,parse_config
from sim.llm.usage import RequestPacer
from sim.news_controls import FINANCIAL_FILES
from sim.provenance import sha256,write_json
from runs import quiet_components_20261105 as prior

BASE=prior.BASE
SOURCE=BASE/'runs/20261105_012335_quiet_components_5066abab'
VERSION='common_prefix_BC_v1_actual5_repeated_branches'
TARGETS=prior.TARGETS
USAGE=prior.USAGE


def read(path):return prior.read(path)


def lines(path):return prior.base.lines(path)


def prepare(output='runs'):
    prior.validate(SOURCE)
    root=Path(output).resolve()/(time.strftime('%Y%m%d_%H%M%S_')+'common_prefix_'+uuid.uuid4().hex[:8])
    root.mkdir(parents=True,exist_ok=False);(root/'prefixes').mkdir();(root/'configs').mkdir()
    old=read(BASE.parent/'thesis/sources.json')['prior_archives']
    audit_receipt=read(BASE/'runs/examiner_audit_20261105_evidence_manifest.json')
    old[Path(audit_receipt['path']).name]=audit_receipt['sha256']
    for name,digest in old.items():assert sha256(BASE/'runs'/name)==digest
    write_json(root/'prior_archives.json',old)
    prefixes=[];schedule=[]
    donors=[a for a in read(SOURCE/'runs.json') if a['mode']=='B']
    assert len(donors)==6
    for arm in sorted(donors,key=lambda a:(a['seed'],a['repetition'])):
        original=SOURCE/arm['run_path'];prior.base.verify_market(original)
        assert sha256(original/'manifest.json')==arm['manifest_sha256']
        pid=f"s{arm['seed']}_source{arm['repetition']}";dest=root/'prefixes'/pid;dest.mkdir()
        tape=[c for c in lines(original/'llm_requests.jsonl') if c['record_type']=='model_call' and c['round']<=5]
        assert len(tape)==10 and all(c['status']=='returned' and c['call_type']=='decision' and c['json_attempt']==c['transport_attempt']==1 for c in tape)
        write_json(dest/'calls.json',tape)
        for name in FINANCIAL_FILES:
            with (original/name).open(newline='',encoding='utf-8') as stream:
                reader=csv.DictReader(stream);fields=reader.fieldnames
                selected=[r for r in reader if 'round' not in r or int(r['round'])<=5]
            with (dest/name).open('w',newline='',encoding='utf-8') as stream:
                writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader();writer.writerows(selected)
        for name in ('personas.json','config.yaml'):shutil.copyfile(original/name,dest/name)
        shutil.copyfile(original/'manifest.json',dest/'donor_manifest.json')
        write_json(dest/'outcomes.json',[x for x in lines(original/'agent_outcomes.jsonl') if x['outcome']['round']<=5])
        prefix=dict(prefix_id=pid,seed=arm['seed'],source_repetition=arm['repetition'],source_run=original.relative_to(BASE).as_posix(),
            source_manifest_sha256=sha256(original/'manifest.json'),source_request_log_sha256=sha256(original/'llm_requests.jsonl'),
            files={p.name:sha256(p) for p in dest.iterdir() if p.is_file()})
        prefixes.append(prefix)
        for mode in 'BC':
            for rep in (1,2):
                cfg=load_config(dest/'config.yaml').to_dict();cfg['name']=f'prefix_{pid}_{mode}_branch{rep}'
                cfg['agents'][-1]['llm'].update(condition=mode,reflect_every=5 if mode=='C' else 0)
                cfg['llm_limits'].update(max_requests=28,max_reserved_tokens=400000)
                path=root/'configs'/(cfg['name']+'.yaml');path.write_text(yaml.safe_dump(parse_config(cfg).to_dict()),encoding='utf-8')
                schedule.append(dict(prefix_id=pid,seed=arm['seed'],source_repetition=arm['repetition'],mode=mode,branch_repetition=rep,
                    config=path.relative_to(root).as_posix(),config_sha256=sha256(path)))
    random.Random(472047).shuffle(schedule)
    sources={p.relative_to(BASE).as_posix():sha256(p) for p in (BASE/'sim').rglob('*.py')}
    # Include ALL top-level research helpers,closing the R043 transitive import gap.
    sources.update({p.relative_to(BASE).as_posix():sha256(p) for p in (BASE/'runs').glob('*.py')})
    sources.update({p.relative_to(BASE).as_posix():sha256(p) for p in (BASE/'tests').glob('*.py')})
    with zipfile.ZipFile(root/'prepared_source.zip','x',zipfile.ZIP_DEFLATED) as archive:
        for name in sources:archive.write(BASE/name,name)
    shutil.copyfile(__file__,root/'driver_source.py')
    protocol=dict(version=VERSION,status='frozen_before_new_live_calls',created_utc=datetime.now(timezone.utc).isoformat(),
        parent_revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=BASE,text=True).strip(),
        working_tree_status=subprocess.check_output(['git','status','--short'],cwd=BASE,text=True).splitlines(),
        source_sha256=sources,source_archive_sha256=sha256(root/'prepared_source.zip'),prefixes=prefixes,schedule=schedule,
        prior_archives_sha256=sha256(root/'prior_archives.json'),
        design='ALL six R043 B actual first5 histories,3 exogenous seeds x2 source draws. Two fresh B and two fresh C continuations per prefix,rounds6-12. Cached first5 requests do not consume live budgets,pacer or provider tokens. All14 accounts must match before first fresh call.',
        treatment='C first reflects after5 on shared actual history,then after10 on its own continuation;B never reflects. Only diary policy differs,common economics/personas/facts/exogenous draws. A/B/C source/defaults remain selectable and unchanged.',
        primary='Within each prefix Cmean-Bmean across two fresh branches:mean absolute price/value gap6-12;each target conditional passive excess from COMMON closing5 accounts under BOTH auction/private marks,normalized by closing5 auction wealth;fresh model cost/failures. Show all4 paths and B1-B2/C1-C2 variation. Average prefix contrasts within seed,THREE exogenous histories,not24 independent scenarios.',
        secondary='First fresh decision6 intent/accepted/fills,continuation signed/gross execution/opportunity,MM/liquidity/counterpart accounts,reflection texts and source fidelity. Fixed post-treatment window;no sign-based gating or new scalar winner.',
        profile=dict(model='qwen-3.8-27b',base_url='https://bharatcode.ai/api/model/v1',max_tokens=8192,reasoning_effort='low',decision_temperature=.3,reflection_temperature=0,timeout_seconds=180,memory_window=5,provider_seed=None,backend_fingerprint=None),
        limits=dict(per_branch_requests=28,per_branch_reserved_tokens=400000,campaign_requests=672,campaign_reserved_tokens=9600000,normal_live_decisions=336,normal_live_reflections=48,normal_live_calls=384,cached_prefix_decisions=240),
        schedule_seed=472047,
        failure_policy='First fatal provider/output/budget or operationally affected branch stops entire campaign. Existing shared one identical-message transport/503 extra attempt and JSON repair policy retained;any repair flags affected. No continuation amendment,restart,selected resample,splicing,model switch or billing. Partial prefixes and fresh missing/uncleared outcomes remain explicit.',
        limitations='Six selected-by-protocol existing B histories nest in3 exogenous scenarios;no fresh population or unconditional mean-policy claim. Small unseeded branch samples and unpinned provider backend. Matched prefix removes observed pre-treatment state imbalance but does not guarantee stable provider draws or universal causal/human-realism conclusions. Treatment is the generated-diary policy bundle;no length-matched sham diary separates added context from reflection content. Replay is not a fresh sample. No novelty claim from architecture alone.')
    write_json(root/'protocol.json',protocol);write_json(root/'preparation.json',dict(protocol_sha256=sha256(root/'protocol.json')))
    print(f'prepared -> {root}',flush=True);return root


def validate(root):
    root=Path(root);p=read(root/'protocol.json')
    assert p['version']==VERSION and sha256(root/'protocol.json')==read(root/'preparation.json')['protocol_sha256']
    for name,digest in p['source_sha256'].items():assert sha256(BASE/name)==digest,name
    assert sha256(root/'prepared_source.zip')==p['source_archive_sha256']
    assert sha256(root/'prior_archives.json')==p['prior_archives_sha256']
    for prefix in p['prefixes']:
        for name,digest in prefix['files'].items():assert sha256(root/'prefixes'/prefix['prefix_id']/name)==digest
    for arm in p['schedule']:assert sha256(root/arm['config'])==arm['config_sha256']
    return p


@contextmanager
def context(prefix_path,*,offline=False):
    prefix_path=Path(prefix_path);tape={(c['agent_id'],c['round']):c for c in read(prefix_path/'calls.json')}
    closing={r['agent_id']:r for r in prior.base.read_rows(prefix_path/'agents_state.csv') if r['round']=='5'}
    state=dict(agents={},prefix_requests=0,first_live_gate=False)
    with prior.disclosure():
        previous=prior.base.engine.LLMAgent;build=prior.base.engine.build_agents
        def capture(*args,**kwargs):
            agents=build(*args,**kwargs);state['agents']=agents;return agents
        class PrefixAgent(previous):
            def __init__(self,*args,**kwargs):
                original=kwargs.get('log_fn') or (lambda r:None)
                def log(record):original({**record,'prompt_version':VERSION+':'+str(record.get('condition')),'common_prefix_version':VERSION})
                kwargs['log_fn']=log;super().__init__(*args,**kwargs)
            def _request(self,messages,rnd,kind,attempt=1,*,temperature=None,json_mode=True):
                if kind=='decision' and rnd<=5:
                    assert attempt==1;call=tape[self.agent_id,rnd]
                    assert messages==call['messages'],'Prefix messages differ from original B history'
                    assert self.temperature==call['temperature']==.3 and self.params['max_tokens']==call['max_tokens']==8192
                    assert json_mode==call['json_mode'] and getattr(self.client,'reasoning_effort',None)==call['reasoning_effort']
                    meta=dict(status='returned',messages=messages,raw=call['raw'],call_type=kind,round=rnd,
                        json_attempt=1,transport_attempt=1,call_id=f'{self.agent_id}:{rnd}:cached_prefix',
                        response_metadata={**call['response_metadata'],'recorded_prefix':True},
                        prefix_replay=True,new_http_request=False,usage=None,source_call_id=call['call_id'])
                    self.log_fn(dict(record_type='prefix_replay_call',agent_id=self.agent_id,condition=self.condition,**meta))
                    state['prefix_requests']+=1
                    return call['raw'],meta
                if offline:raise RuntimeError('Fresh request forbidden in prefix-only gate')
                if not state['first_live_gate']:
                    assert state['prefix_requests']==10
                    for aid,agent in state['agents'].items():
                        expected=closing[aid]
                        assert agent.cash==float(expected['cash']) and agent.shares==int(expected['shares']) and agent.avg_cost==float(expected['avg_cost']),aid
                    state['first_live_gate']=True
                    self.log_fn(dict(record_type='first_live_state_gate',agent_id=self.agent_id,condition=self.condition,round=rnd,all14_accounts_equal=True))
                return super()._request(messages,rnd,kind,attempt,temperature=temperature,json_mode=json_mode)
        # Retain the inherited economic-agent type label in state CSVs;
        # research adapter identity is separately versioned in request logs.
        PrefixAgent.__name__=previous.__name__
        prior.base.engine.LLMAgent=PrefixAgent;prior.base.engine.build_agents=capture
        try:yield state
        finally:prior.base.engine.LLMAgent=previous;prior.base.engine.build_agents=build


def prefix_check(prefix_path,path):
    for name in FINANCIAL_FILES:
        original=prior.base.read_rows(Path(prefix_path)/name)
        rows=[r for r in prior.base.read_rows(Path(path)/name) if 'round' not in r or int(r['round'])<=5]
        assert rows==original,(name,'prefix drift')
    assert read(Path(path)/'personas.json')==read(Path(prefix_path)/'personas.json')


def prefix_gates(root):
    root=Path(root);p=validate(root)
    if (root/'prefix_gate_summary.json').exists():
        assert read(root/'prefix_gate_summary.json')['status']=='passed'
        for entry in read(root/'prefix_gate_runs.json'):
            path=root/entry['run_path'];prior.base.verify_market(path)
            assert sha256(path/'manifest.json')==entry['manifest_sha256']
            prefix_check(root/'prefixes'/entry['prefix_id'],path)
        return
    class NoClient:
        def __init__(self,model,base_url,reasoning_effort=None,send_temperature=True,**kwargs):
            self.model=model;self.base_url=base_url;self.reasoning_effort=reasoning_effort;self.send_temperature=send_temperature;self.total_tokens=0
        def chat(self,*args,**kwargs):raise RuntimeError('Provider forbidden in prefix gate')
    from unittest.mock import patch
    index=[]
    for prefix in p['prefixes']:
        for mode in 'BC':
            arm=next(a for a in p['schedule'] if a['prefix_id']==prefix['prefix_id'] and a['mode']==mode)
            cfg=load_config(root/arm['config']).to_dict();cfg['rounds']=5;cfg['llm_limits'].update(max_requests=0,max_reserved_tokens=0)
            config=root/'configs'/f"gate_{prefix['prefix_id']}_{mode}.yaml";config.write_text(yaml.safe_dump(cfg))
            with patch.object(prior.base.engine,'LLMClient',NoClient),context(root/'prefixes'/prefix['prefix_id'],offline=True) as state:
                path=Path(prior.base.engine.run(config,output_root=root/'prefix_gate_runs'))
            prefix_check(root/'prefixes'/prefix['prefix_id'],path);ss=read(path/'summary.json')
            for name in FINANCIAL_FILES:assert sha256(path/name)==sha256(root/'prefixes'/prefix['prefix_id']/name)
            assert ss['status']=='completed' and ss['rounds']==5 and ss['llm_usage']['requests_made']==0 and state['prefix_requests']==10
            index.append(dict(prefix_id=prefix['prefix_id'],mode=mode,run_path=path.relative_to(root).as_posix(),manifest_sha256=sha256(path/'manifest.json')))
    write_json(root/'prefix_gate_runs.json',index)
    write_json(root/'prefix_gate_summary.json',dict(status='passed',prefix_paths=12,replayed_requests=120,new_api_requests=0,financial_prefix_files_compared=84))


def execute(root):
    root=Path(root);p=validate(root)
    if (root/'execution.json').exists():raise ValueError('Study already started;never restart')
    if any((x/'execution.json').exists() for x in root.parent.glob('*_common_prefix_*') if x.resolve()!=root.resolve()):raise ValueError('Campaign version already attempted')
    prefix_gates(root)
    with (root/'execution.json').open('x') as stream:json.dump(dict(pid=os.getpid(),started_utc=datetime.now(timezone.utc).isoformat()),stream)
    pacer=RequestPacer(10,60000);index=[];status='running';failure=None
    try:
        for arm in p['schedule']:
            write_json(root/'progress.json',dict(status='running',recorded_branches=len(index),active=arm))
            with context(root/'prefixes'/arm['prefix_id']) as state:
                path=Path(prior.base.engine.run(root/arm['config'],output_root=root/'branch_runs',request_pacer=pacer))
            ss=read(path/'summary.json');prior.base.verify_market(path)
            prefix_check(root/'prefixes'/arm['prefix_id'],path)
            failures={k:ss[k] for k in ('parse_failures','api_failures','reflection_failures','output_truncations','json_repairs')}
            entry={**arm,'run_path':path.relative_to(root).as_posix(),'manifest_sha256':sha256(path/'manifest.json'),
                'status':ss['status'],'rounds':ss['rounds'],'usage':ss['llm_usage'],'operational_failures':failures,
                'cached_prefix_requests':state['prefix_requests'],'first_live_state_gate':state['first_live_gate']}
            index.append(entry);write_json(root/'runs.json',index)
            assert sum(a['usage']['requests_made'] for a in index)<=672 and sum(a['usage']['reserved_tokens'] for a in index)<=9600000
            if ss['status']!='completed' or ss['rounds']!=12 or any(failures.values()):status='stopped';failure=ss['failure_type'] or 'operational_fallback';break
            assert state['first_live_gate'] and state['prefix_requests']==10
            print(f"completed {arm['prefix_id']} {arm['mode']} branch{arm['branch_repetition']}",flush=True)
        else:status='completed'
    except BaseException as exc:status='interrupted' if isinstance(exc,KeyboardInterrupt) else 'failed';failure=type(exc).__name__;raise
    finally:
        summary=dict(status=status,recorded_branches=len(index),planned_branches=24,
            completed_branches=sum(a['status']=='completed' and a['rounds']==12 and not any(a['operational_failures'].values()) for a in index),
            failure_type=failure,usage={k:sum(a['usage'][k] for a in index) for k in USAGE},
            cached_prefix_requests=sum(a['cached_prefix_requests'] for a in index),finished_utc=datetime.now(timezone.utc).isoformat())
        write_json(root/'summary.json',summary);write_json(root/'progress.json',dict(**summary,active=None))
    print(json.dumps(summary),flush=True);return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=('prepare','gates','run'));parser.add_argument('--study');parser.add_argument('--output',default='runs');args=parser.parse_args()
    if args.action=='prepare':prepare(args.output)
    elif args.action=='gates':prefix_gates(args.study)
    else:execute(args.study)
