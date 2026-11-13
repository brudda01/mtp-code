"""Offline checks of the one untouched-source amendment; no real requests."""
import contextlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
BASE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(BASE/"tests"))
from test_news_components import ScriptedClient,NoDelay
from runs import news_source10729_20261104 as d

class SourceGateChecks(unittest.TestCase):
    def setUp(self):
        scratch=BASE/".tmp";scratch.mkdir(exist_ok=True);temp=tempfile.TemporaryDirectory(dir=scratch);self.addCleanup(temp.cleanup);self.out=Path(temp.name)
        ScriptedClient.calls=0;ScriptedClient.fail_on=None;ScriptedClient.empty_reflection=ScriptedClient.malformed=False
        self.before=d.inventory(d.PARENT)
        with contextlib.redirect_stdout(io.StringIO()):self.root=d.prepare(self.out)
    def offline(self):
        with patch("sim.engine.LLMClient",ScriptedClient),patch.object(d,"LLMClient",ScriptedClient),patch.object(d,"RequestPacer",NoDelay),contextlib.redirect_stdout(io.StringIO()):d.execute(self.root)
        self.assertEqual(d.inventory(d.PARENT),self.before);return d.read(self.root/"summary.json")
    def test48_calls_only10729_source18_original_cases(self):
        s=self.offline();self.assertEqual((s["status"],s["completed_sources"],s["completed_auctions"],ScriptedClient.calls),("completed_phase_schedule",1,18,48))
        self.assertEqual((s["original_study_planned_sources"],s["original_study_planned_auctions"]),(2,36));self.assertTrue(s["missing_source9623"])
        b=d.read(self.root/"battery.json");self.assertEqual([(f["seed"],f["round"]) for f in b["frames"]],[(10729,2),(10729,6)])
        expected=[];names=list(d.parent.NEWS);targets=d.parent.TARGETS
        for rep in (1,2,3):
            for idx in (range(4) if rep!=2 else reversed(range(4))):
                order=names[(idx+rep-1)%3:]+names[:(idx+rep-1)%3]
                for ni,n in enumerate(order):
                    if idx>=2:expected.append((idx,rep,n,list(targets if (idx+rep+ni)%2 else reversed(targets))))
        self.assertEqual([(2 if x["frame_id"].endswith("r2") else 3,x["repetition"],x["headline"],x["agent_order"]) for x in b["schedule"]],expected)
        self.assertEqual(len(d.read(self.root/"queries/choices.json")),36);self.assertEqual(len(d.read(self.root/"queries/auctions.json")),18)
        for e in d.read(self.root/"source_runs.json"):d.parent.verify_market(self.root/e["run_path"])
        d.parent.verify_market(self.root/"queries");d.validate(self.root)
    def test_source_failure_no_query_or_other_seed(self):
        ScriptedClient.fail_on=1;s=self.offline()
        self.assertEqual((s["status"],s["completed_sources"],s["completed_auctions"]),("stopped",0,0));self.assertFalse((self.root/"queries").exists())
        self.assertEqual([e["seed"] for e in d.read(self.root/"source_runs.json")],[10729]);self.assertEqual(s["cumulative_usage"]["requests_made"],s["usage"]["requests_made"]+2)
    def test_query_partner_failure_never_clears_with_hold(self):
        ScriptedClient.fail_on=14;s=self.offline()
        self.assertEqual((s["status"],s["completed_sources"],s["completed_auctions"]),("stopped",1,0))
        self.assertEqual(len(d.read(self.root/"queries/choices.json")),1);self.assertFalse((self.root/"queries/auctions.json").exists())
    def test_drift_and_duplicate_block_before_requests(self):
        p=self.root/"configs/source.yaml";original=p.read_text();p.write_text(original+"\n# drift\n")
        with self.assertRaisesRegex(ValueError,"drift"):self.offline()
        self.assertEqual(ScriptedClient.calls,0);p.write_text(original)
        self.offline()
        with self.assertRaisesRegex(ValueError,"already started"):d.execute(self.root)
        with contextlib.redirect_stdout(io.StringIO()):second=d.prepare(self.out)
        with self.assertRaisesRegex(ValueError,"already attempted"):d.execute(second)

if __name__=="__main__":unittest.main()
