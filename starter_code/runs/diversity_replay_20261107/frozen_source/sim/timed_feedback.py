"""Opt-in R050 feedback schema; frozen v2 agents/defaults remain unchanged.

Use ``with timed_feedback(): engine.run(...)`` in a new, versioned study.
The adapter changes representation, not the exchange or information available
at decision time. It is offline-verified, not behaviorally validated.
"""
from contextlib import contextmanager
from copy import deepcopy
import json

from sim.agents.llm_agent import LLMAgent, market_rules_prompt

VERSION = "timed_feedback_v1"
TIMING_RULES = """Feedback timing: decision_time records information available BEFORE that session's auction.
clearing_price_after_decision and post_settlement_account are later outcomes, unavailable when deciding.
A decision referring to the last observed price is not a reading error merely because the subsequent clearing price differs.
recorded_decision_explanation is the agent's unverified earlier explanation, not a verified observation or known cause of an outcome.
An accepted market or limit order may fill partially or not at all; a market order does not guarantee a full fill."""


def labelled_outcome(outcome, decision_time):
    """Separate facts by timing and remove prose from factual order fields."""
    if outcome["round"] != decision_time["round"]:
        raise ValueError("outcome and captured decision refer to different rounds")
    requested, accepted = deepcopy(outcome["requested_order"]), deepcopy(outcome["accepted_order"])
    explanation = requested.pop("reasoning", "")
    accepted.pop("reasoning", None)
    return dict(
        schema_version=VERSION, round=outcome["round"], decision_time=deepcopy(decision_time),
        requested_order=requested, accepted_order=accepted,
        recorded_decision_explanation=dict(text=explanation, status="unverified_agent_explanation"),
        clearing_price_after_decision=outcome["price"],
        executed_buy_quantity=outcome["executed_buy_quantity"],
        executed_sell_quantity=outcome["executed_sell_quantity"], fills=deepcopy(outcome["fills"]),
        post_settlement_account={k:outcome[k] for k in ("cash", "shares", "avg_cost", "wealth", "dividend_income", "interest_income", "wealth_change")})


def agent_class(base=LLMAgent):
    """Compose with an existing disclosure adapter without changing its economics."""
    class TimedFeedbackAgent(base):
        def __init__(self, *args, **kwargs):
            self._decision_time = None
            original = kwargs.get("log_fn") or (lambda record: None)
            def log(record):
                record = {**record, "feedback_schema": VERSION,
                          "upstream_feedback_prompt_version": record.get("prompt_version"),
                          "prompt_version": VERSION + ":" + str(record.get("condition"))}
                if record.get("record_type") == "outcome":
                    record["outcome"] = labelled_outcome(record["outcome"], self._decision_time)
                original(record)
            kwargs["log_fn"] = log
            super().__init__(*args, **kwargs)

        def decide(self, obs):
            self._decision_time = dict(
                round=obs.round, last_observed_price=obs.price_history[-1],
                opening_account=dict(cash=obs.my_cash, shares=obs.my_shares,
                                     avg_cost=obs.my_avg_cost, wealth=obs.my_wealth))
            return super().decide(obs)

        def system_prompt(self, ticker):
            return super().system_prompt(ticker) + "\n" + TIMING_RULES

        def user_prompt(self, obs):
            return super().user_prompt(obs).replace(
                "Your recent verified outcomes:",
                "Your recent outcomes (timed execution facts and unverified explanations):")

        def end_round(self, obs, order, price, *, reflect=True, **kwargs):
            if self._decision_time is None or self._decision_time["round"] != obs.round:
                raise ValueError("capture the actual decision observation before recording feedback")
            super().end_round(obs, order, price, reflect=False, **kwargs)
            self.memory[-1] = labelled_outcome(self.memory[-1], self._decision_time)
            if reflect:
                self.reflect_if_due(obs)

        def reflect_if_due(self, obs):
            if (self.condition != "C" or obs.round >= obs.total_rounds or
                    obs.round <= self._last_reflected_round or obs.round <= 0 or
                    obs.round % self.reflect_every):
                return
            self._last_reflected_round = obs.round
            p = self.persona
            system = (f"You are {p.get('name', self.agent_id)}, reflecting on your own trading experience.\n"
                      f"Stable profile: risk {p.get('risk_tolerance', 'medium')}; style {p.get('strategy_inclination', 'balanced')}; "
                      f"horizon {p.get('horizon', 'medium')}. {p.get('bias_clauses', '')}\n"
                      "Distinguish Observations, Beliefs and Plan. Do not invent fills, unavailable fundamentals or causes. "
                      "Do not rewrite your stable profile. Write under 120 words in first person.\n" + TIMING_RULES + "\n" +
                      market_rules_prompt(self.params.get("tick", .1), self.price_band, self.transaction_tax))
            messages = [{"role":"system", "content":system}, {"role":"user", "content":
                "Previous reflection (fallible): " + (self.diary or "none") +
                "\nRecent outcomes (execution facts and unverified explanations): " + json.dumps(self.memory, allow_nan=False)}]
            raw, meta = self._request(messages, obs.round, "reflection", temperature=0., json_mode=False)
            failed = (meta["status"] == "error" or not isinstance(raw, str) or not raw.strip() or
                      meta["response_metadata"].get("finish_reason") in ("length", "content_filter"))
            if failed:
                self.reflection_failures += 1
            else:
                self.diary = " ".join(raw.split()[:120])
            self.log_fn(dict(record_type="reflection", call_type="reflection", agent_id=self.agent_id,
                             round=obs.round, condition=self.condition, prompt_version=VERSION,
                             attempts=self._attempt_refs([meta]), raw=raw, diary=self.diary,
                             failure_type="reflection_failed" if failed else None))
    return TimedFeedbackAgent


@contextmanager
def timed_feedback():
    """Explicit single-study adapter; do not nest concurrent engine runs."""
    from sim import engine
    previous = engine.LLMAgent
    engine.LLMAgent = agent_class(previous)
    try:
        yield
    finally:
        engine.LLMAgent = previous
