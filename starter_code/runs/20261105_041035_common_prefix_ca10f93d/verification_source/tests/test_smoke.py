"""Smoke + conservation tests for the starter simulator."""
import numpy as np
from sim.market import CallAuctionMarket, Order, settle
from sim.agents.base import Agent


def test_clearing_textbook():
    m = CallAuctionMarket(tick=0.1, price_band=0.5)
    orders = [
        Order("b1", "buy", 10, 102.0), Order("b2", "buy", 5, 101.0),
        Order("b3", "buy", 5, None),               # market buy
        Order("s1", "sell", 8, 100.0), Order("s2", "sell", 7, 103.0),
    ]
    p, trades, unmatched = m.clear(orders, 100.0, 1)
    # At p in [100,101]: demand=20, supply=8 -> V=8. At 102: demand=15,supply=8.
    # At 103: demand=5(mkt only)... wait b1 limit 102<103 so demand=5, supply=15 -> V=5.
    # Max V=8, achieved for p in {100,101,102}; tie-break nearest prev close 100.
    assert p == 100.0
    assert sum(t.quantity for t in trades) == 8


def test_no_cross_no_trade():
    m = CallAuctionMarket()
    orders = [Order("b", "buy", 5, 90.0), Order("s", "sell", 5, 110.0)]
    p, trades, _ = m.clear(orders, 100.0, 1)
    assert p == 100.0 and trades == []


def test_conservation():
    rng = np.random.default_rng(0)
    m = CallAuctionMarket()
    agents = {f"a{i}": Agent(f"a{i}", 10000, 100, rng) for i in range(6)}
    total_shares = sum(a.shares for a in agents.values())
    total_cash = sum(a.cash for a in agents.values())
    for rnd in range(50):
        orders = []
        for aid, a in agents.items():
            side = "buy" if rng.random() < 0.5 else "sell"
            o = a.validate(Order(aid, side, int(rng.integers(1, 20)),
                                 float(100 * rng.uniform(0.9, 1.1)), rnd), 100.0)
            orders.append(o)
        p, trades, _ = m.clear(orders, 100.0, rnd)
        settle(trades, agents, m)
        for t in trades:  # fills never exceed holdings pre-round is enforced
            assert t.quantity > 0
    assert sum(a.shares for a in agents.values()) == total_shares
    assert abs(sum(a.cash for a in agents.values()) - total_cash) < 1e-6


def test_engine_end_to_end(tmp_path, monkeypatch):
    import os
    monkeypatch.chdir(tmp_path)
    import shutil, pathlib
    src = pathlib.Path(__file__).resolve().parents[1]
    shutil.copytree(src / "configs", tmp_path / "configs")
    from sim.engine import run
    run_dir = run("configs/dev_mock.yaml")
    assert os.path.exists(os.path.join(run_dir, "prices.csv"))
    assert os.path.exists(os.path.join(run_dir, "summary.json"))
