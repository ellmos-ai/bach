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


def test_send_path_stores_send_chat_id_on_timeout():
    """E2E Send-Pfad: bei Client-Timeout (POST /api/chat -> None) muss das
    idle_pending-Tupel die echte Send-chat_id als 4. Element vormerken."""
    mod = _load_mod()
    tray = object.__new__(mod.BACHTray)          # __init__ umgehen: keine GUI
    tray.gui_url = "http://127.0.0.1:8000"
    tray.idle_processing = False
    tray.idle_pending = None
    tray.idle_task_name = None
    tray.idle_consecutive = 0
    tray.icon = None
    tray._update_icon = lambda *a, **k: None

    def fake_api(method, path, body=None, base=None, timeout=8):
        if method == "GET" and "assigned_to=OLLAMA" in path:
            return {"success": True, "tasks": [{
                "id": 1241, "title": "T", "description": "",
                "assigned_to": "OLLAMA", "status": "pending",
            }]}
        if method == "GET":
            return {"status": "in_progress"}     # /api/tasks/{id}: nicht terminal
        if method == "PUT":
            return {"success": True}             # Claim ok
        assert method == "POST", f"unerwarteter Call: {method} {path}"
        return None                              # POST /api/chat: Client-Timeout

    tray._api = fake_api
    tray._process_idle_task()
    assert tray.idle_pending is not None, "Client-Timeout muss idle_pending setzen"
    assert len(tray.idle_pending) >= 4, f"Tupel muss chat_id tragen (#1303): {tray.idle_pending}"
    assert tray.idle_pending[3].startswith("idle-bach-1241-"), \
        f"Send-chat_id muss idle-{{role}}-{{id}} sein, ist aber: {tray.idle_pending[3]}"


def test_settle_polls_send_chat_id_and_settles():
    """E2E Settle-Pfad: nach Client-Timeout muss _settle_pending_task die
    echte Send-chat_id pollen, die verspaetete Antwort finden und den Task
    sauber abschliessen (vor #1303: PATH A 'ohne Antwort' -> stranded)."""
    mod = _load_mod()
    tray = object.__new__(mod.BACHTray)
    tray.gui_url = "http://127.0.0.1:8000"
    tray.idle_pending = (1241, _time.time(), "T", "idle-bach-1241")
    polled_history, puts = [], []

    def fake_api(method, path, body=None, base=None, timeout=8):
        if method == "GET" and "/api/history" in path:
            polled_history.append(path)
            return {"messages": [{"role": "assistant", "content": "FERTIG. Erledigt.", "ok": True,
                                  "completed_task_ids": [1241]}]}
        if method == "GET":
            return {"status": "in_progress"}     # task_now: nicht terminal
        assert method == "PUT", f"unerwarteter Call: {method} {path}"
        puts.append(body)
        return {"success": True}

    tray._api = fake_api
    tray._auto_commit_task = lambda *a, **k: None
    ok = tray._settle_pending_task()
    assert ok is True
    assert polled_history and "idle-bach-1241" in polled_history[0], \
        f"Settle muss die Send-chat_id pollen, pollte aber: {polled_history}"
    assert not polled_history or "idle-task-1241" not in polled_history[0], \
        "hartkodierter idle-task-Praefix darf nicht mehr gepollt werden"
    assert puts == [], "The tool already closed the task; tray must not write a second completion"
    assert tray.idle_pending is None, "Nach erfolgreichem Settle muss idle_pending geleert sein"


@pytest.mark.parametrize("answer", ["FERTIG", "Task #1241 analysiert", "Teilaufgaben geplant", "Antwort"])
@pytest.mark.parametrize("pending", [False, True])
def test_tray_never_closes_task_from_model_words(answer, pending):
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


def test_settle_legacy_tuple_uses_old_prefix():
    """Negativ-Kontrolle: Legacy-3-Tupel (ohne chat_id) fallen auf den alten
    Praefix zurueck -- genau deshalb muss der Send-Pfad die chat_id vormerken."""
    mod = _load_mod()
    tray = object.__new__(mod.BACHTray)
    tray.gui_url = "http://127.0.0.1:8000"
    tray.idle_pending = (1241, _time.time(), "T")   # Pre-#1303-Form
    polled_history = []

    def fake_api(method, path, body=None, base=None, timeout=8):
        if method == "GET" and "/api/history" in path:
            polled_history.append(path)
            return {"messages": []}              # idle-task-1241 existiert nicht
        if method == "GET":
            return {"status": "in_progress"}
        return {"success": True}

    tray._api = fake_api
    tray._settle_pending_task()
    assert polled_history and "idle-task-1241" in polled_history[0], \
        "Legacy-Tupel pollt den alten Praefix (dokumentiert das Pre-#1303-Verhalten)"


def test_idle_worker_skips_parked_task_and_picks_next_valid():
    """Verifiziert, dass ein geparkter Task am Anfang der Liste nicht den ganzen Idle-Worker blockiert."""
    mod = _load_mod()
    tray = object.__new__(mod.BACHTray)
    tray.gui_url = "http://127.0.0.1:8000"
    tray.idle_processing = False
    tray.idle_pending = None
    tray.idle_task_name = None
    tray.idle_consecutive = 0
    tray.icon = None
    tray.slots = {}
    tray._update_icon = lambda *a, **k: None

    claimed_ids = []

    def fake_api(method, path, body=None, base=None, timeout=8):
        if method == "GET" and "assigned_to=OLLAMA" in path:
            return {
                "success": True,
                "tasks": [
                    {"id": 1729, "title": "Parked Task", "status": "blocked", "assigned_to": "OLLAMA"},
                    {"id": 1730, "title": "Valid Task", "status": "pending", "assigned_to": "OLLAMA"},
                ],
            }
        if method == "GET" and "/api/tasks/1730" in path:
            return {"status": "in_progress"}
        if method == "PUT" and "/api/tasks/1730" in path:
            claimed_ids.append(1730)
            return {"success": True}
        if method == "POST" and "/api/chat" in path:
            return {"ok": True, "chat_id": "idle-foerderplaner-1730"}
        return {"success": True}

    tray._api = fake_api
    tray._process_idle_task()
    assert 1730 in claimed_ids, "Idle-Worker muss den geparkten Task 1729 überspringen und Task 1730 beanspruchen"
    assert 1729 not in claimed_ids, "Geparkter Task 1729 darf nicht beansprucht werden"


def test_settle_pending_task_settles_immediately_when_db_shows_done_without_waiting_ttl():
    """Wenn die DB den Task bereits als done/completed ausweist (z. B. durch Tool call),
    muss _settle_pending_task sofort abschliessen, ohne 30 Min PENDING_TTL abzuwarten."""
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

    settled = tray._settle_pending_task()
    assert settled is True, "Muss sofort True zurueckgeben, da Task in DB done ist"
    assert tray.idle_pending is None, "idle_pending muss zurueckgesetzt sein"
    assert any(p.get("task_completed") for p in progress), "Progress muss task_completed vermerken"
    assert len(commits) == 1, "Auto-Commit muss aufgerufen werden"



if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
            print(f"PASS: {_name}")
    print("ALLE TESTS BESTANDEN")
