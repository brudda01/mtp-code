"""Summarize explicit analyst annotations, never infer errors from keywords."""
import argparse
from collections import Counter
import json
from pathlib import Path

from research import feedback_validation as f
from research.feedback_validation_review import inspect

FIELDS=('raw_temporal','diary_temporal','raw_guarantee','diary_guarantee')
LABELS=('absent','definite','ambiguous')


def analyze(root, annotations, output):
    root=Path(root);annotations=Path(annotations);output=Path(output)
    verification=inspect(root)
    assert verification['provider_status'] in ('completed','stopped')
    results=f.read(root/'results.json');coding=f.read(annotations)
    assert coding['status']=='reviewed' and len(coding['annotations'])==len(results)
    by={a['slot']:a for a in coding['annotations']}
    assert len(by)==len(results)
    for r in results:
        a=by[r['slot']]
        assert all(a[k]==r[k] for k in ('case','format','repetition'))
        assert all(a[k] in LABELS for k in FIELDS)
        assert type(a['raw_price_discussion']) is bool and type(a['raw_fill_discussion']) is bool
        assert isinstance(a['rationale'],str) and a['rationale']
        for evidence in a['evidence']:
            assert evidence['field'] in FIELDS
            text=r['retained_diary'] if evidence['field'].startswith('diary') else r['raw']
            assert evidence['quote'] in text and evidence['rationale']
        for key in FIELDS:
            if a[key]!='absent':assert any(e['field']==key for e in a['evidence'])
        for issue in a.get('ancillary',[]):assert issue['quote'] in r['raw'] and issue['rationale']
    totals={};context_rows=[]
    for fmt in ('original','timed'):
        selected=[a for a in by.values() if a['format']==fmt]
        totals[fmt]=dict(delivered=len(selected),**{key:dict(Counter(a[key] for a in selected)) for key in FIELDS},
                        price_discussion=sum(a['raw_price_discussion'] for a in selected),
                        fill_discussion=sum(a['raw_fill_discussion'] for a in selected))
    for case in sorted(f.read(root/'cases.json')):
        row=dict(case=case)
        for fmt in ('original','timed'):
            selected=[a for a in by.values() if a['case']==case and a['format']==fmt]
            row[fmt]=dict(delivered=len(selected),**{key:sum(a[key]=='definite' for a in selected) if selected else None for key in FIELDS},
                          ambiguous={key:sum(a[key]=='ambiguous' for a in selected) if selected else None for key in FIELDS})
        context_rows.append(row)
    calls=[json.loads(s) for s in (root/'requests.jsonl').read_text(encoding='utf-8').splitlines()]
    cost={}
    for fmt in ('original','timed'):
        selected=[c for c in calls if c['record_type']=='model_call' and c['format']==fmt]
        cost[fmt]=dict(http_attempts=len(selected),reported_tokens=sum((c.get('usage') or {}).get('total_tokens',0) for c in selected),
                       unknown_usage_attempts=sum(c.get('usage') is None for c in selected),
                       reserved_tokens=sum(c['reservation']['input_token_estimate']+c['reservation']['max_output_tokens'] for c in selected))
    report=dict(verification=verification,annotation_sha256=f.digest(annotations),
                totals=totals,contexts=context_rows,cost=cost,
                scope='Fixed-history prompt-bundle comparison;focused nonblinded AI-assisted coding;not independent human scoring,closed-loop behavior,profits or generalization.')
    output.mkdir(parents=True,exist_ok=False)
    f.write(output/'report.json',report)
    lines=['# R052: matched first-reflection readout','',
           'Counts are definite target issues per two planned replies. All twelve actor histories are shown.',
           'Six inherited contexts nest within three original seeds; these rows/calls are not independent markets.','',
           '|History|Original delivered|Timed delivered|Original temporal: raw / diary|Timed temporal: raw / diary|Original guarantees: raw / diary|Timed guarantees: raw / diary|',
           '|---|---:|---:|---:|---:|---:|---:|']
    for c in context_rows:
        a,b=c['original'],c['timed']
        def cell(row,kind):
            return f"{row['raw_'+kind]} / {row['diary_'+kind]}" if row['delivered'] else 'Missing'
        lines.append(f"|{c['case']}|{a['delivered']}|{b['delivered']}|{cell(a,'temporal')}|{cell(b,'temporal')}|{cell(a,'guarantee')}|{cell(b,'guarantee')}|")
    lines+=['',report['scope'],'','Ambiguous labels,discussion coverage and all attempt costs remain in report.json. No detected target issue does not imply comprehensive factual correctness.']
    (output/'READOUT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--study',required=True);p.add_argument('--annotations',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    print(json.dumps(analyze(a.study,a.annotations,a.output),indent=2))
