"""Before-outcome design checks, using a non-study seed and no provider."""
from copy import deepcopy
import unittest
from sim.engine import build_agents,make_rngs
from research.background_diversity import recipe,SEEDS


class DiversityTests(unittest.TestCase):
    def test_groups_preserve_account_positions_resources_and_random_streams(self):
        sets=[]
        for h in (False,True):
            for skew in (.02,0.):
                cfg=recipe(42,h,skew)
                rng=make_rngs(42);agents=build_agents(cfg,rng['population'],persona_rng=rng['personas'])
                self.assertEqual(len(agents),14)
                self.assertEqual(sum(a.cash for a in agents.values()),160000)
                self.assertEqual(sum(a.shares for a in agents.values()),1450)
                sets.append([(i,type(a).__name__,a.cash,a.shares,deepcopy(a.rng.bit_generator.state)) for i,a in agents.items()])
                self.assertEqual(agents['fund_012'].params,{'delta':.03,'aggressiveness':.5,'dividend_window':1})
                self.assertEqual(agents['mome_013'].params,{'window':5,'aggressiveness':.5})
                self.assertEqual(cfg.llm_limits.max_requests,0)
        self.assertTrue(all(x==sets[0] for x in sets))

    def test_bundle_changes_only_prespecified_background_parameters(self):
        a,b=recipe(42,False,.02).to_dict(),recipe(42,True,.02).to_dict()
        def expand(cfg):
            return [dict(g,count=1) for g in cfg['agents'] for _ in range(g['count'])]
        aa,bb=expand(a),expand(b)
        changed=[]
        for i,(x,y) in enumerate(zip(aa,bb)):
            if x!=y:changed.append(i)
        self.assertEqual(changed,[5,7,8,9,10,11])
        self.assertEqual(sum(bb[i]['params']['delta'] for i in (5,6,7))/3,.03)
        self.assertEqual(sum(bb[i]['params']['window'] for i in (8,9,10,11))/4,5)
        self.assertEqual(a['asset'],b['asset']);self.assertEqual(a['market'],b['market'])
        self.assertEqual(len(set(SEEDS)),4)


if __name__=='__main__':unittest.main()
