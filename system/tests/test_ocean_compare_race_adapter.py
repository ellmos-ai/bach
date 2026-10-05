"""Compare-Race wiring exercises fake SDK data only; no provider subprocess."""
import asyncio
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from starlette.requests import Request

from gui.api import compare_race_adapter as adapter
from gui.api import unified_api


def fake_state():
    return {
        "availability": "ready", "blockers": [],
        "models": [
            {"id": "fixture-a", "backend": "claude", "runtime": "cli_detected"},
            {"id": "fixture-b", "backend": "codex", "runtime": "cli_detected"},
        ],
        "budget": {"max_lanes": 2, "max_seconds": 30},
    }


def request():
    return Request({"type": "http", "method": "POST", "path": "/api/chat/compare-race",
                    "headers": [], "query_string": b""})


class CompareRaceAdapterTest(unittest.TestCase):
    def test_missing_spend_authority_blocks_readiness(self):
        with patch.object(adapter, "_sdk_settings", return_value=None), \
                patch.object(adapter, "_config_path", return_value=None), \
                patch.object(adapter, "_budget", return_value=(2, 30)):
            state = adapter.readiness()
        self.assertEqual(state["availability"], "unavailable")
        self.assertIn("spend_authority_unavailable", state["blockers"])
        self.assertEqual(state["provider_auth"], "not_checked")

    def test_request_rejects_unconfigured_and_unconfirmed_lanes(self):
        payload = {"prompt": "fixture", "models": ["fixture-a", "fixture-b"]}
        with patch.object(adapter, "_budget", return_value=(2, 30)):
            with self.assertRaises(adapter.RaceUnavailable):
                adapter._validate_request(payload, fake_state())
            payload["confirm_cost"] = True
            adapter._validate_request(payload, fake_state())
            payload["models"] = ["fixture-a", "unknown"]
            with self.assertRaises(adapter.RaceUnavailable):
                adapter._validate_request(payload, fake_state())

    def test_mock_sdk_keeps_non_live_evidence_out_of_answer(self):
        kinds = ["live", "manual", "simulated", "blocked", "failed"]
        results = [SimpleNamespace(identity=SimpleNamespace(model=f"fixture-{kind}"),
                                   backend="claude", evidence_kind=kind, ok=True,
                                   output="fixture response", latency_s=0.25)
                   for kind in kinds]
        calls = []

        def fake_run(prompt, settings, **kwargs):
            calls.append((prompt, kwargs))
            return SimpleNamespace(results=results)

        settings = SimpleNamespace(timeout_seconds=60)
        race = SimpleNamespace(run_race=fake_run, EVIDENCE_KINDS=set(kinds))
        payload = {"prompt": "fixture", "models": ["fixture-a", "fixture-b"], "confirm_cost": True}
        with patch.object(adapter, "readiness", return_value=fake_state()), \
                patch.object(adapter, "_budget", return_value=(2, 30)), \
                patch.object(adapter, "_sdk_settings", return_value=(settings, race)):
            data = adapter._worker_result(payload)
        self.assertEqual(calls, [("fixture", {"models": payload["models"], "mode": "sequential", "repeats": 1})])
        self.assertEqual(settings.timeout_seconds, 30)
        self.assertIsNone(data["winner"])
        self.assertEqual([bool(item["response"]) for item in data["candidates"]],
                         [True, False, False, False, False])
        self.assertEqual(data["evidence"], "partial")

    def test_route_requires_device_before_worker(self):
        with patch.object(unified_api, "_require_memory_device",
                          side_effect=HTTPException(status_code=401, detail="fixture")), \
                patch.object(adapter, "execute_isolated", side_effect=AssertionError("spawned")):
            with self.assertRaises(HTTPException) as result:
                asyncio.run(unified_api.compare_race(request(), {"prompt": "fixture"}))
        self.assertEqual(result.exception.status_code, 401)
        with patch.object(unified_api, "_require_memory_device",
                          side_effect=HTTPException(status_code=401, detail="fixture")), \
                patch.object(adapter, "readiness", side_effect=AssertionError("registry read")):
            with self.assertRaises(HTTPException) as status:
                asyncio.run(unified_api.compare_race_status(request()))
        self.assertEqual(status.exception.status_code, 401)

    def test_reservation_failure_prevents_subprocess(self):
        @contextmanager
        def deny(**_kwargs):
            raise RuntimeError("fixture denied")
            yield

        payload = {"prompt": "fixture", "models": ["fixture-a", "fixture-b"], "confirm_cost": True}
        authority = SimpleNamespace(reserve=deny)
        with patch.object(adapter, "readiness", return_value=fake_state()), \
                patch.object(adapter, "_budget", return_value=(2, 30)), \
                patch.object(adapter, "_spend_authority", return_value=authority), \
                patch.object(adapter.subprocess, "run", side_effect=AssertionError("spawned")):
            with self.assertRaises(adapter.RaceUnavailable) as result:
                adapter.execute_isolated(payload, 7)
        self.assertEqual(result.exception.code, "spend_authority_unavailable")


if __name__ == "__main__":
    unittest.main()
