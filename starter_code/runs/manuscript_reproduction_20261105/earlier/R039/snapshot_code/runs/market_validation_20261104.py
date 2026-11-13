"""R039: fresh one-factor rule-market confirmation plus one empirical context."""
import argparse
import contextlib
import csv
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import time
import urllib.request
import uuid
import zipfile
import numpy as np
import yaml
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sim.background_check import slot_recipe
from sim.config import load_config, parse_config
from sim.engine import run
from sim.evaluation import evaluate_run, read_rows
from sim.provenance import sha256, write_json
from sim.sequential_markets import verify_market

BASE = Path(__file__).resolve().parents[1]
VERSION = "fresh_skew_confirmation_v1"
SEEDS = (16253, 17341, 18433, 19531)
URL = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_Factors_daily_CSV.zip"
CUTOFF = "20251231"


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def acf(values):
    x = np.asarray(values, dtype=float); x = x-x.mean(); denominator = float(x@x)
    return [None if denominator == 0 or len(x) <= lag else float(x[:-lag]@x[lag:]/denominator) for lag in range(1,11)]


def returns(rows, initial):
    prices = np.array([float(r["price"]) for r in rows]); dividends = np.array([float(r["dividend"]) for r in rows])
    previous = np.r_[initial, prices[:-1]]
    return np.log(prices/previous), np.log((prices+dividends)/previous)


def empirical(data, count=600, cutoff=CUTOFF):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = [n for n in archive.namelist() if n.lower().endswith(".csv")]
        assert len(names) == 1
        text = archive.read(names[0]).decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text))); header = next(row for row in rows if "Mkt-RF" in [v.strip() for v in row])
    fields = [x.strip() for x in header]; mi, ri = fields.index("Mkt-RF"),fields.index("RF")
    dated = [row for row in rows if row and re.fullmatch(r"\d{8}",row[0].strip())]
    dates = [row[0].strip() for row in dated]
    assert dates == sorted(set(dates)), "Unordered or duplicate observation dates"
    chosen = [row for row in dated if row[0].strip() <= cutoff][-count:]
    assert len(chosen) == count, "Insufficient observations at frozen cutoff"
    records = []
    for row in chosen:
        m, r = float(row[mi]), float(row[ri])
        assert np.isfinite(m+r) and m not in (-99.99,-999.) and r not in (-99.99,-999.)
        simple = (m+r)/100; assert simple > -1
        records.append(dict(date=row[0].strip(),market_excess_pct=m,rf_pct=r,simple_total_return=simple,log_total_return=float(np.log1p(simple))))
    values = np.array([r["log_total_return"] for r in records])
    return dict(zip_member=names[0],banner=text.splitlines()[:5],records=records,first_date=records[0]["date"],last_date=records[-1]["date"],
                acf_total=acf(values),acf_abs_total=acf(np.abs(values)),zero_return_count=int(sum(values==0)),count=len(values))


def recipe(seed, cell):
    raw = slot_recipe(seed, skew=.02 if cell=="original" else 0, dividend_window=1).to_dict()
    raw["name"] = f"skew_confirmation_{cell}_{seed}"
    return parse_config(raw)


def prepare(output="runs"):
    root=Path(output)/(time.strftime("%Y%m%d_%H%M%S_")+"market_validation_"+uuid.uuid4().hex[:8]);root.mkdir(parents=True,exist_ok=False);(root/"configs").mkdir()
    arms=[]
    for j,seed in enumerate(SEEDS):
        for cell in (("original","no_skew") if j%2==0 else ("no_skew","original")):
            path=root/"configs"/f"{seed}_{cell}.yaml";path.write_text(yaml.safe_dump(recipe(seed,cell).to_dict()),encoding="utf-8")
            arms.append(dict(seed=seed,cell=cell,config=path.relative_to(root).as_posix(),config_sha256=sha256(path)))
    files=[*sorted((BASE/"sim").rglob("*.py")),Path(__file__),BASE/"configs/pilot_a_mock.yaml"]
    hashes={p.relative_to(BASE).as_posix():sha256(p) for p in files}
    with zipfile.ZipFile(root/"prepared_source.zip","x",zipfile.ZIP_DEFLATED) as archive:
        for p in files:archive.write(p,p.relative_to(BASE).as_posix())
    shutil.copyfile(__file__,root/"driver_source.py")
    write_json(root/"protocol.json",dict(version=VERSION,status="frozen_before_outcomes",created_utc=datetime.now(timezone.utc).isoformat(),
        parent_revision=subprocess.check_output(["git","rev-parse","HEAD"],cwd=BASE,text=True).strip(),
        working_tree_status=subprocess.check_output(["git","status","--short"],cwd=BASE,text=True).splitlines(),
        source_sha256=hashes,source_zip_sha256=sha256(root/"prepared_source.zip"),arms=arms,seeds=list(SEEDS),rounds=600,
        question="Independent confirmation of existing inventory-skew return-dependence mechanism with liquidity/activity/gap trade-offs, not lowest-gap default selection.",
        primary="Within each of four fresh seeds: no_skew minus original full600 regular-session log-price-return ACF1. Preserve all signs; four scenarios, not eight independent repetitions. No financial-sign gate or significance test.",
        secondary="Price/absolute-return lags1-10,turnover,gaps,MM participation/boundaries,cash/concentration;three200-session blocks;both passive marks/counterparts. Same initial state and dividend path within seed. Rules only, no long LLM or human validation.",
        empirical=dict(url=URL,cutoff=CUTOFF,count=600,selection="Last600 observed dates <=cutoff fixed before download, no date/asset shopping. No fill/drop within selected window; invalid/missing rows fail this context.",
            convention="Real log1p((Mkt-RF+RF)/100) versus simulated log((P_t+d_t)/P_prev). Price-only primary remains distinct. Zeros retained; no annualization,alpha,pass score or numeric calibration.",
            limitations="Broad US value-weighted equity portfolio and single14-agent batch-market stock differ in population,institutions,dividends,clock and fundamentals. One historical window/current-vintage file,not an independent validation sample or universal target. No observed LLM long-run statistics.",
            download="One public HTTPS download <=10MB,60s,no credentials,retries or substitute dataset; unavailable context retained separately from completed simulation.")))
    write_json(root/"preparation.json",dict(protocol_sha256=sha256(root/"protocol.json")));print(root,flush=True);return root


def validate(root):
    p=read(root/"protocol.json");assert sha256(root/"protocol.json")==read(root/"preparation.json")["protocol_sha256"]
    assert sha256(root/"prepared_source.zip")==p["source_zip_sha256"]
    assert all(sha256(BASE/n)==h for n,h in p["source_sha256"].items()),"Source drift"
    assert all(sha256(root/a["config"])==a["config_sha256"] for a in p["arms"]),"Config drift"
    return p


def describe(path):
    cfg=load_config(path/"config.yaml");rows=read_rows(path/"prices.csv");prices,total=returns(rows,cfg.asset.initial_price)
    ev=evaluate_run(path);liquidity=read_rows(path/"liquidity.csv");states=read_rows(path/"agents_state.csv");initial=read_rows(path/"initial_state.csv")
    blocks=[]
    for start in (0,200,400):
        end=start+200;selected=rows[start:end];volume=np.array([int(x["volume"]) for x in selected]);blockstates=[x for x in states if start<int(x["round"])<=end]
        opening=sum(float(x["cash"]) for x in (initial if start==0 else states) if start==0 or int(x["round"])==start)
        closing=sum(float(x["cash"]) for x in blockstates if int(x["round"])==end)
        blocks.append(dict(start=start+1,end=end,price_acf=acf(prices[start:end]),abs_price_acf=acf(np.abs(prices[start:end])),
            total_acf=acf(total[start:end]),abs_total_acf=acf(np.abs(total[start:end])),turnover=float(volume.sum()/1450/200),
            gap=float(np.mean([abs(float(x["price"])/float(x["fundamental"])-1) for x in selected])),
            mm_share=None if volume.sum()==0 else float(sum(float(x["market_maker_volume_fraction"] or 0)*v for x,v in zip(liquidity[start:end],volume))/volume.sum()),
            mm_boundary_fraction=sum(x["type"]=="MarketMakerAgent" and int(x["shares"]) in (0,300) for x in blockstates)/200,cash_growth=closing/opening-1))
    return dict(evaluation=ev,acf_price=acf(prices),acf_abs_price=acf(np.abs(prices)),acf_total=acf(total),acf_abs_total=acf(np.abs(total)),blocks=blocks)


def execute(root):
    root=Path(root);p=validate(root)
    if any((x/"execution.json").exists() for x in root.parent.glob("*_market_validation_*") if x.resolve()!=root.resolve()):raise ValueError("Campaign already attempted")
    with (root/"execution.json").open("x") as stream:json.dump(dict(started_utc=datetime.now(timezone.utc).isoformat()),stream)
    index=[];status="running";failure=None
    try:
        for a in p["arms"]:
            with contextlib.redirect_stdout(io.StringIO()):path=Path(run(root/a["config"],output_root=root/"market_runs"))
            summary=read(path/"summary.json");verify_market(path)
            assert summary["status"]=="completed" and summary["rounds"]==600 and summary["llm_usage"]["requests_made"]==0 and summary["max_cash_conservation_error"]<1e-7
            result=describe(path);ev=result["evaluation"]
            assert 0<=ev["metrics"]["mm_inventory_min"]<=ev["metrics"]["mm_inventory_max"]<=300 and all(abs(x)<1e-7 for x in ev["aggregate_active_minus_passive"].values())
            index.append({**a,"run_path":path.relative_to(root).as_posix(),"manifest_sha256":sha256(path/"manifest.json"),**result});write_json(root/"runs.json",index)
            print(f"completed {a['seed']} {a['cell']}",flush=True)
        for seed in SEEDS:
            pair=[root/x["run_path"] for x in index if x["seed"]==seed]
            assert (pair[0]/"initial_state.csv").read_bytes()==(pair[1]/"initial_state.csv").read_bytes()
            assert [x["dividend"] for x in read_rows(pair[0]/"prices.csv")]==[x["dividend"] for x in read_rows(pair[1]/"prices.csv")]
        status="completed"
    except Exception as exc:
        status="failed";failure=type(exc).__name__;raise
    finally:
        write_json(root/"summary.json",dict(status=status,completed=len(index),planned=8,api_requests=0,failure_type=failure,finished_utc=datetime.now(timezone.utc).isoformat()))
    external=dict(status="unavailable",url=URL,attempted_utc=datetime.now(timezone.utc).isoformat())
    try:
        request=urllib.request.Request(URL,headers={"User-Agent":"MTP academic simulation diagnostic"})
        with urllib.request.urlopen(request,timeout=60) as response:data=response.read(10*1024*1024+1)
        assert len(data)<=10*1024*1024
        (root/"french_daily_source.zip").write_bytes(data)
        external.update(status="available",sha256=sha256(root/"french_daily_source.zip"),bytes=len(data),**empirical(data))
    except Exception as exc:external.update(status="unavailable",error_type=type(exc).__name__)
    write_json(root/"empirical_context.json",external)
    contrasts=[]
    for seed in SEEDS:
        by={a["cell"]:a for a in index if a["seed"]==seed};a,b=by["no_skew"],by["original"]
        contrasts.append(dict(seed=seed,delta_acf1=a["acf_price"][0]-b["acf_price"][0],secondary={k:a["evaluation"]["metrics"][k]-b["evaluation"]["metrics"][k] for k in ("mean_absolute_relative_gap","turnover_per_round","volume_weighted_mm_share","aggregate_cash_growth")},block_delta_acf1=[x["price_acf"][0]-y["price_acf"][0] for x,y in zip(a["blocks"],b["blocks"])]))
    write_json(root/"report.json",dict(version=VERSION,protocol_sha256=sha256(root/"protocol.json"),summary=read(root/"summary.json"),paired_contrasts=contrasts,runs=index,empirical_context=external))
    render(root,index,contrasts,external)
    write_json(root/"output_manifest.json",{x.name:sha256(x) for x in root.iterdir() if x.is_file() and x.name!="output_manifest.json"})


def render(root,index,contrasts,external):
    lines=["# R039: independent market-background confirmation","","Eight600-round rule markets, four fresh seeds; one factor MM inventory skew. Original settings remain unchanged. No LLM API calls. See protocol/report for exact sources, paired financial controls, all blocks, both passive wealth marks and limitations.","","Primary no-skew minus original full600 PRICE-return ACF1; zeros and initial-to-first change retained. No pass score, parameter selection or significance test.","","|Seed|ACF1 difference|Gap difference pp|Turnover difference pp|MM share difference pp|","|---|---:|---:|---:|---:|"]
    for c in contrasts:lines.append(f"|{c['seed']}|{c['delta_acf1']:.4f}|{100*c['secondary']['mean_absolute_relative_gap']:.3f}|{100*c['secondary']['turnover_per_round']:.3f}|{100*c['secondary']['volume_weighted_mm_share']:.3f}|")
    lines += ["", "## Empirical context, not calibration", "",f"Download status:{external['status']}. Official source: https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html ; construction: https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/Data_Library/f-f_factors.html . Fixed last600 dated returns <=2025-12-31, never selected after viewing. Current-vintage file/hash retained; revisions may change historical observations.","", "External market return reconstructs(Mkt-RF+RF)/100 before log1p; simulated TOTAL share return uses log((P_t+d_t)/P_prev). These differ from the price-only primary. Broad US portfolio versus one14-agent batch-market stock, different institutions/fundamentals/cashflows; one window is not a universal real-market target. This is not human validation or long-run LLM evidence."]
    if external["status"]=="available":lines += ["",f"Selected dates:{external['first_date']}--{external['last_date']};600 observations; total-return ACF1={external['acf_total'][0]:.4f},absolute-total-return ACF1={external['acf_abs_total'][0]:.4f}."]
    lines += ["", "![All paired return-dependence diagnostics](diagnostics.png)","", "Full600 and three200-session blocks expose changing activity/dependence/cash and MM inventory; do not assume stationarity or select a setting by gap alone. Counterpart passive gains cancel; neither profit nor more trading is a realism oracle. Discovery R020 stays separate from these new confirmation seeds. All positive,zero,negative effects retained. A/B/C unchanged and separate."]
    (root/"READOUT.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    fig,axes=plt.subplots(2,2,figsize=(11,7),layout="constrained")
    for a in index:
        style="-" if a["cell"]=="original" else "--";color="C0" if a["cell"]=="original" else "C1"
        for ax,key in zip(axes.flat,("acf_price","acf_abs_price","acf_total","acf_abs_total")):ax.plot(range(1,11),a[key],style,color=color,alpha=.65)
    if external["status"]=="available":
        for ax,key in zip(axes[1],("acf_total","acf_abs_total")):ax.plot(range(1,11),external[key],color="black",lw=2,label="US market: fixed600-date window")
    for ax,title in zip(axes.flat,("Price returns (primary1)","Absolute price returns","Total share returns (+ dividend)","Absolute total share returns")):
        ax.plot([],[],color="C0",label="Original skew .02, four seeds");ax.plot([],[],color="C1",ls="--",label="No skew, same four seeds")
        ax.axhline(0,color="gray",lw=.7);ax.set(xlabel="Session lag",ylabel="Descriptive ACF",title=title);ax.grid(alpha=.2);ax.legend(fontsize=7)
    fig.suptitle("Rule-market confirmation and limited empirical context; no realism pass score")
    fig.savefig(root/"diagnostics.png",dpi=170);fig.savefig(root/"diagnostics.pdf");plt.close(fig)


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("action",choices=("prepare","run"));parser.add_argument("--study");parser.add_argument("--output",default="runs");args=parser.parse_args()
    prepare(args.output) if args.action=="prepare" else execute(Path(args.study))
