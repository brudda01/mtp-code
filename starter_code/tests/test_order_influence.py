"""R054: conditional cap mechanics and isolation, without scientific frames."""
from copy import deepcopy
from dataclasses import asdict
import unittest
from research import order_influence as d


def frame(q=100):
    config=dict(seed=5,market=dict(tick=.1,price_band=.2,transaction_tax=0.),
                market_without_mechanism=dict(tick=.1,price_band=.2,transaction_tax=0.))
    accounts=[dict(agent_id=a,cash=100000.,shares=150 if a=='mark_000' else 100,avg_cost=100.)
              for a in ('llm_012','llm_013','mark_000','zero_001','fund_005')]
    book=[d.Order('llm_012','buy',q,110.,1),d.Order('llm_013','hold',0,None,1),
          d.Order('zero_001','buy',20,99.,1),d.Order('mark_000','sell',20,99.,1),d.Order('fund_005','sell',20,105.,1)]
    return dict(round=1,previous_price=100.,config=config,opening=accounts,
                orders=[dict(round=o.round,agent_id=o.agent_id,side=o.side,quantity=o.quantity,limit_price=o.limit_price) for o in book],
                allocation_state=d.market_from(config).rng.bit_generator.state)


class OrderInfluenceTests(unittest.TestCase):
    def test_cap_can_change_price_and_keeps_all_other_orders(self):
        f=frame();before=deepcopy(f)
        original=d.clear_frame(f,'original');capped=d.clear_frame(f,'cap10')
        self.assertEqual((original['price'],original['volume']),(105.,40))
        self.assertEqual((capped['price'],capped['volume']),(99.,20))
        self.assertEqual(f,before)
        self.assertEqual(d.clear_frame(f,'original'),original)

    def test_cap_noop_and_removal_preserve_resources(self):
        f=frame(q=5)
        self.assertEqual(d.clear_frame(f,'original'),d.clear_frame(f,'cap10'))
        removed=d.clear_frame(f,'remove')
        self.assertEqual(removed['target_involved_volume'],0)
        self.assertEqual(removed['posttrade_accounts']['llm_012']['shares'],100)
        self.assertEqual(removed['posttrade_accounts']['llm_012']['cash'],100000.)
        self.assertAlmostEqual(sum(a['cash'] for a in removed['posttrade_accounts'].values()),500000.)
        self.assertEqual(sum(a['shares'] for a in removed['posttrade_accounts'].values()),550)

    def test_rng_and_book_never_propagate_between_conditions(self):
        f=frame();book=d.book_from(f['orders']);original=deepcopy(book)
        changed=d.intervene(book,'cap10')
        self.assertEqual([asdict(o) for o in book],[asdict(o) for o in original])
        self.assertEqual(changed[0].quantity,10)
        baseline=d.clear_frame(f,'original')
        for condition in ('remove','cap10','remove'):d.clear_frame(f,condition)
        self.assertEqual(d.clear_frame(f,'original'),baseline)


if __name__=='__main__':unittest.main()
