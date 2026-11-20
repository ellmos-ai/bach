# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Echte Modultests fuer system/agents/ati/recurring/recurring_tasks.py.

Diese Testdatei ersetzt die fruehere Regression (Trivialtests mit
Host-Selbstasserts) durch verhaltensbasierte Pruefungen gegen das echte
Modul:

* list_recurring_tasks(): leere/fehlende Konfiguration, Fälligkeit,
  unabhängige Auswertung je Host.
* check_recurring_tasks(): Fälligkeitsfenster (last_run + interval_days),
  INSERT in ati_tasks (tool_name='BACH', source_file='recurring',
  tags='recurring,<id>'), Duplikat-Schutz gegen offene Tasks mit
  identischem task_text, Deaktivierung, defektes last_run, leere
  Konfiguration, Konfig-Update (last_run) nach erfolgreicher Erstellung,
  stabiles Verhalten bei mehrfachem Lauf.
* trigger_recurring_task(): manuelle Auslösung, unbekannte Task-ID.

Cross-Host ueber ASUS-GEI, mac-studio und WORKSTATION-LG:
* getrennte Konfiguration/Datenbank je Host (unabhängige Hosts),
* geteilte Datenbank mit je eigener Konfiguration: hier greift der
  Duplikat-SCHUTZ des Moduls wirklich (Kollisionspfad),
* geteilte Konfiguration mit geteilter Datenbank: nur Fälligkeits-Skip.

Isolation: Das Modul wird einmal via importlib geladen (spec_from_file_
location). Pro Testfall werden die Modulattribute CONFIG_FILE und USER_DB
per monkeypatch auf tmp-Dateien (ggf. geteilt zwischen Hosts) umgebogen;
deshalb beruehren die Tests nie das echte BACH-Datenverzeichnis.
"""

import datetime
import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

_MODULE_PATH = (
    Path(__file__).resolve().parent.parent
    / "agents" / "ati" / "recurring" / "recurring_tasks.py"
)

_SPEC = importlib.util.spec_from_file_location("recurring_tasks_under_test", _MODULE_PATH)
mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(mod)

HOSTS = ["ASUS-GEI", "mac-studio", "WORKSTATION-LG"]

OLD_LAST_RUN = "2020-01-01T00:00:00"

SCHEMA = """CREATE TABLE IF NOT EXISTS ati_tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tool_name TEXT,
  tool_path TEXT,
  task_text TEXT,
  aufwand TEXT,
  status TEXT,
  priority_score INTEGER,
  source_file TEXT,
  line_number INTEGER,
  synced_at TEXT,
  is_synced INTEGER,
  tags TEXT
);"""


def write_config(path, tasks):
    """Schreibt eine recurring-Tasks-Konfiguration als JSON."""
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"recurring_tasks": tasks or {}}, handle, ensure_ascii=False, indent=2)


def make_entry(task_text, task_id, enabled=True, interval_days=7, last_run=None):
    """Baut einen Eintraege-Dict {task_id: {...}} mit bewusst gesetzten Defaults."""
    return {
        task_id: {
            "enabled": enabled,
            "task_text": task_text,
            "interval_days": interval_days,
            "last_run": last_run,
        }
    }


def prepare_host(tmp_path, monkeypatch, host, *, entry=None, shared_config=None, shared_db=None):
    """Bindet die Modulattribute CONFIG_FILE/USER_DB auf Host-Dateien.

    Ohne shared_config/shared_db landen config.json und bach.db in einem
    Host-eigenen Unterverzeichnis (tmp_path/<host.lower()>); mit shared_*
    werden genau die uebergebenen gemeinsam genutzten Dateien verwendet
    (eine geteilte Konfiguration wird dabei NICHT neu geschrieben).
    """
    host_dir = tmp_path / host.lower()
    host_dir.mkdir(parents=True, exist_ok=True)
    if shared_config is not None:
        cfg = shared_config
    else:
        cfg = host_dir / "config.json"
        write_config(cfg, entry)
    if shared_db is not None:
        db = shared_db
    else:
        db = host_dir / "bach.db"
    conn = sqlite3.connect(db)
    try:
        conn.execute(SCHEMA)
        conn.commit()
    finally:
        conn.close()
    monkeypatch.setattr(mod, "CONFIG_FILE", cfg)
    monkeypatch.setattr(mod, "USER_DB", db)
    return cfg, db


def count_tasks(db):
    """Zaehlt alle Zeilen in ati_tasks der gegebenen DB."""
    conn = sqlite3.connect(db)
    try:
        cur = conn.execute("SELECT COUNT(*) FROM ati_tasks")
        return int(cur.fetchone()[0])
    finally:
        conn.close()


def fetch_rows(db):
    """Liest alle ati_tasks-Zeilen als Dict-Liste."""
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute("SELECT * FROM ati_tasks ORDER BY id")
        return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def _insert_offen(db, task_text, task_id):
    """Legt vorab einen offenen Task mit identischem task_text an."""
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            "INSERT INTO ati_tasks (tool_name, tool_path, task_text, aufwand, status,"
            " priority_score, source_file, line_number, synced_at, is_synced, tags)"
            " VALUES ('BACH', '', ?, 'mittel', 'offen', 50, 'recurring', 0, NULL, 1, ?)",
            (task_text, f"recurring,{task_id}"),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# list_recurring_tasks
# ---------------------------------------------------------------------------


def test_list_recurring_tasks_ohne_config_leer(tmp_path, monkeypatch):
    """Fehlende Konfigurationsdatei -> leeres Ergebnis."""
    fehlend = tmp_path / "gibts-nicht" / "config.json"
    monkeypatch.setattr(mod, "CONFIG_FILE", fehlend)
    monkeypatch.setattr(mod, "USER_DB", tmp_path / "unbenutzt.db")
    assert mod.list_recurring_tasks() == {}


def test_list_recurring_tasks_faelig(tmp_path, monkeypatch):
    """Altes last_run -> faellig, next_due = last_run + interval_days."""
    text = "Recurring: Backup pruefen"
    prepare_host(
        tmp_path, monkeypatch, "ASUS-GEI",
        entry=make_entry(text, "backup", interval_days=7, last_run=OLD_LAST_RUN),
    )
    ergebnis = mod.list_recurring_tasks()
    assert set(ergebnis) == {"backup"}
    info = ergebnis["backup"]
    assert info["is_due"] is True
    assert info["days_until"] <= 0
    assert info["next_due"] == "2020-01-08T00:00:00"
    assert info["enabled"] is True
    assert info["task_text"] == text
    assert info["interval_days"] == 7
    assert info["last_run"] == OLD_LAST_RUN


def test_list_recurring_tasks_nicht_faelig(tmp_path, monkeypatch):
    """last_run vor 1 Stunde -> nicht faellig, next_due exakt last_run + 7 Tage."""
    last_run = (datetime.datetime.now() - datetime.timedelta(hours=1)).isoformat()
    prepare_host(
        tmp_path, monkeypatch, "mac-studio",
        entry=make_entry("Woechentlicher Check", "check", interval_days=7, last_run=last_run),
    )
    info = mod.list_recurring_tasks()["check"]
    assert info["is_due"] is False
    assert 6 <= info["days_until"] <= 7
    erwartet = (
        datetime.datetime.fromisoformat(last_run) + datetime.timedelta(days=7)
    ).isoformat()
    assert info["next_due"] == erwartet


# ---------------------------------------------------------------------------
# check_recurring_tasks
# ---------------------------------------------------------------------------


def test_check_recurring_tasks_erstellt_task(tmp_path, monkeypatch):
    """Faelliger Eintrag -> genau ein INSERT mit allen erwarteten Feldern; last_run-Update."""
    text = "Recurring: Backup"
    cfg, db = prepare_host(
        tmp_path, monkeypatch, "WORKSTATION-LG",
        entry=make_entry(text, "backup", last_run=OLD_LAST_RUN),
    )
    assert mod.check_recurring_tasks() == [text]
    zeilen = fetch_rows(db)
    assert len(zeilen) == 1
    zeile = zeilen[0]
    assert zeile["tool_name"] == "BACH"
    assert zeile["tool_path"] == ""
    assert zeile["task_text"] == text
    assert zeile["aufwand"] == "mittel"
    assert zeile["status"] == "offen"
    assert zeile["priority_score"] == 50
    assert zeile["source_file"] == "recurring"
    assert zeile["line_number"] == 0
    assert zeile["is_synced"] == 1
    assert zeile["synced_at"]
    assert zeile["tags"] == "recurring,backup"
    with open(cfg, encoding="utf-8") as handle:
        config_ist = json.load(handle)
    last_run = datetime.datetime.fromisoformat(config_ist["recurring_tasks"]["backup"]["last_run"])
    assert last_run >= datetime.datetime.now() - datetime.timedelta(minutes=1)


def test_check_recurring_tasks_nicht_faelig(tmp_path, monkeypatch):
    """last_run = jetzt -> Faelligkeitsfenster schliesst Erstellung aus."""
    _, db = prepare_host(
        tmp_path, monkeypatch, "ASUS-GEI",
        entry=make_entry("Recurring: Backup", "backup", last_run=datetime.datetime.now().isoformat()),
    )
    assert mod.check_recurring_tasks() == []
    assert count_tasks(db) == 0


def test_check_recurring_tasks_deaktiviert(tmp_path, monkeypatch):
    """enabled=False -> skip; an der Konfiguration aendert sich nichts."""
    cfg, db = prepare_host(
        tmp_path, monkeypatch, "mac-studio",
        entry=make_entry("Recurring: Backup", "backup", enabled=False, last_run=OLD_LAST_RUN),
    )
    assert mod.check_recurring_tasks() == []
    assert count_tasks(db) == 0
    with open(cfg, encoding="utf-8") as handle:
        config_ist = json.load(handle)
    assert config_ist["recurring_tasks"]["backup"]["last_run"] == OLD_LAST_RUN


def test_check_recurring_tasks_duplikatschutz(tmp_path, monkeypatch):
    """Offener Task mit identischem task_text -> SKIP ohne Erstellung und ohne last_run-Update."""
    text = "Recurring: Backup"
    cfg, db = prepare_host(
        tmp_path, monkeypatch, "WORKSTATION-LG",
        entry=make_entry(text, "backup", last_run=OLD_LAST_RUN),
    )
    _insert_offen(db, text, "backup")
    assert count_tasks(db) == 1
    assert mod.check_recurring_tasks() == []
    assert count_tasks(db) == 1
    with open(cfg, encoding="utf-8") as handle:
        config_ist = json.load(handle)
    assert config_ist["recurring_tasks"]["backup"]["last_run"] == OLD_LAST_RUN


def test_check_recurring_tasks_mehrfacher_lauf(tmp_path, monkeypatch):
    """Zweiter Lauf erstellt nichts mehr (Faelligkeitsfenster und Duplikatschutz)."""
    text = "Recurring: Backup"
    _, db = prepare_host(
        tmp_path, monkeypatch, "ASUS-GEI",
        entry=make_entry(text, "backup", last_run=OLD_LAST_RUN),
    )
    assert mod.check_recurring_tasks() == [text]
    assert count_tasks(db) == 1
    assert mod.check_recurring_tasks() == []
    assert count_tasks(db) == 1


def test_check_recurring_tasks_ungueltiges_last_run(tmp_path, monkeypatch):
    """Parse-Fehler bei last_run -> Task wird trotzdem erstellt."""
    text = "Recurring: Backup"
    _, db = prepare_host(
        tmp_path, monkeypatch, "ASUS-GEI",
        entry=make_entry(text, "backup", last_run="garbage"),
    )
    assert mod.check_recurring_tasks() == [text]
    assert count_tasks(db) == 1


def test_check_recurring_tasks_leere_konfig(tmp_path, monkeypatch):
    """Leeres recurring_tasks -> nichts passiert."""
    _, db = prepare_host(tmp_path, monkeypatch, "mac-studio", entry={})
    assert mod.check_recurring_tasks() == []
    assert count_tasks(db) == 0


# ---------------------------------------------------------------------------
# trigger_recurring_task
# ---------------------------------------------------------------------------


def test_trigger_recurring_task_erstellt(tmp_path, monkeypatch):
    """Manueller Trigger erstellt Task analog zum automatischen Lauf; last_run-Update."""
    text = "Recurring: Backup"
    cfg, db = prepare_host(
        tmp_path, monkeypatch, "ASUS-GEI",
        entry=make_entry(text, "backup", last_run=None),
    )
    assert mod.trigger_recurring_task("backup") is True
    zeilen = fetch_rows(db)
    assert len(zeilen) == 1
    zeile = zeilen[0]
    assert zeile["tool_name"] == "BACH"
    assert zeile["tool_path"] == ""
    assert zeile["task_text"] == text
    assert zeile["aufwand"] == "mittel"
    assert zeile["status"] == "offen"
    assert zeile["priority_score"] == 50
    assert zeile["source_file"] == "recurring"
    assert zeile["line_number"] == 0
    assert zeile["is_synced"] == 1
    assert zeile["synced_at"]
    assert zeile["tags"] == "recurring,backup"
    with open(cfg, encoding="utf-8") as handle:
        config_ist = json.load(handle)
    last_run = datetime.datetime.fromisoformat(config_ist["recurring_tasks"]["backup"]["last_run"])
    assert last_run >= datetime.datetime.now() - datetime.timedelta(minutes=1)


def test_trigger_recurring_task_unbekannt(tmp_path, monkeypatch):
    """Unbekannte Task-ID -> False, keine Zeile."""
    _, db = prepare_host(
        tmp_path, monkeypatch, "WORKSTATION-LG",
        entry=make_entry("Recurring: Backup", "backup", last_run=None),
    )
    assert mod.trigger_recurring_task("fehlt") is False
    assert count_tasks(db) == 0


# ---------------------------------------------------------------------------
# Cross-Host: getrennte Hosts, geteilte DB, geteilte Konfiguration
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("host", HOSTS)
def test_check_recurring_tasks_cross_host_je_host_eigenstaendig(tmp_path, monkeypatch, host):
    """Jeder der drei Hosts wertet seine eigene Konfiguration/DB isoliert faellig aus."""
    text = "Recurring: Backup"
    cfg, db = prepare_host(
        tmp_path, monkeypatch, host,
        entry=make_entry(text, "backup", last_run=OLD_LAST_RUN),
    )
    assert host.lower() in str(cfg)
    assert mod.check_recurring_tasks() == [text]
    assert count_tasks(db) == 1


def test_check_recurring_tasks_cross_host_getrennte_dbs(tmp_path, monkeypatch):
    """Alle drei Hosts nacheinander, je eigene config+DB -> je genau ein Task, gesamt drei."""
    text = "Recurring: Backup"
    erstellt_gesamt = 0
    for host in HOSTS:
        _, db = prepare_host(
            tmp_path, monkeypatch, host,
            entry=make_entry(text, "backup", last_run=OLD_LAST_RUN),
        )
        assert mod.check_recurring_tasks() == [text]
        erstellt_gesamt += count_tasks(db)
    assert erstellt_gesamt == 3


def test_check_recurring_tasks_geteilte_db_kollision(tmp_path, monkeypatch):
    """Kern-Kollisionspfad: geteilte DB, je Host eigene Konfiguration mit identischem task_text.

    Realistische Topologie im BACH-Hub: ati_tasks liegt in der geteilten
    Datenbank, die recurring-Konfiguration bleibt host-lokal. Damit bleibt
    jede Host-Konfiguration einzeln faellig (last_run je Host), und der
    Duplikat-Schutz des Moduls (SELECT ... WHERE task_text=? AND
    status='offen') greift wirklich: nur der erste Host erstellt den Task,
    die anderen Hosts laufen wegen des Duplikat-SKIP leer. Eine geteilte
    Konfiguration allein wuerde nach dem ersten Host nur den
    Faelligkeits-Skip ausloesen, nicht den Duplikat-SKIP (dafuer gibt es
    den naechsten Test).
    """
    text = "Recurring: Backup"
    geteilt_dir = tmp_path / "geteilt"
    geteilt_dir.mkdir()
    shared_db = geteilt_dir / "bach.db"
    erstellt_pro_host = []
    for host in HOSTS:
        _, db = prepare_host(
            tmp_path, monkeypatch, host,
            entry=make_entry(text, "backup", last_run=OLD_LAST_RUN),
            shared_db=shared_db,
        )
        assert db == shared_db
        erstellt_pro_host.append(mod.check_recurring_tasks())
    assert erstellt_pro_host[0] == [text]
    assert erstellt_pro_host[1] == []
    assert erstellt_pro_host[2] == []
    assert count_tasks(shared_db) == 1


def test_check_recurring_tasks_geteilte_konfig_zeitfenster(tmp_path, monkeypatch):
    """Geteilte Konfiguration + geteilte DB: nur der erste Host laeuft.

    Nach dem ersten Lauf aktualisiert das Modul last_run in der geteilten
    Konfiguration; Host 2 und 3 sind deshalb nicht mehr faellig und
    erstellen nichts (Faelligkeits-Skip statt Duplikat-SKIP).
    """
    text = "Recurring: Backup"
    geteilt_dir = tmp_path / "geteilt"
    geteilt_dir.mkdir()
    shared_cfg = geteilt_dir / "config.json"
    shared_db = geteilt_dir / "bach.db"
    write_config(shared_cfg, make_entry(text, "backup", last_run=OLD_LAST_RUN))
    erstellt_pro_host = []
    for host in HOSTS:
        _, db = prepare_host(
            tmp_path, monkeypatch, host,
            shared_config=shared_cfg, shared_db=shared_db,
        )
        erstellt_pro_host.append(mod.check_recurring_tasks())
    assert [len(erstellt) for erstellt in erstellt_pro_host] == [1, 0, 0]
    assert count_tasks(shared_db) == 1


def test_list_recurring_tasks_cross_host(tmp_path, monkeypatch):
    """Faelligkeit wird je Host unabhaengig ausgewertet (Host 2 frisch, 1 und 3 alt)."""
    text = "Recurring: Backup"
    frisch_index = 1
    for index, host in enumerate(HOSTS):
        if index == frisch_index:
            last_run = datetime.datetime.now().isoformat()
        else:
            last_run = OLD_LAST_RUN
        prepare_host(
            tmp_path, monkeypatch, host,
            entry=make_entry(text, "backup", last_run=last_run),
        )
        info = mod.list_recurring_tasks()["backup"]
        assert info["is_due"] is (index != frisch_index)
        assert info["last_run"] == last_run
