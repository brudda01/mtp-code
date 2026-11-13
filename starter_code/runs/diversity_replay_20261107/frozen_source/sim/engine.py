"""Auditable batch-auction pilots with comparable A/B/C agents and bounded calls."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from dataclasses import asdict
import csv
import json
import math
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import yaml

from sim.config import ConfigError, RunConfig, load_config, parse_config
from sim.market import CallAuctionMarket, settle
from sim.assets import Asset
from sim.agents.base import Observation
from sim.agents.rule_agents import RULE_AGENTS, MarketMakerAgent
from sim.agents.llm_agent import LLMAgent, PROMPT_VERSION
from sim.agents.personas import get_personas
from sim.llm.mock import MockLLMClient
from sim.llm.client import LLMClient
from sim.llm.usage import ProviderUnavailable, UsageBudget, UsageLimitExceeded
from sim.provenance import finish_manifest, start_manifest, write_json


def make_rngs(seed):
    """Versioned streams: setup/allocation cannot consume environmental draws."""
    names = ("environment", "population", "personas", "allocation")
    return {name: np.random.default_rng(child)
            for name, child in zip(names, np.random.SeedSequence(seed).spawn(len(names)))}


def build_agents(cfg, rng, run_dir=None, *, persona_rng=None, log_fn=None, budget=None):
    cfg = cfg if isinstance(cfg, RunConfig) else parse_config(cfg)
    budget = budget if budget is not None else UsageBudget(**asdict(cfg.llm_limits))
    agents = {}
    idx = 0
    for group in cfg.agents:
        for _ in range(group.count):
            aid = f"{group.type[:4]}_{idx:03d}"
            idx += 1
            common = dict(initial_price=cfg.asset.initial_price, initial_cost=group.initial_cost,
                          transaction_tax=cfg.market.transaction_tax, price_band=cfg.market.price_band)
            cash = group.cash_dist.sample(rng) if group.cash_dist is not None else group.cash
            arng = np.random.default_rng(rng.integers(0, 2**31))
            if group.type == "llm":
                llm = group.llm
                client = (MockLLMClient() if llm.provider == "mock" else
                          LLMClient(model=llm.model, base_url=llm.base_url, timeout=llm.timeout_seconds,
                                    reasoning_effort=llm.reasoning_effort, send_temperature=llm.send_temperature))
                agents[aid] = LLMAgent(
                    aid, cash, group.shares, arng,
                    params={"ticker": cfg.asset.ticker, "round_unit": cfg.time.round_unit, "tick": cfg.market.tick,
                            "condition": llm.condition, "memory_window": llm.memory_window,
                            "reflect_every": llm.reflect_every, "max_tokens": llm.max_tokens,
                            "transport_retries": llm.transport_retries, "retry_http_503": llm.retry_http_503},
                    client=client, temperature=llm.temperature, log_fn=log_fn,
                    budget=budget, input_price=llm.input_usd_per_million or 0.0,
                    output_price=llm.output_usd_per_million or 0.0, **common)
            else:
                agents[aid] = RULE_AGENTS[group.type](
                    aid, cash, group.shares, arng, params=group.params, **common)
    llm_agents = [a for a in agents.values() if isinstance(a, LLMAgent)]
    for agent, persona in zip(llm_agents, get_personas(
            len(llm_agents), persona_rng if persona_rng is not None else rng)):
        agent.persona = persona
    return agents


def _compound_factor(rate, periods):
    if periods is None:
        return None
    try:
        result = math.exp(periods * math.log1p(rate))
    except OverflowError:
        return None
    return result if math.isfinite(result) else None


def run(cfg_path, *, output_root="runs", request_pacer=None):
    cfg = load_config(cfg_path)
    rounds, seed = cfg.rounds, cfg.seed
    rngs = make_rngs(seed)
    run_dir = os.path.join(output_root, time.strftime("%Y%m%d_%H%M%S_")
                           + cfg.name + "_" + uuid.uuid4().hex[:8])
    os.makedirs(run_dir, exist_ok=False)
    with open(os.path.join(run_dir, "config.yaml"), "w", encoding="utf-8") as target:
        yaml.safe_dump(cfg.to_dict(), target)
    manifest = start_manifest(run_dir, cfg)
    budget = UsageBudget(**asdict(cfg.llm_limits))
    if request_pacer is not None:
        if (request_pacer.requests_per_minute != cfg.llm_limits.requests_per_minute or
                request_pacer.input_tokens_per_minute != cfg.llm_limits.input_tokens_per_minute):
            raise ValueError("shared pacer must match the saved rate-limit configuration")
        budget.pacer = request_pacer
    agents = {}
    price = cfg.asset.initial_price
    cash_after = initial_cash = None
    total_shares = 0
    completed = reduced_orders = 0
    started = time.time()
    status, failure_type, stop_reason = "running", None, None
    fill_rates, spreads, maker_fractions = [], [], []
    no_trade_rounds = band_hits = 0
    total_dividends = total_interest = max_cash_error = 0.0
    event_count = announcements_available = 0
    asset = None
    try:
        market = CallAuctionMarket(tick=cfg.market.tick, price_band=cfg.market.price_band,
                                   transaction_tax=cfg.market.transaction_tax, rng=rngs["allocation"])
        asset = Asset(cfg.asset, rngs["environment"], news_events=cfg.news)
        hist = [price]
        last_volume, last_div = 0, asset.last_dividend
        with ExitStack() as stack:
            files = {}

            def writer(filename, columns):
                handle = stack.enter_context(open(
                    os.path.join(run_dir, filename), "w", newline="", encoding="utf-8"))
                files[filename] = handle
                result = csv.writer(handle)
                result.writerow(columns)
                return result

            llm_log = stack.enter_context(open(
                os.path.join(run_dir, "llm_calls.jsonl"), "w", encoding="utf-8"))
            outcome_log = stack.enter_context(open(
                os.path.join(run_dir, "agent_outcomes.jsonl"), "w", encoding="utf-8"))
            request_log = stack.enter_context(open(
                os.path.join(run_dir, "llm_requests.jsonl"), "w", encoding="utf-8"))
            event_audit = stack.enter_context(open(
                os.path.join(run_dir, "event_audit.jsonl"), "w", encoding="utf-8"))
            log_lock = threading.Lock()

            def log_fn(record):
                kind = record.get("record_type")
                target = (outcome_log if kind == "outcome" else request_log
                          if kind in ("model_call", "request_blocked") else llm_log)
                with log_lock:
                    target.write(json.dumps(record, allow_nan=False) + "\n")
                    target.flush()

            agents = build_agents(cfg, rngs["population"], persona_rng=rngs["personas"],
                                  log_fn=log_fn, budget=budget)
            write_json(os.path.join(run_dir, "personas.json"), {
                a.agent_id: a.persona for a in agents.values() if isinstance(a, LLMAgent)})
            manifest["endpoints"] = sorted({
                a.client.base_url for a in agents.values()
                if isinstance(a, LLMAgent) and isinstance(a.client, LLMClient)})
            write_json(os.path.join(run_dir, "manifest.json"), manifest)
            initial_cash = cash_after = math.fsum(a.cash for a in agents.values())
            total_shares = sum(a.shares for a in agents.values())
            initial = writer("initial_state.csv", ["agent_id", "type", "cash", "shares", "avg_cost", "wealth"])
            for agent in agents.values():
                initial.writerow([agent.agent_id, type(agent).__name__, agent.cash,
                                  agent.shares, agent.avg_cost, agent.wealth(price)])
            pw = writer("prices.csv", ["round", "price", "volume", "dividend", "fundamental", "unmatched_volume"])
            ow = writer("orders.csv", ["round", "agent_id", "side", "quantity", "limit_price",
                                       "reasoning", "validation_note", "llm_requested_side",
                                       "llm_requested_quantity", "llm_requested_limit_price"])
            tw = writer("trades.csv", ["round", "buyer_id", "seller_id", "quantity", "price"])
            sw = writer("agents_state.csv", ["round", "agent_id", "type", "cash", "shares",
                                             "wealth", "avg_cost", "dividend_income", "interest_income"])
            ew = writer("events.csv", ["round", "event_type", "headline", "regime_benchmark"])
            cw = writer("cashflows.csv", ["round", "cash_before", "cash_after_settlement",
                                          "dividends_paid", "interest_paid", "tax_paid",
                                          "cash_after", "total_shares", "conservation_error"])
            lw = writer("liquidity.csv", ["round", "best_bid", "best_ask", "quoted_spread",
                                          "submitted_quantity", "volume", "fill_rate",
                                          "market_maker_volume_fraction", "at_price_band"])
            maker_ids = {a.agent_id for a in agents.values() if isinstance(a, MarketMakerAgent)}
            with ThreadPoolExecutor(max_workers=cfg.execution.max_workers) as executor:
                for rnd in range(1, rounds + 1):
                    headlines = asset.open_round(rnd)
                    event_count += len(asset.round_events)
                    announcements_available += len(headlines)
                    for event in asset.round_events:
                        event_audit.write(json.dumps(event, allow_nan=False) + "\n")
                    event_audit.flush()
                    for headline in headlines:
                        ew.writerow([rnd, "news", headline, asset.fundamental(rnd)])

                    def obs_for(agent):
                        return Observation(
                            round=rnd, total_rounds=rounds,
                            price_history=hist[-cfg.observation.price_history_len:],
                            last_volume=last_volume, last_dividend=last_div, risk_free_rate=asset.risk_free,
                            fundamental_hint=asset.fundamental(rnd) if cfg.reveal_fundamental else None,
                            news=headlines, bbs_posts=[], round_unit=cfg.time.round_unit,
                            my_cash=agent.cash, my_shares=agent.shares, my_avg_cost=agent.avg_cost,
                            my_wealth=agent.wealth(hist[-1]), my_recent_trades=list(agent.recent_trades))

                    opening_wealth = {a.agent_id: a.wealth(hist[-1]) for a in agents.values()}
                    decisions = list(executor.map(lambda a: a.decide(obs_for(a)), agents.values()))
                    orders = []
                    for agent, decision in zip(agents.values(), decisions):
                        checked = agent.validate_orders(decision, hist[-1])
                        reduced_orders += sum(bool(o.validation_note) for o in checked)
                        orders.extend(checked)
                    orders.sort(key=lambda o: (o.agent_id, o.side))
                    for order in orders:
                        holder = agents[order.agent_id]
                        intent = (holder.last_intent or {}) if isinstance(holder, LLMAgent) else {}
                        ow.writerow([rnd, order.agent_id, order.side, order.quantity, order.limit_price,
                                     order.reasoning, order.validation_note, intent.get("side"),
                                     intent.get("quantity"), intent.get("limit_price")])

                    quote_stats = market.quote_statistics(orders)
                    cash_before = math.fsum(a.cash for a in agents.values())
                    tax_before = market.tax_collected
                    previous_price = hist[-1]
                    price, trades, unmatched = market.clear(orders, previous_price, rnd)
                    settle(trades, agents, market)
                    cash_after_settlement = math.fsum(a.cash for a in agents.values())
                    tax_paid = market.tax_collected - tax_before
                    for trade in trades:
                        tw.writerow([trade.round, trade.buyer_id, trade.seller_id, trade.quantity, trade.price])

                    dividend = asset.draw_dividend()
                    incomes = {}
                    for agent in agents.values():
                        incomes[agent.agent_id] = agent.pay_dividend(dividend, asset.risk_free)
                        div_income, int_income = incomes[agent.agent_id]
                        sw.writerow([rnd, agent.agent_id, type(agent).__name__, agent.cash, agent.shares,
                                     agent.wealth(price), agent.avg_cost, div_income, int_income])
                    dividends_paid = math.fsum(v[0] for v in incomes.values())
                    interest_paid = math.fsum(v[1] for v in incomes.values())
                    total_dividends += dividends_paid
                    total_interest += interest_paid
                    cash_after = math.fsum(a.cash for a in agents.values())
                    expected_cash = cash_before - tax_paid + dividends_paid + interest_paid
                    cash_error = cash_after - expected_cash
                    if (sum(a.shares for a in agents.values()) != total_shares or
                            not math.isclose(cash_after, expected_cash, rel_tol=1e-12, abs_tol=1e-7)):
                        raise RuntimeError("round cash-flow/share conservation invariant failed")
                    max_cash_error = max(max_cash_error, abs(cash_error))
                    cw.writerow([rnd, cash_before, cash_after_settlement, dividends_paid, interest_paid,
                                 tax_paid, cash_after, total_shares, cash_error])

                    last_volume = sum(t.quantity for t in trades)
                    submitted = quote_stats["submitted_quantity"]
                    fill_rate = 2 * last_volume / submitted if submitted else 0.0
                    maker_volume = sum(t.quantity for t in trades if t.buyer_id in maker_ids or t.seller_id in maker_ids)
                    maker_fraction = maker_volume / last_volume if last_volume else None
                    lo, hi = market.price_bounds(previous_price)
                    band_hit = bool(trades) and (math.isclose(price, lo, abs_tol=1e-9) or
                                                math.isclose(price, hi, abs_tol=1e-9))
                    lw.writerow([rnd, quote_stats["best_bid"], quote_stats["best_ask"],
                                 quote_stats["quoted_spread"], submitted, last_volume,
                                 fill_rate, maker_fraction, band_hit])
                    fill_rates.append(fill_rate)
                    if quote_stats["quoted_spread"] is not None:
                        spreads.append(quote_stats["quoted_spread"])
                    if maker_fraction is not None:
                        maker_fractions.append(maker_fraction)
                    no_trade_rounds += last_volume == 0
                    band_hits += band_hit
                    last_div = dividend
                    hist.append(price)
                    pw.writerow([rnd, price, last_volume, dividend, asset.fundamental(rnd), unmatched])
                    for handle in files.values():
                        handle.flush()
                    completed = rnd  # The financial round is complete before any reflection request.
                    for agent in agents.values():
                        if isinstance(agent, LLMAgent):
                            my_order = next(o for o in orders if o.agent_id == agent.agent_id)
                            div_income, int_income = incomes[agent.agent_id]
                            agent.end_round(obs_for(agent), my_order, price, fills=trades,
                                            dividend_income=div_income, interest_income=int_income,
                                            opening_wealth=opening_wealth[agent.agent_id], reflect=False)
                    for agent in agents.values():
                        if isinstance(agent, LLMAgent):
                            agent.reflect_if_due(obs_for(agent))
                    if rnd % 10 == 0:
                        print(f"round {rnd}/{rounds} price={price:.2f} vol={last_volume}")
        status = "completed"
    except UsageLimitExceeded as exc:
        status, failure_type, stop_reason = "budget_exhausted", type(exc).__name__, str(exc)
    except ProviderUnavailable as exc:
        status, failure_type, stop_reason = "provider_error", type(exc).__name__, str(exc)
    except KeyboardInterrupt:
        status, failure_type = "interrupted", "KeyboardInterrupt"
        raise
    except Exception as exc:
        status, failure_type = "failed", type(exc).__name__
        raise
    finally:
        llm_agents = [a for a in agents.values() if isinstance(a, LLMAgent)]
        summary = {
            "status": status, "rounds": completed, "requested_rounds": rounds, "seed": seed,
            "failure_type": failure_type, "stop_reason": stop_reason,
            "seconds": round(time.time() - started, 1), "final_price": price,
            "total_llm_tokens": sum(a.client.total_tokens for a in llm_agents),
            "parse_failures": sum(a.parse_failures for a in llm_agents),
            "api_failures": sum(a.api_failures for a in llm_agents),
            "reflection_failures": sum(a.reflection_failures for a in llm_agents),
            "output_truncations": sum(a.output_truncations for a in llm_agents),
            "transport_retries": sum(a.transport_retries for a in llm_agents),
            "json_repairs": sum(a.json_repairs for a in llm_agents),
            "server_retries": sum(a.server_retries for a in llm_agents),
            "llm_usage": budget.snapshot(), "orders_adjusted": reduced_orders,
            "tax_collected": market.tax_collected if asset is not None else None,
            "random_stream_scheme": "seedsequence_v1:environment,population,personas,allocation",
            "economic_model": cfg.asset.model, "benchmark_kind": asset.benchmark_kind if asset else None,
            "event_records": event_count, "announcements_available": announcements_available,
            "reveal_fundamental": cfg.reveal_fundamental,
            "decision_prompt_version": PROMPT_VERSION,
            "conditions": sorted({a.condition for a in llm_agents}),
            "round_unit": cfg.time.round_unit, "periods_per_year": cfg.time.periods_per_year,
            "interest_per_round": cfg.asset.risk_free,
            "cash_only_interest_factor": _compound_factor(cfg.asset.risk_free, completed),
            "initial_cash": initial_cash, "final_cash": cash_after, "total_shares": total_shares,
            "total_dividends_paid": total_dividends, "total_interest_paid": total_interest,
            "max_cash_conservation_error": max_cash_error,
            "zero_volume_fraction": no_trade_rounds / completed if completed else None,
            "mean_fill_rate": math.fsum(fill_rates) / completed if completed else None,
            "mean_submitted_quote_spread": math.fsum(spreads) / len(spreads) if spreads else None,
            "mean_market_maker_volume_fraction": math.fsum(maker_fractions) / len(maker_fractions) if maker_fractions else None,
            "price_band_hits": band_hits, "implementation_stage": "3_comparable_agents_pilot"}
        write_json(os.path.join(run_dir, "summary.json"), summary)
        finish_manifest(run_dir, manifest, summary)
    print(f"{status} -> {run_dir}")
    return run_dir


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--output-root", default="runs")
    args = parser.parse_args()
    try:
        run(args.config, output_root=args.output_root)
    except ConfigError as exc:
        parser.error(str(exc))
