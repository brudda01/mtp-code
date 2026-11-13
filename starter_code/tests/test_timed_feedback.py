"""Timing semantics and economic invariance for the opt-in feedback adapter."""
import contextlib
from copy import deepcopy
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import uuid
import shutil

import numpy as np
import yaml

from sim import engine
from sim.agents.base import Observation
from sim.agents.llm_agent import LLMAgent
from sim.timed_feedback import agent_class, timed_feedback, VERSION


class FixedClient:
    def __init__(self, *args, **kwargs):
        self.calls = []
        self.total_tokens = 0
        self.last_usage = None
        self.last_response_metadata = {}

    def chat(self, messages, **kwargs):
        self.calls.append(deepcopy(messages))
        return ('{"action":"hold","quantity":0,"limit_price":null,"reasoning":"Latest price is 103.3."}'
                if kwargs.get("json_mode", True) else "Observations: No fills. Beliefs: uncertain. Plan: hold.")


def obs(rnd=1):
    return Observation(rnd, 3, [100., 103.3], 10, .02, .0002,
                       None, [], [], 10000., 100, 100., 20330., [])


class TimingTests(unittest.TestCase):
    def trader(self, mode="C"):
        records = []
        t = agent_class()("target", 10000, 100, np.random.default_rng(1),
            params=dict(condition=mode, reflect_every=1 if mode=="C" else 0, memory_window=2),
            client=FixedClient(), log_fn=records.append)
        return t, records

    def test_actual_predecision_observation_is_distinct_from_later_clearing(self):
        t, records = self.trader()
        o = t.decide(obs())
        self.assertNotIn("104.0", json.dumps(t.client.calls[0]))
        later = obs(); later.price_history.append(104.)
        t.end_round(later, o, 104.)
        memory = t.memory[-1]
        self.assertEqual(memory["decision_time"]["last_observed_price"], 103.3)
        self.assertEqual(memory["clearing_price_after_decision"], 104.)
        self.assertEqual(memory["recorded_decision_explanation"]["status"], "unverified_agent_explanation")
        self.assertNotIn("reasoning", memory["requested_order"])
        self.assertEqual(next(r["outcome"] for r in records if r["record_type"]=="outcome"), memory)
        self.assertIn("not a reading error", t.client.calls[-1][0]["content"])
        self.assertIn("does not guarantee", t.client.calls[-1][0]["content"])
        self.assertEqual((t.cash, t.shares), (10000., 100))
        self.assertTrue(all(r["feedback_schema"]==VERSION for r in records))

    def test_all_modes_receive_same_factual_records_and_BC_initial_inputs_match(self):
        memories=[]; prompts=[]
        for mode in "ABC":
            t,_ = self.trader(mode); o=t.decide(obs())
            prompts.append(t.client.calls[0])
            t.end_round(obs(),o,104.,reflect=False);memories.append(t.memory)
            # B/C derived summaries must continue to work on the new schema.
            self.assertEqual(t.factual_summary(obs(2))["last_executed_buy_quantity"],0)
        self.assertEqual(memories[0],memories[1]);self.assertEqual(memories[1],memories[2])
        self.assertEqual(prompts[1],prompts[2])
        self.assertEqual(prompts[0][0],prompts[1][0])

    def test_missing_or_mismatched_decision_is_rejected(self):
        from sim.market import Order
        t,_=self.trader()
        with self.assertRaises(ValueError):t.end_round(obs(),Order("target","hold"),104.)
        o=t.decide(obs())
        with self.assertRaises(ValueError):t.end_round(obs(2),o,104.)

    def test_failed_reflection_keeps_previous_diary_and_final_round_does_not_reflect(self):
        t,_=self.trader();t.diary="old belief"
        o=t.decide(obs())
        with patch.object(t.client,"chat",return_value=""):
            t.end_round(obs(),o,104.)
        self.assertEqual(t.diary,"old belief");self.assertEqual(t.reflection_failures,1)
        o=t.decide(obs(3));before=len(t.client.calls);t.end_round(obs(3),o,104.)
        self.assertEqual(len(t.client.calls),before)

    def test_adapter_restores_engine_after_exception(self):
        original=engine.LLMAgent
        with self.assertRaises(RuntimeError):
            with timed_feedback():
                self.assertIsNot(engine.LLMAgent,original);raise RuntimeError("expected")
        self.assertIs(engine.LLMAgent,original)

    def test_real_engine_fixed_replies_preserve_financial_files_all_modes(self):
        scratch=Path(__file__).resolve().parents[2]/'.tmp'
        scratch.mkdir(exist_ok=True)
        # Python3.13's Windows mkdir(mode=0700), used by TemporaryDirectory,
        # installs an ACL that excludes the restricted runner token here.
        root=scratch/('timed_feedback_test_'+uuid.uuid4().hex)
        root.mkdir()
        if not root.resolve().is_relative_to(scratch.resolve()):
            raise RuntimeError('temporary path escaped workspace')
        self.addCleanup(shutil.rmtree, root)
        with contextlib.nullcontext(str(root)) as tmp:
            root=Path(tmp);outputs=[]
            for timed in (False,True):
                for mode in "ABC":
                    cfg=dict(rounds=3,seed=47,execution=dict(max_workers=1),agents=[
                        dict(type="zero_intelligence",count=3),dict(type="llm",count=1,
                        llm=dict(provider="mock",condition=mode,memory_window=2,reflect_every=1 if mode=="C" else 0))])
                    path=root/f'{timed}_{mode}.yaml';path.write_text(yaml.safe_dump(cfg))
                    with patch.object(engine,"MockLLMClient",FixedClient), contextlib.redirect_stdout(io.StringIO()):
                        with timed_feedback() if timed else contextlib.nullcontext():
                            outputs.append(Path(engine.run(path,output_root=root/'runs')))
            for name in ('prices.csv','orders.csv','trades.csv','cashflows.csv','liquidity.csv'):
                self.assertEqual(len({(p/name).read_bytes() for p in outputs}),1,name)
            # Class labels differ by design; actual account state does not.
            import csv
            for filename in ('agents_state.csv','initial_state.csv'):
                states=[]
                for p in outputs:
                    with (p/filename).open() as f:
                        states.append([{k:v for k,v in r.items() if k!='type'} for r in csv.DictReader(f)])
                self.assertTrue(all(s==states[0] for s in states))
            self.assertIs(engine.LLMAgent,LLMAgent)


if __name__ == '__main__':unittest.main()
