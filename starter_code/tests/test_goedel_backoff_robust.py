import copy
from datetime import datetime, timezone
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
import numpy as np
from research.goedel_backoff_robust import RobustBackoffAgent, parse_retry_after, MAX_429_RETRIES, MAX_SERVER_RETRIES
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


class RobustBackoffTests(unittest.TestCase):
    def agent(self, values, budget=None):
        log = []
        client = Client(values)
        a = RobustBackoffAgent('llm_008', 10000, 100, np.random.default_rng(0),
                               params={'condition': 'B', 'transport_retries': 1, 'retry_http_503': True, 'max_tokens': 2048},
                               client=client, budget=budget or UsageBudget(stop_on_api_error=True), log_fn=log.append)
        obs = Observation(1, 25, [100], 0, .02, .0002, None, [], [], 10000, 100, 100, 20000, [])
        return a, client, log, obs

    def test_502_bad_gateway_retried(self):
        # HTTP 502 should be retried and succeed
        a, c, log, obs = self.agent([error(502), HOLD])
        with patch('research.goedel_backoff_robust.time.sleep') as sleep:
            self.assertEqual(a.decide(obs).side, 'hold')
        self.assertEqual(len(c.calls), 2)
        self.assertEqual(sleep.call_args_list[0].args[0], 5.0)

    def test_504_gateway_timeout_retried(self):
        # HTTP 504 should be retried and succeed
        a, c, log, obs = self.agent([error(504), HOLD])
        with patch('research.goedel_backoff_robust.time.sleep') as sleep:
            self.assertEqual(a.decide(obs).side, 'hold')
        self.assertEqual(len(c.calls), 2)
        self.assertEqual(sleep.call_args_list[0].args[0], 5.0)

    def test_mixed_429_and_502_succeeds(self):
        # 429 then 502 then success
        a, c, log, obs = self.agent([error(429), error(502), HOLD])
        with patch('research.goedel_backoff_robust.time.sleep') as sleep:
            self.assertEqual(a.decide(obs).side, 'hold')
        self.assertEqual(len(c.calls), 3)

    def test_exponential_progression_429(self):
        a, c, log, obs = self.agent([error(429)] * 6 + [HOLD])
        with patch('research.goedel_backoff_robust.time.sleep') as sleep:
            self.assertEqual(a.decide(obs).side, 'hold')
        waits = [x.args[0] for x in sleep.call_args_list]
        self.assertEqual(len(waits), 6)
        self.assertEqual(waits[0], 5.0)
        self.assertEqual(waits[1], 5.0)
        self.assertAlmostEqual(waits[2], 6.75)


if __name__ == '__main__':
    unittest.main()
