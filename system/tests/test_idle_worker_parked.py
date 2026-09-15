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


if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
            print(f"PASS: {_name}")
    print("ALLE TESTS BESTANDEN")
