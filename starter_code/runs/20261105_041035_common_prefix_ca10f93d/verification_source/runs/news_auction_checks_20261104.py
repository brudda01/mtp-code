"""Offline R033 source reconstruction, joint settlement and failure gates."""
import contextlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
BASE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(BASE/"tests"))
from test_news_components import ScriptedClient,NoDelay
from runs import news_auctions_20261104 as d

class AuctionChecks(unittest.TestCase):
    def setUp(self):
        scratch=BASE/".tmp";scratch.mkdir(exist_ok=True)
        temp=tempfile.TemporaryDirectory(dir=scratch);self.addCleanup(temp.cleanup);self.out=Path(temp.name)
        ScriptedClient.calls=0;ScriptedClient.fail_on=None;ScriptedClient.empty_reflection=ScriptedClient.malformed=False
        with contextlib.redirect_stdout(io.StringIO()):self.root=d.prepare(self.out)

    def run_offline(self):
        with patch("sim.engine.LLMClient",ScriptedClient),patch.object(d,"LLMClient",ScriptedClient),patch.object(d,"RequestPacer",NoDelay),contextlib.redirect_stdout(io.StringIO()):d.execute(self.root)
        return d.read(self.root/"summary.json")

    def test_all96_calls_source_replay_message_isolation_real_settlement(self):
        s=self.run_offline();self.assertEqual((s["status"],s["completed_sources"],s["completed_auctions"],ScriptedClient.calls),("completed",2,36,96))
        b=d.read(self.root/"battery.json");self.assertEqual([(f["seed"],f["round"]) for f in b["frames"]],[(9623,2),(9623,6),(10729,2),(10729,6)])
        self.assertTrue(all(c["headline_negative_control"] and c["source_auction_exactly_reproduced"] for c in b["rule_controls"]))
        for f in b["frames"]:
            for aid in d.TARGETS:
                silent=f["messages"]["silent"][aid]
                for n in ("positive","negative"):
                    actual=f["messages"][n][aid];self.assertEqual(actual[0],silent[0])
                    self.assertEqual(actual[1]["content"].replace("News today: "+d.NEWS[n]+"\n","",1),silent[1]["content"])
            original={aid:d.parsed_order(next(o for o in f["source_orders"] if o["agent_id"]==aid)) for aid in d.TARGETS}
            replay=d.execute_auction(f,original,1);self.assertEqual((replay["price"],replay["trades"]),(f["source_price"],f["source_trades"]))
        auctions=d.read(self.root/"queries/auctions.json");self.assertEqual(len(auctions),36)
        for a in auctions:
            first=a["settlements"][0]
            for settlement in a["settlements"]:
                self.assertEqual((first["price"],first["trades"],first["targets"]),(settlement["price"],settlement["trades"],settlement["targets"]))
                self.assertLess(abs(settlement["cash_error"]),1e-7)
                self.assertEqual(sum(r["closing_shares"] for r in settlement["accounts"]),1450)
        calls=[r for r in d.lines(self.root/"queries/llm_requests.jsonl") if r["record_type"]=="model_call"]
        self.assertEqual(len(calls),72);self.assertEqual(len({r["study_call_id"] for r in calls}),72)
        frames={f["frame_id"]:f for f in b["frames"]}
        self.assertTrue(all(r["messages"]==frames[r["frame_id"]]["messages"][r["headline"]][r["agent_id"]] for r in calls))
        d.verify_market(self.root/"queries");d.validate(self.root)
        with self.assertRaisesRegex(ValueError,"already started"):d.execute(self.root)

    def test_source_quota_stops_without_substituting_old_frames(self):
        ScriptedClient.fail_on=1;s=self.run_offline()
        self.assertEqual(s["status"],"stopped");self.assertEqual(s["completed_sources"],0);self.assertFalse((self.root/"queries").exists())

    def test_joint_partner_failure_preserves_delivered_order_without_auction(self):
        ScriptedClient.fail_on=26;s=self.run_offline()
        self.assertEqual((s["status"],s["completed_sources"],s["completed_auctions"]),("stopped",2,0))
        q=self.root/"queries";self.assertEqual(len(d.read(q/"choices.json")),1)
        self.assertFalse((q/"auctions.json").exists());self.assertIsNotNone(d.read(q/"summary.json")["incomplete_case"])
        self.assertEqual(ScriptedClient.calls,26);d.verify_market(q)

    def test_drift_blocks_before_source_generation(self):
        e=d.read(self.root/"protocol.json")["configs"][0];p=self.root/e["config"];p.write_text(p.read_text()+"\n# drift\n")
        with self.assertRaisesRegex(ValueError,"config drift"):self.run_offline()
        self.assertEqual(ScriptedClient.calls,0)

if __name__=="__main__":unittest.main()
