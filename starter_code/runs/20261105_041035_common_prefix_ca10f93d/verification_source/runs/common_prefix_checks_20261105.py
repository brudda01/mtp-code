"""Offline common-prefix identification,cost isolation and failure checks."""
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from runs import common_prefix_20261105 as d
from runs.quiet_components_checks_20261105 import TradingClient,NoDelay
from sim.agents.llm_agent import LLMAgent


class Checks(unittest.TestCase):
    def setUp(self):
        scratch=d.BASE/'.tmp';scratch.mkdir(exist_ok=True)
        temp=tempfile.TemporaryDirectory(dir=scratch);self.addCleanup(temp.cleanup)
        with contextlib.redirect_stdout(io.StringIO()):self.root=d.prepare(Path(temp.name))
        TradingClient.calls=0;TradingClient.fail_on=None;TradingClient.empty_reflection=TradingClient.malformed=False
    def execute(self):
        with patch('sim.engine.LLMClient',TradingClient),patch.object(d,'RequestPacer',NoDelay),contextlib.redirect_stdout(io.StringIO()):
            result=d.execute(self.root)
        self.assertIs(d.prior.base.engine.LLMAgent,LLMAgent)
        return result
    def test_full384fresh_calls_zero_prefix_cost_and_common_all_account_state(self):
        result=self.execute()
        self.assertEqual((result['status'],result['completed_branches'],TradingClient.calls,result['cached_prefix_requests']),('completed',24,384,240))
        self.assertEqual(result['usage']['requests_made'],384)
        index=d.read(self.root/'runs.json')
        for arm in index:
            self.assertTrue(arm['first_live_state_gate']);self.assertEqual(arm['cached_prefix_requests'],10)
            expected=14 if arm['mode']=='B' else 18
            self.assertEqual(arm['usage']['requests_made'],expected)
            path=self.root/arm['run_path'];requests=d.lines(path/'llm_requests.jsonl')
            cached=[c for c in d.lines(path/'llm_calls.jsonl') if c['record_type']=='prefix_replay_call']
            fresh=[c for c in requests if c['record_type']=='model_call']
            self.assertEqual(len(cached),10);self.assertEqual(len(fresh),expected)
            self.assertTrue(all(c['prefix_replay'] and not c['new_http_request'] and c['usage'] is None for c in cached))
            self.assertTrue(all(c['round']>=6 or c['call_type']=='reflection' for c in fresh))
            if arm['mode']=='C':self.assertEqual([(c['round'],c['call_type']) for c in fresh if c['call_type']=='reflection'],[(5,'reflection'),(5,'reflection'),(10,'reflection'),(10,'reflection')])
        self.assertEqual(d.read(self.root/'prefix_gate_summary.json')['new_api_requests'],0)
    def test_first_live_provider_failure_retains_complete_prefix_and_stops(self):
        TradingClient.fail_on=1;result=self.execute()
        self.assertEqual((result['status'],result['recorded_branches'],result['completed_branches'],TradingClient.calls),('stopped',1,0,1))
        arm=d.read(self.root/'runs.json')[0]
        self.assertEqual(arm['rounds'],5);self.assertEqual(arm['cached_prefix_requests'],10)
        self.assertEqual(result['usage']['unknown_usage_requests'],1)
    def test_prefix_drift_and_duplicate_guard_precede_any_fresh_call(self):
        protocol=d.read(self.root/'protocol.json');path=self.root/'prefixes'/protocol['prefixes'][0]['prefix_id']/'calls.json'
        original=path.read_bytes();path.write_bytes(original+b'\n')
        with self.assertRaises(AssertionError):self.execute()
        self.assertEqual(TradingClient.calls,0);path.write_bytes(original)
        (self.root/'execution.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'already started'):self.execute()
    def test_empty_reflection_is_affected_not_a_successful_treatment(self):
        TradingClient.empty_reflection=True;result=self.execute()
        self.assertEqual(result['status'],'stopped')
        arm=d.read(self.root/'runs.json')[-1]
        self.assertEqual((arm['mode'],arm['rounds'],arm['operational_failures']['reflection_failures']),('C',12,4))
        self.assertEqual(result['completed_branches'],result['recorded_branches']-1)
    def test_first_live_gate_detects_account_mismatch_before_client_chat(self):
        protocol=d.read(self.root/'protocol.json');arm=protocol['schedule'][0]
        prefix=self.root/'prefixes'/arm['prefix_id'];path=prefix/'agents_state.csv'
        import csv
        with path.open(newline='',encoding='utf-8') as f:
            reader=csv.DictReader(f);fields=reader.fieldnames;rows=list(reader)
        target=next(r for r in rows if r['round']=='5' and r['agent_id']=='llm_013');target['cash']=str(float(target['cash'])+1)
        with path.open('w',newline='',encoding='utf-8') as f:
            writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(rows)
        with patch('sim.engine.LLMClient',TradingClient),d.context(prefix),contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(AssertionError):d.prior.base.engine.run(self.root/arm['config'],output_root=self.root/'bad_state_check')
        self.assertEqual(TradingClient.calls,0)
    def test_raw_prefix_messages_cannot_be_replaced_with_arbitrary_replies(self):
        protocol=d.read(self.root/'protocol.json');prefix=self.root/'prefixes'/protocol['prefixes'][0]['prefix_id']
        tape=d.read(prefix/'calls.json');tape[0]['messages'][1]['content']='fabricated prefix'
        from sim.provenance import write_json
        write_json(prefix/'calls.json',tape)
        arm=next(a for a in protocol['schedule'] if a['prefix_id']==protocol['prefixes'][0]['prefix_id'])
        with patch('sim.engine.LLMClient',TradingClient),d.context(prefix),contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(AssertionError,'Prefix messages differ'):
                d.prior.base.engine.run(self.root/arm['config'],output_root=self.root/'corrupted_check')
        self.assertEqual(TradingClient.calls,0)


if __name__=='__main__':unittest.main()
