"""Offline HTTP-adapter/real-loop tests. No provider requests."""
import json
from pathlib import Path
import unittest
import uuid
from unittest.mock import patch
from live_campaign import LiveClient
from sandbox import ROOT,Config,_run_market,fixture_policy
from delivery import campaign_budget

class Reply:
    code=200
    headers={}
    def __init__(self,body): self.body=body
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def read(self): return json.dumps(self.body).encode()

class FakeOpener:
    def open(self,request,timeout):
        body=json.loads(request.data)
        return Reply(dict(model=body['model'],choices=[dict(finish_reason='stop',message=dict(content=fixture_policy(body['messages'])))],
            usage=dict(prompt_tokens=10,completion_tokens=10,total_tokens=20)))

class LiveTests(unittest.TestCase):
    def test_http_adapter_and_shared_loop_without_network(self):
        budget=campaign_budget()
        budget.pacer.acquire=lambda estimate:0.
        path=ROOT/'runs'/('live_adapter_mock_'+uuid.uuid4().hex)
        _run_market(Config(rounds=2),path,client_factory=lambda log:LiveClient('fixture-key',log,budget,FakeOpener()))
        manifest=json.loads((path/'manifest.json').read_text())
        self.assertEqual(manifest['provider_requests'],24)
        self.assertEqual(manifest['delivered_provider_responses'],24)
        self.assertEqual(manifest['completed_rounds'],2)
        rows=[json.loads(line) for line in (path/'ledger.jsonl').read_text().splitlines()]
        self.assertEqual(sum(r['kind']=='wire_response' for r in rows),24)
        self.assertNotIn('fixture-key',(path/'ledger.jsonl').read_text())
        # Explicitly relabel synthetic transport evidence; never preserve it as real collection.
        manifest['evidence_type']='OFFLINE_LIVE_ADAPTER_TEST_NOT_BEHAVIORAL_DATA'
        (path/'manifest.json').write_text(json.dumps(manifest,indent=2))
    def test_fatal_response_has_no_hidden_retry(self):
        class Wrong(FakeOpener):
            def open(self,request,timeout):
                return Reply(dict(model='wrong',choices=[]))
        records=[]; budget=campaign_budget(); budget.pacer.acquire=lambda estimate:0.
        c=LiveClient('fixture-key',records.append,budget,Wrong())
        with self.assertRaises(RuntimeError): c.complete([dict(role='user',content='test')])
        self.assertEqual(budget.requests,1)

if __name__=='__main__': unittest.main(verbosity=2)
