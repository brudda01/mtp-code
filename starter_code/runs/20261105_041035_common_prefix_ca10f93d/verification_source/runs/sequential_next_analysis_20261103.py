"""Read-only R028/R029 linked market audit; no model calls or raw-run mutations."""
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import shutil
import zipfile

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from sim.agents.llm_agent import REFLECTION_TEMPLATE
from sim.evaluation import evaluate_run,read_rows,passive_cash_path
from sim.config import load_config
from sim.llm.client import dotenv_api_key
from sim.news_pilot import market_metrics
from sim.provenance import sha256,write_json
from sim.sequential_markets import validate,verify_market
from runs.sequential_next_20261103 import validate_phase

ROOT=Path(__file__).resolve().parent/"20261103_183126_sequential_markets_bb927356"
PHASE=ROOT.parent/"20261103_195320_sequential_next_fd0fc07c"
OUTPUT=ROOT.parent/"sequential_next_analysis_20261103"


def read(path,default):
    return json.loads(path.read_text()) if path.exists() else default


def lines(path):return [json.loads(s) for s in path.read_text().splitlines()]


def audit_run(path):
    m=verify_market(path)
    with zipfile.ZipFile(path/"source.zip") as z:
        for name,digest in m["source_sha256"].items():assert hashlib.sha256(z.read(name)).hexdigest()==digest
    return m


def observed_prefix(arm,horizon):
    """Secondary read-only accounting; never constructs or relabels a run."""
    path=Path(arm["artifact_root"])/arm["run_path"];cfg=load_config(path/"config.yaml")
    prices=read_rows(path/"prices.csv")[:horizon]
    assert len(prices)==horizon
    states={r["agent_id"]:r for r in read_rows(path/"agents_state.csv") if int(r["round"])==horizon}
    trades=[r for r in read_rows(path/"trades.csv") if int(r["round"])<=horizon]
    accounts={}
    for start in read_rows(path/"initial_state.csv"):
        aid=start["agent_id"]
        if aid not in ("llm_012","llm_013"):continue
        end=states[aid];cash=passive_cash_path(float(start["cash"]),int(start["shares"]),[float(r["dividend"]) for r in prices],cfg.asset.risk_free)[-1]
        marks={name:(float(end["cash"])-cash+(int(end["shares"])-int(start["shares"]))*mark)/float(start["wealth"])
            for name,mark in (("auction",float(prices[-1]["price"])),("regime_benchmark",float(prices[-1]["fundamental"])))}
        post=[r for r in trades if int(r["round"])>=11]
        bought=sum(int(r["quantity"]) for r in post if r["buyer_id"]==aid)
        sold=sum(int(r["quantity"]) for r in post if r["seller_id"]==aid)
        accounts[aid]=dict(passive_excess=marks,post_executed_gross=bought+sold,post_executed_net=bought-sold,shares=int(end["shares"]))
        if horizon==arm["rounds"]:
            full=next(a for a in arm["target_accounts"] if a["agent_id"]==aid)
            assert all(math.isclose(v,full["marks"][m]["excess_return"],abs_tol=1e-12) for m,v in marks.items())
    return dict(post_mean_gap=float(np.mean([abs(float(r["price"])/float(r["fundamental"])-1) for r in prices if int(r["round"])>=11])),accounts=accounts)


def analyze():
    protocol=validate(ROOT);amendment=validate_phase(PHASE);OUTPUT.mkdir(exist_ok=True)
    baseline=read(ROOT/"baseline_runs.json",[]);base_rows=[];all_paths=[];arms=[];requests=[]
    for entry in baseline:
        path=ROOT/entry["run_path"];audit_run(path);all_paths.append(path)
        assert sha256(path/"manifest.json")==entry["manifest_sha256"]
        evaluation=evaluate_run(path)
        assert evaluation==read(ROOT/f"baseline_evaluation_{entry['cell']}_{entry['seed']}.json",{})
        base_rows.append(dict(seed=entry["seed"],cell=entry["cell"],run_path=entry["run_path"],metrics=evaluation["metrics"],
            event_metrics=market_metrics(path)["event_metrics"] if entry["cell"]=="combined" else None,
            target_accounts=[a for a in evaluation["accounts"] if int(a["agent_id"].rsplit("_",1)[1]) in (12,13)]))
    first_prompts={};statuses=[];reflection_checks=0;reflection_cycles=set();common_personas={};delivered_decisions=0;window_cases=[];uncleared=[];retention=[];quote_examples=[]
    for block in protocol["blocks"]:
        artifact_root=PHASE if block["seed"]==5209 else ROOT
        folder=artifact_root/f"block_{block['seed']}"
        statuses.append(dict(seed=block["seed"],summary=read(folder/"summary.json",None),progress=read(folder/"progress.json",None)))
        for entry in read(folder/"runs.json",[]):
            path=artifact_root/entry["run_path"];m=audit_run(path);all_paths.append(path)
            assert sha256(path/"manifest.json")==entry["manifest_sha256"]
            summary=read(path/"summary.json",{});prices=read_rows(path/"prices.csv")
            ref=ROOT/next(e["run_path"] for e in baseline if e["seed"]==entry["seed"] and e["cell"]=="combined")
            assert [r["dividend"] for r in prices]==[r["dividend"] for r in read_rows(ref/"prices.csv")[:len(prices)]]
            resource=lambda p:[(r["cash"],r["shares"],r["wealth"]) for r in read_rows(p/"initial_state.csv")]
            assert resource(path)==resource(ref)
            cfg=load_config(path/"config.yaml")
            assert cfg==load_config(ROOT/entry["config"])
            if entry["seed"]==5209:
                trades=read_rows(path/"trades.csv")
                for order in read_rows(path/"orders.csv"):
                    rnd=int(order["round"]);aid=order["agent_id"]
                    if aid=="llm_012" and 11<=rnd<=min(15,len(prices)):
                        quote_examples.append(dict(mode=entry["mode"],round=rnd,side=order["side"],accepted=int(order["quantity"]),
                            limit=None if not order["limit_price"] else float(order["limit_price"]),price=float(prices[rnd-1]["price"]),
                            filled=sum(int(t["quantity"]) for t in trades if int(t["round"])==rnd and aid in (t["buyer_id"],t["seller_id"]))))
            calls=[r for r in lines(path/"llm_requests.jsonl") if r["record_type"]=="model_call"]
            requests+=calls
            assert len(calls)==summary["llm_usage"]["requests_made"]
            assert len({r["call_id"] for r in calls})==len(calls)
            groups={}
            for call in calls:groups.setdefault(call["request_group_id"],[]).append(call)
            for group in groups.values():
                assert len(group)<=2
                if len(group)==2:
                    assert group[0]["status"]=="error" and group[0]["transport_retry_planned"]
                    for name in ("messages","temperature","max_tokens","reasoning_effort","json_mode"):assert group[0][name]==group[1][name]
            for call in calls:
                assert call["max_tokens"]==8192 and call["reasoning_effort"]=="low"
                if call["call_type"]=="decision" and call["round"]==1 and call.get("json_attempt",1)==1:
                    first_prompts[entry["seed"],entry["mode"],call["agent_id"]]=call["messages"]
            outcomes=lines(path/"agent_outcomes.jsonl");records=lines(path/"llm_calls.jsonl")
            delivered_decisions+=sum(r["record_type"]=="decision" and r.get("failure_type") is None for r in records)
            uncleared.extend(dict(seed=entry["seed"],mode=entry["mode"],agent_id=r["agent_id"],round=r["round"],intent=r["intent"],note="Delivered but no auction/execution/feedback for this financial round.")
                for r in records if r["record_type"]=="decision" and r.get("failure_type") is None and r["round"]>len(prices))
            for r in records:
                if r["record_type"]=="reflection" and r.get("failure_type") is None:
                    assert r["diary"]==" ".join(r["raw"].split()[:120])
                    retention.append(dict(seed=entry["seed"],agent_id=r["agent_id"],round=r["round"],raw_words=len(r["raw"].split()),retained_words=len(r["diary"].split()),cut_by_120_word_retention=len(r["raw"].split())>120))
            personas=read(path/"personas.json",{})
            assert personas==common_personas.setdefault(entry["seed"],personas)
            for aid,p in personas.items():
                prior="none"
                for call in [r for r in calls if r["agent_id"]==aid and r["call_type"]=="reflection"]:
                    memory=[r["outcome"] for r in outcomes if r["agent_id"]==aid and r["outcome"]["round"]<=call["round"]][-5:]
                    expected=[dict(role="system",content=REFLECTION_TEMPLATE.format(name=p["name"],risk=p["risk_tolerance"],
                        style=p["strategy_inclination"],horizon=p["horizon"],biases=p["bias_clauses"])),
                        dict(role="user",content="Previous reflection (fallible): "+prior+"\nVerified recent outcomes: "+json.dumps(memory,allow_nan=False))]
                    assert call["messages"]==expected and call["temperature_sent"]==0
                    if call["status"]=="returned":
                        record=next((r for r in records if r["record_type"]=="reflection" and r["agent_id"]==aid and r["round"]==call["round"]),None)
                        if record is not None:
                            prior=record["diary"] or prior
                            if record["diary"] and record.get("failure_type") is None:reflection_cycles.add((entry["seed"],aid,call["round"]))
                    reflection_checks+=1
            if entry["seed"]==4103 and entry["mode"]=="C":
                diaries={r["round"]:r["diary"] for r in records if r["record_type"]=="reflection" and r["agent_id"]=="llm_013"}
                fills={r["outcome"]["round"]:r["outcome"]["fills"] for r in outcomes if r["agent_id"]=="llm_013"}
                assert fills[11]==[dict(side="buy",quantity=5,price=106.8)] and fills[16]==[dict(side="buy",quantity=1,price=116.1)]
                assert "5 shares at 106.8" in diaries[15] and "not the 5 at 106.8 I recalled" in diaries[20]
                window_cases.append(dict(seed=4103,mode="C",agent_id="llm_013",source_run=entry["run_path"],
                    earlier_diary_round=15,later_diary_round=20,later_verified_window=list(range(16,21)),
                    actual_fills={11:fills[11],16:fills[16]},earlier_diary=diaries[15],later_diary=diaries[20],
                    interpretation="Qualitative, post-hoc candidate window-scope conflation: both purchases occurred, but the later diary calls the earlier true purchase a mistaken recollection. No estimated error rate or measured causal trading harm."))
            metrics=market_metrics(path) if len(prices)>=protocol["event_round"] else None
            if metrics is not None:assert metrics==read(folder/f"metrics_{entry['mode']}.json",{})
            evaluation=evaluate_run(path) if prices else None
            if evaluation is not None:
                assert all(abs(v)<1e-7 for v in evaluation["aggregate_active_minus_passive"].values())
                assert 0<=evaluation["metrics"]["mm_inventory_min"]<=evaluation["metrics"]["mm_inventory_max"]<=300
                states=read_rows(path/"agents_state.csv")
                assert all(float(r["cash"])>=-1e-7 and int(r["shares"])>=0 for r in states)
                assert all(sum(int(r["shares"]) for r in states if int(r["round"])==i)==1450 for i in range(1,len(prices)+1))
            trading=[];headroom=[]
            if metrics is not None:
                for aid in sorted(personas):
                    for label in ("pre","post"):
                        rows=[r for r in metrics["target_rounds"] if r["agent_id"]==aid and (r["round"]<protocol["event_round"])==(label=="pre")]
                        accepted=sum(r["accepted_quantity"] for r in rows)
                        filled=sum(r["executed_buy"]+r["executed_sell"] for r in rows)
                        trading.append(dict(agent_id=aid,name=personas[aid]["name"],period=label,
                            requested=sum(abs(r["requested_signed"]) for r in rows if r["requested_signed"] is not None),accepted=accepted,
                            executed=filled,net_executed=sum(r["executed_signed"] for r in rows),
                            gross_fill_fraction=None if not accepted else filled/accepted))
                    state=next(r for r in read_rows(path/"agents_state.csv") if r["agent_id"]==aid and int(r["round"])==protocol["event_round"]-1)
                    price=float(prices[protocol["event_round"]-2]["price"])
                    low_tick=math.ceil(price*(1-cfg.market.price_band)/cfg.market.tick-1e-12)*cfg.market.tick
                    headroom.append(dict(agent_id=aid,cash=float(state["cash"]),shares=int(state["shares"]),price=price,
                        stock_weight=int(state["shares"])*price/float(state["wealth"]),
                        best_band_limit_buy_capacity=math.floor(float(state["cash"])/(low_tick*(1+cfg.market.transaction_tax))+1e-12),
                        market_buy_capacity=math.floor(float(state["cash"])/(price*(1+cfg.market.price_band)*(1+cfg.market.transaction_tax))+1e-12)))
            accounts=[] if evaluation is None else [a for a in evaluation["accounts"] if int(a["agent_id"].rsplit("_",1)[1]) in (12,13)]
            arms.append({**entry,"artifact_root":str(artifact_root),"summary":summary,"event_metrics":None if metrics is None else metrics["event_metrics"],
                "market_metrics":None if evaluation is None else evaluation["metrics"],"target_trading":trading,
                "event_account_constraints":headroom,"target_accounts":accounts,
                "initial_choices":[dict(agent_id=r["agent_id"],**{k:r["intent"][k] for k in ("side","quantity","limit_price")})
                    for r in records if r["record_type"]=="decision" and r["round"]==1],
                "usage_by_call_type":{kind:dict(http_attempts=sum(r["call_type"]==kind for r in calls),
                    provider_reported_tokens=sum(r["usage"]["total_tokens"] for r in calls if r["call_type"]==kind and r.get("usage") and r["usage"]["source"]=="provider"),
                    unknown_usage_attempts=sum(r["call_type"]==kind and not (r.get("usage") and r["usage"]["source"]=="provider") for r in calls))
                    for kind in ("decision","reflection")}})
    equal_initial=[]
    for seed in protocol["seeds"]:
        for aid in ("llm_012","llm_013"):
            if all((seed,c,aid) in first_prompts for c in ("B","C")):
                assert first_prompts[seed,"B",aid]==first_prompts[seed,"C",aid]
                equal_initial.append(dict(seed=seed,agent_id=aid))
    usage={k:sum(a["summary"]["llm_usage"][k] for a in arms) for k in ("requests_made","reserved_tokens","provider_reported_tokens","unknown_usage_requests","failed_requests","blocked_requests")}
    phase_usage={k:sum(a["summary"]["llm_usage"][k] for a in arms if a["seed"]==5209) for k in usage}
    assert all(sum(a["summary"]["llm_usage"][k] for a in arms if a["seed"]==4103)==v for k,v in amendment["parent_usage"].items())
    assert phase_usage["requests_made"]<=270 and phase_usage["reserved_tokens"]<=3300000
    assert usage["requests_made"]<=810 and usage["reserved_tokens"]<=9900000
    assert sum(r["usage"]["total_tokens"] for r in requests if r.get("usage") and r["usage"]["source"]=="provider")==usage["provider_reported_tokens"]
    secrets={v.encode() for n in ("API_KEY","BHARATCODE_API_KEY","GEMINI_API_KEY","NVIDIA_API_KEY") if (v:=dotenv_api_key(n)) and len(v)>=8}
    scanned=0
    for path in all_paths:
        for file in path.iterdir():
            if not file.is_file():continue
            assert not file.name.startswith(".env")
            if file.suffix==".zip":
                with zipfile.ZipFile(file) as z:
                    for name in z.namelist():assert not any(v in z.read(name) for v in secrets);scanned+=1
            else:assert not any(v in file.read_bytes() for v in secrets);scanned+=1
    completed={(a["seed"],a["mode"]) for a in arms if a["status"]=="completed" and a["rounds"]==protocol["rounds"] and not any(a["operational_failures"].values())}
    by_condition={(a["seed"],a["mode"]):a for a in arms};contrasts=[];observed_pairs=[]
    for arm in arms:
        if arm["rounds"]>=11:observed_prefix(arm,arm["rounds"])
    for seed in protocol["seeds"]:
        for before,after in (("A","B"),("B","C")):
            if not all((seed,c) in completed for c in (before,after)):
                contrasts.append(dict(seed=seed,contrast=f"{after}-{before}",comparable=False,reason="At least one arm unrun or partial/operationally affected; no full-horizon contrast."));continue
            x,y=[by_condition[seed,c] for c in (before,after)]
            accounts_x={a["agent_id"]:a for a in x["target_accounts"]};accounts_y={a["agent_id"]:a for a in y["target_accounts"]}
            contrasts.append(dict(seed=seed,contrast=f"{after}-{before}",comparable=True,
                post_gap_difference=y["event_metrics"]["post_mean_absolute_relative_gap"]-x["event_metrics"]["post_mean_absolute_relative_gap"],
                reported_token_difference=y["usage"]["provider_reported_tokens"]-x["usage"]["provider_reported_tokens"],
                passive_excess_differences={aid:{mark:accounts_y[aid]["marks"][mark]["excess_return"]-accounts_x[aid]["marks"][mark]["excess_return"] for mark in ("auction","regime_benchmark")} for aid in accounts_x},
                interpretation="Descriptive difference between these specified policies and unseeded model draws on a common scenario; one trajectory per condition, not isolated causal component efficacy."))
        if all((seed,c) in by_condition for c in ("B","C")):
            horizon=min(by_condition[seed,c]["rounds"] for c in ("B","C"))
            if 11<=horizon<24:
                observed_pairs.append(dict(seed=seed,rounds=horizon,B=observed_prefix(by_condition[seed,"B"],horizon),C=observed_prefix(by_condition[seed,"C"],horizon),
                    selection="Post-hoc minimum completed horizon, determined by operational stopping. Descriptive only; no assumption of noninformative censoring, replacement terminal result, cross-horizon averaging or causal effect."))
    report=dict(version=protocol["version"],protocol_sha256=sha256(ROOT/"protocol.json"),amendment_sha256=sha256(PHASE/"amendment.json"),
        parent_usage_preserved=amendment["parent_usage"],blocks=statuses,baselines=base_rows,arms=arms,
        uncompleted_live_arms=[dict(seed=b["seed"],mode=a["mode"]) for b in protocol["blocks"] for a in b["arms"] if (b["seed"],a["mode"]) not in completed],
        finalized_usage=usage,usage_scope="Finalized arms only; excludes active in-flight market during generation.",
        finalized_R029_usage=phase_usage,complete_ABC_scenarios=[s for s in protocol["seeds"] if all((s,c) in completed for c in "ABC")],
        returned_models=dict(Counter(r.get("response_metadata",{}).get("model","unreported") for r in requests if r["status"]=="returned")),
        delivered_valid_decisions=delivered_decisions,delivered_decisions_in_cleared_rounds=delivered_decisions-len(uncleared),
        delivered_but_uncleared=uncleared,reflection_retention_inventory=retention,qualitative_window_cases=window_cases,
        Meera_5209_rounds11_15_execution_examples=quote_examples,
        full_horizon_contrasts=contrasts,
        secondary_observed_horizon_pairs=observed_pairs,
        audits=dict(source_and_output_hashes=True,matched_resources_dividends=True,own_history_reflections_verified=len(reflection_cycles),
            own_history_reflection_attempt_prompts_verified=reflection_checks,
            observed_accounting_matches_canonical_at_each_own_horizon=True,
            identical_initial_B_C_messages=equal_initial,secret_scan_passed=True,scanned_members=scanned),
        limitations=protocol["limitations"],analysis_source_sha256=sha256(Path(__file__)))
    write_json(OUTPUT/"report.json",report)
    text=["# Linked sequential markets: next independent seed", "",f"Completed clean live arms: {len(completed)}/9. This pass targets seed5209 B/C/A only. Original seed4103 A/B24 and C22 remain preserved; seed6317 stays unrun.","",
        "R029 explicitly amends only BETWEEN-seed stopping after the provider error, allowing the next originally designated independent seed. No simulator/config/prompt/economic/cap change, repeated failed C4103 case, new seed or within-market stop amendment. New block status: "+str(read(PHASE/"block_5209/summary.json",read(PHASE/"block_5209/progress.json",{})).get("status","not started"))+".","",
        "R029 terminal delivery stop: B5209 completed24; C5209 ends19 after Arjun round20 HTTP503 and its failed identical-payload retry. Meera's round20 HOLD was delivered but never cleared; no order, trade, payout or outcome from that round is included in market metrics. A5209 never started. Six new reflections completed, not eight. No complete A/B/C scenario yet; four campaign arms remain unattempted.","",
        f"Coverage: {delivered_decisions} valid delivered decisions across linked blocks, of which {delivered_decisions-len(uncleared)} belong to completed financial rounds. The one other delivered choice is preserved as cancelled, not executed feedback. Reflection verification covers {len(reflection_cycles)} completed cycles and {reflection_checks} HTTP-attempt prompts, so a retry is not counted as another reflection.","",
        "First block STOPPED on Meera/C round23 HTTP503 and its one identical-payload retry (also503). A/B are complete24; C ends22 with all eight reflections. Round23 never cleared; Arjun's request was blocked after the provider stop, and round24 was unattempted. These missing outcomes are not HOLD preferences. No rerun, continuation or full-horizon C result.","",
        "24 rounds; public forecast plus actual permanent +20% dividend-mean change at round11. Same endowments, rules, personas and exogenous dividend path. A raw/B facts/C reflection start from round1; C reflects on its own real fills and outcomes. New common Qwen8192 profile, not pooled with old4096 probes.","",
        "Two preselected exogenous scenarios are represented, with the first C partial. A completed seed5209 would still be only ONE complete A/B/C scenario. Policies can produce different pre-news prices; the shared event is not an isolated causal headline comparison. B/C initial messages are checked identical: C has no diary until after round5, so earlier divergence cannot be attributed to reflection.","",
        "## Longer rule-only background context (600 quiet rounds)","",
        "| Seed | Mean benchmark gap | Return ACF1 | Absolute-return ACF1 | Turnover/round | MM volume share |",
        "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for b in base_rows:
        if b["cell"]!="long_quiet":continue
        m=b["metrics"];text.append(f"| {b['seed']} | {100*m['mean_absolute_relative_gap']:.2f}% | {m['acf_returns_lag1']:.3f} | {m['acf_absolute_returns_lag1']:.3f} | {100*m['turnover_per_round']:.2f}% | {100*m['volume_weighted_mm_share']:.1f}% |")
    text += ["", "Fresh seeds retain return dependence and substantial MM participation. These are descriptive, uncalibrated background results, not validation of financial stylized facts. No baseline was tuned/selected after these outcomes.","",
        "## Finalized markets with the same event", "", "| Policy/seed | Financial rounds | Pre-news price | Event price | Post mean gap | Target union trade share | Turnover/round | MM volume share |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    rule_context=[dict(mode="rules",seed=b["seed"],rounds=protocol["rounds"],status="completed",event_metrics=b["event_metrics"],market_metrics=b["metrics"])
        for b in base_rows if b["cell"]=="combined" and b["seed"] in {a["seed"] for a in arms}]
    for a in rule_context+arms:
        e=a["event_metrics"];m=a["market_metrics"]
        vals=["not observed"]*6 if e is None else [f"{e['pre_event_price']:.2f}",f"{e['event_price']:.2f}",f"{100*e['post_mean_absolute_relative_gap']:.2f}%", "no trades" if e['target_union_volume_share'] is None else f"{100*e['target_union_volume_share']:.1f}%",f"{100*m['turnover_per_round']:.2f}%",f"{100*m['volume_weighted_mm_share']:.1f}%"]
        text.append(f"| {a['mode']}/{a['seed']} | {a['rounds']}/{protocol['rounds']} ({a['status']}) | "+" | ".join(vals)+" |")
    text += ["", "Target union trade share counts a target-to-target trade once. It is not the share of trader legs. Equal resources do not equalize policy order sizes; these are specified-policy comparisons, not intrinsic LLM superiority.","",
        "## Actual orders and fills", "", "| Mode/seed/agent | Period | Requested / accepted / executed shares | Net executed shares |", "| --- | --- | ---: | ---: |"]
    for a in arms:
        for t in a["target_trading"]:text.append(f"| {a['mode']}/{a['seed']}/{t['name'].split()[0]} | {t['period']} | {t['requested']} / {t['accepted']} / {t['executed']} | {t['net_executed']:+d} |")
    text += ["", "Quantities here count target trader legs, not union market trades. A request, acceptance and fill are different. Pre/post headroom, all market diagnostics and failures are retained in report.json.","",
        "### Concrete execution example: Meera5209, rounds11-15", "",
        "| Mode / round | Accepted order | Limit | Actual auction price | Shares filled |", "| --- | --- | ---: | ---: | ---: |"]
    for q in quote_examples:text.append(f"| {q['mode']} / {q['round']} | {q['side']} {q['accepted']} | {q['limit']} | {q['price']} | {q['filled']} |")
    text += ["", "C requested five20-share buys, but its first four limits were below the realized auction price; only13 shares filled on its fifth bid. Zero fills therefore do not imply zero buying intent or ignored news. B/C market states and quote sizes differ, so this is an execution-mechanism illustration, not an isolated reflection effect.","",
        "## Opportunity just before the event", "", "| Mode/seed/agent | Stock weight | Market-buy capacity | Most optimistic band-limit buy capacity | Shares sellable |",
        "| --- | ---: | ---: | ---: | ---: |"]
    for a in arms:
        for h in a["event_account_constraints"]:
            text.append(f"| {a['mode']}/{a['seed']}/{h['agent_id']} | {100*h['stock_weight']:.2f}% | {h['market_buy_capacity']} | {h['best_band_limit_buy_capacity']} | {h['shares']} |")
    text += ["", "Market buys reserve the upper band; the optimistic limit capacity assumes the lowest tick within the band, which need not fill. These are pre-round11 accounts, not unconstrained measures of news attention. Large passive-relative gains can reflect exposure accumulated before the announcement.","",
        "## Conditional passive-relative returns", "", "Percentage-point excess over retaining initial shares and receiving the same payments, on this realized price path. Both terminal marks use the same initial wealth denominator. Not a separate no-trading equilibrium, risk-adjusted alpha or liquidation return.","",
        "| Mode/seed/agent | Completed rounds | Auction mark | Regime-benchmark mark |", "| --- | ---: | ---: | ---: |"]
    rule_accounts=[dict(mode="rules",seed=b["seed"],rounds=protocol["rounds"],target_accounts=b["target_accounts"])
        for b in base_rows if b["cell"]=="combined" and b["seed"] in {a["seed"] for a in arms}]
    for a in rule_accounts+arms:
        for x in a["target_accounts"]:
            text.append(f"| {a['mode']}/{a['seed']}/{x['agent_id']} | {a['rounds']}/24 | {100*x['marks']['auction']['excess_return']:+.2f} | {100*x['marks']['regime_benchmark']['excess_return']:+.2f} |")
    text += ["", "## Full-horizon component contrasts", "",
        "Each entry uses two clean24-round arms from the same seed; missing/partial pairs stay missing. These are descriptive differences with one unseeded trajectory per policy, not causal efficacy estimates. Negative gap differences mean closer average post-event prices; positive wealth differences mean higher conditional passive excess. Reported-token totals exclude unknown failed-request usage, so token differences are not complete billed-cost differences.","",
        "| Seed / contrast | Gap difference (pp) | Meera auction / benchmark excess difference (pp) | Arjun auction / benchmark excess difference (pp) | Reported token difference |",
        "| --- | ---: | ---: | ---: | ---: |"]
    for c in contrasts:
        if not c["comparable"]:
            text.append(f"| {c['seed']} / {c['contrast']} | missing | missing | missing | missing |");continue
        values=c["passive_excess_differences"]
        text.append(f"| {c['seed']} / {c['contrast']} | {100*c['post_gap_difference']:+.2f} | "+" | ".join(f"{100*values[aid]['auction']:+.2f} / {100*values[aid]['regime_benchmark']:+.2f}" for aid in ("llm_012","llm_013"))+f" | {c['reported_token_difference']:+d} |")
    text += ["", "## Secondary comparisons over observed rounds", "",
        "Post-hoc: compare B/C only through the last round completed in BOTH. These service-dependent cutoffs were not the planned24-round horizon; no assumption that missingness is harmless, no replacement terminal result, no pooling of different horizons or causal inference. Raw runs are unchanged; only recorded prices/fills/accounts are evaluated.","",
        "| Seed / observed rounds | C-B post gap (pp) | Meera C-B auction / benchmark excess (pp) | Arjun C-B auction / benchmark excess (pp) | Meera B / C post gross fills |",
        "| --- | ---: | ---: | ---: | ---: |"]
    for pair in observed_pairs:
        b,c=pair["B"],pair["C"]
        diffs={aid:{m:c["accounts"][aid]["passive_excess"][m]-b["accounts"][aid]["passive_excess"][m] for m in ("auction","regime_benchmark")} for aid in b["accounts"]}
        text.append(f"| {pair['seed']} / {pair['rounds']} | {100*(c['post_mean_gap']-b['post_mean_gap']):+.2f} | "+" | ".join(f"{100*diffs[aid]['auction']:+.2f} / {100*diffs[aid]['regime_benchmark']:+.2f}" for aid in ("llm_012","llm_013"))+f" | {b['accounts']['llm_012']['post_executed_gross']} / {c['accounts']['llm_012']['post_executed_gross']} |")
    text += ["", "## One qualitative memory caution", "",
        "The original seed4103's eight C reflection prompts were verified against its own actual last-five outcomes and previous diary. At15 Arjun correctly recalls buying5 at106.8 (round11). At20 it says the earlier5-share recollection was wrong and its only buy was1 at116.1 (round16); both trades actually occurred. The newer verified window covers16-20, while the earlier trade is outside it. This is a post-hoc candidate for conflating a recent window with total history, not an estimated hallucination rate or demonstrated trading harm. Raw diaries, inputs and both actual fills are preserved in report.json and the source run. No prompt change was made during the campaign.","",
        "## Before any reflection", "", "| Mode/seed/agent | First requested order |",
        "| --- | --- |"]
    for a in arms:
        for x in a["initial_choices"]:
            text.append(f"| {a['mode']}/{a['seed']}/{x['agent_id']} | {x['side']} {x['quantity']}, limit {x['limit_price']} |")
    text += ["", "B/C first messages are identical for each persona. C first reflects after round5; its diary first enters the decision at6. Differences already present at1 cannot be caused by added reflection. Model generation is unseeded; one trajectory per mode does not separate reflection effects from response variability and their subsequent feedback.","",
        "## Generation cost", "", "| Mode/seed | Decision attempts / reported tokens | Reflection attempts / reported tokens | Conservative reservations |",
        "| --- | ---: | ---: | ---: |"]
    for a in arms:
        d=a["usage_by_call_type"]["decision"];r=a["usage_by_call_type"]["reflection"]
        text.append(f"| {a['mode']}/{a['seed']} | {d['http_attempts']} / {d['provider_reported_tokens']} | {r['http_attempts']} / {r['provider_reported_tokens']} | {a['usage']['reserved_tokens']} |")
    text += ["",f"Finalized-arm usage: {json.dumps(usage)}. Full raw requests/reflections/failures and config/source manifests remain in each run. Student declared incremental prices zero; daily remaining quota is unverified.","",
        "Fatal provider/output/budget failure stops the block. Existing parse-HOLD/old-diary fallback is operationally flagged, not a model preference. No failed arm is resampled or spliced. Every arm's metrics and wealth marks end at its own listed financial horizon; a partial arm is not a comparable full-horizon result. Report all signs and missing/partial arms; do not infer human realism, headline causality or a uniform reflection upgrade from the first gate.","",
        "[Seed5209 market and portfolio paths](next_seed_paths.pdf) | [Full linked report](report.json) | [Preserved first-seed readout](../sequential_analysis_20261103/READOUT.md)", ""]
    (OUTPUT/"READOUT.md").write_text("\n".join(text),encoding="utf-8")
    fig,axes=plt.subplots(2,2,figsize=(11,7),constrained_layout=True)
    first=amendment["seed"];colors={"A":"#356999","B":"#cc8126","C":"#629448"}
    for a in arms:
        if a["seed"]!=first:continue
        path=Path(a["artifact_root"])/a["run_path"];p=read_rows(path/"prices.csv")
        if not p:continue
        x=[int(r["round"]) for r in p];color=colors[a["mode"]]
        initial=read_rows(path/"initial_state.csv")
        axes[0,0].plot([0]+x,[100.0]+[float(r["price"]) for r in p],label=f"{a['mode']} ({a['rounds']}/24)",color=color)
        axes[0,1].plot([0]+x,np.r_[0,np.cumsum([int(r["volume"]) for r in p])],label=a["mode"],color=color)
        states=read_rows(path/"agents_state.csv")
        for ax,aid in zip(axes[1],("llm_012","llm_013")):
            own=[r for r in states if r["agent_id"]==aid]
            start=next(r for r in initial if r["agent_id"]==aid)
            weight=100*int(start["shares"])*100.0/float(start["wealth"])
            ax.plot([0]+x,[weight]+[100*int(r["shares"])*float(price["price"])/float(r["wealth"]) for r,price in zip(own,p)],color=color,label=a["mode"])
    for entry in baseline:
        if entry["seed"]!=first or entry["cell"]=="long_quiet":continue
        p=read_rows(ROOT/entry["run_path"]/"prices.csv")
        axes[0,0].plot([0]+[int(r["round"]) for r in p],[100.0]+[float(r["price"]) for r in p],"--",color="gray" if entry["cell"]=="combined" else "black",alpha=.6,label="rules "+entry["cell"])
        if entry["cell"]=="combined":axes[0,0].step([0]+[int(r["round"]) for r in p],[100.0]+[float(r["fundamental"]) for r in p],where="post",color="#9361a7",linestyle=":",label="hidden regime reference")
    for ax,title,y in zip(axes.flat,("Auction price","Cumulative market volume","Meera's stock weight","Arjun's stock weight"),("Price","Traded shares","Percent","Percent")):
        ax.set_title(title);ax.set_ylabel(y);ax.set_xlabel("Round");ax.axvline(11,color="gray",linestyle=":");ax.grid(alpha=.15)
    if axes[0,0].get_legend_handles_labels()[0]:axes[0,0].legend(fontsize=8)
    horizons=", ".join(f"{a['mode']} {a['rounds']}/24" for a in arms if a["seed"]==first)
    fig.suptitle(f"Next independent seed5209: finalized arms {horizons}\nEvent at11; policies can diverge beforehand; one trajectory per mode in this scenario.",fontsize=11)
    fig.savefig(OUTPUT/"next_seed_paths.png",dpi=180);fig.savefig(OUTPUT/"next_seed_paths.pdf");plt.close(fig)
    shutil.copyfile(Path(__file__),OUTPUT/"analysis_source.py")
    shutil.copyfile(Path(__file__).parents[1]/"tests/test_sequential_markets.py",OUTPUT/"test_sequential_markets.py")
    shutil.copyfile(PHASE/"driver_source.py",OUTPUT/"driver_source.py")
    shutil.copyfile(Path(__file__).with_name("sequential_next_checks_20261103.py"),OUTPUT/"offline_checks_source.py")
    write_json(OUTPUT/"artifact_hashes.json",{p.name:sha256(p) for p in OUTPUT.iterdir() if p.is_file() and p.name!="artifact_hashes.json"})
    print(json.dumps(dict(clean_live_arms=len(completed),finalized_usage=usage,own_reflection_checks=len(reflection_cycles),reflection_attempt_prompt_checks=reflection_checks,identical_B_C_initial_prompts=len(equal_initial))))


if __name__=="__main__":analyze()
