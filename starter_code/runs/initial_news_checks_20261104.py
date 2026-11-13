"""R036 offline initial information, exact controls, histories and failure bounds."""
import contextlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
BASE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(BASE/"tests"))
from test_news_components import ScriptedClient,NoDelay
from runs import initial_news_20261104 as d

class InitialNewsChecks(unittest.TestCase):
    def setUp(self):
        scratch=BASE/".tmp";scratch.mkdir(exist_ok=True);temp=tempfile.TemporaryDirectory(dir=scratch);self.addCleanup(temp.cleanup);self.out=Path(temp.name)
        ScriptedClient.calls=0;ScriptedClient.fail_on=None;ScriptedClient.empty_reflection=ScriptedClient.malformed=False
        with contextlib.redirect_stdout(io.StringIO()):self.root=d.prepare(self.out);d.baselines(self.root)
    def offline(self):
        with patch("sim.engine.LLMClient",ScriptedClient),patch.object(d,"RequestPacer",NoDelay),contextlib.redirect_stdout(io.StringIO()):d.execute(self.root)
        self.assertIs(d.engine.LLMAgent,__import__('sim.agents.llm_agent',fromlist=['LLMAgent']).LLMAgent);return d.read(self.root/"summary.json")
    def test_all240_fake_calls_bothblocks_controls_and_true_history(self):
        s=self.offline();self.assertEqual((s["status"],s["completed_markets"],s["completed_blocks"],ScriptedClient.calls),("completed",10,2,240))
        refs=d.read(self.root/"baseline_runs.json");self.assertEqual(len(refs),10);d.baseline_gates(self.root,refs)
        index=d.read(self.root/"runs.json");self.assertEqual([(e["seed"],e["cell"]) for e in index],[(seed,c) for seed in d.SEEDS for c in d.ORDERS[seed]])
        for seed in d.SEEDS:d.first_input_gates(self.root,index,seed)
        for e in index:
            path=self.root/e["run_path"];d.verify_market(path);outcomes=d.lines(path/"agent_outcomes.jsonl")
            calls=[r for r in d.lines(path/"llm_requests.jsonl") if r["record_type"]=="model_call"]
            self.assertEqual(len(calls),24)
            for call in calls:
                self.assertEqual(call["prompt_version"],d.VERSION);self.assertEqual(call["base_prompt_version"],"simple_A_v2")
                user=call["messages"][1]["content"];self.assertTrue(user.startswith(f"Round {call['round']}."))
                self.assertEqual("Initialization references:" in user,call["round"]==1)
                if call["round"]==1:self.assertNotIn("dividend paid",user)
                memory=__import__('json').loads(user.split("Your recent verified outcomes: ",1)[1].split("\nDecide your order",1)[0]);expected=[r["outcome"] for r in outcomes if r["agent_id"]==call["agent_id"] and r["outcome"]["round"]<call["round"]][-5:]
                self.assertEqual(memory,expected)
        d.validate(self.root)
    def test_source_error_stops_campaign_without_next_condition(self):
        ScriptedClient.fail_on=1;s=self.offline();self.assertEqual((s["status"],s["recorded_markets"],s["completed_markets"]),("stopped",1,0));self.assertEqual(ScriptedClient.calls,1)
    def test_secondmarket_error_preserves_complete_quiet_and_partial(self):
        ScriptedClient.fail_on=27;s=self.offline();self.assertEqual((s["status"],s["recorded_markets"],s["completed_markets"]),("stopped",2,1))
        index=d.read(self.root/"runs.json");self.assertEqual([e["rounds"] for e in index],[12,1]);self.assertEqual(index[1]["cell"],"up_silent");self.assertEqual(ScriptedClient.calls,27)
    def test_drift_or_duplicate_blocks_before_generation(self):
        p=self.root/d.read(self.root/"protocol.json")["blocks"][0]["arms"][0]["config"];raw=p.read_text();p.write_text(raw+"\n# drift\n")
        with self.assertRaisesRegex(ValueError,"drift"):self.offline()
        self.assertEqual(ScriptedClient.calls,0);p.write_text(raw);self.offline()
        with self.assertRaisesRegex(ValueError,"already started"):d.execute(self.root)

if __name__=="__main__":unittest.main()
