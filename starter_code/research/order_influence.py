"""R054: conditional one-auction order-size interventions, no LLM/new paths.

prepare -> gate (ALL factual auctions) -> run (isolated counterfactuals).
Never propagate hypothetical accounts/prices into the next observed frame.
"""
import argparse
from copy import deepcopy
import csv
from dataclasses import asdict,replace
from datetime import datetime,timezone
from hashlib import sha256
import json
from pathlib import Path
import platform
import socket
import subprocess
from unittest.mock import patch
import zipfile
import numpy as np
import yaml
from sim.agents.base import Agent
from sim.market import Order,CallAuctionMarket,settle
from sim.llm.client import LLMClient

BASE=Path(__file__).resolve().parents[1]
DONOR=BASE/'runs/20261105_012335_quiet_components_5066abab'
TARGETS=('llm_012','llm_013')
VERSION='R054_fixed_auction_order_influence_v1'


def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def write(p,x):Path(p).write_text(json.dumps(x,indent=2,allow_nan=False)+'\n',encoding='utf-8')
def digest(p):return sha256(Path(p).read_bytes()).hexdigest()
def rows(p):
    with Path(p).open(newline='',encoding='utf-8') as f:return list(csv.DictReader(f))


def market_from(cfg,rng_state=None):
    rng=np.random.default_rng(np.random.SeedSequence(cfg['seed']).spawn(4)[3])
    if rng_state is not None:rng.bit_generator.state=deepcopy(rng_state)
    return CallAuctionMarket(**cfg['market_without_mechanism'],rng=rng)


def book_from(records):
    return [Order(r['agent_id'],r['side'],int(r['quantity']),float(r['limit_price']) if r['limit_price'] else None,
                  int(r['round'])) for r in records]


def intervene(book,condition):
    assert condition in ('original','cap10','remove')
    out=[]
    for o in book:
        if o.agent_id not in TARGETS or condition=='original':out.append(replace(o))
        elif condition=='cap10':out.append(replace(o,quantity=min(10,o.quantity)))
        else:out.append(Order(o.agent_id,'hold',0,None,o.round))
    assert [asdict(o) for o in out if o.agent_id not in TARGETS]==[asdict(o) for o in book if o.agent_id not in TARGETS]
    return out


def accounts_from(records,cfg):
    return {r['agent_id']:Agent(r['agent_id'],float(r['cash']),int(r['shares']),np.random.default_rng(0),
            initial_cost=float(r['avg_cost']),transaction_tax=cfg['market']['transaction_tax'],
            price_band=cfg['market']['price_band']) for r in records}


def clear_frame(frame,condition):
    cfg=frame['config'];market=market_from(cfg,frame['allocation_state']);accounts=accounts_from(frame['opening'],cfg)
    book=intervene(book_from(frame['orders']),condition)
    price,trades,unmatched=market.clear(book,frame['previous_price'],frame['round'])
    settle(trades,accounts,market)
    target={aid:dict(buy=sum(t.quantity for t in trades if t.buyer_id==aid),sell=sum(t.quantity for t in trades if t.seller_id==aid)) for aid in TARGETS}
    volume=sum(t.quantity for t in trades)
    involved=sum(t.quantity for t in trades if t.buyer_id in TARGETS or t.seller_id in TARGETS)
    result=dict(price=price,volume=volume,unmatched=unmatched,target_fills=target,
                target_involved_volume=involved,target_net_buy=sum(x['buy']-x['sell'] for x in target.values()),
                maker_closing_shares=accounts['mark_000'].shares,
                trades=[asdict(t) for t in trades],posttrade_accounts={aid:dict(cash=a.cash,shares=a.shares,avg_cost=a.avg_cost) for aid,a in accounts.items()})
    assert all(a.cash>=-1e-8 and a.shares>=0 for a in accounts.values())
    assert 0<=accounts['mark_000'].shares<=300
    return result


def prepare(root):
    root=Path(root);root.mkdir(parents=True,exist_ok=False)
    arms=read(DONOR/'runs.json');assert len(arms)==18 and all(a['status']=='completed' and a['rounds']==12 for a in arms)
    inputs={}
    for name in ('runs.json','protocol.json','summary.json'):inputs[(DONOR/name).relative_to(BASE).as_posix()]=digest(DONOR/name)
    for a in arms:
        for name in ('config.yaml','initial_state.csv','agents_state.csv','prices.csv','orders.csv','trades.csv','manifest.json'):
            p=DONOR/a['run_path']/name;inputs[p.relative_to(BASE).as_posix()]=digest(p)
        manifest=read(DONOR/a['run_path']/'manifest.json')
        for name in ('sim/market.py','sim/agents/base.py','sim/engine.py'):
            assert digest(BASE/name)==manifest['source_sha256'][name],name
    sources=sorted((BASE/'sim').rglob('*.py'))+[Path(__file__),BASE/'tests/test_order_influence.py']
    hashes={p.relative_to(BASE).as_posix():digest(p) for p in sources}
    with zipfile.ZipFile(root/'source.zip','x',zipfile.ZIP_DEFLATED) as z:
        for p in sources:z.write(p,p.relative_to(BASE).as_posix())
    protocol=dict(version=VERSION,status='frozen_before_counterfactual_results',created_utc=datetime.now(timezone.utc).isoformat(),
        parent_revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=BASE,text=True).strip(),
        working_tree_status=subprocess.check_output(['git','status','--short'],cwd=BASE,text=True).splitlines(),
        python=platform.python_version(),numpy=np.__version__,pyyaml=yaml.__version__,
        donor= DONOR.relative_to(BASE).as_posix(),arms=arms,inputs_sha256=inputs,source_sha256=hashes,source_zip_sha256=digest(root/'source.zip'),
        frames=216,conditions=['cap10','remove'],counterfactual_clears=432,
        question='Do large LLM order quantities translate into immediate price influence,or mainly trading-volume participation,conditional on the observed auction books?',
        primary='cap10 versus factual:exact price-change fraction and mean absolute price difference aspercent of precedingactualclose,reported per18markets and within3originalseeds. Showall216frames and separately frameswithatleastonetargetacceptedquantity>10. No significance test,optimization or preferredsign gate.',
        secondary='removeboth targetorders; signed price difference,benchmark-gap difference,volume,each targetbuys/sells,jointnetflow,makerclosinginventory and changedfills withoutpricechange. Allframes/modes/seeds retained; no pooledindependence claim.',
        cap_rationale='10shares is existingZIordermaximum andMMquote size,not a fitted,optimal or empiricallycalibrated bound;fundamentalist/momentum quantities vary. Applyafterfeasibilityvalidation,keepacceptedside/limit. No recalculation of agentchoices.',
        controls='Allnon-targetacceptedorders,14openingaccounts,actualprecedingprice andexactpreauctionallocationRNGstate fixed. SuppressionkeepsLLMaccounts/endowments butreplacesorderswithHOLD. EachCFisolated;noCFcash/price/RNG propagated into anotherframe. Alloriginal216clears mustmatch savedprices,trades,closingaccounts before anyCF.',
        independence='3existingexogenousseeds x2providerdraws xABC x12actualsessions. Nestedendogenousframes,not216independentmarkets or432newmodeldraws. HistoricalR043replies are not regenerated or used as adaptiveCFbehavior.',
        limitations='Conditional one-auction mechanical interventions,not permanentcaps,agent-countscaling,behavioraladaptation,closed-loop policyreturns,isolated intelligence or humanrealism. Neither tax,BBS,halts nor model/horizon changes included. Mechanism targeted after existing sizingdiagnostic;not an externally preregistered or held-outcohort.',
        failure_policy='Single-use gate/run,stop and retain on any mismatch;no changing frozen originals or repairing source records. No provider/network access,no extension/resampling/tuning.')
    write(root/'protocol.json',protocol);write(root/'preparation.json',dict(protocol_sha256=digest(root/'protocol.json')))
    print(json.dumps(dict(study=str(root),frames=216,counterfactuals=432,protocol_sha256=digest(root/'protocol.json'))))


def validate(root):
    root=Path(root);p=read(root/'protocol.json')
    assert digest(root/'protocol.json')==read(root/'preparation.json')['protocol_sha256']
    assert digest(root/'source.zip')==p['source_zip_sha256']
    for n,h in {**p['inputs_sha256'],**p['source_sha256']}.items():assert digest(BASE/n)==h,n
    return p


def gate(root):
    root=Path(root);p=validate(root);frames=[];max_error=0.
    with (root/'gate_execution.json').open('x') as f:json.dump(dict(started_utc=datetime.now(timezone.utc).isoformat()),f)
    try:
        for arm in p['arms']:
            path=BASE/p['donor']/arm['run_path'];cfg=yaml.safe_load((path/'config.yaml').read_text())
            cfg['market_without_mechanism']={k:v for k,v in cfg['market'].items() if k!='mechanism'}
            assert cfg['market']['transaction_tax']==0
            market=market_from(cfg);opening=rows(path/'initial_state.csv');orders=rows(path/'orders.csv')
            states=rows(path/'agents_state.csv');trades=rows(path/'trades.csv');prices=rows(path/'prices.csv');previous=cfg['asset']['initial_price']
            for rnd,pr in enumerate(prices,1):
                records=[r for r in orders if int(r['round'])==rnd]
                frame=dict(seed=arm['seed'],mode=arm['mode'],repetition=arm['repetition'],run_path=arm['run_path'],round=rnd,
                           previous_price=previous,benchmark=float(pr['fundamental']),config=cfg,opening=opening,orders=records,
                           allocation_state=deepcopy(market.rng.bit_generator.state),
                           cap_affected=any(r['agent_id'] in TARGETS and int(r['quantity'])>10 for r in records),
                           targets_active=any(r['agent_id'] in TARGETS and int(r['quantity'])>0 and r['side']!='hold' for r in records))
                price,actual,unmatched=market.clear(book_from(records),previous,rnd)
                expected=[(r['buyer_id'],r['seller_id'],int(r['quantity']),float(r['price'])) for r in trades if int(r['round'])==rnd]
                assert price==float(pr['price']) and unmatched==int(pr['unmatched_volume'])
                assert [(t.buyer_id,t.seller_id,t.quantity,t.price) for t in actual]==expected
                reconstructed=clear_frame(frame,'original')
                assert reconstructed['trades']==[asdict(t) for t in actual]
                end=[r for r in states if int(r['round'])==rnd]
                for r in end:
                    a=reconstructed['posttrade_accounts'][r['agent_id']]
                    cash=a['cash']+a['cash']*cfg['asset']['risk_free']+a['shares']*float(pr['dividend'])
                    errors=[abs(cash-float(r['cash'])),abs(a['avg_cost']-float(r['avg_cost'])),abs(cash+a['shares']*price-float(r['wealth']))]
                    max_error=max(max_error,*errors);assert max(errors)<1e-7 and a['shares']==int(r['shares'])
                frame['factual']=reconstructed;frames.append(frame);opening=end;previous=price
        assert len(frames)==216
        write(root/'frames.json',frames)
        receipt=dict(status='passed',frames=216,markets=18,financial_accounts=3024,max_account_error=max_error,
                     all_original_prices_trades_accounts_match=True,frames_sha256=digest(root/'frames.json'),new_api_requests=0)
        write(root/'factual_verification.json',receipt);print(json.dumps(receipt))
    except BaseException as exc:
        write(root/'gate_failure.json',dict(error_type=type(exc).__name__,verified_frames=len(frames)));raise


def run(root):
    root=Path(root);p=validate(root);gate_result=read(root/'factual_verification.json')
    assert gate_result['status']=='passed' and digest(root/'frames.json')==gate_result['frames_sha256']
    with (root/'execution.json').open('x') as f:json.dump(dict(started_utc=datetime.now(timezone.utc).isoformat()),f)
    records=[];status='running';failure=None;network=[]
    def forbidden(*args,**kwargs):network.append('blocked');raise RuntimeError('No network/provider access allowed')
    try:
        with patch.object(LLMClient,'chat',forbidden),patch.object(socket.socket,'connect',forbidden),patch.object(socket,'create_connection',forbidden):
            for i,frame in enumerate(read(root/'frames.json')):
                factual=frame['factual']
                for condition in p['conditions']:
                    result=clear_frame(frame,condition)
                    assert result['volume']<=factual['volume']
                    if condition=='cap10' and not frame['cap_affected']:assert result==factual
                    if condition=='remove' and not frame['targets_active']:assert result==factual
                    changed=result['price']!=factual['price']
                    records.append(dict(frame_index=i,**{k:frame[k] for k in ('seed','mode','repetition','run_path','round','cap_affected','targets_active','previous_price','benchmark')},
                        condition=condition,factual=factual,result=result,price_changed=changed,
                        absolute_price_impact_pct=100*abs(result['price']-factual['price'])/frame['previous_price'],
                        signed_price_difference=result['price']-factual['price'],volume_difference=result['volume']-factual['volume'],
                        gap_difference_pp=100*(abs(result['price']/frame['benchmark']-1)-abs(factual['price']/frame['benchmark']-1)),
                        target_fills_changed=result['target_fills']!=factual['target_fills']))
                write(root/'results.json',records)
        assert len(records)==432;status='completed'
    except BaseException as exc:failure=type(exc).__name__;raise
    finally:
        write(root/'results.json',records)
        write(root/'summary.json',dict(status=status if failure is None else 'failed',failure_type=failure,
              completed_counterfactuals=len(records),planned_counterfactuals=432,factual_frames=216,
              new_endogenous_markets=0,new_model_samples=0,new_api_requests=0,network_attempts=len(network),
              finished_utc=datetime.now(timezone.utc).isoformat()))
    write(root/'output_manifest.json',{p.name:digest(p) for p in root.iterdir() if p.is_file() and p.name!='output_manifest.json'})
    print(json.dumps(read(root/'summary.json')))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=('prepare','gate','run'));p.add_argument('--study',required=True);a=p.parse_args()
    {'prepare':prepare,'gate':gate,'run':run}[a.action](a.study)
