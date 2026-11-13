"""
High-Speed Concurrent Live Campaign (110 RPM, 4 Concurrent Workers).
Optimized for Goedel Machines Student Pass (120 RPM, 4 Concurrent, 200k TPM).
Replays 410 historical decisions from prior root (fast-forwarding Rounds 1-34 in 0.2s).
Dispatches the 12 LLMs per round in parallel batches of 4, completing each round in ~6-7 seconds.
Total runtime for 100 rounds: ~11 minutes!
"""
import sys
sys.dont_write_bytecode = True
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import os
import time
import shutil
import concurrent.futures
import threading
from dataclasses import asdict

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "starter_code"))

from sandbox import Config, source_hashes, POSTS, build_accounts, rule_decision
from fast_delivery import ThreadSafeFastDelivery
from delivery import campaign_budget
from sim.llm.client import dotenv_api_key
from sim.llm.usage import UsageBudget, RequestPacer
from repaired_engine import Observation, atomic_settle, Order
from repaired_llm_trader import RepairedLLMTrader
from repaired_market_sim import CallAuction, DecoupledAsset

PRIOR_ROOT = ROOT / 'runs' / 'wealth_live_12llm_100round_finish'
CAMPAIGN = ROOT / 'runs' / 'wealth_live_12llm_100round_fast110'

def write_json(path, data):
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(data, indent=2, allow_nan=False), encoding='utf-8')
    temp.replace(path)

def run_concurrent_market(cfg, market_dir, client_factory):
    market_dir.mkdir(parents=True, exist_ok=False)
    manifest = dict(
        status='running',
        evidence_type='LIVE_SANDBOX_CONCURRENT_110RPM',
        config=asdict(cfg),
        source_sha256=source_hashes(),
        provider_requests=0
    )
    def save_manifest():
        (market_dir / 'manifest.json').write_text(json.dumps(manifest, indent=2, allow_nan=False), encoding='utf-8')
    save_manifest()

    price_history = [100.0]
    volume_history = []
    rows = []

    log_lock = threading.Lock()
    with (market_dir / 'ledger.jsonl').open('x', encoding='utf-8') as ledger:
        def log(record):
            with log_lock:
                ledger.write(json.dumps(record, allow_nan=False, ensure_ascii=False) + '\n')
                ledger.flush()

        client = client_factory(log)
        accounts = build_accounts(cfg, client)
        initial = {aid: dict(cash=a.cash, shares=a.shares, avg_cost=a.avg_cost, wealth=a.wealth(100), allow_short=a.allow_short)
                   for aid, a in accounts.items()}
        log(dict(kind='initial', accounts=initial))
        total_shares = sum(a.shares for a in accounts.values())

        passive = {aid: [a.cash, a.shares] for aid, a in accounts.items()}
        outcomes = {aid: [] for aid in accounts}
        asset = DecoupledAsset(cfg.seed + 904)
        auction = CallAuction(cfg.seed + 905)

        llm_agents = [a for a in accounts.values() if isinstance(a, RepairedLLMTrader)]
        rule_agents = [a for a in accounts.values() if not isinstance(a, RepairedLLMTrader)]

        for rnd in range(1, cfg.rounds + 1):
            p = price_history[-1]
            opening = {aid: dict(cash=a.cash, shares=a.shares) for aid, a in accounts.items()}
            orders = []
            accepted_by = {}
            requested_by = {}

            # 1. Evaluate Rule Traders first
            for a in rule_agents:
                obs = Observation(rnd, cfg.rounds, list(price_history), list(volume_history),
                                  asset.dividend_history[-1] if asset.dividend_history else 0.02,
                                  0.0002, None, POSTS.get(rnd, []) if cfg.forum else [], [],
                                  a.cash, a.shares, a.get_required_collateral(p), a.wealth(p), [], outcomes[a.agent_id][-5:])
                dec = rule_decision(a, obs)
                req = [asdict(o) for o in (dec if isinstance(dec, list) else [dec])]
                acc = a.validate_orders(dec, p)
                log(dict(kind='decision', round=rnd, agent=a.agent_id, requested=req, accepted=[asdict(o) for o in acc]))
                orders.extend(acc)
                requested_by[a.agent_id] = req
                accepted_by[a.agent_id] = [asdict(o) for o in acc]

            # 2. Evaluate 12 LLMs concurrently using 4 workers
            def eval_one_llm(a):
                obs = Observation(rnd, cfg.rounds, list(price_history), list(volume_history),
                                  asset.dividend_history[-1] if asset.dividend_history else 0.02,
                                  0.0002, None, POSTS.get(rnd, []) if cfg.forum else [], [],
                                  a.cash, a.shares, a.get_required_collateral(p), a.wealth(p), [], outcomes[a.agent_id][-5:])
                acc_order = a.decide(obs)
                return a.agent_id, acc_order, a.last_requested_order, a.last_raw_response

            llm_results = {}
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
                futures = {ex.submit(eval_one_llm, a): a.agent_id for a in llm_agents}
                for fut in concurrent.futures.as_completed(futures):
                    aid, acc_order, req_order, raw_resp = fut.result()
                    llm_results[aid] = (acc_order, req_order, raw_resp)

            # Process LLM results in stable order
            for a in llm_agents:
                aid = a.agent_id
                acc_order, req_order, raw_resp = llm_results[aid]
                log(dict(kind='decision', round=rnd, agent=aid, raw=raw_resp, requested=req_order, accepted=[asdict(acc_order)]))
                if acc_order.status in ('missing', 'error'):
                    raise RuntimeError(f"missing/invalid decision for {aid}; stop without auction")
                orders.append(acc_order)
                requested_by[aid] = req_order
                accepted_by[aid] = [asdict(acc_order)]

            # 3. Match in Call Auction
            clearing, volume, trades = auction.match(rnd, orders, p)
            log(dict(kind='auction', round=rnd, price=clearing, volume=volume, trades=[asdict(t) for t in trades]))
            atomic_settle(trades, accounts, auction)

            # 4. Dividends & Interest
            div = asset.draw_dividend()
            closing = {}
            for aid, a in accounts.items():
                di, interest = a.pay_income(div, 0.0002)
                passive[aid][0] = passive[aid][0] * (1 + 0.0002) + passive[aid][1] * div
                bought = sum(t.quantity for t in trades if t.buyer_id == aid)
                sold = sum(t.quantity for t in trades if t.seller_id == aid)
                closing[aid] = dict(cash=a.cash, shares=a.shares, avg_cost=a.avg_cost, wealth=a.wealth(clearing),
                                    dividend_income=di, interest_income=interest,
                                    collateral=a.get_required_collateral(clearing))
                outcomes[aid].append(dict(round=rnd, requested=requested_by[aid], accepted=accepted_by[aid],
                                         executed_buys=bought, executed_sells=sold, opening=opening[aid], closing=closing[aid]))

            row = dict(kind='round', round=rnd, opening=opening, closing=closing, price=clearing, volume=volume, dividend=div)
            log(row)
            rows.append(row)
            price_history.append(clearing)
            volume_history.append(volume)

            for a in accounts.values():
                a.check_maintenance(clearing)

            if rnd % 5 == 0 or rnd == cfg.rounds:
                print(f" [{cfg.wealth.upper()}]: Round {rnd:03d}/{cfg.rounds:03d} Cleared | Price: ${clearing:.2f} | Volume: {volume:2d} sh")

        manifest.update(status='complete', completed_rounds=len(rows))
        save_manifest()

def run():
    if CAMPAIGN.exists():
        shutil.rmtree(CAMPAIGN)
    CAMPAIGN.mkdir(parents=True, exist_ok=False)

    # 1. Load historical tape of 410 decisions from prior root
    prior_ledger = PRIOR_ROOT / 's42_equal' / 'ledger.jsonl'
    tape = []
    if prior_ledger.exists():
        for line in open(prior_ledger, 'r', encoding='utf-8'):
            d = json.loads(line)
            if d.get('kind') == 'delivery_attempt' and d.get('status') == 'returned':
                tape.append(d.get('response'))
    print(f"Loaded {len(tape)} historical responses from prior root for fast-forward replay.")

    configs = [
        {"seed": 42, "rounds": 100, "llm_count": 12, "wealth": "equal", "sigma": 0.7, "assignment": 0, "allow_short": False, "forum": False},
        {"seed": 42, "rounds": 100, "llm_count": 12, "wealth": "heterogeneous", "sigma": 0.7, "assignment": 0, "allow_short": False, "forum": False},
        {"seed": 43, "rounds": 100, "llm_count": 12, "wealth": "equal", "sigma": 0.7, "assignment": 0, "allow_short": False, "forum": False},
        {"seed": 43, "rounds": 100, "llm_count": 12, "wealth": "heterogeneous", "sigma": 0.7, "assignment": 0, "allow_short": False, "forum": False}
    ]

    protocol = {
        "status": "fast_running",
        "authorization": "User authorized 110 RPM with 4 concurrent workers (Student Pass)",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "configs": configs,
        "planned_decisions": 4800,
        "max_http_attempts": 6000,
        "max_reserved_tokens": 96000000,
        "requests_per_minute": 110,
        "max_workers": 4
    }
    write_json(CAMPAIGN / 'protocol.json', protocol)
    write_json(CAMPAIGN / 'execution.json', {"pid": os.getpid(), "started_utc": datetime.now(timezone.utc).isoformat()})

    # UsageBudget calibrated to 110 RPM and 200k input TPM per Student Pass
    budget = UsageBudget(max_requests=6000, max_reserved_tokens=96000000, requests_per_minute=110, input_tokens_per_minute=200000)
    summary = dict(status='running', pid=os.getpid(), completed_markets=0, planned_markets=4, markets=[], replayed_decisions=len(tape))

    def save():
        summary['usage'] = budget.snapshot()
        summary['updated_utc'] = datetime.now(timezone.utc).isoformat()
        write_json(CAMPAIGN / 'summary.json', summary)
    save()

    key = dotenv_api_key('GODEL_MACHINES_API_KEY')
    if not key:
        raise RuntimeError('Named Goedel credential unavailable')

    try:
        for idx, raw_cfg in enumerate(configs):
            cfg = Config(**raw_cfg)
            market_dir = CAMPAIGN / f's{cfg.seed}_{cfg.wealth}'
            summary.update(current_market=market_dir.name, current_market_path=str(market_dir))
            save()

            # Tape only applies to s42_equal (market index 0)
            market_tape = tape if idx == 0 else []

            def factory(log):
                def durable(record):
                    log(record)
                    if record.get('kind') == 'delivery_attempt':
                        summary['last_attempt_status'] = record.get('status')
                        summary['last_attempt_model'] = (record.get('response') or {}).get('model')
                        summary['delivered_responses'] = summary.get('delivered_responses', 0) + (record.get('status') == 'returned')
                        save()
                return ThreadSafeFastDelivery(key, durable, budget, tape=market_tape)

            print(f"\n=======================================================")
            print(f" LAUNCHING HIGH-SPEED CONCURRENT MARKET: {market_dir.name} (110 RPM, 4 workers)")
            print(f"=======================================================")
            run_concurrent_market(cfg, market_dir, client_factory=factory)

            m = json.loads((market_dir / 'manifest.json').read_text())
            summary['markets'].append(dict(path=market_dir.name, completed_rounds=m['completed_rounds']))
            summary['completed_markets'] += 1
            save()

        summary['status'] = 'complete'
    except BaseException as exc:
        summary.update(status='stopped', error_type=type(exc).__name__, error=str(exc))
        print(f"Campaign stopped with error: {exc}")
        raise
    finally:
        save()

if __name__ == '__main__':
    run()
