#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Testweite Isolation der BACH-Datenbank + produktiver ~/.bach-Pfade.

hub.bach_paths loest Pfade zuerst ueber Env-Vars auf (BACH_DB, BACH_BACKUPS_DIR).
Ohne diese Isolation laufen Tests, die App/Database/Backup ohne eigenen Pfad
instanziieren (z. B. TestApp.test_db_lazy), gegen die ECHTE Produktiv-DB
~/.bach/bach.db — am 2026-09-01 hat genau das real Migrationen gegen
Produktivdaten ausgefuehrt (PR-#10-Review, Vorfallsbericht; Bereinigung
dokumentiert in T-20260901-620606145).

Die urspruengliche Isolation deckte nur BACH_DB ab. Ein Volllauf am 2026-09-02
zeigte, dass Tests trotzdem in ~/.bach/bach_secrets.json, ~/.bach/backups/
und ~/.bach/plans schreiben, weil secrets_handler.py und plan_agent.py ihre
Pfade nicht (nur) ueber hub.bach_paths aufloesen (T-20260902-646684582).
Deshalb hier zusaetzlich BACH_BACKUPS_DIR/BACH_SECRETS_FILE/BACH_PLANS_DIR
setzen — dieselbe Env-Var-Isolation, nur fuer die drei weiteren Pfade.

Auf Modulebene (nicht als Fixture), damit die Env-Vars gesetzt sind, BEVOR
Testmodule die betroffenen Module importieren. Bereits extern gesetzte Werte
(z. B. CI) werden respektiert (setdefault).
"""

import os
import tempfile
from pathlib import Path

import pytest

_TEST_DB_DIR = Path(tempfile.mkdtemp(prefix="bach_test_db_"))
os.environ.setdefault("BACH_DB", str(_TEST_DB_DIR / "bach_test.db"))
os.environ.setdefault("BACH_BACKUPS_DIR", str(_TEST_DB_DIR / "backups"))
os.environ.setdefault("BACH_SECRETS_FILE", str(_TEST_DB_DIR / "bach_secrets.json"))
os.environ.setdefault("BACH_PLANS_DIR", str(_TEST_DB_DIR / "plans"))


def _snapshot_home_bach():
    """mtime jeder Datei/jedes Ordners unter ~/.bach, sofern vorhanden."""
    root = Path.home() / ".bach"
    if not root.exists():
        return None
    return {str(p.relative_to(root)): p.stat().st_mtime_ns for p in root.rglob("*")}


@pytest.fixture(scope="session", autouse=True)
def _guard_production_bach_dir():
    """Regressionswaechter: kein Testlauf darf ~/.bach anfassen (T-20260902-646684582).

    Ein Volllauf am 2026-09-02 zeigte Schreibzugriffe auf die produktive
    ~/.bach/bach_secrets.json, ~/.bach/backups und ~/.bach/plans trotz
    BACH_DB-Isolation. Diese Fixture haelt die Zusage ein: mtime jeder Datei
    unter ~/.bach muss vor und nach der Suite identisch sein.
    """
    before = _snapshot_home_bach()
    yield
    if before is None:
        return  # ~/.bach existierte vor dem Lauf nicht -> nichts zu vergleichen
    after = _snapshot_home_bach()
    changed = sorted(
        k for k in before.keys() | (after or {}).keys()
        if before.get(k) != (after or {}).get(k)
    )
    assert not changed, (
        f"Testlauf hat produktives ~/.bach veraendert (T-20260902-646684582): {changed}"
    )


@pytest.fixture(autouse=True)
def _reset_lang_cache():
    """Reihenfolge-Leckage ueber hub.lang beheben (T-20260902-646684582, Befund B).

    hub.lang haelt die aufgeloeste Sprache in einem PROZESSWEITEN globalen
    Cache (_t_lang_cache). Jeder Test/Handler, der get_lang()/set_lang() auf
    Spanisch/Englisch stellt (direkt oder ueber einen DB-Wert), aendert diesen
    Cache fuer den Rest der Suite — unabhaengig davon, welche DB spaeter
    genutzt wird. Vor/nach jedem Test zuruecksetzen macht den naechsten Test
    unabhaengig vom vorherigen.
    """
    from hub.lang import clear_t_cache
    clear_t_cache()
    yield
    clear_t_cache()
