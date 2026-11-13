"""R050 retrospective audit of ALL R047 branches; never calls a model.

python -B -m research.feedback_audit --output runs/feedback_audit_20261106
Pair comparisons reuse branches and are descriptive, not independent samples.
"""
import argparse
import csv
from hashlib import sha256
from itertools import combinations
import json
from pathlib import Path
import re

BASE=Path(__file__).resolve().parents[1]
R047=BASE/'runs/20261105_041035_common_prefix_ca10f93d'
R043=BASE/'runs/20261105_012335_quiet_components_5066abab'
TARGETS=('llm_012','llm_013')


def read(p):return json.loads(p.read_text(encoding='utf-8'))
def rows(p):
    with p.open(newline='',encoding='utf-8') as f:return list(csv.DictReader(f))
def calls(p):return [json.loads(s) for s in p.read_text(encoding='utf-8').splitlines()]
def write(p,x):p.write_text(json.dumps(x,indent=2,allow_nan=False)+'\n',encoding='utf-8')
def digest(p):return sha256(p.read_bytes()).hexdigest()


def signature(book, requested=False):
    prefix='llm_requested_' if requested else ''
    return tuple((r['agent_id'],r[prefix+'side'],int(r[prefix+'quantity']),
                  None if not r[prefix+'limit_price'] else float(r[prefix+'limit_price']))
                 for r in sorted(book,key=lambda r:r['agent_id']))


def run(output):
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    inputs={}; arms=read(R047/'runs.json'); by={}; ledger=[]; activity=[]
    def pin(p):inputs[p.relative_to(BASE).as_posix()]=digest(p)
    for p in (R047/'runs.json',R047/'protocol.json',R043/'runs.json',Path(__file__)):pin(p)
    for arm in arms:
        root=R047/arm['run_path']; data={}
        for n in ('prices','orders','trades','agents_state'):
            p=root/(n+'.csv');pin(p);data[n]=rows(p)
        p=root/'llm_requests.jsonl';pin(p);requests=calls(p)
        tape=R047/'prefixes'/arm['prefix_id']/'calls.json';pin(tape)
        decisions={(c['agent_id'],c['round']):c for c in read(tape)+requests
                   if c.get('call_type')=='decision' and c.get('status')=='returned'}
        stream={}
        for rnd in range(6,13):
            book=[r for r in data['orders'] if int(r['round'])==rnd and r['agent_id'] in TARGETS]
            trades=[r for r in data['trades'] if int(r['round'])==rnd]
            fill=tuple((aid,sum(int(t['quantity']) for t in trades if t['buyer_id']==aid),
                        sum(int(t['quantity']) for t in trades if t['seller_id']==aid),
                        sum(int(t['quantity'])*float(t['price']) for t in trades if t['buyer_id']==aid),
                        sum(int(t['quantity'])*float(t['price']) for t in trades if t['seller_id']==aid)) for aid in TARGETS)
            state=tuple((r['agent_id'],float(r['cash']),int(r['shares'])) for r in sorted(data['agents_state'],key=lambda r:r['agent_id'])
                        if int(r['round'])==rnd and r['agent_id'] in TARGETS)
            stream[rnd]=dict(requested=signature(book,True),accepted=signature(book),fills=fill,accounts=state,
                             price=float(next(r['price'] for r in data['prices'] if int(r['round'])==rnd)))
        key=(arm['prefix_id'],arm['mode'],arm['branch_repetition']);by[key]=stream
        for aid in TARGETS:
            book=[r for r in data['orders'] if int(r['round'])>5 and r['agent_id']==aid]
            activity.append(dict(prefix=key[0],mode=key[1],branch=key[2],agent_id=aid,decisions=len(book),
                requested_hold=sum(r['llm_requested_side']=='hold' for r in book),accepted_hold=sum(r['side']=='hold' for r in book),
                adjusted=sum(bool(r['validation_note']) for r in book),
                sessions_with_fills=sum(any(int(t['round'])==rnd and aid in (t['buyer_id'],t['seller_id']) for t in data['trades']) for rnd in range(6,13))))
        for line,c in enumerate(requests,1):
            if c.get('call_type')!='reflection':continue
            contexts=[]
            for rnd in range(max(1,c['round']-4),c['round']+1):
                d=decisions[c['agent_id'],rnd]
                match=re.search(r'Recent auction closing prices \(old to new\): (\[[^\n]+\])',d['messages'][1]['content'])
                assert match,'Unknown prompt format'
                contexts.append(dict(round=rnd,last_price_available=json.loads(match[1])[-1],
                    clearing_price=float(next(r['price'] for r in data['prices'] if int(r['round'])==rnd)),decision_raw=d['raw']))
            ledger.append(dict(prefix=key[0],branch=key[2],agent_id=c['agent_id'],round=c['round'],
                source=(root/'llm_requests.jsonl').relative_to(BASE).as_posix(),line=line,
                reflection_raw=c['raw'],messages=c['messages'],decision_contexts=contexts,
                review_status='not_automatically_graded'))
    pairs=[]
    for prefix in sorted({k[0] for k in by}):
        keys=sorted(k for k in by if k[0]==prefix)
        for x,y in combinations(keys,2):
            differences={field:[r for r in range(6,13) if by[x][r][field]!=by[y][r][field]] for field in ('requested','accepted','fills','accounts','price')}
            pairs.append(dict(prefix=prefix,left=list(x[1:]),right=list(y[1:]),kind='same_mode' if x[1]==y[1] else 'cross_mode',
                              differing_rounds=differences,first_common_state_round6={k:6 in v for k,v in differences.items()}))
    distinct=[]
    for prefix in sorted({k[0] for k in by}):
        keys=[k for k in by if k[0]==prefix]
        distinct.append(dict(prefix=prefix,**{field:len({tuple(by[k][r][field] for r in range(6,13)) for k in keys}) for field in ('requested','accepted','fills','accounts','price')}))
    synchrony={}
    for name,ids in [('fundamentalists',('fund_005','fund_006','fund_007')),('momentum',('mome_008','mome_009','mome_010','mome_011'))]:
        total=equal=active=active_equal=0
        for arm in read(R043/'runs.json'):
            p=R043/arm['run_path']/'orders.csv';pin(p);book=rows(p)
            for rnd in range(1,13):
                b=[r for r in book if r['agent_id'] in ids and int(r['round'])==rnd]
                same=len({(r['side'],r['quantity'],r['limit_price']) for r in b})==1
                assert len(b)==len(ids)
                moving=any(r['side']!='hold' for r in b)
                total+=1;equal+=same;active+=moving;active_equal+=moving and same
        synchrony[name]=dict(sessions=total,identical=equal,active_sessions=active,identical_active=active_equal)
    assert len(ledger)==48 and len(pairs)==36 and len(activity)==48
    report=dict(version='R050_saved_feedback_execution_audit_v1',new_api_requests=0,new_scientific_markets=0,
                scope='Post-hoc all24 R047 branches,48 reflections,36 dependent branch pairs; R043 background orders. No causal mediation or independent-pair inference.',
                distinct_paths=distinct,pairs=pairs,activity=activity,background_synchrony=synchrony,
                reflection_ledger='reflection_ledger.json',inputs_sha256=inputs)
    write(output/'report.json',report);write(output/'reflection_ledger.json',ledger)
    text=['# R050 saved evidence: execution and feedback','',report['scope'],'',
          '|Context|Requested paths|Accepted paths|Fill paths|Target account paths|Price paths|',
          '|---|---:|---:|---:|---:|---:|']
    for d in distinct:text.append('|'+ '|'.join(str(d[k]) for k in ('prefix','requested','accepted','fills','accounts','price'))+'|')
    text+=['','Counts are distinct whole trajectories among four branches/context, not independent observations. Differences in fills include quantities and transaction values.','',
           'The pair ledger retains every within-mode and cross-mode comparison. Only session6 shares the same pre-decision state; later differences combine inherited histories, decisions and execution. No monotone causal funnel is assumed.',
           '', 'All48 reflections and corresponding decision-time/latest and clearing prices are exported for manual, source-linked factual review. No automatic hallucination-rate claim.']
    (output/'READOUT.md').write_text('\n'.join(text)+'\n',encoding='utf-8')
    print(json.dumps(dict(status='complete',output=str(output),reflections=len(ledger),dependent_pairs=len(pairs),distinct_paths=distinct)))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);run(p.parse_args().output)
