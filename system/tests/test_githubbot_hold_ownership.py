# -*- coding: utf-8 -*-
"""githubbot-hold: manuelle HOLD-Markierungen bleiben erhalten (BACH-4126, Befund P2 zu PR 704).

Nur synthetische Labels/Events und ein Fake-API-Objekt: kein Netz, keine echten Kommentare oder Label-Aenderungen.
"""
import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / ".github" / "workflows" / "hold_ownership.py"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "githubbot-hold.yml"

spec = importlib.util.spec_from_file_location("hold_ownership_under_test", SCRIPT)
ho = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ho)

BOT = {"login": "github-actions[bot]", "type": "Bot"}
HUMAN = {"login": "lukisch", "type": "User"}
OTHER_BOT = {"login": "dependabot[bot]", "type": "Bot"}


def ev(kind, actor, label="HOLD", n=1, at=None):
    return {"id": n, "event": kind, "actor": actor, "label": {"name": label}, "created_at": at or f"2026-11-12T00:00:{n:02d}Z"}


# ----------------------------------------------------------------------------- Entscheidung


def test_manual_hold_without_bot_marker_is_kept():
    decision = ho.decide(["HOLD"], [ev("labeled", HUMAN)])
    assert decision["remove"] == []


def test_manual_hold_with_stale_marker_keeps_hold_and_removes_only_the_marker():
    decision = ho.decide(["HOLD", "module-gate-fehler"], [ev("labeled", HUMAN)])
    assert decision["remove"] == ["module-gate-fehler"]


def test_bot_owned_hold_with_marker_is_removed_together_with_the_marker():
    decision = ho.decide(["HOLD", "module-gate-fehler"], [ev("labeled", BOT, n=1), ev("labeled", BOT, "module-gate-fehler", n=2)])
    assert sorted(decision["remove"]) == ["HOLD", "module-gate-fehler"]


def test_hold_set_again_by_a_human_after_the_bot_is_kept():
    events = [ev("labeled", BOT, n=1), ev("unlabeled", BOT, n=2), ev("labeled", HUMAN, n=3)]
    assert ho.decide(["HOLD", "module-gate-fehler"], events)["remove"] == ["module-gate-fehler"]


def test_hold_set_again_by_the_bot_after_a_human_is_bot_owned():
    events = [ev("labeled", HUMAN, n=1), ev("unlabeled", HUMAN, n=2), ev("labeled", BOT, n=3)]
    assert sorted(ho.decide(["HOLD", "module-gate-fehler"], events)["remove"]) == ["HOLD", "module-gate-fehler"]


def test_event_order_follows_timestamp_and_id_not_list_order():
    events = [ev("labeled", HUMAN, n=9, at="2026-11-12T00:00:09Z"), ev("labeled", BOT, n=1, at="2026-11-12T00:00:01Z")]
    assert ho.decide(["HOLD", "module-gate-fehler"], events)["remove"] == ["module-gate-fehler"]


@pytest.mark.parametrize("actor", [OTHER_BOT, {"login": "github-actions[bot]", "type": "User"}, {"login": "github-actions", "type": "Bot"}, {}, None])
def test_other_unknown_or_incomplete_actors_are_not_the_workflow_bot(actor):
    assert ho.decide(["HOLD", "module-gate-fehler"], [ev("labeled", actor)])["remove"] == ["module-gate-fehler"]


def test_no_hold_event_or_last_event_unlabeled_means_unknown_origin():
    assert ho.decide(["HOLD", "module-gate-fehler"], [])["remove"] == ["module-gate-fehler"]
    assert ho.decide(["HOLD", "module-gate-fehler"], [ev("labeled", BOT, n=1), ev("unlabeled", BOT, n=2)])["remove"] == ["module-gate-fehler"]
    assert ho.decide(["HOLD", "module-gate-fehler"], [ev("labeled", BOT, "HOLD-review", n=1)])["remove"] == ["module-gate-fehler"]


def test_label_names_are_compared_case_insensitively_like_github():
    assert sorted(ho.decide(["hold", "Module-Gate-Fehler"], [ev("labeled", BOT, "hold")])["remove"]) == ["Module-Gate-Fehler", "hold"]


def test_marker_without_hold_is_removed_and_no_labels_means_nothing_to_do():
    assert ho.decide(["module-gate-fehler", "bug"], None)["remove"] == ["module-gate-fehler"]
    assert ho.decide(["bug"], None)["remove"] == []


def test_unreadable_data_fails_closed():
    assert ho.decide(None, None)["remove"] == []                                  # Labels unlesbar
    assert ho.decide(["HOLD", "module-gate-fehler"], None)["remove"] == []        # Events unlesbar/unvollstaendig: auch der Marker bleibt


# ----------------------------------------------------------------------------- API-Readback und run()


class FakeApi:
    def __init__(self, labels=(), events=(), fail_events=False, fail_labels=False, delete_status=200):
        self.labels, self.events = list(labels), list(events)
        self.fail_events, self.fail_labels, self.delete_status = fail_events, fail_labels, delete_status
        self.calls = []

    def __call__(self, method, path, token):
        self.calls.append((method, path))
        assert token == "synthetisch"
        base, _, query = path.partition("?")
        if method == "DELETE":
            return self.delete_status, None
        page = int(dict(p.split("=") for p in query.split("&"))["page"])
        data = self.labels if base.endswith("/labels") else self.events
        failing = self.fail_labels if base.endswith("/labels") else self.fail_events
        if failing:
            return 500, None
        if base.endswith("/labels"):
            data = [{"name": n} for n in data]
        return 200, data[(page - 1) * 100:page * 100]


def deletes(api):
    return [c for c in api.calls if c[0] == "DELETE"]


def test_run_removes_only_the_expected_labels_for_a_bot_hold():
    api = FakeApi(["HOLD", "module-gate-fehler"], [ev("labeled", BOT)])
    ho.run(api, "o/r", 7, "synthetisch", log=lambda *_: None)
    assert sorted(c[1] for c in deletes(api)) == ["/repos/o/r/issues/7/labels/HOLD", "/repos/o/r/issues/7/labels/module-gate-fehler"]
    assert {c[0] for c in api.calls} == {"GET", "DELETE"}


def test_run_with_manual_hold_deletes_only_the_marker():
    api = FakeApi(["HOLD", "module-gate-fehler"], [ev("labeled", HUMAN)])
    ho.run(api, "o/r", 7, "synthetisch", log=lambda *_: None)
    assert [c[1] for c in deletes(api)] == ["/repos/o/r/issues/7/labels/module-gate-fehler"]


def test_run_fails_closed_when_events_cannot_be_read_or_labels_are_unreadable():
    for api in (FakeApi(["HOLD", "module-gate-fehler"], [ev("labeled", BOT)], fail_events=True), FakeApi(["HOLD"], fail_labels=True)):
        ho.run(api, "o/r", 7, "synthetisch", log=lambda *_: None)
        assert deletes(api) == []


def test_events_are_read_completely_across_pages_and_the_last_event_decides():
    filler = [ev("labeled", HUMAN, "bug", n=i, at=f"2026-11-11T00:00:{i % 60:02d}Z") for i in range(1, 251)]
    events = filler + [ev("labeled", BOT, n=1000, at="2026-11-12T00:00:00Z")]
    api = FakeApi(["HOLD", "module-gate-fehler"], events)
    ho.run(api, "o/r", 7, "synthetisch", log=lambda *_: None)
    event_pages = [c for c in api.calls if "/events" in c[1]]
    assert len(event_pages) == 3 and sorted(c[1] for c in deletes(api))[0].endswith("/HOLD")


def test_incomplete_event_readback_is_not_used(monkeypatch):
    monkeypatch.setattr(ho, "MAX_PAGES", 2)
    api = FakeApi(["HOLD", "module-gate-fehler"], [ev("labeled", HUMAN, "bug", n=i) for i in range(1, 501)])
    ho.run(api, "o/r", 7, "synthetisch", log=lambda *_: None)
    assert deletes(api) == []


def test_non_list_or_error_payloads_are_unreadable():
    def odd_api(method, path, token):
        return 200, {"message": "kein Array"}
    assert ho.read_events(odd_api, "o/r", 1, "t") is None and ho.read_labels(odd_api, "o/r", 1, "t") is None


def test_failed_delete_is_reported_not_silent_and_404_means_already_gone():
    lines = []
    ho.run(FakeApi(["module-gate-fehler"], delete_status=403), "o/r", 7, "synthetisch", log=lines.append)
    assert any("WARNUNG" in line and "403" in line for line in lines)
    lines.clear()
    ho.run(FakeApi(["module-gate-fehler"], delete_status=404), "o/r", 7, "synthetisch", log=lines.append)
    assert any("bereits entfernt" in line for line in lines)


def test_dry_run_changes_nothing():
    api = FakeApi(["HOLD", "module-gate-fehler"], [ev("labeled", BOT)])
    ho.run(api, "o/r", 7, "synthetisch", dry_run=True, log=lambda *_: None)
    assert deletes(api) == []


def test_command_line_dry_run_uses_only_given_files_and_no_network(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ho.urllib.request, "urlopen", lambda *a, **k: pytest.fail("Netzzugriff im Trockenlauf"))
    labels, events = tmp_path / "labels.json", tmp_path / "events.json"
    labels.write_text(json.dumps(["HOLD", "module-gate-fehler"]), encoding="utf-8")
    events.write_text(json.dumps([ev("labeled", HUMAN)]), encoding="utf-8")
    assert ho.main(["--labels-json", str(labels), "--events-json", str(events)]) == 0
    assert json.loads(capsys.readouterr().out)["remove"] == ["module-gate-fehler"]


def test_incomplete_environment_changes_nothing(monkeypatch, capsys):
    for name in ("GITHUB_TOKEN", "GITHUB_REPOSITORY", "PR_NUMBER"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(ho.urllib.request, "urlopen", lambda *a, **k: pytest.fail("Netzzugriff ohne Umgebung"))
    assert ho.main([]) == 0 and "fail-closed" in capsys.readouterr().out


# ----------------------------------------------------------------------------- Workflow


def test_workflow_uses_the_ownership_check_and_no_unconditional_removal():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "python3 .github/workflows/hold_ownership.py" in text
    assert "for label in HOLD module-gate-fehler" not in text and "labels/HOLD" not in text
    assert "if: steps.check_gate.outputs.gate_status == 'PASS'" in text


def test_workflow_keeps_the_gate_detection_trigger_and_permissions_and_has_a_per_pr_concurrency_group():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "python3 .github/workflows/module_gate_check.py" in text
    assert "pull_request:" in text and "pull_request_target" not in text
    assert "pull-requests: write" in text and "contents: read" in text
    assert "group: githubbot-hold-${{ github.event.pull_request.number || github.run_id }}" in text
    assert "cancel-in-progress: true" in text
    assert text.index("concurrency:") < text.index("jobs:")
