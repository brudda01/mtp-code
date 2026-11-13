"""R043 local completion cannot resume API work or certify a failed archive."""
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from runs.quiet_components_checks_20261105 import TradingClient, NoDelay
from runs import quiet_components_20261105 as d
from runs import quiet_components_finish_20261105 as completion


class Checks(unittest.TestCase):
    def setUp(self):
        scratch=d.BASE/'.tmp';scratch.mkdir(exist_ok=True)
        temp=tempfile.TemporaryDirectory(dir=scratch);self.addCleanup(temp.cleanup);self.scratch=Path(temp.name)
        TradingClient.calls=0;TradingClient.fail_on=1;TradingClient.empty_reflection=TradingClient.malformed=False
        with patch('sim.engine.LLMClient',TradingClient),patch.object(d,'RequestPacer',NoDelay),contextlib.redirect_stdout(io.StringIO()):
            self.root=d.prepare(self.scratch);d.execute(self.root)
        self.original=d.base.sha256(self.root/'summary.json');self.calls=TradingClient.calls
    def test_stopped_study_is_analyzed_once_without_more_model_calls(self):
        receipt=dict(path='offline-synthetic-receipt',sha256='not-a-live-archive')
        with patch.object(completion,'preserve',return_value=receipt),contextlib.redirect_stdout(io.StringIO()):
            status=completion.finish(self.root,self.scratch/'analysis',append_diary=False)
        self.assertEqual(status['study_status'],'stopped')
        self.assertEqual(TradingClient.calls,self.calls)
        self.assertEqual(d.base.sha256(self.root/'summary.json'),self.original)
        self.assertEqual(status['summary']['recorded_markets'],1)
        self.assertTrue((self.root/'postprocessing_summary.json').exists())
    def test_archive_failure_never_writes_a_successful_completion_receipt(self):
        with patch.object(completion,'preserve',side_effect=RuntimeError('offline archive failure')),contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError,'offline archive failure'):
                completion.finish(self.root,self.scratch/'analysis',append_diary=False)
        self.assertFalse((self.root/'postprocessing_summary.json').exists())
        self.assertEqual(TradingClient.calls,self.calls)
        self.assertEqual(d.base.sha256(self.root/'summary.json'),self.original)


if __name__=='__main__':unittest.main()
