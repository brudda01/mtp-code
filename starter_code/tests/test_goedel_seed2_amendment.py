import unittest
from unittest.mock import patch
import yaml
from research import goedel_seed2_transport_amendment as a


class AmendmentTests(unittest.TestCase):
    def test_failed_attempt_charged_to_original_caps(self):
        old = yaml.safe_load((a.FIRST / 'config.yaml').read_text());new = a.config()
        usage = a.g.read(a.FIRST / 'summary.json')['usage']
        self.assertEqual(new['llm_limits']['max_requests'] + usage['requests_made'], 180)
        self.assertEqual(new['llm_limits']['max_reserved_tokens'] + usage['reserved_tokens'], 3000000)
        self.assertEqual({k for k in old if old[k] != new[k]}, {'llm_limits'})
        for key in ('max_requests', 'max_reserved_tokens'):
            new['llm_limits'][key] = old['llm_limits'][key]
        self.assertEqual(old, new)

    def test_freeze_guard_precedes_worker(self):
        with patch.object(a, 'FREEZE_MARKER', a.FIRST / 'summary.json'), patch.object(a.g, 'execute') as worker:
            with self.assertRaisesRegex(RuntimeError, 'permanently frozen'):
                a.execute(a.FIRST)
            worker.assert_not_called()


if __name__ == '__main__':unittest.main()
