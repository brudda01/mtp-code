"""Run-specific offline integrity checks against sealed real parent artifacts."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE/"tests"))
from test_news_components import ScriptedClient, NoDelay
from runs.component_tail_20261103 import prepare, execute, key
from sim.provenance import sha256, write_json

PARENT=BASE/"runs/20261103_023441_news_components_da6bdf79"
PHASE=BASE/"runs/20261103_172911_components_continue_f62a08f1"


class OneLengthFailure(ScriptedClient):
    def chat(self,*args,**kwargs):
        raw=super().chat(*args,**kwargs)
        if type(self).calls==1:
            self.last_response_metadata["finish_reason"]="length"
            return ""
        return raw


def check(client, expected_status, valid, failed, calls):
    scratch=BASE/".tmp";scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=scratch) as directory:
        assert Path(directory).resolve().is_relative_to(scratch.resolve())
        client.calls=0;client.empty_reflection=False;client.malformed=False
        with contextlib.redirect_stdout(io.StringIO()):
            root=prepare(PARENT,PHASE,directory)
            with patch("runs.component_tail_20261103.LLMClient",client),patch("runs.component_tail_20261103.RequestPacer",NoDelay):execute(root)
        plan=json.loads((root/"plan.json").read_text());summary=json.loads((root/"summary.json").read_text())
        assert summary["status"]==expected_status
        assert summary["cumulative_valid_decisions"]==valid and summary["cumulative_failed_decisions"]==failed
        assert client.calls==calls
        results=json.loads((root/"results.json").read_text())
        prior_keys={key(r) for r in plan["prior_cases"]}
        assert all(key(r) not in prior_keys for r in results)
        assert plan["prior_usage"]["requests_made"]==70
        assert plan["prior_usage"]["reserved_tokens"]==912386
        assert summary["llm_usage"]["max_requests"]==194
        assert summary["llm_usage"]["max_reserved_tokens"]==3087614
        records=[json.loads(s) for s in (root/"llm_requests.jsonl").read_text().splitlines()]
        assert all(r["max_tokens"]==4096 for r in records if r["record_type"]=="model_call")
        if expected_status=="completed_all_scheduled_cases":
            assert summary["cumulative_decisions"]==108 and summary["cumulative_reflections"]==24
            combined=json.loads((root/"combined_results.json").read_text())
            assert len(combined)==len({key(r) for r in combined})==108
            assert all(r["accepted_signed_quantity"] is None for r in combined if not r["valid_choice"])


if __name__=="__main__":
    ScriptedClient.fail_on=None;check(ScriptedClient,"completed_all_scheduled_cases",107,1,69)
    OneLengthFailure.fail_on=None;check(OneLengthFailure,"completed_all_scheduled_cases",106,2,69)
    ScriptedClient.fail_on=1;check(ScriptedClient,"provider_error",50,1,1)
    write_json(BASE/"runs/component_tail_offline_checks_20261103.json",dict(passed=3,live_calls=0,
        driver_sha256=sha256(BASE/"runs/component_tail_20261103.py"),
        checks=["skip all prior cases/keep caps and inherited diary","length failure stays missing and independent tail completes","provider failure still stops"]))
    print("Three offline tail checks passed; no API calls.")
