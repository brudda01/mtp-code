"""R041 offline gate, schedule, matching and failure-preservation checks."""
import contextlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from sim.llm.usage import UsageBudget
from sim.agents.llm_agent import LLMAgent
from runs import candidate_reading_20261104 as reading
from runs.semantic_checks_20261104 import Client
from runs import downside_confirmation_20261104 as d

sys.path.insert(0,str(d.BASE/"tests"))
from test_news_components import ScriptedClient,NoDelay


class Checks(unittest.TestCase):
    def setUp(self):
        scratch=d.BASE/".tmp";scratch.mkdir(exist_ok=True);temp=tempfile.TemporaryDirectory(dir=scratch);self.addCleanup(temp.cleanup);self.out=Path(temp.name)
        with contextlib.redirect_stdout(io.StringIO()):
            gate=reading.prepare(self.out/"reading")
            reading.execute(gate,client=Client(),budget=UsageBudget(max_requests=20,max_reserved_tokens=350000,stop_on_api_error=True))
            self.root=d.prepare(self.out/"markets",gate_root=gate)
        ScriptedClient.calls=0;ScriptedClient.fail_on=None;ScriptedClient.empty_reflection=ScriptedClient.malformed=False
    def execute(self):
        with patch("sim.engine.LLMClient",ScriptedClient),patch.object(d,"RequestPacer",NoDelay),contextlib.redirect_stdout(io.StringIO()):result=d.execute(self.root)
        self.assertIs(d.base.engine.LLMAgent,LLMAgent);return result
    def test_full256_fake_calls_and_matching_initial_inputs(self):
        s=self.execute();self.assertEqual((s["status"],s["completed_markets"],s["completed_seed_checks"],ScriptedClient.calls),("completed",16,2,256))
        index=d.read(self.root/"runs.json");self.assertEqual([(x["seed"],x["repetition"],x["background"],x["visible"]) for x in index],[(x["seed"],x["repetition"],x["background"],x["visible"]) for b in d.read(self.root/"protocol.json")["blocks"] for x in b["arms"]])
        for seed in d.SEEDS:d.first_input_gates(self.root,index,seed)
        for e in index:
            path=self.root/e["run_path"];calls=[x for x in d.base.lines(path/"llm_requests.jsonl") if x["record_type"]=="model_call"];outcomes=d.base.lines(path/"agent_outcomes.jsonl")
            for c in calls:
                self.assertEqual(c["prompt_version"],d.VERSION);self.assertEqual(c["base_prompt_version"],"simple_A_v2")
                user=c["messages"][1]["content"]
                actual=[x["outcome"] for x in outcomes if x["agent_id"]==c["agent_id"] and x["outcome"]["round"]<c["round"]][-5:]
                observed=__import__('json').loads(user.split("Your recent verified outcomes: ",1)[1].split("\nDecide your order",1)[0]);self.assertEqual(actual,observed)
    def test_first_provider_failure_stops_entire_campaign(self):
        ScriptedClient.fail_on=1;s=self.execute()
        self.assertEqual((s["status"],s["recorded_markets"],s["completed_markets"],ScriptedClient.calls),("stopped",1,0,1))
    def test_later_failure_retains_full_pairs_and_partial(self):
        ScriptedClient.fail_on=35;s=self.execute();self.assertEqual((s["completed_markets"],s["recorded_markets"],ScriptedClient.calls),(2,3,35))
        self.assertEqual([x["rounds"] for x in d.read(self.root/"runs.json")],[8,8,1])
    def test_unpassed_reading_gate_cannot_start_market(self):
        receipt=self.root/"reading_gate";gate=d.read(receipt/"gate.json");gate["passed"]=False;__import__('sim.provenance',fromlist=['write_json']).write_json(receipt/"gate.json",gate)
        with self.assertRaises(AssertionError):self.execute()
        self.assertEqual(ScriptedClient.calls,0)
    def test_config_drift_and_duplicate_block_before_calls(self):
        p=d.read(self.root/"protocol.json");path=self.root/p["blocks"][0]["arms"][0]["config"];raw=path.read_text();path.write_text(raw+"\n# drift\n")
        with self.assertRaises(AssertionError):self.execute()
        self.assertEqual(ScriptedClient.calls,0);path.write_text(raw);(self.root/"execution.json").write_text('{}')
        with self.assertRaisesRegex(ValueError,"already started"):self.execute()


if __name__=="__main__":unittest.main()
