#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Testweite Isolation der BACH-Datenbank.

hub.bach_paths loest den DB-Pfad zuerst ueber die Env-Var BACH_DB auf.
Ohne diese Isolation laufen Tests, die App/Database ohne eigenen Pfad
instanziieren (z. B. TestApp.test_db_lazy), gegen die ECHTE Produktiv-DB
~/.bach/bach.db — am 2026-09-01 hat genau das real Migrationen gegen
Produktivdaten ausgefuehrt (PR-#10-Review, Vorfallsbericht; Bereinigung
dokumentiert in T-20260901-620606145).

Auf Modulebene (nicht als Fixture), damit die Env-Var gesetzt ist, BEVOR
Testmodule hub.bach_paths importieren. Eine bereits extern gesetzte
BACH_DB (z. B. CI) wird respektiert.
"""

import os
import tempfile
from pathlib import Path

_TEST_DB_DIR = Path(tempfile.mkdtemp(prefix="bach_test_db_"))
os.environ.setdefault("BACH_DB", str(_TEST_DB_DIR / "bach_test.db"))
