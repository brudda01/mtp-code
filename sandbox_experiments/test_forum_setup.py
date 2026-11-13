"""Offline exposure/configuration tests; no API access or scientific markets."""
import json
from pathlib import Path
import unittest
import uuid
from forum_experiment import posts,phase,prompt_pair,ForumTrader,prepare,ROOT
from repaired_engine import Observation
from repaired_client import FixtureClient
from sandbox import Config,build_accounts

class ForumSetupTests(unittest.TestCase):
    def test_exact_windows_and_silent_control(self):
        self.assertEqual(sum(len(posts(r,'sentiment')) for r in range(1,101)),40)
        self.assertEqual([r for r in range(1,101) if posts(r,'sentiment')],list(range(21,61)))
        self.assertTrue(all(posts(r,'silent')==[] for r in range(1,101)))
        for r in (0,101):
            with self.assertRaises(ValueError): posts(r,'sentiment')
    def test_only_post_field_changes_at_common_state(self):
        for sample in prompt_pair(44,21)+prompt_pair(45,41):
            silent,sentiment=sample['silent'],sample['sentiment']
            self.assertTrue(sentiment['observation']['public_forum_posts'])
            sentiment['observation']['public_forum_posts']=[]
            self.assertEqual(silent,sentiment)
    def test_baseline_and_after_feed_are_identical_at_common_state(self):
        for r in (1,20,61,100):
            for p in prompt_pair(44,r): self.assertEqual(p['silent'],p['sentiment'])
    def test_twelve_recipients_and_no_future_schedule(self):
        pair=prompt_pair(44,21)
        self.assertEqual(len(pair),12)
        for p in pair:
            self.assertEqual(p['sentiment']['observation']['public_forum_posts'],posts(21,'sentiment'))
            self.assertNotIn('phases',p['sentiment']); self.assertNotIn('total_rounds',json.dumps(p['sentiment']))
            self.assertIsNone(p['sentiment']['observation']['disclosed_reference'])
    def test_protocol_is_unapproved_and_exclusive(self):
        out=ROOT/'runs'/('forum_setup_test_'+uuid.uuid4().hex)
        prepare(out)
        d=json.loads((out/'plan.json').read_text())
        self.assertIn('NOT_AUTHORIZED',d['status']); self.assertEqual(d['planned_decisions'],4800)
        self.assertEqual(d['provider_requests_made'],0)
        self.assertEqual(d['delivery']['concurrent_requests'],4)
        accounts=json.loads((out/'initial_accounts.json').read_text())
        for a in accounts.values():
            self.assertEqual(len(a),20)
            self.assertAlmostEqual(sum(x['cash'] for x in a.values()),220000)
            self.assertEqual(sum(x['shares'] for x in a.values()),2050)
        with self.assertRaises(FileExistsError): prepare(out)
    def test_zero_active_quantity_rejected_in_new_protocol(self):
        a=ForumTrader('a',1000,10,None,dict(name='test'),None)
        o=a.parse_decision(json.dumps(dict(action='buy',quantity=0,limit_price=100,reasoning='test')))
        self.assertEqual(o.status,'error')

if __name__=='__main__': unittest.main(verbosity=2)
