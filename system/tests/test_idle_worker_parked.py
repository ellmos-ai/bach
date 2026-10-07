"""Unit-Test fuer den erweiterten idle-worker Terminal-Waechter.

Verifiziert _is_terminal_parked (chat_tray.py) -- der Root-Cause-Fix fuer den
Resurrektions-Loop bei geparkten Gate-Tasks (T-20260912-1240loop / #1235 4x-Claim
/ #1293 Option A). Die Funktion ist GUI-unabhaengig (reine Logik), damit sie
ohne laufende Tray-Instanz testbar ist.

Faelle:
- blocked -> terminal (NEU: bricht den #1235-Loop)
- future due_date -> terminal (NEU)
- completed_at -> terminal (BACKWARD-COMPAT, alter Zweig)
- open ohne Marker -> NICHT terminal (alter Zweig unveraendert)
- past due_date -> NICHT terminal
- Nicht-Dict / None -> NICHT terminal (defensiv)
"""
import importlib.util
from datetime import datetime, timedelta
import os
import pytest
from system.tests.test_task_lease_client import mem_db, _insert_task

_HERE = os.path.dirname(os.path.abspath(__file__))
_MOD_PATH = os.path.normpath(
    os.path.join(_HERE, "..", "hub", "_services", "chat", "chat_tray.py")
)


def _load_func():
    spec = importlib.util.spec_from_file_location("_chat_tray_parked", _MOD_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._is_terminal_parked


def test_blocked_is_terminal():
    f = _load_func()
    assert f({"status": "blocked"}) is True, "blocked-Task muess terminal sein"


def test_open_not_terminal():
    f = _load_func()
    assert f({"status": "open"}) is False, "open-Task darf nicht terminal sein"


def test_completed_at_backward_compat():
    f = _load_func()
    assert f({"completed_at": "2026-01-01T00:00:00"}) is True, "completed_at-Zweig muss erhalten bleiben"


def test_future_due_date_terminal():
    f = _load_func()
    fut = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
    assert f({"status": "open", "due_date": fut}) is True, "future due_date muess terminal sein"


def test_past_due_date_not_terminal():
    f = _load_func()
    assert f({"status": "open", "due_date": "2000-01-01"}) is False, "past due_date darf nicht terminal sein"


def test_no_markers_not_terminal():
    f = _load_func()
    assert f({}) is False, "Task ohne Marker muess nicht terminal sein"


def test_non_dict_not_terminal():
    f = _load_func()
    assert f(None) is False
    assert f("not-a-dict") is False


def test_bad_due_date_not_terminal():
    f = _load_func()
    assert f({"status": "open", "due_date": "not-a-date"}) is False, "ungueltiges due_date -> fail-safe nicht terminal"


def test_claimed_by_blocked_terminal():
    f = _load_func()
    assert f({"status": "blocked", "claimed_by": "idle-worker"}) is True, "claimed_by+blocked muess terminal sein"


def test_claimed_by_in_progress_terminal():
    f = _load_func()
    assert f({"status": "in_progress", "claimed_by": "idle-worker"}) is True, "claimed_by+in_progress muess terminal sein"


def test_open_with_claimed_by_not_terminal():
    f = _load_func()
    assert f({"status": "open", "claimed_by": "idle-worker"}) is False, "open+claimed_by darf nicht terminal sein (Scan-Pfad filtert open)"


# ---------------------------------------------------------------------------
# #1303: Settle-Pfad muss dieselbe chat_id pollen, an die der Send-Pfad sendet
# ---------------------------------------------------------------------------
# _process_idle_task sendet an 'idle-{role_id}-{task_id}', _settle_pending_task
# pollte vorher hartkodiert 'idle-task-{task_id}' -- Antworten nach Client-Timeout
# (>300s) waren damit unauffindbar (PATH A / stranded Tasks).
import time as _time


def _load_mod():
    spec = importlib.util.spec_from_file_location("_chat_tray_parked", _MOD_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_pending_fields_uses_send_chat_id():
    """Kernassertion #1303: Tupel traegt die exakte Send-chat_id."""
    f = _load_mod()._pending_fields
    send_chat_id = "idle-foerderplaner-1241"
    task_id, seit, title, polled = f((1241, _time.time(), "Titel", send_chat_id))
    assert polled == send_chat_id, "Settle muss die exakte Send-chat_id (idle-{role}-{id}) pollen, nicht idle-task-{id}"
    assert (task_id, title) == (1241, "Titel")


def test_pending_fields_legacy_3tuple_fallback():
    """Legacy-Tupel (Deploy-Fenster): defensiver Fallback auf alten Praefix."""
    f = _load_mod()._pending_fields
    task_id, seit, title, polled = f((1241, 0.0, "Titel"))
    assert polled == "idle-task-1241", "3-Tupel ohne chat_id -> alter Praefix"
    assert title == "Titel"


def test_pending_fields_legacy_2tuple_fallback():
    f = _load_mod()._pending_fields
    task_id, seit, title, polled = f((1241, 0.0))
    assert title == "Task #1241" and polled == "idle-task-1241"


def test_pending_fields_empty_none():
    f = _load_mod()._pending_fields
    assert f(None) == (None, 0.0, "", "")
    assert f(()) == (None, 0.0, "", "")


def test_legacy_timeout_retains_the_exact_send_chat_id():
    """No history or timeout can establish the old physical call's end."""
    mod = _load_mod()
    tray = object.__new__(mod.BACHTray)
    pending = (1241, 0, "T", "idle-bach-1241-old")
    tray.idle_pending = pending
    tray._api = lambda *_a, **_k: pytest.fail("No speculative TaskDB/history reads")
    assert tray._settle_pending_task() is False
    assert tray.idle_pending == pending
    assert mod._pending_fields(tray.idle_pending)[3] == "idle-bach-1241-old"


def test_late_tool_receipt_does_not_prove_legacy_physical_end():
    mod = _load_mod()
    tray = object.__new__(mod.BACHTray)
    tray.idle_pending = (1241, _time.time(), "T", "idle-bach-1241")
    calls = []
    def api(*args, **kwargs):
        calls.append(args)
        return {"ok": True, "messages": [{"role": "assistant", "ok": True,
                                          "completed_task_ids": [1241]}]}
    tray._api = api
    assert tray._settle_pending_task() is False
    assert tray.idle_pending is not None
    assert calls == []


@pytest.mark.parametrize("answer", ["FERTIG", "Task #1241 analysiert", "Teilaufgaben geplant", "Antwort"])
@pytest.mark.parametrize("pending", [False, True])
def test_tray_never_closes_task_from_model_words(answer, pending, tmp_path):
    mod = _load_mod()
    tray = object.__new__(mod.BACHTray)
    tray.gui_url = "http://127.0.0.1:8000"
    tray.idle_processing = False
    tray.idle_pending = (1241, _time.time(), "T", "idle-bach-1241") if pending else None
    tray.idle_task_name = None
    tray.idle_consecutive = 0
    tray.icon = None
    tray._update_icon = lambda *_a: None
    puts, progress, commits = [], [], []

    def fake_api(method, path, body=None, **kwargs):
        if path.startswith("/api/history"):
            return {"ok": True, "messages": [{"role": "assistant", "content": answer, "ok": True}]}
        if method == "GET" and "assigned_to=OLLAMA" in path:
            return {"success": True, "tasks": [{"id": 1241, "title": "T", "status": "pending"}]}
        if method == "GET":
            return {"status": "in_progress"}
        if method == "PUT":
            puts.append(body)
            return {"status": "updated"}
        return {"ok": True, "answer": answer}

    from hub._services.chat.tray_worker_execution import NativeWorkerObserver
    import threading
    tray._idle_run_lock = threading.Lock()
    tray._native_worker = NativeWorkerObserver("http://testhost:8081", tmp_path / "intent.json",
        lambda *_a: (200, {"ok": True, "answer": answer}))
    tray.state = {"connected": True}
    tray.remote = False
    tray.idle_enabled = True
    tray.slots = {"buddha_always_on": {"id": "buddha_always_on", "enabled": True,
                                      "pause_info": {"is_paused": False}}}
    tray._api = fake_api
    tray._record_always_on_progress = lambda **kwargs: progress.append(kwargs)
    tray._auto_commit_task = lambda *_a: commits.append(True)
    if pending:
        tray._settle_pending_task()
    else:
        tray._process_idle_task()
    assert not any(p.get("status") in ("done", "completed") for p in puts)
    assert not any(p.get("task_completed") for p in progress)
    assert commits == []


@pytest.mark.parametrize("task_state", [None, {"status": "blocked"}, {"status": "completed"},
                                        {"status": "in_progress", "claimed_by": "other-worker"}])
def test_pending_result_cannot_reopen_unknown_or_terminal_task(task_state):
    mod = _load_mod()
    tray = object.__new__(mod.BACHTray)
    tray.gui_url = "http://127.0.0.1:8000"
    tray.idle_pending = (1241, _time.time(), "T", "idle-bach-1241")
    puts = []

    def fake_api(method, path, body=None, **kwargs):
        if "/api/history" in path:
            return {"ok": True, "messages": [{"role": "assistant", "content": "Antwort", "ok": True}]}
        if method == "GET":
            return task_state
        puts.append(body)
        return {"status": "updated"}

    tray._api = fake_api
    tray._record_always_on_progress = lambda **_k: None
    tray._auto_commit_task = lambda *_a: pytest.fail("Unconfirmed task must not auto-commit")
    tray._settle_pending_task()
    assert puts == []
    if task_state is None:
        assert tray.idle_pending is not None


@pytest.mark.parametrize("history", [None, {"ok": False, "error": "Dienst nicht verfügbar"}])
def test_history_outage_does_not_reset_pending_task(history):
    mod = _load_mod()
    tray = object.__new__(mod.BACHTray)
    tray.gui_url = "http://127.0.0.1:8000"
    tray.idle_pending = (1241, _time.time(), "T", "idle-bach-1241")
    writes = []

    def api(method, path, body=None, **kwargs):
        if "/api/history" in path:
            return history
        if method == "GET":
            return {"status": "in_progress"}
        writes.append(body)

    tray._api = api
    assert tray._settle_pending_task() is False
    assert writes == []
    assert tray.idle_pending is not None


def test_legacy_tuple_retains_old_prefix_without_history_recovery():
    mod = _load_mod()
    tray = object.__new__(mod.BACHTray)
    tray.idle_pending = (1241, _time.time(), "T")
    tray._api = lambda *_a, **_k: pytest.fail("History is not physical-end evidence")
    assert tray._settle_pending_task() is False
    assert mod._pending_fields(tray.idle_pending)[3] == "idle-task-1241"


def _native_pickup(conn):
    import threading
    from hub._services.task_lease_client import TaskLeaseClient
    from hub._services.chat.worker_lease_binding import WorkerLeaseBinding
    from system.tests.test_task_lease_client_review import T0
    return WorkerLeaseBinding.acquire_next(
        TaskLeaseClient(conn=conn), {"id": "buddha_always_on"},
        worker_id="test-worker@HOST", host="HOST", generation="isolated-run",
        is_current=lambda: True, stop_event=threading.Event(), clock=lambda: T0,
    )


def test_idle_worker_skips_parked_task_and_picks_next_valid(mem_db):
    """Der native Controller überspringt geparkte Tasks vor dem Lease-Claim."""
    parked = _insert_task(mem_db, "Parked", status="blocked")
    ready = _insert_task(mem_db, "Ready", status="pending")
    mem_db.execute("UPDATE tasks SET assigned_to='BACH'")
    mem_db.commit()
    binding = _native_pickup(mem_db)
    assert binding.task_id == ready
    assert mem_db.execute("SELECT claimed_by FROM tasks WHERE id=?", (parked,)).fetchone()[0] is None


def test_legacy_pending_call_stays_unknown_even_when_task_db_reports_done():
    """Taskstatus belegt kein physisches Ende eines alten HTTP-Aufrufs."""
    mod = _load_mod()
    tray = object.__new__(mod.BACHTray)
    tray.gui_url = "http://127.0.0.1:8000"
    # seit liegt erst 60s zurueck, also weit unter PENDING_TTL (1800s)
    tray.idle_pending = (1603, _time.time() - 60, "Task 1603", "idle-bach-1603")
    progress, commits = [], []

    def fake_api(method, path, body=None, base=None, timeout=8):
        if method == "GET" and "/api/history" in path:
            # Kein assistant message bisher (z. B. noch in Toolrunden oder vor Zusammenfassung)
            return {"ok": True, "messages": [{"role": "user", "content": "Start"}]}
        if method == "GET" and "/api/tasks/1603" in path:
            # DB meldet bereits erledigt!
            return {"id": 1603, "status": "done", "completed_at": "2026-10-06T23:43:34"}
        return {"success": True}

    tray._api = fake_api
    tray._record_always_on_progress = lambda **kwargs: progress.append(kwargs)
    tray._auto_commit_task = lambda *a, **k: commits.append(a)

    assert tray._settle_pending_task() is False
    assert tray.idle_pending is not None
    assert progress == []
    assert commits == []




if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
            print(f"PASS: {_name}")
    print("ALLE TESTS BESTANDEN")


# ---------------------------------------------------------------------------
# Abhaengigkeiten: der Idle-Worker darf keinen Task ziehen, dessen Vorgaenger
# noch offen sind (aus rescue/live-wip-20260928 uebernommen, fail-closed).
# ---------------------------------------------------------------------------
def _idle_tray(mod, fake_api):
    tray = object.__new__(mod.BACHTray)
    tray.gui_url = "http://127.0.0.1:8000"
    tray.idle_processing = False
    tray.idle_pending = None
    tray.idle_task_name = None
    tray.idle_consecutive = 0
    tray.icon = None
    tray.slots = {}
    tray._update_icon = lambda *a, **k: None
    tray._api = fake_api
    return tray


def test_idle_worker_skips_dependency_blocked_task_and_picks_next(mem_db):
    predecessor = _insert_task(mem_db, "Predecessor")
    waiting = _insert_task(mem_db, "Waiting", status="pending")
    ready = _insert_task(mem_db, "Ready", status="pending")
    mem_db.execute("UPDATE tasks SET assigned_to='codex' WHERE id=?", (predecessor,))
    mem_db.execute("UPDATE tasks SET assigned_to='BACH' WHERE id IN (?,?)", (waiting, ready))
    mem_db.execute("UPDATE tasks SET depends_on=?,priority='P1' WHERE id=?", (str(predecessor), waiting))
    mem_db.commit()
    binding = _native_pickup(mem_db)
    assert binding.task_id == ready
    assert mem_db.execute("SELECT claimed_by FROM tasks WHERE id=?", (waiting,)).fetchone()[0] is None


def test_idle_worker_never_claims_when_only_blocked_tasks_exist(mem_db):
    predecessor = _insert_task(mem_db, "Predecessor")
    waiting = _insert_task(mem_db, "Waiting")
    mem_db.execute("UPDATE tasks SET assigned_to='codex' WHERE id=?", (predecessor,))
    mem_db.execute("UPDATE tasks SET assigned_to='BACH',depends_on=? WHERE id=?", (str(predecessor), waiting))
    mem_db.commit()
    assert _native_pickup(mem_db) is None
    assert mem_db.execute("SELECT claimed_by FROM tasks WHERE id=?", (waiting,)).fetchone()[0] is None


@pytest.mark.parametrize("detail,expected", [
    ({"id": 5, "is_blocked_by_dep": True}, True),
    ({"id": 5, "is_blocked_by_dep": False}, False),
    ({"id": 5}, True),          # aeltere API ohne Feld -> fail-closed
    (None, True),               # Server nicht erreichbar -> fail-closed
])
def test_dependency_check_without_list_flag_asks_detail_fail_closed(detail, expected):
    mod = _load_mod()
    calls = []

    def fake_api(method, path, body=None, base=None, timeout=8):
        calls.append((method, path))
        return detail

    tray = _idle_tray(mod, fake_api)
    assert tray._is_blocked_by_dep({"id": 5, "depends_on": "4"}) is expected
    assert calls == [("GET", "/api/tasks/5")]


def test_dependency_check_skips_lookup_without_depends_on():
    mod = _load_mod()

    def fake_api(*a, **k):
        raise AssertionError("kein Detail-Lookup ohne depends_on")

    tray = _idle_tray(mod, fake_api)
    assert tray._is_blocked_by_dep({"id": 6, "depends_on": ""}) is False
    assert tray._is_blocked_by_dep({"id": 7}) is False
    assert tray._is_blocked_by_dep(None) is False
