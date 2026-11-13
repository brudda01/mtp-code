"""Read-only R052 checks and an unscored review packet; no provider access."""
import argparse
import json
from pathlib import Path

from research import feedback_validation as f


def inspect(root):
    root=Path(root);p=f.validate(root);cases=f.read(root/'cases.json')
    schedule=p['schedule']
    assert len(schedule)==48 and len({(s['case'],s['format'],s['repetition']) for s in schedule})==48
    chars={fmt:[sum(len(m['content']) for m in c['messages'][fmt]) for c in cases.values()]
           for fmt in ('original','timed')}
    result=dict(protocol_sha256=f.digest(root/'protocol.json'),cases=12,inherited_histories=6,
                original_exogenous_seeds=3,planned_fresh_reflections=48,new_markets=0,
                normal_reservation_estimate=p['normal_reservation_estimate'],
                prompt_characters={k:dict(min=min(v),max=max(v),mean=sum(v)/len(v)) for k,v in chars.items()},
                all_source_input_hashes_match=True,provider_status='not_started',delivered=0,http_attempts=0)
    if (root/'summary.json').exists():
        summary=f.read(root/'summary.json');delivered=f.read(root/'results.json')
        calls=[json.loads(s) for s in (root/'requests.jsonl').read_text(encoding='utf-8').splitlines()]
        actual=[c for c in calls if c['record_type']=='model_call']
        assert summary['delivered']==len(delivered)
        assert summary['missing_slots']==schedule[len(delivered):]
        assert len(actual)==summary['usage']['requests_made']
        for i,r in enumerate(delivered,1):
            expected=schedule[i-1]
            assert r['slot']==i and all(r[k]==v for k,v in expected.items())
            assert r['retained_diary']==' '.join(r['raw'].split()[:120])
            assert r['response_metadata']['model']==p['profile']['model']
            corresponding=[c for c in actual if c['slot']==i and c['status']=='returned']
            assert len(corresponding)==1 and corresponding[0]['raw']==r['raw']
        for c in actual:
            assert c['messages']==cases[c['case']]['messages'][c['format']]
            assert c['temperature']==0 and c['max_tokens']==8192 and c['json_mode'] is False
        for n,h in f.read(root/'output_manifest.json').items():assert f.digest(root/n)==h,n
        result.update(provider_status=summary['status'],delivered=len(delivered),http_attempts=len(actual),
                      usage=summary['usage'],raw_over_120_words=sum(r['raw_words']>120 for r in delivered))
    elif (root/'execution.json').exists():
        result['provider_status']='execution_record_present_not_finalized'
    return result


def packet(root,output):
    root=Path(root);output=Path(output);output.mkdir(parents=True,exist_ok=False)
    receipt=inspect(root);cases=f.read(root/'cases.json')
    results=f.read(root/'results.json') if (root/'results.json').exists() else []
    lines=['# R052 reflection review packet','',
           'This is an unscored packet. Empty annotations are not negative findings.',
           'Review is AI-assisted and nonblinded unless an independent reviewer is separately documented.',
           'Primary: definite temporal misattribution. Secondary: explicit unsupported full-fill guarantee.',
           'Code raw and retained diary separately; retain ambiguous cases and verbatim evidence quotes.',
           'A true prior mistake is not a timing error. Wanting a full fill is not a guarantee.',
           'No mention of timing/fills is not evidence of comprehension. No significance/equivalence claim.',
           'All twelve histories follow; six inherited contexts nested in three original seeds.','']
    for key,c in sorted(cases.items()):
        lines += ['## '+key,'','|Session|Available last price|Later clearing|Buy fills|Sell fills|',
                  '|---|---:|---:|---:|---:|']
        for o,d in zip(c['original_memory'],c['decision_times']):
            lines.append(f"|{o['round']}|{d['last_observed_price']}|{o['price']}|{o['executed_buy_quantity']}|{o['executed_sell_quantity']}|")
        lines+=['','Earlier explanations (unverified):','']
        for o in c['original_memory']:
            lines+=['Session '+str(o['round'])+': '+o['requested_order']['reasoning'],'']
        for r in results:
            if r['case']!=key:continue
            lines += [f"### Slot {r['slot']}: {r['format']}, draw {r['repetition']}",'',
                      '**Full raw:**','',r['raw'],'','**Retained diary:**','',r['retained_diary'],'']
    (output/'PACKET.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    f.write(output/'verification.json',receipt)
    f.write(output/'unscored_annotations.json',dict(status='unscored',annotations=[dict(slot=r['slot'],
        case=r['case'],format=r['format'],repetition=r['repetition'],raw_temporal=None,diary_temporal=None,
        raw_guarantee=None,diary_guarantee=None,evidence_quotes=[],rationale=None) for r in results]))
    print(json.dumps(receipt,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--study',required=True);p.add_argument('--packet');a=p.parse_args()
    if a.packet:packet(a.study,a.packet)
    else:print(json.dumps(inspect(a.study),indent=2))
