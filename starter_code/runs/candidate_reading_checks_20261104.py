"""R040 offline tests for transparent extraction and independent missing slots."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from sim.llm.usage import UsageBudget
from runs.semantic_checks_20261104 import Client
from runs import candidate_reading_20261104 as d


class Strings(Client):
    def chat(self,messages,**kwargs):
        value=json.loads(super().chat(messages,**kwargs))
        return json.dumps({k:str(v) if k in d.FIELDS else v for k,v in value.items()})


class InvalidFirst(Client):
    def chat(self,messages,**kwargs):
        raw=super().chat(messages,**kwargs)
        return "{}" if self.calls==1 else raw


class Checks(unittest.TestCase):
    def setUp(self):
        scratch=d.BASE/".tmp";scratch.mkdir(exist_ok=True);temp=tempfile.TemporaryDirectory(dir=scratch);self.addCleanup(temp.cleanup)
        with contextlib.redirect_stdout(io.StringIO()):self.root=d.prepare(Path(temp.name))
    def execute(self,client):
        with contextlib.redirect_stdout(io.StringIO()):return d.execute(self.root,client=client,budget=UsageBudget(max_requests=20,max_reserved_tokens=350000,stop_on_api_error=True))
    def test_exact_user_context_and_new_response_requirements(self):
        old=d.read(d.PARENT/"cases.json");new=d.read(self.root/"cases.json")
        self.assertEqual(len(new),4)
        for key,case in new.items():
            self.assertEqual(case["messages"][1],old[key]["messages"]["clarified"][1])
            self.assertNotIn("<number>",case["messages"][0]["content"])
            self.assertIn("without quotation marks",case["messages"][0]["content"])
    def test_numeric_strings_transparent_not_expressions_or_booleans(self):
        raw=json.dumps({k:"0.024" for k in d.FIELDS});r=d.classify(raw,"up")
        self.assertTrue(all(r["matches_level"]));self.assertFalse(r["strict_json_numbers"]);self.assertEqual(r["extracted_string_fields"],list(d.FIELDS))
        for invalid in (True,".024","0.02*1.2","0.024 currency","NaN",None):
            self.assertFalse(d.classify(json.dumps({k:invalid for k in d.FIELDS}),"up")["valid_numeric_reading"])
    def test_complete_reading_gate_separates_string_formats(self):
        client=Strings();s=self.execute(client)
        self.assertEqual((client.calls,s["delivered"],s["level_fields"],s["strict_number_replies"]),(12,12,36,0));self.assertTrue(s["gate_passed"])
    def test_invalid_independent_slot_preserved_without_retry(self):
        client=InvalidFirst();s=self.execute(client)
        self.assertEqual((client.calls,s["delivered"],s["valid_numeric_readings"],s["status"]),(12,12,11,"completed"));self.assertFalse(s["gate_passed"])
    def test_provider_stop_no_zero_imputation_or_duplicate(self):
        client=Client(fail=True);s=self.execute(client)
        self.assertEqual((client.calls,s["delivered"],s["status"]),(1,0,"stopped"));self.assertFalse(s["gate_passed"])
        with self.assertRaises(FileExistsError):self.execute(Client())
        path=self.root/"cases.json";path.write_text(path.read_text()+"\n")
        with self.assertRaises(AssertionError):d.validate(self.root)


if __name__=="__main__":unittest.main()
