"""R056: isolated six-LLM/25-session capped B cohort; no old defaults edited."""
import argparse
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from datetime import datetime,timezone
import json
import math
import os
from pathlib import Path
import socket
import subprocess
import urllib.request
import urllib.error
from unittest.mock import patch
import zipfile
import numpy as np
import yaml
import sim.engine as engine
from sim.agents.llm_agent import LLMAgent
from sim.llm.client import LLMClient,dotenv_api_key,_error_metadata
from sim.llm.usage import ProviderUnavailable
from sim.evaluation import evaluate_run
from research.order_influence import BASE,read,write,digest,rows

MODEL='deepseek/deepseek-v4.1-flash'
URL='https://api.goedelmachines.com/v1'
VERSION='R056_6LLM_B_cap10_hidden_prior_thinkingoff_v1'
DONOR=BASE/'runs/20261105_012335_quiet_components_5066abab/configs/quiet_components_B_s22853_rep1.yaml'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):raise RuntimeError('Provider redirect refused')


class GoedelClient(LLMClient):
    transport_path=None
    def __init__(self,*args,**kwargs):
        assert kwargs.get('model')==MODEL and kwargs.get('base_url')==URL
        super().__init__(*args,api_key=dotenv_api_key('GODEL_MACHINES_API_KEY'),**kwargs)
        if not self.api_key:raise ValueError('Missing GODEL_MACHINES_API_KEY')
        self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())

    def chat(self,messages,temperature=.3,max_tokens=2048,json_mode=True,retries=1):
        assert retries==1 and max_tokens==2048
        self.last_usage=None;self.last_response_metadata={};self.last_error_metadata={}
        body=dict(model=MODEL,messages=messages,temperature=temperature,max_tokens=max_tokens,
                  chat_template_kwargs={'thinking':False},stream=False)
        # No response_format assumption: exact JSON is requested by the agent prompt.
        record=dict(timestamp_utc=datetime.now(timezone.utc).isoformat(),request=body,
                    json_mode_handling='prompt-only JSON; response_format omitted')
        request=urllib.request.Request(URL+'/chat/completions',data=json.dumps(body).encode(),
                    headers={'Authorization':'Bearer '+self.api_key,'Content-Type':'application/json'})
        try:
            with self.opener.open(request,timeout=self.timeout) as response:
                data=json.loads(response.read());record['response']=data
                request_id=response.headers.get('x-request-id')
            self.last_response_metadata={k:data[k] for k in ('model','system_fingerprint') if isinstance(data.get(k),str)}
            if request_id:self.last_response_metadata['request_id']=request_id
            usage=data.get('usage',{})
            if all(type(usage.get(k)) is int and usage[k]>=0 for k in ('prompt_tokens','completion_tokens')):
                total=usage.get('total_tokens',usage['prompt_tokens']+usage['completion_tokens'])
                if type(total) is int and total>=usage['prompt_tokens']+usage['completion_tokens']:
                    self.last_usage={k:usage[k] for k in ('prompt_tokens','completion_tokens')}
                    self.last_usage.update(total_tokens=total,source='provider');self.total_tokens+=total
            if data.get('model') not in (MODEL,'deepseek-v4.1-flash'):raise ValueError('Unexpected response model')
            choice=data['choices'][0];self.last_response_metadata['finish_reason']=choice.get('finish_reason')
            result=choice['message']['content']
            if not isinstance(result,str) or not result.strip():raise ValueError('Empty provider content')
            return result
        except urllib.error.HTTPError as exc:
            self.last_error_metadata=_error_metadata(exc);record['error']=self.last_error_metadata;raise
        except Exception as exc:
            record['error_type']=type(exc).__name__;raise
        finally:
            if self.transport_path:
                with Path(self.transport_path).open('a',encoding='utf-8') as f:f.write(json.dumps(record,allow_nan=False)+'\n')


class CappedAgent(LLMAgent):
    def system_prompt(self,ticker):
        return super().system_prompt(ticker)+'\nStudy exchange constraint: each order is limited to 10 shares. Request an integer quantity from 0 through 10. This limit is enforced before resource validation.'
    def user_prompt(self,obs):
        prompt=super().user_prompt(obs).replace(f'Round {obs.round}/{obs.total_rounds}.',f'Round {obs.round}.',1)
        if obs.round==1:
            old=f'Previous round: volume {obs.last_volume}, dividend paid {obs.last_dividend} per share.'
            assert old in prompt
            prompt=prompt.replace(old,f'Initialization references: volume {obs.last_volume}; prior dividend {obs.last_dividend} per share. No earlier auction or paid dividend is recorded in this episode.',1)
        return prompt
    def validate(self,order,last_price):
        if type(order.quantity) is int and order.quantity>10:
            order=replace(order,quantity=10,validation_note='study_cap10')
        return super().validate(order,last_price)
    def decide(self,obs):
        result=super().decide(obs)
        if self.parse_failures or self.output_truncations:raise ProviderUnavailable('Affected decision stops cohort')
        return result


@contextmanager
def strict_accounting(agent_class):
    original_settle=engine.settle;original_end=agent_class.end_round;state={};checked=set()
    def settle(trades,agents,market):
        cash=math.fsum(a.cash for a in agents.values());shares=sum(a.shares for a in agents.values());tax=market.tax_collected
        original_settle(trades,agents,market)
        after=math.fsum(a.cash for a in agents.values())
        assert abs(after-cash+market.tax_collected-tax)<=1e-7
        assert sum(a.shares for a in agents.values())==shares
        state.update(agents=agents,settled_cash=after,shares=shares)
    def end(self,obs,*args,**kwargs):
        if obs.round not in checked:
            expected=state['settled_cash']*(1+obs.risk_free_rate)+state['shares']*obs.last_dividend
            assert abs(math.fsum(a.cash for a in state['agents'].values())-expected)<=1e-7
            assert sum(a.shares for a in state['agents'].values())==state['shares'];checked.add(obs.round)
        return original_end(self,obs,*args,**kwargs)
    with patch.object(engine,'settle',settle),patch.object(agent_class,'end_round',end):yield


def recipe():
    cfg=yaml.safe_load(DONOR.read_text());cfg.update(name='goedel_6LLM_B_cap10_s30841',seed=30841,rounds=25)
    cfg['agents'][1]['count']=2;cfg['agents'][3]['count']=2;cfg['agents'][-1]['count']=6
    llm=cfg['agents'][-1]['llm'];llm.update(model=MODEL,base_url=URL,max_tokens=2048,timeout_seconds=180,
          transport_retries=1,retry_http_503=True,input_usd_per_million=0.,output_usd_per_million=0.)
    llm.pop('reasoning_effort',None)
    cfg['llm_limits'].update(max_requests=180,max_reserved_tokens=3000000,max_cost_usd=0.,requests_per_minute=10,input_tokens_per_minute=60000)
    return cfg


def freeze(root,protocol,extra_sources=()):
    sources=sorted((BASE/'sim').rglob('*.py'))+[Path(__file__),BASE/'research/order_influence.py']+[BASE/n for n in extra_sources]
    sources=sorted(set(sources))
    protocol.update(created_utc=datetime.now(timezone.utc).isoformat(),parent_revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=BASE,text=True).strip(),
        working_tree_status=subprocess.check_output(['git','status','--short'],cwd=BASE,text=True).splitlines(),
        python=__import__('platform').python_version(),numpy=np.__version__,
        source_sha256={p.relative_to(BASE).as_posix():digest(p) for p in sources})
    with zipfile.ZipFile(root/'source.zip','x',zipfile.ZIP_DEFLATED) as z:
        for p in sources:z.write(p,p.relative_to(BASE).as_posix())
    protocol['source_zip_sha256']=digest(root/'source.zip');write(root/'protocol.json',protocol)
    write(root/'preparation.json',dict(protocol_sha256=digest(root/'protocol.json')))


def validate(root):
    p=read(root/'protocol.json');assert digest(root/'protocol.json')==read(root/'preparation.json')['protocol_sha256']
    assert digest(root/'source.zip')==p['source_zip_sha256']
    for n,h in p['source_sha256'].items():assert digest(BASE/n)==h,n
    for n,h in p.get('inputs_sha256',{}).items():assert digest(BASE/n)==h,n
    return p


def prepare(root):
    root=Path(root).resolve();root.mkdir(parents=True,exist_ok=False)
    docs=BASE/'runs/provider_docs_20261108';modelcheck=read(docs/'model_check.json')
    assert MODEL in modelcheck['model_ids'] and modelcheck['key_tier_prefix']=='free'
    (root/'config.yaml').write_text(yaml.safe_dump(recipe()),encoding='utf-8')
    protocol=dict(version=VERSION,study='R056',status='frozen_before_live_requests',config_sha256=digest(root/'config.yaml'),
        inputs_sha256={p.relative_to(BASE).as_posix():digest(p) for p in docs.iterdir() if p.is_file()},
        requested_profile=dict(model=MODEL,endpoint=URL,credential_name='GODEL_MACHINES_API_KEY',credential_tier_prefix='free',
            thinking=False,temperature=.3,max_tokens=2048,memory_window=5,condition='B',provider_seed=None),
        design='ONE new seed30841,25 sessions,6LLMs+8rules. Four rule slots replaced:ZI4->2,momentum4->2;3fundamentalists/1maker unchanged. Equal per-slot endowments and total resources preserved. Fixed6librarypersonas. Prompted and enforced cap10;original maker depth10/target150/bound300 retained. All actual states propagate.',
        primary='Operational completion of150 own-history B decisions;price log-return SD,referencegap,makerboundaryfraction,volume/fill/targetunionparticipation,perpersona trades and BOTH-mark passive excess. Descriptive single unpooled cohort.',
        limits=dict(normal_calls=150,max_http_attempts=180,max_reserved_tokens=3000000,requests_per_minute=10,input_estimate_tokens_per_minute=60000,timeout_seconds=180),
        transport='One existing identical transport/503retry shared;JSONrepair recorded by existing agent. First fatal/provider/cap/output/persistentparse failure stops. No resampling/modelchange/resume/hiddenretry. No extra response_format;prompt-only JSON. Exact body and raw response saved without headers/key.',
        retention='Provider free/student policy retains fictional personas and simulated histories and may use them for training. User explicitly requested this endpoint and supplied credential;no real personal data or secrets in model payloads.',
        costs='Credential prefix free;no declared monetary charge assumed. Token/attempt accounting retained;no plan or billing change.',
        limitations='Model,population composition,cap andhorizon differ fromQwen. NOT an identifiedcross-model effect/scalingcurve or long-runstylizedfacts validation. Sixpersonas and25sessions are not independent replications. Cap limitsperorder,doesnotguarantee perpetualinventoryorliquidity.',
        preservation='All old Qwen protocols/archives/defaults andR052closed status remain untouched.')
    freeze(root,protocol,['tests/test_final_extensions.py'])
    print(json.dumps(read(root/'preparation.json')))


def audit_financial(path):
    initial=rows(path/'initial_state.csv');states=rows(path/'agents_state.csv');cashflows=rows(path/'cashflows.csv');trades=rows(path/'trades.csv')
    opening={r['agent_id']:r for r in initial};maxerror=0.;count=0
    cfg=yaml.safe_load((path/'config.yaml').read_text());rate=cfg['asset']['risk_free'];tax=cfg['market']['transaction_tax']
    for pr in rows(path/'prices.csv'):
        rnd=int(pr['round']);closing={r['agent_id']:r for r in states if int(r['round'])==rnd}
        tt=[t for t in trades if int(t['round'])==rnd]
        for aid,start in opening.items():
            buy=[t for t in tt if t['buyer_id']==aid];sell=[t for t in tt if t['seller_id']==aid]
            shares=int(start['shares'])+sum(int(t['quantity']) for t in buy)-sum(int(t['quantity']) for t in sell)
            cash=float(start['cash'])+math.fsum([int(t['quantity'])*float(t['price'])*(1-tax) for t in sell]+[-int(t['quantity'])*float(t['price'])*(1+tax) for t in buy])
            expected=cash*(1+rate)+shares*float(pr['dividend']);error=abs(expected-float(closing[aid]['cash']))
            assert error<=1e-7 and shares==int(closing[aid]['shares']) and cash>=-1e-7
            maxerror=max(maxerror,error);count+=1
        assert sum(int(a['shares']) for a in closing.values())==sum(int(a['shares']) for a in initial)
        opening=closing
    assert all(abs(float(r['conservation_error']))<=1e-7 for r in cashflows)
    return dict(status='passed',account_rounds=count,max_individual_cash_error=maxerror,rounds=len(cashflows))


def metrics(path):
    p=rows(path/'prices.csv');states=rows(path/'agents_state.csv');cfg=yaml.safe_load((path/'config.yaml').read_text())
    prices=np.array([cfg['asset']['initial_price']]+[float(r['price']) for r in p]);ret=np.diff(np.log(prices))
    makers=[int(r['shares']) for r in states if r['agent_id']=='mark_000']
    targets={r['agent_id'] for r in rows(path/'initial_state.csv') if r['agent_id'].startswith('llm_')}
    tt=rows(path/'trades.csv');volume=sum(int(t['quantity']) for t in tt)
    return dict(rounds=len(p),price_return_sd_pct=float(np.std(ret,ddof=0)*100) if len(ret) else None,
        mean_gap_pct=float(np.mean([abs(float(r['price'])/float(r['fundamental'])-1) for r in p])*100) if p else None,
        max_drawdown_pct=float(np.max(1-prices/np.maximum.accumulate(prices))*100),
        maker_boundary_fraction=sum(x in (0,300) for x in makers)/len(makers) if makers else None,
        maker_min=min(makers,default=None),maker_max=max(makers,default=None),volume=volume,terminal_price=float(prices[-1]),
        target_union_volume=sum(int(t['quantity']) for t in tt if t['buyer_id'] in targets or t['seller_id'] in targets),
        zero_volume_rounds=sum(int(r['volume'])==0 for r in p))


def execute(root):
    root=Path(root).resolve();p=validate(root);assert digest(root/'config.yaml')==p['config_sha256']
    with (root/'execution.json').open('x') as f:json.dump(dict(pid=os.getpid(),started_utc=datetime.now(timezone.utc).isoformat()),f)
    GoedelClient.transport_path=root/'provider_transport.jsonl'
    path=None
    try:
        with patch.object(engine,'LLMClient',GoedelClient),patch.object(engine,'LLMAgent',CappedAgent),strict_accounting(CappedAgent):
            path=Path(engine.run(root/'config.yaml',output_root=root/'market'))
        s=read(path/'summary.json');audit=audit_financial(path);write(root/'financial_audit.json',audit)
        if s['rounds']:
            write(root/'evaluation.json',evaluate_run(path));write(root/'metrics.json',metrics(path))
        records=[json.loads(l) for l in (path/'llm_calls.jsonl').read_text().splitlines()]
        clean=s['status']=='completed' and s['rounds']==25 and all(s[k]==0 for k in ('parse_failures','output_truncations','reflection_failures'))
        assert all(int(o['quantity'])<=10 for o in rows(path/'orders.csv') if o['agent_id'].startswith('llm_'))
        write(root/'summary.json',dict(status='completed' if clean else 'stopped',run_path=path.relative_to(root).as_posix(),
            completed_rounds=s['rounds'],planned_rounds=25,delivered_decisions=len(records),planned_decisions=150,
            missing_decisions=150-len(records),usage=s['llm_usage'],failure_type=s['failure_type'],
            no_resume=True,finished_utc=datetime.now(timezone.utc).isoformat()))
    except BaseException as exc:
        write(root/'driver_failure.json',dict(error_type=type(exc).__name__,run_path=str(path) if path else None));raise
    finally:
        GoedelClient.transport_path=None
    write(root/'output_manifest.json',{p.relative_to(root).as_posix():digest(p) for p in root.rglob('*') if p.is_file() and p.name!='output_manifest.json'})
    print(json.dumps(read(root/'summary.json')))


if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('action',choices=('prepare','run'));a.add_argument('--study',required=True);x=a.parse_args()
    {'prepare':prepare,'run':execute}[x.action](x.study)
