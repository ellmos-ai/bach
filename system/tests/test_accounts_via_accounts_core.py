# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""D-20260903-003 = A: gui/server.py und hub/steuer.py duerfen bank_accounts nur noch
ueber accounts_core.AccountStore anfassen, kein rohes SQL mehr selbst schreiben.

Zwei Dinge werden geprueft:
1. Verhalten unveraendert: die vier /api/financial/bank-accounts-Endpunkte und der
   CAMT-Saldenimport wirken exakt wie vor der Umstellung (gleiche JSON-Form, gleiche
   Datenbankwirkung) -- nur der Aufrufweg ist jetzt AccountStore statt Inline-SQL.
2. Waechter: keine rohe bank_accounts-SQL mehr im Quelltext dieser beiden Dateien
   (T-20260903-836395493, Punkt 2 des Auftrags -- "der eigentliche Punkt").
"""
import re
import sqlite3
import sys
from pathlib import Path

import pytest

BACH_ROOT = Path(__file__).parent.parent
if str(BACH_ROOT) not in sys.path:
    sys.path.insert(0, str(BACH_ROOT))

from gui import server
from hub.steuer import SteuerHandler

SCHEMA_SQL = (BACH_ROOT / "data" / "schema" / "schema.sql").read_text(encoding="utf-8")


@pytest.fixture
def bach_db(tmp_path, monkeypatch):
    """Echtes BACH-Schema (inkl. bank_accounts) in einer tmp-DB; Server zeigt darauf."""
    db_path = tmp_path / "bach.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    conn.close()
    monkeypatch.setattr(server, "BACH_DB", db_path)
    monkeypatch.setattr(server, "USER_DB", db_path)
    return db_path


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    return TestClient(server.app, raise_server_exceptions=False)


# ═══════════════════════════════════════════════════════════════
# gui/server.py: /api/financial/bank-accounts via AccountStore
# ═══════════════════════════════════════════════════════════════


class TestBankAccountsEndpoints:
    def test_create_list_update_delete_roundtrip(self, client, bach_db):
        resp = client.post("/api/financial/bank-accounts", json={
            "name": "Girokonto", "bank_name": "Sparkasse", "iban": "DE89370400440532013000",
            "bic": "COBADEFFXXX", "account_type": "girokonto", "notes": "Test",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        account_id = body["id"]
        assert account_id

        resp = client.get("/api/financial/bank-accounts")
        assert resp.json()["success"] is True
        accounts = resp.json()["accounts"]
        assert len(accounts) == 1
        assert accounts[0]["name"] == "Girokonto"
        assert accounts[0]["iban"] == "DE89370400440532013000"

        resp = client.put(f"/api/financial/bank-accounts/{account_id}", json={
            "name": "Girokonto neu", "bank_name": "Sparkasse", "iban": "DE89370400440532013000",
            "bic": "COBADEFFXXX", "account_type": "girokonto", "notes": None,
        })
        assert resp.json() == {"success": True}
        accounts = client.get("/api/financial/bank-accounts").json()["accounts"]
        assert accounts[0]["name"] == "Girokonto neu"

        resp = client.delete(f"/api/financial/bank-accounts/{account_id}")
        assert resp.json() == {"success": True}
        assert client.get("/api/financial/bank-accounts").json()["accounts"] == []

    def test_list_error_shape_on_missing_db(self, client, tmp_path, monkeypatch):
        """Fehlerform bleibt erhalten: success False + leere accounts-Liste."""
        monkeypatch.setattr(server, "BACH_DB", tmp_path / "does-not-exist.db")
        resp = client.get("/api/financial/bank-accounts")
        body = resp.json()
        assert body["success"] is False
        assert body["accounts"] == []


# ═══════════════════════════════════════════════════════════════
# hub/steuer.py: CAMT-Saldenimport via AccountStore
# ═══════════════════════════════════════════════════════════════


class TestPersistCamtBalancesViaAccountsCore:
    def test_insert_and_update_by_iban(self, bach_db):
        lines = SteuerHandler._persist_camt_balances(bach_db, [
            {"iban": "DE89 3704 0044 0532 0130 00", "balance": 100.0, "currency": "EUR", "date": "2026-09-01"},
        ])
        assert any("neu angelegt" in line for line in lines)

        conn = sqlite3.connect(bach_db)
        row = conn.execute("SELECT balance, iban FROM bank_accounts").fetchone()
        assert row == (100.0, "DE89370400440532013000")  # IBAN normalisiert (Leerzeichen raus)
        conn.close()

        lines = SteuerHandler._persist_camt_balances(bach_db, [
            {"iban": "DE89370400440532013000", "balance": 250.5, "currency": "EUR", "date": "2026-09-02"},
        ])
        assert any("aktualisiert" in line for line in lines)
        conn = sqlite3.connect(bach_db)
        assert conn.execute("SELECT COUNT(*) FROM bank_accounts").fetchone()[0] == 1
        assert conn.execute("SELECT balance FROM bank_accounts").fetchone()[0] == 250.5
        conn.close()

    def test_empty_balances_is_noop(self, bach_db):
        lines = SteuerHandler._persist_camt_balances(bach_db, [])
        # accounts_core schreibt echte Umlaute ("unverändert" statt "unveraendert") --
        # kein Verhaltensbruch, keine bestehende BACH-Test haengt an der ASCII-Form.
        assert lines == ["[WARN] Keine Salden in der Datei - bank_accounts unverändert."]


# ═══════════════════════════════════════════════════════════════
# Waechter: kein rohes bank_accounts-SQL mehr in gui/server.py oder hub/steuer.py
# ═══════════════════════════════════════════════════════════════

RAW_SQL_RE = re.compile(
    r"\b(SELECT|INSERT\s+INTO|UPDATE|DELETE\s+FROM)\b[^;\"']*\bbank_accounts\b",
    re.IGNORECASE,
)
GUARDED_FILES = (
    BACH_ROOT / "gui" / "server.py",
    BACH_ROOT / "hub" / "steuer.py",
)


class TestNoRawBankAccountsSql:
    """T-20260903-836395493: nach der Umstellung darf kein SQL-Statement gegen
    bank_accounts mehr direkt in diesen Dateien stehen -- nur noch ueber
    accounts_core.AccountStore. Ein spaeter neu eingefuegtes 'SELECT ... FROM
    bank_accounts' (oder INSERT/UPDATE/DELETE) laesst diesen Test rot werden."""

    @pytest.mark.parametrize("path", GUARDED_FILES, ids=lambda p: p.name)
    def test_file_contains_no_raw_bank_accounts_sql(self, path):
        text = path.read_text(encoding="utf-8")
        hits = RAW_SQL_RE.findall(text)
        assert not hits, f"{path.name} enthaelt rohe bank_accounts-SQL: {hits}"

    def test_guard_actually_detects_raw_sql(self):
        """Selbsttest des Waechters: ohne die Migration haette er angeschlagen."""
        sample = 'cursor.execute("SELECT * FROM bank_accounts ORDER BY name")'
        assert RAW_SQL_RE.search(sample)
