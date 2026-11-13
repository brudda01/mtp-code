"""Offline end-to-end isolated replay and actual archive path regression."""
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from sim.provenance import write_json,sha256
from runs import common_prefix_20261105 as d
from runs import common_prefix_finish_20261105 as completion
from runs.quiet_components_checks_20261105 import TradingClient,NoDelay


class Checks(unittest.TestCase):
    def setUp(self):
        scratch=d.BASE/'.tmp';scratch.mkdir(exist_ok=True);tmp=tempfile.TemporaryDirectory(dir=scratch);self.addCleanup(tmp.cleanup);self.out=Path(tmp.name)
    def test_full_mock_campaign_replays_from_self_contained_source(self):
        TradingClient.calls=0;TradingClient.fail_on=None;TradingClient.empty_reflection=TradingClient.malformed=False
        with contextlib.redirect_stdout(io.StringIO()):root=d.prepare(self.out)
        with patch('sim.engine.LLMClient',TradingClient),patch.object(d,'RequestPacer',NoDelay),contextlib.redirect_stdout(io.StringIO()):d.execute(root)
        before=TradingClient.calls
        with patch.object(completion,'preserve',return_value={'offline_fixture':True}),contextlib.redirect_stdout(io.StringIO()):
            status=completion.finish(root,self.out/'analysis',append_diary=False)
        self.assertEqual((status['verification']['verified_clean_paths'],status['verification']['network_attempts']),(24,0))
        self.assertEqual(status['verification']['not_replayed'],[])
        self.assertEqual(TradingClient.calls,before)
        replay=d.read(self.out/'analysis/replay_report.json')
        self.assertEqual(sum(len(x['financial_files']) for x in replay['records']),168)
    def test_real_preservation_uses_absolute_paths_and_verifies_archive(self):
        base=self.out/'repo/starter_code';runs=base/'runs';runs.mkdir(parents=True);(base.parent/'thesis').mkdir()
        old=runs/'old.zip'
        with zipfile.ZipFile(old,'x') as z:z.writestr('old.txt','old evidence')
        write_json(base.parent/'thesis/sources.json',{'prior_archives':{'old.zip':sha256(old)}})
        write_json(runs/'examiner_audit_20261105_evidence_manifest.json',{'path':'starter_code/runs/old.zip','sha256':sha256(old)})
        study=runs/'study';analysis=runs/'analysis';study.mkdir();analysis.mkdir()
        write_json(study/'prior_archives.json',{'old.zip':sha256(old)})
        (study/'example.txt').write_text('actual fixture');(analysis/'report.json').write_text('{}')
        with patch.object(d,'BASE',base):receipt=completion.preserve(study.resolve(),analysis.resolve())
        self.assertTrue(receipt['all_member_hashes_verified']);self.assertEqual(receipt['exported_hashes'],3)
        with zipfile.ZipFile(runs/'common_prefix_20261105_evidence.zip') as z:self.assertIsNone(z.testzip())


if __name__=='__main__':unittest.main()
