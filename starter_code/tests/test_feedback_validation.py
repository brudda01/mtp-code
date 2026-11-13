"""R052 gates: exact actual prompts, full schedule, fatal-stop/single-use policy."""
import contextlib
import io
from pathlib import Path
import shutil
import unittest
import uuid

from research import feedback_validation as f
from sim.llm.usage import UsageBudget


class Client:
    last_usage = None
    last_response_metadata = {}
    last_error_metadata = {}
    reasoning_effort = 'low'
    send_temperature = True

    def __init__(self, wrong=False):
        self.calls=[];self.wrong=wrong

    def chat(self, messages, **kwargs):
        self.calls.append((messages,kwargs))
        self.last_response_metadata=dict(model='wrong' if self.wrong else f.PROFILE['model'],finish_reason='stop')
        self.last_usage=dict(prompt_tokens=5,completion_tokens=5,total_tokens=10,source='mock')
        return 'Observations: Partial fills occurred. Beliefs: uncertain. Plan: hold.'


class FeedbackValidationTests(unittest.TestCase):
    @contextlib.contextmanager
    def prepared(self):
        parent=f.BASE/'.tmp';parent.mkdir(exist_ok=True)
        root=parent/('feedback_validation_'+uuid.uuid4().hex)
        try:
            with contextlib.redirect_stdout(io.StringIO()):f.prepare(root)
            yield root
        finally:
            assert root.resolve().parent==parent.resolve() and root.name.startswith('feedback_validation_')
            if root.exists():shutil.rmtree(root)

    def test_all_twelve_actual_histories_without_response_selection(self):
        cases,_=f.definitions()
        self.assertEqual(len(cases),12)
        for case in cases.values():
            self.assertEqual(len(case['original_memory']),5)
            for old,new,d in zip(case['original_memory'],case['timed_memory'],case['decision_times']):
                self.assertEqual(old['price'],new['clearing_price_after_decision'])
                self.assertEqual(old['fills'],new['fills'])
                self.assertEqual(old['requested_order']['reasoning'],new['recorded_decision_explanation']['text'])
                self.assertEqual(new['decision_time'],d)
        c=cases['s23971_source2_llm_012']
        self.assertEqual(c['decision_times'][-1]['last_observed_price'],103.3)
        self.assertEqual(c['timed_memory'][-1]['clearing_price_after_decision'],104.)

    def test_all_48_independent_mock_calls_preserve_messages_settings_and_schedule(self):
        with self.prepared() as root:
            client=Client();budget=UsageBudget(max_requests=80,max_reserved_tokens=1600000,stop_on_api_error=True)
            with contextlib.redirect_stdout(io.StringIO()):s=f.execute(root,client=client,budget=budget)
            self.assertEqual((s['status'],s['delivered']),('completed',48))
            cases=f.read(root/'cases.json');schedule=f.read(root/'protocol.json')['schedule']
            for item,(messages,settings) in zip(schedule,client.calls):
                self.assertEqual(messages,cases[item['case']]['messages'][item['format']])
                self.assertEqual(settings,dict(temperature=0.,max_tokens=8192,json_mode=False))
            self.assertEqual(len({(s['case'],s['format'],s['repetition']) for s in schedule}),48)
            with self.assertRaises(FileExistsError):f.execute(root,client=client,budget=budget)
            self.assertEqual(len(client.calls),48)

    def test_wrong_model_stops_after_one_reply_and_preserves_raw_attempt(self):
        with self.prepared() as root:
            c=Client(wrong=True)
            with contextlib.redirect_stdout(io.StringIO()):s=f.execute(root,client=c,budget=UsageBudget())
            self.assertEqual((s['status'],s['delivered'],len(c.calls)),('stopped',0,1))
            self.assertEqual(len(s['missing_slots']),48)
            self.assertIn('Partial fills',(root/'requests.jsonl').read_text())


if __name__=='__main__':unittest.main()
