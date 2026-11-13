# Isolated snapshot of completed concurrent market; only an audit callback is added.
# No original campaign launcher is called. Historical prompt/outcome shape retained.
from run_fast_campaign import *

def run_concurrent_market(cfg, market_dir, client_factory, audit_callback=None):
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
                if audit_callback is not None: audit_callback(record)
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
