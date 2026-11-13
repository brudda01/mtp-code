import copy
from datetime import datetime, timezone
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
import numpy as np
from research.goedel_backoff_exp import ExpBackoffAgent, parse_retry_after, MAX_429_RETRIES
from sim.agents.base import Observation
from sim.llm.usage import UsageBudget, UsageLimitExceeded, ProviderUnavailable

HOLD = '{"action":"hold","quantity":0,"limit_price":null}'


class Client:
    send_temperature = True
    def __init__(self, values):
        self.values = iter(values)
        self.calls = []
        self.last_usage = None
        self.last_response_metadata = {}
        self.last_error_metadata = {}

    def chat(self, messages, **kwargs):
        self.calls.append((copy.deepcopy(messages), dict(kwargs)))
        x = next(self.values)
        if isinstance(x, Exception): raise x
        return x


def error(code=429, header='2.0'):
    return HTTPError('https://example.invalid', code, 'test', {'Retry-After': header}, None)


class ExpBackoffTests(unittest.TestCase):
    def agent(self, values, budget=None):
        log = []
        client = Client(values)
        a = ExpBackoffAgent('llm_008', 10000, 100, np.random.default_rng(0),
                            params={'condition': 'B', 'transport_retries': 1, 'retry_http_503': True, 'max_tokens': 2048},
                            client=client, budget=budget or UsageBudget(stop_on_api_error=True), log_fn=log.append)
        obs = Observation(1, 25, [100], 0, .02, .0002, None, [], [], 10000, 100, 100, 20000, [])
        return a, client, log, obs

    def test_decimal_date_and_invalid_headers(self):
        self.assertEqual(parse_retry_after({'Retry-After': '2.0'})['retry_after_seconds'], 2)
        self.assertEqual(parse_retry_after({'Retry-After': 'Mon, 09 Nov 2026 00:00:03 GMT'},
                                           datetime(2026, 11, 9, tzinfo=timezone.utc))['retry_after_seconds'], 3)
        for x in ('nan', '-2', 'inf', 'bad'):
            self.assertFalse(parse_retry_after({'Retry-After': x})['retry_after_valid'])

    def test_exponential_progression_delays(self):
        # 6 consecutive errors then success
        a, c, log, obs = self.agent([error()] * 6 + [HOLD])
        with patch('research.goedel_backoff_exp.time.sleep') as sleep:
            self.assertEqual(a.decide(obs).side, 'hold')
        waits = [x.args[0] for x in sleep.call_args_list]
        self.assertEqual(len(waits), 6)
        # Verify monotonically non-decreasing waits:
        for i in range(len(waits) - 1):
            self.assertGreaterEqual(waits[i + 1], waits[i])
        # First wait is at least 5.0s (2.0 + 3.0)
        self.assertEqual(waits[0], 5.0)
        self.assertEqual(waits[1], 5.0)
        self.assertAlmostEqual(waits[2], 6.75)
        self.assertAlmostEqual(waits[3], 10.125)
        self.assertAlmostEqual(waits[4], 15.1875)
        self.assertAlmostEqual(waits[5], 22.78125)

    def test_max_retries_ceiling(self):
        self.assertEqual(MAX_429_RETRIES, 25)
        a, c, log, obs = self.agent([error()] * (MAX_429_RETRIES + 1))
        with patch('research.goedel_backoff_exp.time.sleep'), self.assertRaises(ProviderUnavailable):
            a.decide(obs)
        self.assertEqual(len(c.calls), MAX_429_RETRIES + 1)


if __name__ == '__main__':
    unittest.main()
