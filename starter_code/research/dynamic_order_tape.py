"""R055: dynamic rules with fixed original accepted LLM order tapes; zero API.

Not adaptive LLM counterfactuals: future tape choices came from factual histories.
All eighteen uncapped tape paths must reproduce before any intervention path.
"""
import argparse
from contextlib import contextmanager
from dataclasses import replace
import json
import os
from pathlib import Path
import socket
from unittest.mock import patch
import yaml
from sim.agents.llm_agent import LLMAgent
from sim.llm.client import LLMClient
from sim.market import Order
import sim.engine as engine
from research.order_influence import BASE,DONOR,TARGETS,read,write,digest,rows
from research.goedel_cohort import freeze,validate,strict_accounting,audit_financial,metrics

VERSION='R055_dynamic_rules_fixed_accepted_LLM_tape_v1'


class OfflineClient(LLMClient):
    def __init__(self,*args,**kwargs):super().__init__(*args,api_key='offline-no-network',**kwargs)
    def chat(self,*args,**kwargs):raise RuntimeError('Network forbidden in fixed-tape study')


def tape_agent(tape,condition):
    assert condition in ('uncapped','cap10','remove')
    class TapeAgent(LLMAgent):
        def decide(self,obs):
            record=tape[(self.agent_id,obs.round)]
            o=Order(self.agent_id,record['side'],int(record['quantity']),float(record['limit_price']) if record['limit_price'] else None,obs.round,
                    'Fixed factual accepted-order tape;not a fresh/adaptive LLM decision')
            if condition=='cap10':o=replace(o,quantity=min(10,o.quantity))
            if condition=='remove':o=Order(self.agent_id,'hold',0,None,obs.round,'Target orders suppressed')
            self.last_intent=dict(o.__dict__)
            return self.validate(o,obs.price_history[-1])
        def reflect_if_due(self,obs):return None
    return TapeAgent


@contextmanager
def offline(tape,condition):
    Agent=tape_agent(tape,condition)
    def forbidden(*args,**kwargs):raise RuntimeError('No network permitted')
    with patch.object(engine,'LLMAgent',Agent),patch.object(engine,'LLMClient',OfflineClient),strict_accounting(Agent),\
         patch.object(socket.socket,'connect',forbidden),patch.object(socket,'create_connection',forbidden):yield


def prepare(root):
    root=Path(root).resolve();root.mkdir(parents=True,exist_ok=False)
    donor=read(BASE/'runs/order_influence_20261107/protocol.json')
    for n,h in donor['inputs_sha256'].items():assert digest(BASE/n)==h,n
    protocol=dict(version=VERSION,study='R055',status='frozen_before_dynamic_interventions',arms=donor['arms'],donor=donor['donor'],
        inputs_sha256=donor['inputs_sha256'],
        conditions=['cap10','remove'],control='uncapped original accepted tape with resource revalidation;all18controlpaths first',
        dynamic_paths=36,control_paths=18,rounds=12,original_exogenous_seeds=3,
        question='Does limiting or suppressing recorded LLM order flow change multi-round price variability and maker inventory when all rule agents react to the evolving branch?',
        primary='Within each inherited path,cap10-minus-uncapped population SD of12logprice returns(includinginitialprice),and maker0/300boundaryfraction. All18 pathcontrasts and3seed means;no inferential independence across modes/draws/sessions.',
        secondary='Removal same endpoints;referencegap,maxdrawdown,inventoryrange,volume andtargetparticipation. Report allsigns;no preferredsign gate. No ACF/stylizedfacts inference from12sessions.',
        state='Regenerate rule decisions from branch price history,holdings,cash,dividend-memory and private RNG. Branch clearing RNG evolves naturally;same initial generators andexogenousdividends. Allcash/shares/avgcost/income propagate. Targets replay original ACCEPTED side/quantity/absolute limit at eachtime,then cap10 if applicable,then revalidate on branch resources. Suppressionkeepsownedresources.',
        gate='All216factualprices/trades and3024closingaccounts must match regenerateduncapped controls beforeany36interventionpaths. Exactshares/cash<=1e-7 atsettlement/closing,independent allaccountaudit.',
        limitations='Semi-endogenous fixed-tape sensitivity,NOT adaptiveLLM policycounterfactual. LaterLLMchoices were generatedfrom factualhistories thatmaynotoccur inbranch;absolute limits may become stale. No newprovider draws,independentseeds or permanentcapbehavioralclaim. Removal is specified12rule+2passiveaccount system,not cash/share redistribution. Short12rounds cannot establish long-runstability.',
        failure_policy='Single-use gate/run;first mismatch or invariant failure stops. Preserve failures;no silent rerun/tape adjustment or forward filling.')
    freeze(root,protocol,['research/dynamic_order_tape.py','tests/test_dynamic_order_tape.py'])
    print(json.dumps(read(root/'preparation.json')))


def one(root,arm,condition):
    donor=BASE/read(root/'protocol.json')['donor']/arm['run_path']
    tape={(r['agent_id'],int(r['round'])):r for r in rows(donor/'orders.csv') if r['agent_id'] in TARGETS}
    assert len(tape)==24
    with offline(tape,condition):path=Path(engine.run(donor/'config.yaml',output_root=root/condition))
    s=read(path/'summary.json')
    assert s['status']=='completed' and s['rounds']==12 and s['llm_usage']['requests_made']==0
    original=rows(donor/'prices.csv');actual=rows(path/'prices.csv')
    assert [r['dividend'] for r in original]==[r['dividend'] for r in actual]
    audit=audit_financial(path)
    result=dict(seed=arm['seed'],mode=arm['mode'],repetition=arm['repetition'],condition=condition,
        donor_path=arm['run_path'],run_path=path.relative_to(root).as_posix(),metrics=metrics(path),audit=audit)
    if condition=='uncapped':
        assert original==actual,'Uncapped tape price path differs'
        assert rows(donor/'trades.csv')==rows(path/'trades.csv'),'Uncapped trade path differs'
        old=rows(donor/'agents_state.csv');new=rows(path/'agents_state.csv');assert len(old)==len(new)==168
        for a,b in zip(old,new):
            assert (a['agent_id'],a['round'],a['shares'])==(b['agent_id'],b['round'],b['shares'])
            assert all(abs(float(a[k])-float(b[k]))<=1e-7 for k in ('cash','wealth','avg_cost','dividend_income','interest_income'))
        result['factual_reconstruction']='passed'
    elif condition=='cap10':
        assert all(int(r['quantity'])<=10 for r in rows(path/'orders.csv') if r['agent_id'] in TARGETS)
    else:assert result['metrics']['target_union_volume']==0
    return result


def gate(root):
    root=Path(root).resolve();p=validate(root);records=[]
    with (root/'gate_execution.json').open('x') as f:json.dump(dict(pid=os.getpid()),f)
    try:
        for arm in p['arms']:
            records.append(one(root,arm,'uncapped'));write(root/'controls.json',records)
        write(root/'gate_summary.json',dict(status='passed',paths=18,auctions=216,account_rounds=3024,new_api_requests=0,controls_sha256=digest(root/'controls.json')))
    except BaseException as exc:
        write(root/'gate_failure.json',dict(error_type=type(exc).__name__,verified_paths=len(records)));raise


def run(root):
    root=Path(root).resolve();p=validate(root);gate=read(root/'gate_summary.json')
    assert gate['status']=='passed' and digest(root/'controls.json')==gate['controls_sha256'];records=[]
    with (root/'execution.json').open('x') as f:json.dump(dict(pid=os.getpid()),f)
    try:
        for arm in p['arms']:
            for condition in p['conditions']:
                records.append(one(root,arm,condition));write(root/'runs.json',records)
        write(root/'summary.json',dict(status='completed',dynamic_paths=36,rounds=432,account_rounds=6048,new_api_requests=0,new_model_samples=0))
    except BaseException as exc:
        write(root/'summary.json',dict(status='failed',completed_paths=len(records),error_type=type(exc).__name__,new_api_requests=0));raise
    write(root/'output_manifest.json',{p.relative_to(root).as_posix():digest(p) for p in root.rglob('*') if p.is_file() and p.name!='output_manifest.json'})
    print(json.dumps(read(root/'summary.json')))


if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('action',choices=('prepare','gate','run'));a.add_argument('--study',required=True);x=a.parse_args()
    {'prepare':prepare,'gate':gate,'run':run}[x.action](x.study)
