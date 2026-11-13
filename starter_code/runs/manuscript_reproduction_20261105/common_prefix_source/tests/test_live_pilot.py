"""Offline verification of credential handling, pacing and provider-stop semantics."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

import yaml

from sim.config import ConfigError, parse_config
from sim.engine import run
from sim.llm.client import LLMClient, bharatcode_api_key, gemini_api_key
from sim.llm.usage import RequestPacer, UsageBudget, UsageLimitExceeded
from sim.pilot import market_recipe, probe_cases


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class PacingTests(unittest.TestCase):
    def test_rpm_slots_are_shared_and_evenly_spaced(self):
        clock = Clock()
        pacer = RequestPacer(5, clock=clock, sleep=clock.sleep)
        self.assertEqual(pacer.acquire(100), 0)
        self.assertEqual(pacer.acquire(100), 12)
        self.assertEqual(pacer.acquire(100), 12)

    def test_rolling_input_window_delays_until_enough_tokens_expire(self):
        clock = Clock()
        pacer = RequestPacer(input_tokens_per_minute=1000, clock=clock, sleep=clock.sleep)
        self.assertEqual(pacer.acquire(600), 0)
        clock.now = 10
        self.assertEqual(pacer.acquire(400), 0)
        self.assertEqual(pacer.acquire(601), 60)
        self.assertEqual(clock.now, 70)

    def test_oversized_input_rejected_before_consuming_a_request(self):
        budget = UsageBudget(input_tokens_per_minute=100)
        with self.assertRaises(UsageLimitExceeded):
            budget.reserve([], 20, 0, 0)
        self.assertEqual(budget.requests, 0)
        self.assertEqual(budget.rejections, 1)

    def test_provider_stop_prevents_queued_requests_and_stopped_waiters(self):
        from sim.llm.usage import ProviderUnavailable
        budget = UsageBudget(stop_on_api_error=True)
        budget.reserve([], 20, 0, 0)
        budget.stop_for_provider_error()
        with self.assertRaises(ProviderUnavailable):
            budget.ensure_provider_available()
        with self.assertRaises(ProviderUnavailable):
            budget.reserve([], 20, 0, 0)
        self.assertEqual(budget.requests, 1)

    def test_pacing_configuration_roundtrips_and_rejects_bad_values(self):
        raw = {"agents": [{"type": "zero_intelligence"}], "llm_limits": {
            "requests_per_minute": 5, "input_tokens_per_minute": 15000, "stop_on_api_error": True}}
        cfg = parse_config(raw)
        self.assertEqual(parse_config(cfg.to_dict()), cfg)
        for key, value in [("requests_per_minute", 0), ("input_tokens_per_minute", True),
                           ("stop_on_api_error", "true")]:
            bad = copy.deepcopy(raw)
            bad["llm_limits"][key] = value
            with self.subTest(key=key), self.assertRaises(ConfigError):
                parse_config(bad)


class CredentialTests(unittest.TestCase):
    def test_bharatcode_key_alias_is_local_and_scoped_to_the_official_endpoint(self):
        scratch = Path(__file__).resolve().parents[1] / ".tmp"
        scratch.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as name:
            path = Path(name)/".env"
            path.write_text('GEMINI_API_KEY=google-test\nAPI_KEY="student-test"\n')
            with patch.dict(os.environ, {}, clear=True):
                self.assertEqual(bharatcode_api_key(path), "student-test")
                self.assertNotIn("API_KEY", os.environ)
        with patch.dict(os.environ, {"API_KEY": "student-test", "LLM_API_KEY": "generic-test"}, clear=True):
            official = LLMClient(base_url="https://bharatcode.ai/api/model/v1")
            self.assertEqual(official.api_key, "student-test")
            self.assertEqual(LLMClient(base_url="https://example.invalid").api_key, "generic-test")
            self.assertEqual(LLMClient(base_url="https://bharatcode.ai.evil.invalid/api/model/v1").api_key, "generic-test")
            self.assertEqual(LLMClient(base_url="http://bharatcode.ai/api/model/v1").api_key, "generic-test")
            self.assertEqual(LLMClient(base_url="https://bharatcode.ai/other").api_key, "generic-test")
            self.assertEqual(LLMClient(base_url="https://bharatcode.ai/api/model/v1", api_key="explicit-test").api_key, "explicit-test")

    def test_bharatcode_request_ids_are_retained_without_auth_headers(self):
        payload = {"choices": [{"finish_reason": "stop", "message": {"content": "{}"}}]}
        response = io.BytesIO(json.dumps(payload).encode())
        response.headers = {"x-request-id": "req-test-123"}
        client = LLMClient(api_key="test-secret")
        with patch("urllib.request.urlopen", return_value=response):
            client.chat([])
        self.assertEqual(client.last_response_metadata["request_id"], "req-test-123")
        self.assertNotIn("test-secret", json.dumps(client.last_response_metadata))

    def test_provider_default_sampling_omits_temperature_for_decisions_and_reflections(self):
        payload = {"choices": [{"message": {"content": "{}"}}]}
        client = LLMClient(api_key="test-value", send_temperature=False)
        for temperature in (0.0, 0.3, 1.0):
            with patch("urllib.request.urlopen", return_value=io.BytesIO(json.dumps(payload).encode())) as request:
                client.chat([], temperature=temperature)
            self.assertNotIn("temperature", json.loads(request.call_args.args[0].data))

    def test_reasoning_setting_is_sent_and_provider_thinking_usage_is_retained(self):
        payload = {"model": "actual-test-model", "usage": {
            "prompt_tokens": 20, "completion_tokens": 40, "total_tokens": 60,
            "completion_tokens_details": {"reasoning_tokens": 25}},
            "choices": [{"finish_reason": "stop", "message": {"content": "{}"}}]}
        client = LLMClient(api_key="test-value", reasoning_effort="low")
        with patch("urllib.request.urlopen", return_value=io.BytesIO(json.dumps(payload).encode())) as request:
            client.chat([], max_tokens=2048)
        sent = json.loads(request.call_args.args[0].data)
        self.assertEqual(sent["reasoning_effort"], "low")
        self.assertEqual(sent["max_tokens"], 2048)
        self.assertEqual(client.last_usage["reasoning_tokens"], 25)
        self.assertEqual(client.last_response_metadata["finish_reason"], "stop")

    def test_dotenv_is_read_as_data_only_and_environment_wins(self):
        scratch = Path(__file__).resolve().parents[1] / ".tmp"
        scratch.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as name:
            path = Path(name) / ".env"
            path.write_text('UNRELATED=leave-alone\nexport GEMINI_API_KEY="test-value" # comment\n')
            with patch.dict(os.environ, {}, clear=True):
                self.assertEqual(gemini_api_key(path), "test-value")
                self.assertNotIn("GEMINI_API_KEY", os.environ)
            with patch.dict(os.environ, {"GEMINI_API_KEY": "env-value"}, clear=True):
                self.assertEqual(gemini_api_key(path), "env-value")
            path.write_text('GEMINI_API_KEY="unterminated\n')
            with patch.dict(os.environ, {}, clear=True), self.assertRaises(ValueError) as error:
                gemini_api_key(path)
            self.assertNotIn("unterminated", str(error.exception))

    def test_gemini_key_is_never_inferred_for_another_host_or_plain_http(self):
        with patch.dict(os.environ, {}, clear=True), patch("sim.llm.client.gemini_api_key", return_value="test-value") as loader:
            for base in ["https://example.invalid", "https://generativelanguage.googleapis.com.evil.invalid",
                         "http://generativelanguage.googleapis.com"]:
                self.assertEqual(LLMClient(base_url=base).api_key, "")
            loader.assert_not_called()
            client = LLMClient(base_url="https://generativelanguage.googleapis.com/v1beta/openai")
            self.assertEqual(client.api_key, "test-value")
            loader.assert_called_once()

    def test_http_quota_metadata_excludes_raw_error_and_secret(self):
        data = {"error": {"status": "RESOURCE_EXHAUSTED", "message": "test-secret must not be logged",
                         "details": [{"@type": "type.googleapis.com/google.rpc.QuotaFailure",
                           "violations": [{"quotaMetric": "generate_content_free_tier_requests",
                                           "quotaValue": "20", "quotaDimensions": {"model": "test-model", "project": "private"}}]},
                          {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "12.5s"}]}}
        error = HTTPError("https://example.invalid", 429, "limited", {}, io.BytesIO(json.dumps(data).encode()))
        client = LLMClient(api_key="test-secret")
        with patch("urllib.request.urlopen", side_effect=error) as request, self.assertRaises(HTTPError):
            client.chat([])
        self.assertEqual(request.call_count, 1)
        self.assertEqual(client.last_error_metadata["retry_delay_seconds"], 12.5)
        self.assertEqual(client.last_error_metadata["quota_violations"][0]["quotaValue"], "20")
        self.assertNotIn("test-secret", json.dumps(client.last_error_metadata))
        self.assertNotIn("private", json.dumps(client.last_error_metadata))


class ProviderStopTests(unittest.TestCase):
    def simulate(self, fail_on_reflection):
        class FailingClient:
            def __init__(self, **kwargs):
                self.total_tokens = 0
                self.last_usage = None
                self.last_response_metadata = {}

            def chat(self, messages, **kwargs):
                if not fail_on_reflection or not kwargs.get("json_mode", True):
                    raise HTTPError("https://example.invalid", 429, "quota", {}, None)
                return '{"action":"hold","quantity":0,"limit_price":null}'

        scratch = Path(__file__).resolve().parents[1] / ".tmp"
        scratch.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as name:
            root = Path(name)
            raw = {"rounds": 3, "llm_limits": {"stop_on_api_error": True}, "agents": [
                {"type": "llm", "llm": {"condition": "C" if fail_on_reflection else "A",
                                          "reflect_every": 1 if fail_on_reflection else 0}}]}
            config = root / "config.yaml"
            config.write_text(yaml.safe_dump(raw))
            with patch("sim.engine.MockLLMClient", FailingClient), contextlib.redirect_stdout(io.StringIO()):
                output = Path(run(config, output_root=root))
            summary = json.loads((output / "summary.json").read_text())
            requests = [json.loads(line) for line in (output / "llm_requests.jsonl").read_text().splitlines()]
            self.assertEqual(summary["status"], "provider_error")
            self.assertEqual(summary["rounds"], 1 if fail_on_reflection else 0)
            self.assertEqual(summary["api_failures"], 1)
            self.assertEqual(requests[-1]["http_status"], 429)
            self.assertEqual(requests[-1]["status"], "error")
            manifest = json.loads((output / "manifest.json").read_text())
            self.assertEqual(manifest["status"], "provider_error")

    def test_decision_error_stops_before_partial_clearing(self):
        self.simulate(False)

    def test_reflection_error_preserves_the_fully_paid_round(self):
        self.simulate(True)


class PilotProtocolTests(unittest.TestCase):
    def test_output_cap_does_not_trigger_a_same_cap_repair(self):
        import numpy as np
        from sim.agents.llm_agent import LLMAgent
        from sim.llm.usage import OutputLimitExceeded
        from test_comparable_agents import FixedClient, observation
        for strict in (False, True):
            records = []
            client = FixedClient()
            client.last_response_metadata = {"finish_reason": "length"}
            agent = LLMAgent("a", 10000, 100, np.random.default_rng(1), client=client,
                             budget=UsageBudget(stop_on_api_error=strict), log_fn=records.append)
            if strict:
                with self.assertRaises(OutputLimitExceeded):
                    agent.decide(observation())
            else:
                self.assertEqual(agent.decide(observation()).side, "hold")
                self.assertEqual(records[-1]["failure_type"], "output_truncated")
            self.assertEqual(len(client.calls), 1)
            self.assertEqual(agent.output_truncations, 1)
            self.assertEqual(records[0]["record_type"], "model_call")
            self.assertIsInstance(records[0]["raw"], str)

    def test_old_model_probes_cannot_start_the_new_model_market_batch(self):
        from sim.pilot import markets
        scratch = Path(__file__).resolve().parents[1] / ".tmp"
        scratch.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as name:
            path = Path(name)
            (path/"summary.json").write_text(json.dumps({"status": "completed"}))
            (path/"manifest.json").write_text(json.dumps({"models": [{"configured_model": "gemini-3.5-flash-lite"}]}))
            with self.assertRaisesRegex(ValueError, "do not mix model batches"):
                markets(path)
            self.assertFalse((path/"market_schedule.json").exists())

    def test_reasoning_configuration_is_validated_and_preserved(self):
        raw = market_recipe("A", 704).to_dict()
        self.assertEqual(parse_config(raw).agents[-1].llm.reasoning_effort, "low")
        raw["agents"][-1]["llm"]["reasoning_effort"] = "unlimited"
        with self.assertRaises(ConfigError):
            parse_config(raw)

    def test_truncated_reflection_does_not_replace_prior_memory(self):
        import numpy as np
        from sim.agents.llm_agent import LLMAgent
        from test_comparable_agents import FixedClient, observation
        client = FixedClient()
        client.last_response_metadata = {"finish_reason": "length"}
        agent = LLMAgent("a", 10000, 100, np.random.default_rng(1),
                          params={"condition": "C", "reflect_every": 2}, client=client)
        agent.diary = "previous complete reflection"
        agent.reflect_if_due(observation(2))
        self.assertEqual(agent.reflection_failures, 1)
        self.assertEqual(agent.diary, "previous complete reflection")

    def test_market_comparison_changes_only_the_assistance_condition(self):
        recipes = [market_recipe(c, 704).to_dict() for c in "ABC"]
        for raw in recipes:
            raw.pop("name")
            raw["agents"][-1]["llm"].pop("condition")
            raw["agents"][-1]["llm"].pop("reflect_every")
        self.assertEqual(recipes[0], recipes[1])
        self.assertEqual(recipes[1], recipes[2])

    def test_risk_probe_is_one_trait_and_has_independent_repetition_labels(self):
        cases = [c for c in probe_cases() if c["family"] == "risk_trait"]
        self.assertEqual(len(cases), 4)
        for repetition in (1, 2):
            pair = [copy.deepcopy(c) for c in cases if c["repetition"] == repetition]
            self.assertEqual({c["persona"].pop("risk_tolerance") for c in pair}, {"low", "high"})
            for item in pair:
                item.pop("variant")
            self.assertEqual(pair[0], pair[1])


if __name__ == "__main__":
    unittest.main()
