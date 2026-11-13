"""
Verification suite for repaired_engine.py.
Executes the exact 10 synthetic unit tests from Astra's AUDIT_REPORT.md / audit_saved.py.
"""
import math
import numpy as np
from repaired_engine import (
    RepairedMarginAgent,
    RepairedMarginFundamentalist,
    Order,
    Trade,
    Observation,
    atomic_settle
)

def agent(cash=1000, shares=10, allow=True):
    return RepairedMarginAgent('a', cash, shares, np.random.default_rng(1), allow_short=allow)

passed = 0
failed = 0

def test(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f" PASS: {name} {detail}")
    else:
        failed += 1
        print(f" FAIL: {name} {detail}")

print("--- Running Synthetic Unit Tests Against Repaired Engine ---")

# Test 1: partial_short_cover_cost_basis
a = agent(shares=0)
a._add_shares(-10, 100)  # Short 10 @ 100
a._add_shares(5, 120)    # Cover 5 @ 120
test("1. partial_short_cover_cost_basis", a.avg_cost == 100.0, f"(actual={a.avg_cost}, expected=100.0)")

# Test 2: partial_long_sale_cost_basis
a = agent(cash=1000, shares=10) # 10 @ 100
a._add_shares(-5, 120)  # Sell 5 @ 120
test("2. partial_long_sale_cost_basis", a.avg_cost == 100.0, f"(actual={a.avg_cost}, expected=100.0)")

# Test 3: existing_short_not_reserved
a = agent(shares=0)
a.cash, a.shares = 2000, -10
# Ceiling price = 100 * 1.2 = 120. Required margin = 10 * 120 * 1.5 = 1800.
# Available cash = 2000 - 1800 = 200.
# Margin per new short at ceiling = 120 * 1.5 = 180.
# max_new_shorts = int(200 // 180) = 1.
valid = a.validate_orders(Order('a', 'sell', 100), 100)
qty_accepted = valid[0].quantity if valid else 0
test("3. existing_short_not_reserved (prevents excessive shorts)", qty_accepted == 1, f"(accepted={qty_accepted}, expected=1)")

# Test 4: buy_can_spend_short_collateral
a = agent(shares=0)
a.cash, a.shares = 1800, -10 # All cash is locked in collateral (10 * 120 * 1.5 = 1800)
valid_buy = a.validate_orders(Order('a', 'buy', 10, 100), 100)
buy_qty = valid_buy[0].quantity if valid_buy else 0
test("4. buy_can_spend_short_collateral (locked collateral cannot be spent)", buy_qty == 0, f"(accepted={buy_qty}, expected=0)")

# Test 5: duplicate_sells_reuse_shares
a = agent(cash=1000, shares=10, allow=False)
valid_dup = a.validate_orders([Order('a', 'sell', 10, 100), Order('a', 'sell', 10, 100)], 100)
dup_quantities = [o.quantity for o in valid_dup]
test("5. duplicate_sells_reuse_shares (no double-spending owned shares)", dup_quantities == [10], f"(accepted={dup_quantities}, expected=[10])")

# Test 6: wrong_agent_id_accepted
a = agent()
valid_wrong_id = a.validate_orders(Order('someone_else', 'buy', 1, 100), 100)
test("6. wrong_agent_id_accepted (rejects orders for other agents)", len(valid_wrong_id) == 0, f"(accepted_count={len(valid_wrong_id)}, expected=0)")

# Test 7: negative_quantity_accepted
a = agent()
valid_neg = a.validate_orders(Order('a', 'buy', -5, 100), 100)
test("7. negative_quantity_accepted (rejects negative quantities)", len(valid_neg) == 0, f"(accepted_count={len(valid_neg)}, expected=0)")

# Test 8: fundamentalist_cannot_initiate_short
f = RepairedMarginFundamentalist('f', 30000, 0, np.random.default_rng(1), allow_short=True)
obs = Observation(2, 10, [120.0], 0, .02, .0002, 100, [], [], 30000, 0, 0, 30000, [])
o = f.decide(obs)
test("8. fundamentalist_initiates_short (can short when overpriced)", o.side == 'sell' and o.quantity > 0, f"(side={o.side}, qty={o.quantity}, expected sell with qty>0)")

# Test 9: unfunded_settlement_passes_conservation
a, b = agent(cash=1, shares=0), RepairedMarginAgent('b', 0, 1, np.random.default_rng(1), allow_short=False)
atomic_settle([Trade(1, 'a', 'b', 1, 100)], {'a': a, 'b': b})
test("9. unfunded_settlement_rejected (buyer cash cannot become negative)", a.cash == 1 and b.shares == 1, f"(buyer_cash={a.cash}, expected=1, seller_shares={b.shares}, expected=1)")

# Test 10: banned_short_settlement_passes
a, b = agent(cash=1000, shares=0, allow=False), RepairedMarginAgent('b', 0, 0, np.random.default_rng(1), allow_short=False)
atomic_settle([Trade(1, 'a', 'b', 1, 100)], {'a': a, 'b': b})
test("10. banned_short_settlement_rejected (seller shares cannot become negative when banned)", b.shares == 0 and a.cash == 1000, f"(seller_shares={b.shares}, expected=0, buyer_cash={a.cash}, expected=1000)")

print(f"\nSummary: {passed}/10 tests PASSED, {failed}/10 FAILED")
