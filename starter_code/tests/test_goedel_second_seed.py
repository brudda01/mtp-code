"""Offline checks only; mocks are never behavioral evidence."""
import contextlib
import io
import unittest
from pathlib import Path
from unittest.mock import patch
import yaml
from research import goedel_second_seed as s
from research import goedel_cohort as g
from tests.test_final_extensions import FakeClient, mock_space


class SecondSeedTests(unittest.TestCase):
    def test_only_seed_and_name_change(self):
        old = yaml.safe_load((s.DONOR / 'config.yaml').read_text())
        new = s.recipe()
        self.assertEqual(new['seed'], 31991)
        self.assertEqual({k for k in old if old[k] != new[k]}, {'seed', 'name'})
        self.assertEqual(new['rounds'] * new['agents'][-1]['count'], 150)

    def test_freeze_blocks_before_preparation_or_provider_access(self):
        with mock_space() as root:
            marker = root / 'freeze.json'
            marker.write_text('{}')
            with patch.object(s, 'FREEZE_MARKER', marker), patch.object(g, 'execute') as worker:
                with self.assertRaisesRegex(RuntimeError, 'permanently frozen'):
                    s.execute(root)
                with self.assertRaisesRegex(RuntimeError, 'permanently frozen'):
                    s.prepare(root / 'must_not_exist')
                worker.assert_not_called()
                self.assertFalse((root / 'must_not_exist').exists())

    def test_seed2_full_mock_preserves_accounts_and_personas(self):
        with mock_space() as root:
            config = root / 'config.yaml'
            config.write_text(yaml.safe_dump(s.recipe()))
            with patch.object(g.engine, 'LLMClient', FakeClient), patch.object(g.engine, 'LLMAgent', g.CappedAgent), g.strict_accounting(g.CappedAgent), patch('sim.llm.usage.RequestPacer.acquire', return_value=0), contextlib.redirect_stdout(io.StringIO()):
                run = Path(g.engine.run(config, output_root=root / 'mock_only'))
            summary = g.read(run / 'summary.json')
            self.assertEqual(summary['status'], 'completed')
            self.assertEqual(summary['llm_usage']['requests_made'], 150)
            self.assertEqual(g.audit_financial(run)['account_rounds'], 350)
            old = s.DONOR / g.read(s.DONOR / 'summary.json')['run_path']
            self.assertEqual(g.read(run / 'personas.json'), g.read(old / 'personas.json'))
            self.assertEqual(g.rows(run / 'initial_state.csv'), g.rows(old / 'initial_state.csv'))


if __name__ == '__main__':
    unittest.main()
