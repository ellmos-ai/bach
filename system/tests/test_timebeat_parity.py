# -*- coding: utf-8 -*-
"""E5 von T-20260920-823767362: Timebeat wandert nach TimeManager.timebeat().

Paritaet alt gegen neu: die Timebeat-Logik aus tools/injectors.py
TimeInjector.check (Stand vor E5, per git aus origin-Historie geladen) gegen
den neuen Pfad TimeInjector -> TimeManager.timebeat(), auf zwei identischen
Temp-Verzeichnissen mit Uhr, Timer, Countdown (laufend + abgelaufen) und
ungelesenen Partner-Nachrichten, mit fester Uhrzeit.
"""
import importlib.util
import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

SYSTEM_DIR = Path(__file__).resolve().parent.parent
REPO = SYSTEM_DIR.parent
BEFORE_E5 = "85551a0"  # main vor E5 (enthaelt TimeInjector.check noch inline)


def _old_injectors(tmp_path):
    try:
        src = subprocess.run(["git", "-C", str(REPO), "show", f"{BEFORE_E5}:system/tools/injectors.py"],
                             capture_output=True, check=True).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        pytest.skip("Vor-E5-Stand nicht im lokalen git verfuegbar")
    path = tmp_path / "injectors_before_e5.py"
    path.write_bytes(src)
    spec = importlib.util.spec_from_file_location("injectors_before_e5", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _base(root, now):
    data = root / "data"
    data.mkdir(parents=True)
    (data / ".timer_state").write_text(json.dumps({"timers": {
        "session": (now - timedelta(minutes=45)).isoformat()}}), encoding="utf-8")
    (data / ".countdown_state").write_text(json.dumps({"countdowns": {
        "fokus": {"end_time": (now + timedelta(minutes=20)).isoformat(), "paused": False,
                  "after_command": None, "remaining_on_pause": None},
        "tee": {"end_time": (now + timedelta(seconds=90)).isoformat(), "paused": False,
                "after_command": "--status", "remaining_on_pause": None}}}),
        encoding="utf-8")
    conn = sqlite3.connect(data / "bach.db")
    conn.executescript("""
        CREATE TABLE partner_presence (partner_name TEXT, status TEXT, clocked_in TEXT);
        CREATE TABLE messages (id INTEGER PRIMARY KEY, sender TEXT, recipient TEXT, body TEXT,
                               status TEXT, created_at TEXT);
        INSERT INTO partner_presence VALUES ('claude', 'online', '2026-09-26 20:00');
        INSERT INTO messages (sender, recipient, body, status, created_at) VALUES
            ('gemini', 'claude', 'Bitte Review von PR 108', 'unread', '2026-09-26 20:10'),
            ('user', 'claude', 'Zweite Nachricht', 'unread', '2026-09-26 20:11');
    """)
    conn.commit()
    conn.close()
    return root


def test_timebeat_parity(tmp_path, monkeypatch):
    sys.path.insert(0, str(SYSTEM_DIR))
    import tools.time_system as ts
    sys.path.insert(0, str(SYSTEM_DIR / "tools"))
    import injectors as new_injectors

    old_injectors = _old_injectors(tmp_path)
    clock = {"now": datetime(2026, 9, 26, 21, 0, 0)}

    class _Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock["now"]

    monkeypatch.setattr(ts, "datetime", _Clock)
    alt = old_injectors.TimeInjector(60, _base(tmp_path / "alt", clock["now"]))
    neu = new_injectors.TimeInjector(60, _base(tmp_path / "neu", clock["now"]))
    assert alt.manager is not None and neu.manager is not None
    outputs = []
    start = clock["now"]
    for offset in (0, 30, 59, 60, 61, 200):
        clock["now"] = start + timedelta(seconds=offset)
        a, n = alt.check(), neu.check()
        assert n == a, offset
        outputs.append(a)
    assert any(o and "[CLOCK]" in o for o in outputs)
    assert any(o is None for o in outputs)  # Intervall greift
    joined = "\n".join(o for o in outputs if o)
    for part in ("[TIMER]", "[COUNTDOWN]", "ABGELAUFEN", "[NEUE NACHRICHTEN] 2 fuer CLAUDE"):
        assert part in joined, part
