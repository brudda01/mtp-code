"""Offline R038 checks for distinct contexts, scoring and failure preservation."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from sim.llm.usage import UsageBudget
from runs import semantic_check_20261104 as d


class Client:
    reasoning_effort = "low"
    send_temperature = True
    def __init__(self, fail=False, wrong=False):
        self.calls = 0; self.fail = fail; self.wrong = wrong; self.last_usage = None
        self.last_response_metadata = {}; self.last_error_metadata = {}
    def chat(self, messages, **kwargs):
        self.calls += 1
        if self.fail:
            raise RuntimeError("offline injected failure")
        user = messages[1]["content"]; clarified = "one-time 20%" in user
        factor = 1.2 if ("20% increase" in user or "20% rise" in user) else .8
        values = {key:.02*factor**(1 if clarified else n) for key,n in zip(d.FIELDS,(1,5,10))}
        if self.wrong and clarified:
            values[d.FIELDS[1]] = .01
        self.last_usage = dict(prompt_tokens=10,completion_tokens=10,total_tokens=20,source="provider")
        self.last_response_metadata = dict(model="qwen-3.8-27b",finish_reason="stop")
        return json.dumps({**values,"reasoning":"Offline fixture; not behavioural evidence."})


class Checks(unittest.TestCase):
    def setUp(self):
        scratch=d.BASE/".tmp";scratch.mkdir(exist_ok=True)
        temp=tempfile.TemporaryDirectory(dir=scratch);self.addCleanup(temp.cleanup)
        with contextlib.redirect_stdout(io.StringIO()):self.root=d.prepare(Path(temp.name))
    def execute(self,client):
        with contextlib.redirect_stdout(io.StringIO()):
            return d.execute(self.root,client=client,budget=UsageBudget(max_requests=40,max_reserved_tokens=700000,stop_on_api_error=True))
    def test_exact_dedup_and_only_headline_changes(self):
        cases=d.read(self.root/"cases.json");self.assertEqual(len(cases),4)
        self.assertEqual(len(d.read(self.root/"protocol.json")["schedule"]),24)
        for case in cases.values():
            self.assertEqual(len(case["origins"]),2)
            a,b=case["messages"]["original"],case["messages"]["clarified"]
            self.assertEqual(a[0],b[0]);self.assertNotIn("Decide your order",a[1]["content"])
            old=d.HEADLINE if case["direction"]=="up" else d.HEADLINE.replace("20% rise","20% fall")
            self.assertEqual(a[1]["content"].replace(old,d.headline(case["direction"])),b[1]["content"])
    def test_numeric_classification_retains_other_and_invalid(self):
        self.assertEqual(d.classify(json.dumps({k:.024 for k in d.FIELDS}),"up")["interpretation"],"level")
        self.assertEqual(d.classify(json.dumps({k:.02*.8**n for k,n in zip(d.FIELDS,(1,5,10))}),"down")["interpretation"],"repeated_growth")
        self.assertEqual(d.classify(json.dumps({k:.03 for k in d.FIELDS}),"down")["interpretation"],"other_numeric_path")
        self.assertFalse(d.classify('{"expected_dividend_session_1":NaN}',"up")["valid"])
    def test_complete_fake_reading_and_fixed_schedule(self):
        client=Client();s=self.execute(client)
        self.assertEqual((client.calls,s["completed"],s["clarified_level_fields"],s["clarified_gate"]),(24,24,36,True))
        self.assertEqual(sum(r["interpretation"]=="repeated_growth" for r in d.read(self.root/"results.json")),12)
    def test_wrong_finite_answers_not_resampled(self):
        client=Client(wrong=True);s=self.execute(client)
        self.assertEqual((client.calls,s["completed"],s["status"]),(24,24,"completed"));self.assertFalse(s["clarified_gate"])
    def test_failure_stops_and_duplicate_or_drift_cannot_restart(self):
        client=Client(fail=True);s=self.execute(client)
        self.assertEqual((client.calls,s["completed"],s["status"]),(1,0,"stopped"))
        self.assertEqual(s["usage"]["unknown_usage_requests"],1)
        with self.assertRaises(FileExistsError):self.execute(Client())
        path=self.root/"cases.json";path.write_text(path.read_text()+"\n")
        with self.assertRaises(AssertionError):d.validate(self.root)


if __name__=="__main__":unittest.main()
