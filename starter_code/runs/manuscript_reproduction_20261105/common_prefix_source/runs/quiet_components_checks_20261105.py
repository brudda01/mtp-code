"""Offline R043 information, actual-history, drift and failure-preservation checks."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from sim.agents.llm_agent import LLMAgent
from runs import quiet_components_20261105 as d

sys.path.insert(0,str(d.BASE/'tests'))
from test_news_components import ScriptedClient, NoDelay


class TradingClient(ScriptedClient):
    def chat(self,messages,json_mode=True,**kwargs):
        raw=super().chat(messages,json_mode=json_mode,**kwargs)
        if json_mode and not type(self).malformed:
            return json.dumps(dict(action='buy' if type(self).calls%2 else 'sell',
                quantity=5+type(self).calls%9,limit_price=None,reasoning='offline own-history exercise'))
        return raw


class Checks(unittest.TestCase):
    def setUp(self):
        scratch=d.BASE/'.tmp';scratch.mkdir(exist_ok=True)
        temp=tempfile.TemporaryDirectory(dir=scratch);self.addCleanup(temp.cleanup)
        with contextlib.redirect_stdout(io.StringIO()):self.root=d.prepare(Path(temp.name))
        TradingClient.calls=0;TradingClient.fail_on=None
        TradingClient.empty_reflection=TradingClient.malformed=False
    def execute(self):
        with patch('sim.engine.LLMClient',TradingClient),patch.object(d,'RequestPacer',NoDelay),contextlib.redirect_stdout(io.StringIO()):
            result=d.execute(self.root)
        self.assertIs(d.base.engine.LLMAgent,LLMAgent)
        return result
    def test_full_schedule_uses_own_outcomes_and_reflections_and_equal_information(self):
        result=self.execute()
        self.assertEqual((result['status'],result['completed_markets'],result['completed_seed_checks'],TradingClient.calls),('completed',18,3,456))
        index=d.read(self.root/'runs.json');protocol=d.read(self.root/'protocol.json')
        self.assertEqual([(a['seed'],a['mode'],a['repetition']) for a in index],[(a['seed'],a['mode'],a['repetition']) for b in protocol['blocks'] for a in b['arms']])
        self.assertEqual(sum(a['history_audit']['reflections_recorded'] for a in index),24)
        self.assertEqual(sum(a['history_audit']['actual_history_requests_checked'] for a in index),456)
        c=next(a for a in index if a['mode']=='C');path=self.root/c['run_path']
        records=d.base.lines(path/'llm_requests.jsonl')
        self.assertEqual([(r['round'],r['agent_id']) for r in records if r.get('call_type')=='reflection'],[(5,'llm_012'),(5,'llm_013'),(10,'llm_012'),(10,'llm_013')])
        # A deliberately corrupted actual-outcome input must be detected, not silently accepted.
        first=next(r for r in records if r.get('call_type')=='decision' and r['round']==6)
        first['messages'][1]['content']=first['messages'][1]['content'].replace('Your recent verified outcomes: [','Your recent verified outcomes: [{"fabricated": true},',1)
        (path/'llm_requests.jsonl').write_text('\n'.join(json.dumps(x) for x in records)+'\n')
        with self.assertRaises(AssertionError):d.history_audit(path,'C')
    def test_first_provider_failure_stops_without_next_arm_or_fake_hold_endpoint(self):
        TradingClient.fail_on=1;result=self.execute()
        self.assertEqual((result['status'],result['recorded_markets'],result['completed_markets'],TradingClient.calls),('stopped',1,0,1))
        self.assertEqual(d.read(self.root/'runs.json')[0]['rounds'],0)
    def test_empty_reflection_is_retained_and_stops_campaign_after_affected_arm(self):
        TradingClient.empty_reflection=True;result=self.execute()
        self.assertEqual((result['status'],result['recorded_markets'],result['completed_markets']),('stopped',3,2))
        affected=d.read(self.root/'runs.json')[-1]
        self.assertEqual(affected['mode'],'C');self.assertEqual(affected['rounds'],12)
        self.assertEqual(affected['operational_failures']['reflection_failures'],4)
    def test_source_config_and_duplicate_guards_precede_calls(self):
        protocol=d.read(self.root/'protocol.json');path=self.root/protocol['blocks'][0]['arms'][0]['config']
        original=path.read_text();path.write_text(original+'\n# drift\n')
        with self.assertRaises(AssertionError):self.execute()
        self.assertEqual(TradingClient.calls,0)
        path.write_text(original);(self.root/'execution.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'already started'):self.execute()
        self.assertEqual(TradingClient.calls,0)


if __name__=='__main__':unittest.main()
