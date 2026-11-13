"""Verify identical R039/R051 homogeneous configs apart from study name/seed."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import yaml
from research.evidence_synthesis import BASE,read,digest


def check():
    first=BASE/'runs/20261104_154730_market_validation_fff53e3b'
    second=BASE/'runs/background_diversity_20261106'
    records=[('R039',first/a['run_path']/'config.yaml') for a in read(first/'report.json')['runs']]
    records += [('R051',second/a['path']/'config.yaml') for a in read(second/'report.json')['arms'] if not a['heterogeneous']]
    groups={};checked=[]
    for study,path in records:
        original=yaml.safe_load(path.read_text());cfg=deepcopy(original)
        del cfg['name'];del cfg['seed']
        skew=cfg['agents'][0]['params']['inventory_skew']
        if skew in groups:assert cfg==groups[skew],path
        else:groups[skew]=cfg
        checked.append(dict(study=study,seed=original['seed'],skew=skew,path=path.relative_to(BASE).as_posix(),sha256=digest(path)))
    assert len(checked)==16 and set(groups)=={0.,.02}
    a,b=deepcopy(groups[0.]),deepcopy(groups[.02])
    del a['agents'][0]['params']['inventory_skew'];del b['agents'][0]['params']['inventory_skew']
    assert a==b
    return dict(status='passed',checked_paths=16,omitted_fields=['name','seed'],same_config_within_each_skew=True,
                only_config_difference_between_skews='agents[0].params.inventory_skew',records=checked,
                source_sha256=digest(Path(__file__)),new_api_requests=0,new_markets=0,
                limitation='Configuration equivalence,not empirical calibration or a pooled inferential design;heterogeneous cells remain a distinct bundle.')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output');a=p.parse_args();r=check()
    if a.output:
        with Path(a.output).open('x',encoding='utf-8') as f:json.dump(r,f,indent=2)
    print(json.dumps({k:v for k,v in r.items() if k!='records'},indent=2))
