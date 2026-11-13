"""R052: fixed-history original/timed reflection comparison; no trading.

Prepare freezes exact runtime-generated messages before any provider request.
Run is single-use, budgeted and fail-fast. No automatic follow-on experiment.
"""
import argparse
from copy import deepcopy
import csv
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import subprocess
from types import SimpleNamespace
import zipfile

import numpy as np
import yaml

from sim.agents.llm_agent import LLMAgent
from sim.llm.client import LLMClient
from sim.llm.usage import UsageBudget
from sim.timed_feedback import agent_class, labelled_outcome

BASE = Path(__file__).resolve().parents[1]
PARENT = BASE / 'runs/20261105_041035_common_prefix_ca10f93d'
LEDGER = BASE / 'runs/feedback_audit_20261106/reflection_ledger.json'
VERSION = 'matched_first_reflection_v1_original_vs_timed'
PROFILE = dict(model='qwen-3.8-27b', base_url='https://bharatcode.ai/api/model/v1',
               reasoning_effort='low', timeout=180, send_temperature=True)
LIMITS = dict(max_requests=80, max_reserved_tokens=1600000,
              requests_per_minute=10, input_tokens_per_minute=60000,
              max_cost_usd=0, stop_on_api_error=True)


def read(p):
    return json.loads(Path(p).read_text(encoding='utf-8'))


def write(p, value):
    Path(p).write_text(json.dumps(value, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def digest(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def rows(p):
    with Path(p).open(newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def capture(cls, actor, persona, memory, config):
    """Obtain the actual implementation's reflection prompt, without a client."""
    captured = []
    trader = cls(actor, 10000, 100, np.random.default_rng(52), persona=persona,
                 params=dict(condition='C', reflect_every=5, memory_window=5,
                             tick=config['market']['tick']),
                 transaction_tax=config['market']['transaction_tax'],
                 price_band=config['market']['price_band'])
    trader.memory = deepcopy(memory)

    def request(messages, *args, **kwargs):
        captured.append(deepcopy(messages))
        return 'Offline capture only.', dict(status='returned', response_metadata={}, call_id='capture')

    trader._request = request
    trader.reflect_if_due(SimpleNamespace(round=5, total_rounds=12))
    assert len(captured) == 1
    return captured[0]


def definitions():
    ledger = read(LEDGER)
    inputs = {LEDGER.relative_to(BASE).as_posix(): digest(LEDGER)}
    cases = {}
    for record in ledger:
        if record['round'] != 5 or record['branch'] != 1:
            continue
        prefix, actor = record['prefix'], record['agent_id']
        root = PARENT/'prefixes'/prefix
        for name in ('calls.json', 'initial_state.csv', 'agents_state.csv', 'personas.json', 'config.yaml'):
            p = root/name
            inputs[p.relative_to(BASE).as_posix()] = digest(p)
        source = BASE/record['source']
        inputs[record['source']] = digest(source)
        original_call = json.loads(source.read_text(encoding='utf-8').splitlines()[record['line']-1])
        assert original_call['messages'] == record['messages']
        counterparts = [r for r in ledger if r['round']==5 and r['prefix']==prefix and r['agent_id']==actor]
        assert len(counterparts)==2 and all(r['messages']==record['messages'] for r in counterparts)
        memory = json.loads(record['messages'][1]['content'].split('\nVerified recent outcomes: ',1)[1])
        assert [o['round'] for o in memory] == list(range(1,6))
        decisions = {c['round']:c for c in read(root/'calls.json') if c['agent_id']==actor}
        states = {int(r['round']):r for r in rows(root/'agents_state.csv') if r['agent_id']==actor}
        states[0] = next(r for r in rows(root/'initial_state.csv') if r['agent_id']==actor)
        timed, decision_times = [], []
        for outcome in memory:
            rnd = outcome['round']; user = decisions[rnd]['messages'][1]['content']
            price = json.loads(re.search(r'Recent auction closing prices \(old to new\): (\[[^\n]+\])',user)[1])[-1]
            account = {k:(int(states[rnd-1][k]) if k=='shares' else float(states[rnd-1][k]))
                       for k in ('cash','shares','avg_cost','wealth')}
            observed = re.search(r'Your account: cash ([^,]+), shares (\d+) \(avg cost ([^)]+)\), total wealth ([^.]+(?:\.\d+)?).',user)
            assert observed
            assert [float(v) for v in observed.groups()] == [account[k] for k in ('cash','shares','avg_cost','wealth')]
            d = dict(round=rnd,last_observed_price=price,opening_account=account)
            assert price == record['decision_contexts'][rnd-1]['last_price_available']
            assert json.loads(decisions[rnd]['raw'])['reasoning'] == outcome['requested_order']['reasoning']
            decision_times.append(d); timed.append(labelled_outcome(outcome,d))
        persona = read(root/'personas.json')[actor]
        config = yaml.safe_load((root/'config.yaml').read_text())
        original = capture(LLMAgent, actor, persona, memory, config)
        assert original == record['messages'], 'Original runtime prompt differs from saved first reflection'
        revised = capture(agent_class(), actor, persona, timed, config)
        cases[prefix+'_'+actor] = dict(prefix=prefix,agent_id=actor,source=record['source'],source_line=record['line'],
            messages=dict(original=original,timed=revised),original_memory=memory,timed_memory=timed,
            decision_times=decision_times,persona=persona)
    assert len(cases)==12 and len({v['prefix'] for v in cases.values()})==6
    return cases, inputs


def prepare(root):
    cases, inputs = definitions()
    root=Path(root);root.mkdir(parents=True,exist_ok=False)
    write(root/'cases.json',cases)
    paths=[*sorted((BASE/'sim').rglob('*.py')), Path(__file__), BASE/'tests/test_feedback_validation.py']
    hashes={p.relative_to(BASE).as_posix():digest(p) for p in paths}
    with zipfile.ZipFile(root/'source.zip','x',zipfile.ZIP_DEFLATED) as z:
        for p in paths:z.write(p,p.relative_to(BASE).as_posix())
    schedule=[];keys=sorted(cases)
    for rep in (1,2):
        for j in range(12):
            key=keys[(j+rep-1)%12]
            for fmt in (('original','timed') if (j+rep)%2 else ('timed','original')):
                schedule.append(dict(case=key,format=fmt,repetition=rep))
    normal_reservations=sum(len(json.dumps(cases[s['case']]['messages'][s['format']],ensure_ascii=False).encode())+256+8192 for s in schedule)
    assert normal_reservations < LIMITS['max_reserved_tokens']
    write(root/'protocol.json',dict(version=VERSION,status='frozen_before_calls',created_utc=datetime.now(timezone.utc).isoformat(),
        parent_revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=BASE,text=True).strip(),
        working_tree_status=subprocess.check_output(['git','status','--short'],cwd=BASE,text=True).splitlines(),
        libraries={n:importlib.metadata.version(n) for n in ('numpy','PyYAML')},
        source_sha256=hashes,source_zip_sha256=digest(root/'source.zip'),inputs_sha256=inputs,
        cases_sha256=digest(root/'cases.json'),schedule=schedule,profile=PROFILE,limits=LIMITS,
        temperature=0.,max_tokens=8192,json_mode=False,normal_reservation_estimate=normal_reservations,
        design='All12unique first-reflection actor histories from all6R047prefixes;two fresh draws per original/timed format=48. Three original exogenous seeds,two inherited histories each,two personas. Existing branch1/2first reflection prompts match. No cases selected by errors or financial results;round10excluded because endogenous histories and inherited diaries diverge.',
        intervention='Original actual reflection prompt versus exact timed_feedback_v1 runtime prompt;same past trades/persona/no previous diary. Bundle adds explicit earlier observed prices/accounts,temporal labels,fallible-prose labels and execution constraints. Not a pure label,context-length-matched or cognitive mechanism test. Historical actions remain from original policy.',
        primary='Per delivered reflection,focused analyst-coded definite temporal misattribution: blaming an earlier explanation for not matching a clearing price/trend unavailable when that decision was made. Preserve exact evidence quotes and time-grounded rationale;ambiguous separately. Code full raw and retained first120whitespace-word diary separately. Report every context/format/draw;contrasts descriptive,not48independent markets.',
        secondary='Unsupported full-fill guarantees for market orders;whether prices/fills are discussed at all;other concrete factual contradictions as qualitative ancillary observations;actual model/usage/failure and context size. No mention is absence of detected target issue,not comprehensive correctness or proven comprehension.',
        scoring='Before-call rubric. Focused AI-assisted nonblinded review,not independent human adjudication. Acknowledging an actual erroneous earlier number/count is not a timing error. Wanting better fills is not a guarantee;explicit assurance/full execution is required. No desired score gates,automatic grader,repair or outcome-dependent resampling. Two repetitions attemperature0still unseeded provider calls.',
        failure_policy='First fatal provider,budget,wrong-model,empty or truncated output stops entire campaign after existing at-most-one identical-message transport/503 retry. Retain all attempts/missing slots. No retry of delivered prose,model substitution,cap increase,resume or automatic market continuation.',
        limitations='Fixed-history reflection content only;not subsequent choices,portfolio performance,full closed-loop C efficacy,held-out generalization,human realism or pure timing-label causal effect. Token ceiling is conservative reservation,not billing quote;zero configured prices mean dollars unavailable.'))
    write(root/'preparation.json',dict(protocol_sha256=digest(root/'protocol.json')))
    print(json.dumps(dict(root=str(root),cases=len(cases),calls=len(schedule),normal_reservations=normal_reservations)))
    return root


def validate(root):
    root=Path(root);p=read(root/'protocol.json')
    assert digest(root/'protocol.json')==read(root/'preparation.json')['protocol_sha256']
    assert digest(root/'cases.json')==p['cases_sha256'] and digest(root/'source.zip')==p['source_zip_sha256']
    for n,h in {**p['source_sha256'],**p['inputs_sha256']}.items():assert digest(BASE/n)==h,n
    return p


def execute(root, *, client=None, budget=None):
    root=Path(root);p=validate(root)
    with (root/'execution.json').open('x') as f:json.dump(dict(pid=os.getpid(),started_utc=datetime.now(timezone.utc).isoformat()),f)
    client=client or LLMClient(**p['profile']);budget=budget or UsageBudget(**p['limits'])
    cases=read(root/'cases.json');results=[];current={};status='running';failure=None
    with (root/'requests.jsonl').open('x',encoding='utf-8') as stream:
        def log(item):
            stream.write(json.dumps({**item,**current,'study_version':VERSION},allow_nan=False)+'\n');stream.flush()
        try:
            for i,item in enumerate(p['schedule'],1):
                current=dict(slot=i,**item)
                agent=LLMAgent('feedback_validation_'+str(i),0,0,np.random.default_rng(52),client=client,budget=budget,log_fn=log,
                              params=dict(condition='C',reflect_every=5,memory_window=5,max_tokens=8192,transport_retries=1,retry_http_503=True))
                raw,meta=agent._request(cases[item['case']]['messages'][item['format']],5,'reflection',temperature=0.,json_mode=False)
                if meta['status']!='returned' or not isinstance(raw,str) or not raw.strip():raise ValueError('missing_reflection')
                if meta['response_metadata'].get('model')!=p['profile']['model']:raise ValueError('unexpected_response_model')
                if meta['response_metadata'].get('finish_reason') in ('length','content_filter'):raise ValueError('incomplete_reflection')
                results.append(dict(**current,raw=raw,retained_diary=' '.join(raw.split()[:120]),raw_words=len(raw.split()),
                                    response_metadata=meta['response_metadata']))
                write(root/'results.json',results)
                write(root/'progress.json',dict(completed=len(results),planned=48,latest=current,usage=budget.snapshot()))
                print(f"completed {i}/48 {item['case']} {item['format']} rep{item['repetition']}",flush=True)
            status='completed'
        except Exception as exc:
            status='stopped';failure=type(exc).__name__
        finally:
            write(root/'results.json',results)
            summary=dict(status=status,failure_type=failure,last_slot=current,delivered=len(results),planned=48,
                         missing_slots=p['schedule'][len(results):],usage=budget.snapshot(),new_markets=0,
                         finished_utc=datetime.now(timezone.utc).isoformat())
            write(root/'summary.json',summary)
    write(root/'output_manifest.json',{x.name:digest(x) for x in root.iterdir() if x.is_file() and x.name!='output_manifest.json'})
    print(json.dumps(summary),flush=True)
    return summary


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=('prepare','run'));p.add_argument('--study',required=True);a=p.parse_args()
    (prepare if a.action=='prepare' else execute)(a.study)
