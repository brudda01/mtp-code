"""
Unit tests for RepairedLLMTrader parser edge cases from AUDIT_REPORT.md.
"""
import json
import numpy as np
from repaired_llm_trader import RepairedLLMTrader

persona = {"name": "Test", "age": 30, "occupation": "engineer"}
trader = RepairedLLMTrader("a", 1000, 10, np.random.default_rng(1), persona, None)

print("--- Testing Repaired Parser Edge Cases ---")

# 1. Fractional quantity 2.9
res = trader.parse_decision(json.dumps({"action": "buy", "quantity": 2.9, "limit_price": 100}))
assert res.status == "error", f"Expected error for fractional quantity, got {res.status}"
print(" PASS: fractional quantity 2.9 rejected (status='error')")

# 2. Boolean quantity True
res = trader.parse_decision(json.dumps({"action": "buy", "quantity": True, "limit_price": 100}))
assert res.status == "error", f"Expected error for boolean quantity, got {res.status}"
print(" PASS: boolean quantity True rejected (status='error')")

# 3. Invalid limit price -1
res = trader.parse_decision(json.dumps({"action": "buy", "quantity": 2, "limit_price": -1}))
assert res.status == "error", f"Expected error for negative limit price, got {res.status}"
print(" PASS: negative limit price -1 rejected (status='error')")

# 4. Empty object {}
res = trader.parse_decision(json.dumps({}))
assert res.status == "missing", f"Expected missing for empty object, got {res.status}"
print(" PASS: empty JSON object {} rejected (status='missing')")

# 5. Missing / empty string
res = trader.parse_decision("")
assert res.status == "missing", f"Expected missing for empty string, got {res.status}"
print(" PASS: empty string rejected (status='missing')")

# 6. Valid buy
res = trader.parse_decision(json.dumps({"action": "buy", "quantity": 5, "limit_price": 105.5, "reasoning": "growth"}))
assert res.status == "valid" and res.side == "buy" and res.quantity == 5 and res.limit_price == 105.5
print(" PASS: valid buy parsed accurately")

print("\nAll parser verification tests PASSED!")
