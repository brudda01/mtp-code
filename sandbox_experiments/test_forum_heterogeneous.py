"""Targeted offline checks of the reduced forum proposal."""
import json
import unittest
from forum_heterogeneous import previews,controls
from forum_experiment import posts

class HeterogeneousForumTests(unittest.TestCase):
    def test_control_settings_and_initial_prompt_match(self):
        refs=controls()
        self.assertEqual([r['seed'] for r in refs],[42,43])
        self.assertTrue(all(r['config']['wealth']=='heterogeneous' and r['initial_prompt_match'] for r in refs))
    def test_only_posts_change(self):
        for seed in (42,43):
            samples=previews(seed,21)
            self.assertEqual(len(samples),12)
            for p in samples:
                self.assertEqual(p['active']['observation']['public_forum_posts'],posts(21,'sentiment'))
                p['active']['observation']['public_forum_posts']=[]
                self.assertEqual(p['active'],p['silent'])
                self.assertNotIn('forum_policy',p['silent']['rules'])
    def test_pre_post_silence_matches_existing_prompt(self):
        for r in (1,20,61,100):
            self.assertTrue(all(p['active']==p['silent'] for p in previews(42,r)))

if __name__=='__main__': unittest.main(verbosity=2)
