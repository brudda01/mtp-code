"""Matched 2x2 news-control engineering check, with no live model requests."""
import argparse
import contextlib
import csv
import hashlib
import io
import json
from pathlib import Path
import time
import uuid

import numpy as np
import yaml

from sim.config import parse_config
from sim.engine import run
from sim.provenance import write_json

ROOT=Path(__file__).resolve().parents[1]
CELLS={"control":(False,False),"headline_only":(False,True),
       "fundamentals_only":(True,False),"combined":(True,True)}
SEEDS=(211,422,633)
ROUNDS,EVENT_ROUND=600,301
HEADLINE="A news report forecasts a sustained 20% rise in KGP's dividend per trading session; actual future payments remain uncertain."
FINANCIAL_FILES=("prices.csv","orders.csv","trades.csv","agents_state.csv","cashflows.csv","liquidity.csv","initial_state.csv")


def recipe(cell,seed):
    shift,announce=CELLS[cell]
    raw=yaml.safe_load((ROOT/"configs/baseline_rules.yaml").read_text())
    raw.update(name="news_"+cell,seed=seed,rounds=ROUNDS,reveal_fundamental=False,
               llm_limits={"max_requests":0,"max_reserved_tokens":0,"max_cost_usd":0})
    event={"round":EVENT_ROUND,"announce":announce}
    if announce:event["headline"]=HEADLINE
    if shift:event["effect"]={"dbar_mult":1.2}
    raw["news"]=[event]
    cfg=parse_config(raw)
    assert all(group.type!="llm" for group in cfg.agents)
    return cfg


def rows(path):
    with path.open(newline="",encoding="utf-8") as f:return list(csv.DictReader(f))


def verify(paths,seed):
    control,headline,quiet,combined=(paths[c] for c in CELLS)
    prices={c:rows(p/"prices.csv") for c,p in paths.items()}
    summaries={c:json.loads((p/"summary.json").read_text()) for c,p in paths.items()}
    for a,b in ((control,headline),(quiet,combined)):
        for name in FINANCIAL_FILES:
            assert (a/name).read_bytes()==(b/name).read_bytes(),(seed,name,"announcement-only rule control")
    initial=[(p/"initial_state.csv").read_bytes() for p in paths.values()]
    assert all(x==initial[0] for x in initial)
    before=EVENT_ROUND-1
    assert all(prices[c][:before]==prices["control"][:before] for c in CELLS)
    event_price=[p[before]["price"] for p in prices.values()]
    assert all(x==event_price[0] for x in event_price),"rules saw current dividend early"
    base=np.array([float(r["dividend"]) for r in prices["control"]])
    shifted=np.array([float(r["dividend"]) for r in prices["fundamentals_only"]])
    np.testing.assert_array_equal(base[:before],shifted[:before])
    np.testing.assert_allclose(shifted[before:],1.2*base[before:],rtol=1e-13,atol=1e-15)
    for cell,p in paths.items():
        shift,announce=CELLS[cell]
        summary=summaries[cell]
        assert summary["status"]=="completed" and summary["rounds"]==ROUNDS
        assert summary["announcements_available"]==int(announce) and summary["event_records"]==1
        assert summary["llm_usage"]["requests_made"]==0
        assert summary["max_cash_conservation_error"]<1e-7
        audit=[json.loads(line) for line in (p/"event_audit.jsonl").read_text().splitlines()]
        assert len(audit)==1 and audit[0]["announce"]==announce
        assert audit[0]["public_headline"]==(HEADLINE if announce else None)
        assert abs(audit[0]["regime_benchmark_after"]-(120 if shift else 100))<1e-10
        assert len(rows(p/"events.csv"))==int(announce)
    first_change=next((int(a["round"]) for a,b in zip(prices["control"],prices["fundamentals_only"]) if a["price"]!=b["price"]),None)
    assert first_change is None or first_change>EVENT_ROUND
    metrics=[]
    for cell,rs in prices.items():
        close=np.array([float(r["price"]) for r in rs]);fund=np.array([float(r["fundamental"]) for r in rs])
        metrics.append(dict(seed=seed,cell=cell,final_price=close[-1],post_mean_price=float(close[before:].mean()),
            post_mean_absolute_relative_gap=float(np.abs(close[before:]/fund[before:]-1).mean()),
            last100_mean_price=float(close[-100:].mean()),event_price=float(rs[before]["price"])))
    return dict(seed=seed,announcement_pairs_financially_identical=True,initial_resources_equal=True,
                pre_event_prefix_equal=True,scaled_dividend_innovations_equal=True,
                event_auction_unaffected_by_current_payout=True,first_price_difference_round=first_change),metrics


def check(output_root="runs"):
    target=Path(output_root)/(time.strftime("%Y%m%d_%H%M%S_")+"news_rule_controls_"+uuid.uuid4().hex[:8])
    target.mkdir(parents=True)
    (target/"configs").mkdir()
    (target/"driver_source.py").write_bytes(Path(__file__).read_bytes())
    protocol=dict(version="news_factorial_controls_v1",purpose="Verify independent announcement and economic controls before live news experiments",
        cells={c:{"economic_shift":x,"announcement":y} for c,(x,y) in CELLS.items()},seeds=SEEDS,
        rounds=ROUNDS,event_round=EVENT_ROUND,shift_multiplier=1.2,headline=HEADLINE,
        reveal_fundamental=False,population="unchanged 20-rule-agent baseline; all ignore headline text",
        expectation="Announcement-only/control and combined/quiet-shock financial paths must match exactly. Current payout is unknown before the event auction.",
        interpretation="Engineering negative control; not live semantic behaviour, human realism, optimal calibration or an LLM-versus-rule population comparison.")
    write_json(target/"protocol.json",protocol)
    index,checks,metrics=[],[],[]
    for seed in SEEDS:
        paths={}
        for cell in CELLS:
            cfg=recipe(cell,seed)
            path=target/"configs"/f"{cell}_{seed}.yaml"
            path.write_text(yaml.safe_dump(cfg.to_dict()),encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                result=Path(run(path,output_root=target/"market_runs"))
            paths[cell]=result
            index.append(dict(seed=seed,cell=cell,run_path=result.relative_to(target).as_posix(),
                              manifest_sha256=hashlib.sha256((result/"manifest.json").read_bytes()).hexdigest()))
            write_json(target/"runs.json",index)
            print(f"completed {cell} / seed {seed}",flush=True)
        verified,values=verify(paths,seed)
        checks.append(verified);metrics.extend(values)
    write_json(target/"report.json",dict(status="verified_rule_controls",protocol=protocol,runs=index,checks=checks,metrics=metrics))
    print(f"verified rule controls -> {target}",flush=True)
    return target


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--output-root",default="runs")
    args=parser.parse_args()
    check(args.output_root)
