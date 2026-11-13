"""Independent saved-ledger cash/share and terminal-mark checks; no simulation."""
import hashlib
import json
import math
from pathlib import Path

def verify(path):
    path=Path(path)
    manifest=json.loads((path/'manifest.json').read_text(encoding='utf-8'))
    if manifest['evidence_type']!='OFFLINE_MOCK_NOT_BEHAVIORAL_DATA': raise ValueError('not mock evidence')
    for name,digest in manifest['artifacts_sha256'].items():
        target=(path/name).resolve()
        if target.parent!=path.resolve(): raise ValueError('unsafe manifest path')
        if hashlib.sha256(target.read_bytes()).hexdigest()!=digest: raise ValueError('artifact hash mismatch')
    rows=[json.loads(line) for line in (path/'ledger.jsonl').read_text(encoding='utf-8').splitlines()]
    initial=next(r['accounts'] for r in rows if r['kind']=='initial')
    state={aid:dict(cash=a['cash'],shares=a['shares']) for aid,a in initial.items()}
    passive={aid:dict(cash=a['cash'],shares=a['shares']) for aid,a in initial.items()}
    pending=None; count=0; last_price=100.; max_error=0.
    for row in rows:
        if row['kind']=='auction': pending=row
        if row['kind']!='round': continue
        if pending is None or pending['round']!=row['round']: raise ValueError('missing auction')
        price=row['price']; trades=pending['trades']; dividend=row['dividend']
        if row['round']!=count+1: raise ValueError('nonsequential session')
        if sum(t['quantity'] for t in trades)!=row['volume']: raise ValueError('volume mismatch')
        if row['price']!=pending['price']: raise ValueError('price mismatch')
        cash_changes={aid:[] for aid in state}; share_changes={aid:0 for aid in state}
        for t in trades:
            if t['price']!=price or type(t['quantity']) is not int or t['quantity']<=0 or t['buyer_id']==t['seller_id']: raise ValueError('invalid trade')
            b,s,q=t['buyer_id'],t['seller_id'],t['quantity']
            cash_changes[b].append(-q*price); cash_changes[s].append(q*price)
            share_changes[b]+=q; share_changes[s]-=q
        for aid,opening in state.items():
            recorded=row['opening'][aid]
            if abs(recorded['cash']-opening['cash'])>1e-7 or recorded['shares']!=opening['shares']: raise ValueError('broken financial prefix')
            q=opening['shares']+share_changes[aid]
            post=opening['cash']+math.fsum(cash_changes[aid])
            di=q*dividend; interest=post*.0002; cash=post+di+interest
            closing=row['closing'][aid]
            errors=[abs(cash-closing['cash']),abs(di-closing['dividend_income']),abs(interest-closing['interest_income']),abs(cash+q*price-closing['wealth'])]
            max_error=max(max_error,*errors)
            if max(errors)>1e-7 or q!=closing['shares'] or cash<0: raise ValueError('account reconciliation failure')
            state[aid]=dict(cash=cash,shares=q)
            passive[aid]['cash']=passive[aid]['cash']*(1+.0002)+passive[aid]['shares']*dividend
        last_price=price; count+=1; pending=None
    if count!=manifest['completed_rounds']: raise ValueError('completion count mismatch')
    endpoints=next((r['accounts'] for r in rows if r['kind']=='endpoints'),None)
    if manifest['status']=='complete':
        if endpoints is None: raise ValueError('missing endpoints')
        for aid,a in state.items():
            for name,mark in [('auction_excess_pp',last_price),('reference_excess_pp',100)]:
                excess=100*(a['cash']-passive[aid]['cash']+(a['shares']-passive[aid]['shares'])*mark)/initial[aid]['wealth']
                if abs(excess-endpoints[aid][name])>1e-7: raise ValueError('passive mark mismatch')
    return dict(status='passed',sessions=count,account_rounds=count*len(state),max_cash_error=max_error,evidence_type='mock')

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('path')
    print(json.dumps(verify(p.parse_args().path),indent=2))
