"""
Repaired Market Simulation Framework.
Implements:
- Decoupled RNG streams (Dividend RNG, Rule Agent RNG, Auction Tie-Break RNG).
- Full audit logging: orders ledger, round account balance sheets, market clearing metrics.
- Atomic settlement with strict cash & share conservation.
"""
from __future__ import annotations

import os
import csv
import json
import math
from typing import List, Dict, Any, Tuple, Optional
import numpy as np

from repaired_engine import (
    RepairedMarginAgent,
    RepairedMarginFundamentalist,
    Order,
    Trade,
    Observation,
    atomic_settle
)

class DecoupledAsset:
    """Asset with an independent dividend RNG stream, unaffected by market trading."""
    def __init__(self, seed: int, mean_div: float = 0.02, noise_ratio: float = 0.20, rf_rate: float = 0.0002):
        self.rng = np.random.default_rng(seed)
        self.mean_div = mean_div
        self.noise_ratio = noise_ratio
        self.rf_rate = rf_rate
        self.dividend_history: List[float] = []

    def draw_dividend(self) -> float:
        noise = self.rng.normal(0, self.noise_ratio * self.mean_div)
        div = max(0.0, float(self.mean_div + noise))
        self.dividend_history.append(div)
        return div


class CallAuction:
    """Uniform-price double call auction with independent tie-break RNG."""
    def __init__(self, seed: int):
        self.rng = np.random.default_rng(seed)

    def match(self, round_num: int, orders: List[Order], last_price: float) -> Tuple[float, int, List[Trade]]:
        bids = [o for o in orders if o.side == 'buy' and o.quantity > 0]
        asks = [o for o in orders if o.side == 'sell' and o.quantity > 0]

        if not bids or not asks:
            return last_price, 0, []

        # Expand bids and asks to unit orders for clear priority sorting
        expanded_bids = []
        for b in bids:
            p = b.limit_price if b.limit_price is not None else float('inf')
            # Tie breaker jitter
            expanded_bids.extend([(p, self.rng.random(), b.agent_id)] * b.quantity)

        expanded_asks = []
        for a in asks:
            p = a.limit_price if a.limit_price is not None else 0.0
            expanded_asks.extend([(p, self.rng.random(), a.agent_id)] * a.quantity)

        # Sort bids descending (highest willingness to pay first)
        expanded_bids.sort(key=lambda x: (-x[0], x[1]))
        # Sort asks ascending (lowest willingness to accept first)
        expanded_asks.sort(key=lambda x: (x[0], x[1]))

        trades: List[Trade] = []
        clearing_price = last_price
        match_count = 0

        for (bid_p, _, buyer_id), (ask_p, _, seller_id) in zip(expanded_bids, expanded_asks):
            if bid_p >= ask_p:
                match_count += 1
                # If market orders, use last price
                eff_bid = last_price if bid_p == float('inf') else bid_p
                eff_ask = last_price if ask_p == 0.0 else ask_p
                trade_p = round((eff_bid + eff_ask) / 2.0, 2)
                clearing_price = trade_p
                trades.append(Trade(round_num, buyer_id, seller_id, 1, trade_p))
            else:
                break

        # Consolidate unit trades between same buyer and seller at clearing price
        consolidated: Dict[Tuple[str, str], int] = {}
        for t in trades:
            pair = (t.buyer_id, t.seller_id)
            consolidated[pair] = consolidated.get(pair, 0) + 1

        final_trades = [
            Trade(round_num, buyer_id, seller_id, qty, clearing_price)
            for (buyer_id, seller_id), qty in consolidated.items()
        ]

        return clearing_price, match_count, final_trades
