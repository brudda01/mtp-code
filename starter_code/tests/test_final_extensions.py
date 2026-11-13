import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import patch
import yaml
import numpy as np
from research import goedel_cohort as g
from sim.agents.base import Observation
from sim.llm.client import LLMClient
from sim.market import Order


class FakeClient(LLMClient):
    def chat(self,messages,**kwargs):
        self.last_usage=dict(prompt_tokens=50,completion_tokens=20,total_tokens=70,source='mock')
        self.last_response_metadata={'model':g.MODEL,'finish_reason':'stop'};self.total_tokens+=70
        return json.dumps(dict(action='buy',quantity=80,limit_price=None,reasoning='Offline test only'))


@contextlib.contextmanager
def mock_space():
    path=g.BASE/'runs/extension_mock_checks'/uuid.uuid4().hex
    path.mkdir(parents=True,exist_ok=False)
    yield path  # Retained and explicitly labelled mock-only; no scientific samples.


class ExtensionTests(unittest.TestCase):
    def test_profile_has_same_14_slots_and_resources(self):
        cfg=g.recipe();self.assertEqual(sum(x['count'] for x in cfg['agents']),14)
        self.assertEqual(sum(x['count']*x['cash'] for x in cfg['agents']),160000)
        self.assertEqual(sum(x['count']*x['shares'] for x in cfg['agents']),1450)
        self.assertEqual(cfg['agents'][-1]['count'],6);self.assertEqual(cfg['rounds'],25)

    def test_prompt_hides_horizon_and_cap_is_enforced(self):
        a=g.CappedAgent('llm_008',10000,100,np.random.default_rng(0),params={'condition':'B'})
        obs=Observation(1,25,[100],0,.02,.0002,None,[],[],10000,100,100,20000,[])
        prompt=a.user_prompt(obs)
        self.assertNotIn('1/25',prompt);self.assertIn('prior dividend',prompt)
        self.assertIn('limited to 10',a.system_prompt('KGP'))
        self.assertEqual(a.validate(Order(a.agent_id,'buy',80,None,1),100).quantity,10)

    def test_full_25_round_mock_has_actual_own_history_and_conservation(self):
        with mock_space() as d:
            root=Path(d);cfg=root/'config.yaml';cfg.write_text(yaml.safe_dump(g.recipe()))
            with patch.object(g.engine,'LLMClient',FakeClient),patch.object(g.engine,'LLMAgent',g.CappedAgent),g.strict_accounting(g.CappedAgent),patch('sim.llm.usage.RequestPacer.acquire',return_value=0),contextlib.redirect_stdout(io.StringIO()):
                run=Path(g.engine.run(cfg,output_root=root/'out'))
            s=g.read(run/'summary.json');self.assertEqual(s['status'],'completed');self.assertEqual(s['llm_usage']['requests_made'],150)
            self.assertEqual(g.audit_financial(run)['account_rounds'],350)
            self.assertTrue(all(int(o['quantity'])<=10 for o in g.rows(run/'orders.csv') if o['agent_id'].startswith('llm_')))
            requests=[json.loads(l) for l in (run/'llm_requests.jsonl').read_text().splitlines()]
            self.assertEqual(len(requests),150)
            outcomes=[json.loads(l) for l in (run/'agent_outcomes.jsonl').read_text().splitlines()]
            self.assertEqual(len(outcomes),150)
            self.assertEqual(len(json.loads((run/'personas.json').read_text())),6)

    def test_client_payload_model_guard_and_no_key_in_transport(self):
        class Response:
            headers={}
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self):return json.dumps(dict(model='wrong-model',usage=dict(prompt_tokens=2,completion_tokens=2,total_tokens=4),choices=[dict(finish_reason='stop',message={'content':'{}'})])).encode()
        class Opener:
            def open(self,req,timeout):
                self.body=json.loads(req.data);return Response()
        with mock_space() as d,patch.object(g,'dotenv_api_key',return_value='test-key-not-a-real-secret'):
            c=g.GoedelClient(model=g.MODEL,base_url=g.URL);c.opener=Opener();c.transport_path=Path(d)/'requests.jsonl'
            with self.assertRaises(ValueError):c.chat([{'role':'user','content':'test'}])
            self.assertFalse(c.opener.body['chat_template_kwargs']['thinking'])
            self.assertNotIn('response_format',c.opener.body)
            self.assertNotIn('test-key-not-a-real-secret',c.transport_path.read_text())
            self.assertEqual(c.last_usage['total_tokens'],4)


if __name__=='__main__':unittest.main()
