"""Offline concurrent forum worker checks. No credentials/network used."""
import json
import unittest
import uuid
from unittest.mock import patch
from test_live_campaign import FakeOpener
from run_forum_heterogeneous import ConcurrentForumClient,FinancialCheck,existing_market
from sandbox import ROOT,Config
from sim.llm.usage import UsageBudget
from forum_experiment import posts

class ForumLaunchTests(unittest.TestCase):
    def test_concurrent_mock_through_feed_onset(self):
        output=ROOT/'runs'/('forum_launch_mock_'+uuid.uuid4().hex)
        budget=UsageBudget(max_requests=300,max_reserved_tokens=10000000,stop_on_api_error=True)
        budget.pacer.acquire=lambda estimate:0.
        audit=FinancialCheck()
        cfg=Config(seed=42,rounds=22,wealth='heterogeneous',forum=True)
        with patch.object(existing_market,'POSTS',{r:posts(r,'sentiment') for r in range(1,101)}):
            existing_market.run_concurrent_market(cfg,output,
                lambda log:ConcurrentForumClient('fixture-key',log,budget,FakeOpener),audit.accept)
        self.assertEqual(audit.count,22)
        rows=[json.loads(line) for line in (output/'ledger.jsonl').read_text().splitlines()]
        requests=[r for r in rows if r['kind']=='wire_request']
        self.assertEqual(len(requests),264)
        self.assertEqual(len({r['index'] for r in requests}),264)
        for r in requests:
            p=json.loads(r['request']['messages'][1]['content'])
            self.assertEqual(p['observation']['public_forum_posts'],posts(p['observation']['session'],'sentiment'))
        m=json.loads((output/'manifest.json').read_text()); m['evidence_type']='OFFLINE_CONCURRENT_FORUM_TEST_NOT_BEHAVIORAL_DATA'
        (output/'manifest.json').write_text(json.dumps(m,indent=2))

if __name__=='__main__': unittest.main(verbosity=2)
