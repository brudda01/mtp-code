"""Offline correction gates: injected HTTP only; no scientific samples."""
import unittest
import tempfile
import json
from pathlib import Path
from unittest.mock import patch
import run_wealth_correction as correction
from fresh_correction_delivery import FreshOnlyDelivery, MODEL
from sim.llm.usage import UsageBudget, RequestPacer, ProviderUnavailable
from sandbox import fixture_policy

class Response:
    code=200
    headers={}
    def __init__(self,body): self.body=body
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def read(self): return json.dumps(self.body).encode()

class FakeOpener:
    def open(self,req,timeout):
        b=json.loads(req.data)
        return Response(dict(model=MODEL,choices=[dict(finish_reason='stop',message=dict(content=fixture_policy(b['messages'])))],
                             usage=dict(prompt_tokens=10,completion_tokens=10,total_tokens=20)))

class Tests(unittest.TestCase):
    def test_replay_is_rejected_before_delivery(self):
        for tape in ([],[{'choices':[]} ]):
            budget=UsageBudget()
            with self.assertRaises(ValueError): FreshOnlyDelivery('fixture',lambda x:None,budget,tape=tape)
            self.assertEqual(budget.requests,0)

    def test_wrong_model_stops_without_resampling(self):
        class Wrong(FakeOpener):
            def open(self,req,timeout): return Response(dict(model='wrong',choices=[]))
        b=UsageBudget(stop_on_api_error=True); records=[]
        with patch.object(RequestPacer,'acquire',return_value=0):
            with self.assertRaises(ProviderUnavailable): FreshOnlyDelivery('fixture',records.append,b,opener=Wrong()).complete([])
        self.assertEqual(b.requests,1); self.assertTrue(b.snapshot()['provider_stopped'])

    def test_full_mock_then_overwrite_refused(self):
        with tempfile.TemporaryDirectory(prefix='wealth_correction_offline_') as tmp:
            output=Path(tmp)/'new_mock_not_evidence'
            with patch.object(correction,'OUTPUT',output), patch.object(correction,'dotenv_api_key',return_value='fixture'), \
                 patch('urllib.request.build_opener',return_value=FakeOpener()), \
                 patch('socket.socket',side_effect=AssertionError('network forbidden')), \
                 patch.object(RequestPacer,'acquire',return_value=0):
                correction.run()
                summary=json.loads((output/'summary.json').read_text())
                self.assertEqual(summary['status'],'complete')
                self.assertEqual(summary['usage']['requests_made'],1200)
                self.assertEqual(summary['verification']['account_rounds'],2000)
                self.assertEqual(summary['usage']['requests_per_minute'],110)
                self.assertEqual(summary['usage']['input_tokens_per_minute'],200000)
                with self.assertRaises(FileExistsError): correction.run()

if __name__=='__main__': unittest.main(verbosity=2)
