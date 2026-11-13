"""R043: fresh quiet endogenous A/B/C replication, frozen before live calls."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import uuid
import zipfile
import yaml
from sim.agents.llm_agent import CONDITION_VERSIONS
from sim.config import load_config, parse_config
from sim.evaluation import evaluate_run, read_rows
from sim.llm.usage import RequestPacer
from sim.provenance import sha256, write_json
from runs import initial_news_20261104 as base

BASE = base.BASE
VERSION = 'quiet_components_v1_hidden_honest_prior'
SEEDS = (22853, 23971, 25087)
ROUNDS = 12
TARGETS = base.TARGETS
USAGE = base.USAGE


def read(path): return base.read(path)


@contextmanager
def disclosure():
    with base.disclosure():
        previous = base.engine.LLMAgent
        class QuietAgent(previous):
            def __init__(self, *args, **kwargs):
                original = kwargs.get('log_fn') or (lambda record: None)
                def log(record):
                    condition = record.get('condition')
                    original({**record, 'upstream_prompt_version': record.get('prompt_version'),
                        'base_prompt_version': CONDITION_VERSIONS[condition] if condition in CONDITION_VERSIONS else None,
                        'prompt_version': VERSION+':'+str(condition), 'quiet_components_version': VERSION})
                kwargs['log_fn'] = log
                super().__init__(*args, **kwargs)
        base.engine.LLMAgent = QuietAgent
        try: yield
        finally: base.engine.LLMAgent = previous


def recipe(seed, mode, repetition=0):
    raw = base.recipe(seed, 'quiet', mode).to_dict()
    raw['name'] = f'quiet_components_{mode}_s{seed}_rep{repetition}'
    raw['rounds'] = ROUNDS
    assert not raw['news']
    if mode != 'rules':
        raw['llm_limits'].update(max_requests=36, max_reserved_tokens=550000)
    return parse_config(raw)


def prepare(output='runs'):
    root = Path(output)/(time.strftime('%Y%m%d_%H%M%S_')+'quiet_components_'+uuid.uuid4().hex[:8])
    root.mkdir(parents=True, exist_ok=False)
    (root/'configs').mkdir()
    def save(seed, mode, repetition=0):
        cfg = recipe(seed, mode, repetition)
        path = root/'configs'/(cfg.name+'.yaml')
        path.write_text(yaml.safe_dump(cfg.to_dict()), encoding='utf-8')
        return dict(seed=seed, mode=mode, repetition=repetition,
                    config=path.relative_to(root).as_posix(), config_sha256=sha256(path))
    baselines = [save(seed, 'rules') for seed in SEEDS]
    blocks = []
    for i, seed in enumerate(SEEDS):
        arms = []
        for rep in (1, 2):
            shift = (i+rep-1) % 3
            modes = list('ABC')[shift:]+list('ABC')[:shift]
            arms.extend(save(seed, mode, rep) for mode in modes)
        blocks.append(dict(seed=seed, arms=arms))
    sources = {p.relative_to(BASE).as_posix(): sha256(p) for p in (BASE/'sim').rglob('*.py')}
    for name in ('quiet_components_20261105.py', 'initial_news_20261104.py',
                 'horizon_pilot_20261104.py', 'sequential_tail_20261104.py'):
        sources['runs/'+name] = sha256(BASE/'runs'/name)
    with zipfile.ZipFile(root/'prepared_source.zip', 'x', zipfile.ZIP_DEFLATED) as archive:
        for name in sources: archive.write(BASE/name, name)
    shutil.copyfile(__file__, root/'driver_source.py')
    protocol = dict(version=VERSION, status='frozen_before_any_markets', created_utc=datetime.now(timezone.utc).isoformat(),
        parent_revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=BASE,text=True).strip(),
        working_tree_status=subprocess.check_output(['git','status','--short'],cwd=BASE,text=True).splitlines(),
        source_sha256=sources, source_archive_sha256=sha256(root/'prepared_source.zip'), driver_sha256=sha256(__file__),
        baselines=baselines, blocks=blocks, seeds=list(SEEDS), repetitions=2, rounds=ROUNDS,
        prompt_suite='comparable_agents_v2_disclosed_rules', condition_versions=CONDITION_VERSIONS,
        question='Do factual summaries or own-history reflections show repeatable policy-level differences in fresh quiet matched markets, and at what token cost?',
        common_design='No news or fundamental shifts. Same initial resources/personas/economics, MMskew.02/window1. Hidden recording length, continuing stock and honest initialization prior from common R036 adapter applied to ALL modes. Actual modes A raw/B factual summaries/C own endogenous history reflections after5/10. Production defaults/sim source unchanged.',
        profile=dict(model='qwen-3.8-27b',endpoint='https://bharatcode.ai/api/model/v1',max_tokens=8192,
            reasoning_effort='low',decision_temperature=.3,reflection_temperature=0,timeout_seconds=180,
            memory_window=5,provider_seed=None,backend_fingerprint=None,requests_per_minute=10,input_estimate_tokens_per_minute=60000),
        limits=dict(per_arm_requests=36,per_arm_reservations=550000,campaign_requests=648,campaign_reservations=9900000,
            normal_decisions=432,normal_reflections=24,normal_requests=456),
        primary='Descriptive B-A and C-B contrasts per seed/repeat: target full12 conditional passive excess returns under BOTH auction/private benchmark marks; whole-path mean absolute relative value gap; provider-reported tokens/reservations/failures. Show all signs and repeat-averaged contrasts within each of THREE exogenous seeds. No scalar winner, pvalue, profitability=realism or selected default.',
        secondary='Requested/accepted/executed sizing and fill opportunities; exposure, turnover/liquidity/MM inventory/participation; all counterpart accounts and both marks. Prespecified round1-5 pre-reflection and6-12 executed-flow summaries; B/C can differ before reflection through unseeded draws.',
        failure_policy='Existing one shared identical-message transport/503 extra attempt and engine JSON repair policy retained and logged. First fatal provider/output/budget or any operationally affected arm stops campaign; JSON repair also flags affected. No independent-arm continuation, resampling, restart, prefix splicing, delivery amendment or model/billing switch. Retain unknown usage and delivered-but-uncleared choices. Clean technical gates only, never gate on financial sign.',
        limitations='Three exogenous scenarios, two unseeded model trajectories per mode within each; not six independent seed replications. Short quiet markets cannot validate long-run stylized facts, human realism, news response or intrinsic LLM superiority. Treatment changes endogenous state/history; no paired provider seed, isolated same-history reflection effect, causal prose/trait claim or universal benefit. Old ambiguous-news/disclosed-horizon cohorts remain separate.')
    write_json(root/'protocol.json', protocol)
    write_json(root/'preparation.json', dict(protocol_sha256=sha256(root/'protocol.json')))
    print(f'prepared -> {root}', flush=True)
    return root


def validate(root):
    root = Path(root)
    p = read(root/'protocol.json')
    assert p['version']==VERSION and sha256(root/'protocol.json')==read(root/'preparation.json')['protocol_sha256']
    for name,digest in p['source_sha256'].items(): assert sha256(BASE/name)==digest, name
    assert sha256(root/'prepared_source.zip')==p['source_archive_sha256'] and sha256(root/'driver_source.py')==p['driver_sha256']
    for arm in p['baselines']+[a for b in p['blocks'] for a in b['arms']]:
        assert sha256(root/arm['config'])==arm['config_sha256']
        assert load_config(root/arm['config'])==recipe(arm['seed'],arm['mode'],arm['repetition'])
    return p


def baselines(root):
    root = Path(root)
    p = validate(root)
    if (root/'baseline_summary.json').exists():
        assert read(root/'baseline_summary.json')['status']=='completed'
        index = read(root/'baseline_runs.json')
        for arm in index:
            base.verify_market(root/arm['run_path'])
            assert sha256(root/arm['run_path']/'manifest.json')==arm['manifest_sha256']
        return index
    with (root/'baseline_execution.json').open('x') as stream: json.dump(dict(pid=os.getpid()),stream)
    index = []; status = 'failed'
    try:
        for arm in p['baselines']:
            path = Path(base.engine.run(root/arm['config'],output_root=root/'baseline_runs'))
            ss = read(path/'summary.json'); ev = evaluate_run(path); base.verify_market(path)
            assert ss['status']=='completed' and ss['rounds']==ROUNDS and ss['llm_usage']['requests_made']==0
            assert ss['initial_cash']==160000 and ss['total_shares']==1450 and ss['max_cash_conservation_error']<1e-7
            assert 0<=ev['metrics']['mm_inventory_min']<=ev['metrics']['mm_inventory_max']<=300
            assert all(abs(x)<1e-7 for x in ev['aggregate_active_minus_passive'].values())
            index.append({**arm,'run_path':path.relative_to(root).as_posix(),'manifest_sha256':sha256(path/'manifest.json')})
            write_json(root/'baseline_runs.json',index)
        status = 'completed'
    finally: write_json(root/'baseline_summary.json',dict(status=status,completed=len(index),planned=len(p['baselines'])))
    return index


def history_audit(path, mode):
    outcomes = base.lines(path/'agent_outcomes.jsonl')
    logs = base.lines(path/'llm_requests.jsonl')
    diaries = {(r['agent_id'],r['round']):r for r in base.lines(path/'llm_calls.jsonl') if r['record_type']=='reflection'}
    checked = 0; decoder = json.JSONDecoder()
    for call in logs:
        if call['record_type']!='model_call': continue
        assert call['condition']==mode and call['base_prompt_version']==CONDITION_VERSIONS[mode]
        assert call['prompt_version']==VERSION+':'+mode
        assert call['max_tokens']==8192 and call['reasoning_effort']=='low'
        if call['status']=='returned': assert call['response_metadata']['model']=='qwen-3.8-27b'
        aid=call['agent_id']; rnd=call['round']; user=call['messages'][1]['content']
        actual = [r['outcome'] for r in outcomes if r['agent_id']==aid and r['outcome']['round'] < rnd+(call['call_type']=='reflection')][-5:]
        if call['call_type']=='decision':
            assert call['temperature_sent']==.3 and user.startswith(f'Round {rnd}.')
            observed,_ = decoder.raw_decode(user.split('Your recent verified outcomes: ',1)[1])
            assert ('Computed facts' in user)==(mode in ('B','C'))
            prior = [r for (a,t),r in diaries.items() if a==aid and t<rnd and r.get('diary')]
            diary = max(prior,key=lambda r:r['round'])['diary'] if prior else ''
            assert ('Your reflection (beliefs may be wrong): ' in user)==bool(diary)
            if diary: assert 'Your reflection (beliefs may be wrong): '+diary+'\n' in user
            assert ('Initialization references:' in user)==(rnd==1)
        else:
            assert mode=='C' and call['temperature_sent']==0 and rnd in (5,10)
            observed = json.loads(user.split('\nVerified recent outcomes: ',1)[1])
            prior = [r for (a,t),r in diaries.items() if a==aid and t<rnd and r.get('diary')]
            previous = max(prior,key=lambda r:r['round'])['diary'] if prior else 'none'
            assert user.startswith('Previous reflection (fallible): '+previous+'\n')
        assert observed==actual
        checked+=1
    return dict(actual_history_requests_checked=checked,reflections_recorded=len(diaries))


def initial_gates(root, entries):
    reference=root/entries[0]['run_path']; first={}
    for entry in entries:
        path=root/entry['run_path']
        assert base.resources(path)==base.resources(reference) and read(path/'personas.json')==read(reference/'personas.json')
        background=lambda p:[r for r in read_rows(p/'orders.csv') if r['round']=='1' and r['agent_id'] not in TARGETS]
        assert background(path)==background(reference)
        calls=[c for c in base.lines(path/'llm_requests.jsonl') if c['record_type']=='model_call' and c['round']==1 and c['json_attempt']==c['transport_attempt']==1]
        assert len(calls)==2
        first[entry['mode'],entry['repetition']]={c['agent_id']:c['messages'] for c in calls}
    for aid in TARGETS:
        messages=[m[aid] for m in first.values()]
        assert all(m[0]==messages[0][0] for m in messages)
        for rep in (1,2): assert first['B',rep][aid]==first['C',rep][aid]
        assert first['A',1][aid]==first['A',2][aid] and first['B',1][aid]==first['B',2][aid]
        a=first['A',1][aid][1]['content']; b=first['B',1][aid][1]['content']
        prefix,tail=b.split('Computed facts (derived from the same observations, no recommendation): ',1)
        _,remaining=json.JSONDecoder().raw_decode(tail)
        assert prefix+tail[remaining+1:]==a
    return dict(initial_resources_personas_backgrounds_and_system_equal=True,BC_initial_messages_equal=True)


def execute(root):
    root=Path(root); p=validate(root)
    if (root/'execution.json').exists(): raise ValueError('Study already started; never rerun')
    if any((x/'execution.json').exists() for x in root.parent.glob('*_quiet_components_*') if x.resolve()!=root.resolve()):
        raise ValueError('Campaign version already attempted')
    refs=baselines(root)
    with (root/'execution.json').open('x') as stream:json.dump(dict(pid=os.getpid(),started_utc=datetime.now(timezone.utc).isoformat(),protocol_sha256=sha256(root/'protocol.json')),stream)
    pacer=RequestPacer(10,60000); index=[]; checks=[]; status='running'; failure=None
    try:
        for block in p['blocks']:
            for arm in block['arms']:
                write_json(root/'progress.json',dict(status='running',recorded_markets=len(index),active=arm))
                with disclosure(): path=Path(base.engine.run(root/arm['config'],output_root=root/'market_runs',request_pacer=pacer))
                ss=read(path/'summary.json'); manifest=base.verify_market(path)
                manifest['research_adapter']=dict(version=VERSION,protocol_sha256=sha256(root/'protocol.json'),driver_sha256=p['driver_sha256'],common_horizon='hidden',initial_reference='explicit_prior_reference_v1')
                write_json(path/'manifest.json',manifest)
                failures={k:ss[k] for k in ('parse_failures','api_failures','reflection_failures','output_truncations','json_repairs')}
                entry={**arm,'run_path':path.relative_to(root).as_posix(),'manifest_sha256':sha256(path/'manifest.json'),
                    'status':ss['status'],'rounds':ss['rounds'],'usage':ss['llm_usage'],'operational_failures':failures}
                index.append(entry);write_json(root/'runs.json',index)
                ref=root/next(r['run_path'] for r in refs if r['seed']==arm['seed'])
                assert base.resources(path)==base.resources(ref) and ss['max_cash_conservation_error']<1e-7
                assert [r['dividend'] for r in read_rows(path/'prices.csv')]==[r['dividend'] for r in read_rows(ref/'prices.csv')[:ss['rounds']]]
                assert sum(x['usage']['requests_made'] for x in index)<=648 and sum(x['usage']['reserved_tokens'] for x in index)<=9900000
                entry['history_audit']=history_audit(path,arm['mode']);write_json(root/'runs.json',index)
                if ss['status']!='completed' or ss['rounds']!=ROUNDS or any(failures.values()):
                    status='stopped';failure=ss['failure_type'] or 'operational_fallback';break
                assert entry['history_audit']['reflections_recorded']==(4 if arm['mode']=='C' else 0)
                print(f"completed {arm['seed']} rep{arm['repetition']} {arm['mode']}",flush=True)
            if status=='stopped':break
            checks.append(dict(seed=block['seed'],**initial_gates(root,index[-6:])))
            write_json(root/'block_checks.json',checks)
        else:status='completed'
    except BaseException as exc:
        status='interrupted' if isinstance(exc,KeyboardInterrupt) else 'failed';failure=type(exc).__name__;raise
    finally:
        summary=dict(status=status,recorded_markets=len(index),planned_markets=18,
            completed_markets=sum(e['status']=='completed' and e['rounds']==ROUNDS and not any(e['operational_failures'].values()) for e in index),
            completed_seed_checks=len(checks),failure_type=failure,usage={k:sum(e['usage'][k] for e in index) for k in USAGE},finished_utc=datetime.now(timezone.utc).isoformat())
        write_json(root/'summary.json',summary);write_json(root/'progress.json',dict(**summary,active=None))
    print(json.dumps(summary),flush=True)
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=('prepare','baselines','run'))
    parser.add_argument('--study');parser.add_argument('--output',default='runs');args=parser.parse_args()
    if args.action=='prepare':prepare(args.output)
    elif args.action=='baselines':baselines(Path(args.study))
    else:execute(Path(args.study))
