"""
Repaired LLM Agent and Strict Parser.
Directly addresses Findings #5, #12, #14 in AUDIT_REPORT.md:
- No silent casting of fractional/boolean quantities.
- No converting invalid limits into market orders.
- No converting empty objects into valid HOLDs.
- Explicit failure / missing status tracking (never disguise network errors as agent behavior).
"""
import json
import math
from typing import Dict, Any, Optional
import numpy as np

from repaired_engine import RepairedMarginAgent, Order, Observation

class RepairedLLMTrader(RepairedMarginAgent):
    def __init__(self, agent_id: str, cash: float, shares: int,
                 rng: Optional[np.random.Generator],
                 persona: Dict[str, Any],
                 client: Any,
                 allow_short: bool = True,
                 **kwargs):
        super().__init__(agent_id, cash, shares, rng, allow_short=allow_short, **kwargs)
        self.persona = persona
        self.client = client
        self.last_raw_response: Optional[str] = None
        self.last_status: str = "valid"

    def parse_decision(self, raw_content: str) -> Order:
        """
        Strict parser for LLM responses.
        Rejects fractional/boolean quantities, negative/NaN limits, empty objects.
        """
        if not raw_content or not raw_content.strip():
            return Order(self.agent_id, 'hold', 0, None, "empty_model_response", status="missing")

        try:
            data = json.loads(raw_content)
        except Exception as e:
            return Order(self.agent_id, 'hold', 0, None, f"json_parse_error: {str(e)}", status="error")

        if not isinstance(data, dict):
            return Order(self.agent_id, 'hold', 0, None, "non_dict_json", status="error")

        if not data:
            # Finding 12: Empty object must NOT become a valid-looking HOLD
            return Order(self.agent_id, 'hold', 0, None, "empty_json_object", status="missing")

        raw_action = str(data.get("action", "")).strip().lower()
        if raw_action not in ("buy", "sell", "hold"):
            return Order(self.agent_id, 'hold', 0, None, f"invalid_action_{raw_action}", status="error")

        if raw_action == "hold":
            reasoning = str(data.get("reasoning", "")).strip()
            return Order(self.agent_id, 'hold', 0, None, reasoning, status="valid")

        # Check quantity strictly
        raw_qty = data.get("quantity")
        if raw_qty is None:
            return Order(self.agent_id, 'hold', 0, None, "missing_quantity", status="error")
        # Finding 12: Reject boolean quantity
        if isinstance(raw_qty, bool):
            return Order(self.agent_id, 'hold', 0, None, "boolean_quantity_rejected", status="error")
        # Finding 12: Reject fractional float quantities (e.g. 2.9)
        if isinstance(raw_qty, float):
            if not raw_qty.is_integer():
                return Order(self.agent_id, 'hold', 0, None, f"fractional_quantity_rejected: {raw_qty}", status="error")
            raw_qty = int(raw_qty)
        elif not isinstance(raw_qty, (int, np.integer)):
            return Order(self.agent_id, 'hold', 0, None, "non_numeric_quantity", status="error")

        if raw_qty <= 0:
            return Order(self.agent_id, 'hold', 0, None, "non_positive_quantity", status="error")

        # Check limit price
        raw_limit = data.get("limit_price")
        limit_p: Optional[float] = None
        if raw_limit is not None:
            if isinstance(raw_limit, bool):
                return Order(self.agent_id, 'hold', 0, None, "boolean_limit_rejected", status="error")
            try:
                limit_p = float(raw_limit)
                if not math.isfinite(limit_p) or limit_p <= 0:
                    # Finding 12: Invalid/negative limit price must NOT become market order None
                    return Order(self.agent_id, 'hold', 0, None, f"invalid_limit_rejected: {raw_limit}", status="error")
            except (ValueError, TypeError):
                return Order(self.agent_id, 'hold', 0, None, f"non_numeric_limit_rejected: {raw_limit}", status="error")

        reasoning = str(data.get("reasoning", "")).strip()
        return Order(self.agent_id, raw_action, raw_qty, limit_p, reasoning, status="valid")

    def decide(self, obs: Observation) -> Order:
        mark_p = obs.price_history[-1] if obs.price_history else 100.0
        prompt = self._build_prompt(obs, mark_p)
        
        try:
            raw = self.client.complete([
                {"role": "system", "content": "You are a participant in a financial stock market. Return ONLY valid JSON."},
                {"role": "user", "content": prompt}
            ])
            self.last_raw_response = raw
        except Exception as e:
            # Finding 5: Never disguise API timeout / network failure as a valid economic decision
            self.last_status = "missing"
            return Order(self.agent_id, 'hold', 0, None, f"API_TRANSPORT_FAILURE: {str(e)}", status="missing")

        order = self.parse_decision(raw)
        self.last_status = order.status
        
        if order.status != "valid":
            return order

        if order.side == "hold":
            return order

        # Validate through repaired margin engine
        validated = self.validate_orders(order, mark_p)
        if not validated:
            return Order(self.agent_id, 'hold', 0, None, "order_clipped_to_zero_by_margin_engine", status="clipped")
        return validated[0]

    def _build_prompt(self, obs: Observation, mark_p: float) -> str:
        req_collat = self.get_required_collateral(mark_p)
        free_c = self.get_free_cash_at_price(mark_p)
        short_rule = (
            "SHORT-SELLING IS PERMITTED: You may sell shares you do not own if backed by 150% cash collateral."
            if self.allow_short else
            "SHORT-SELLING IS STRICTLY BANNED: You can only sell shares you currently own."
        )

        return (
            f"You are {self.persona['name']}, a {self.persona['age']}-year-old {self.persona['occupation']}.\n"
            f"Strategy inclination: {self.persona.get('strategy_inclination', 'balanced')}. Risk tolerance: {self.persona.get('risk_tolerance', 'medium')}.\n"
            f"Background: {self.persona.get('backstory', '')}\n\n"
            f"MARKET STATUS (Round {obs.round} of {obs.total_rounds}):\n"
            f"- Current Market Price: ${mark_p:.2f}\n"
            f"- Fundamental Anchor Value: $100.00\n"
            f"- Last Realized Dividend Paid: ${obs.last_dividend:.3f} per share\n"
            f"- Risk-Free Cash Interest Rate: {obs.risk_free_rate * 100:.3f}% per round\n"
            f"- Market Trading Rule: {short_rule}\n\n"
            f"YOUR ACCOUNT POSITION:\n"
            f"- Total Cash: ${self.cash:.2f}\n"
            f"- Locked Margin Collateral: ${req_collat:.2f}\n"
            f"- Free Spendable Cash: ${free_c:.2f}\n"
            f"- Share Holdings: {self.shares} shares (can be negative if short)\n"
            f"- Net Portfolio Wealth: ${self.wealth(mark_p):.2f}\n\n"
            f"Choose your action for Round {obs.round}. Return ONLY valid JSON in this exact schema:\n"
            f'{{"action": "buy"|"sell"|"hold", "quantity": <positive_integer>, "limit_price": <number_or_null>, "reasoning": "<brief_explanation>"}}'
        )
