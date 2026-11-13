import unittest
import numpy as np
from research.dynamic_order_tape import tape_agent,offline
from sim.agents.base import Observation
from sim.agents.rule_agents import MomentumAgent,MarketMakerAgent
import socket


class DynamicTapeTests(unittest.TestCase):
    def obs(self,history,cash=10000,shares=100):
        return Observation(6,12,history,10,.02,.0002,None,[],[],cash,shares,100,cash+shares*history[-1],[])
    def test_tape_revalidates_against_counterfactual_cash(self):
        tape={('llm_012',6):dict(side='buy',quantity='80',limit_price='')}
        cls=tape_agent(tape,'cap10');a=cls('llm_012',250,100,np.random.default_rng(0),params={'condition':'A'})
        self.assertEqual(a.decide(self.obs([100]*6,250)).quantity,2)
        a.cash=10000;self.assertEqual(a.decide(self.obs([100]*6)).quantity,10)
    def test_remove_retains_accounts_and_no_network(self):
        tape={('llm_012',6):dict(side='sell',quantity='50',limit_price='')}
        a=tape_agent(tape,'remove')('llm_012',10000,100,np.random.default_rng(0),params={'condition':'B'})
        self.assertEqual(a.decide(self.obs([100]*6)).side,'hold');self.assertEqual(a.shares,100)
        with offline(tape,'remove'):
            with self.assertRaises(RuntimeError):socket.create_connection(('example.com',443))
    def test_rules_respond_to_branch_prices_and_inventory(self):
        m=MomentumAgent('mome_008',10000,100,np.random.default_rng(0),params={'window':5,'aggressiveness':.5})
        self.assertNotEqual(m.decide(self.obs([100,101,102,103,104,110])).side,m.decide(self.obs([100,99,98,97,96,90])).side)
        mm=MarketMakerAgent('mark_000',30000,150,np.random.default_rng(0),params={'quote_size':10,'inventory_target':150,'inventory_limit':300,'inventory_skew':.02,'spread':.005})
        first=mm.decide(self.obs([100]*6));mm.shares=290
        second=mm.decide(self.obs([100]*6,30000,290))
        self.assertNotEqual([o.limit_price for o in first],[o.limit_price for o in second])


if __name__=='__main__':unittest.main()
