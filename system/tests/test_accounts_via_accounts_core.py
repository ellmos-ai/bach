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

Welle 3 (Task 1220) erweitert beides um die Salden-Kette, die Welle 2 delegiert,
aber deren Produzent fehlte: Der D-013-Fix (9ff3df2) mit CamtParser.parse_balances()
lebte nur in der gitignorierten Betriebsinstallation; im oeffentlichen Baum fiel der
Saldenimport seitdem LUTLOS aus (hasattr-Fallback -> balances=[]). Jetzt:
3. parse_balances() existiert im oeffentlichen Baum und liefert exakt den von
   accounts_core dokumentierten Dict-Contract (IBAN, balance, currency, date).
4. Ende-zu-Ende: _import_camt -> parse_balances -> AccountStore.persist_camt_balances
   -> bank_accounts (UPDATE per normalisierter IBAN, sonst INSERT), inkl. dry-run.
5. Waechter: camt_parser.py bleibt reiner XML-Produzent (kein sqlite, keine
   bank_accounts-SQL); steuer.py ruft parse_balances() direkt, ohne hasattr-Fallback,
   der die tote Kette wieder verschleiern koennte.
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
    # Welle 3: auch der CAMT-Produzent darf kein bank_accounts-SQL enthalten
    # (Persistenz lebt allein in accounts_core.AccountStore).
    BACH_ROOT / "tools" / "steuer" / "camt_parser.py",
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


# ═══════════════════════════════════════════════════════════════
# Welle 3 (Task 1220): CAMT-Salden-Kette -- Produzent, Ende-zu-Ende, Waechter
# ═══════════════════════════════════════════════════════════════

CAMT_NS = "urn:iso:std:iso:20022:tech:xsd:camt.053.001.02"


def camt_xml(
    namespace: str = CAMT_NS,
    with_clbd: bool = True,
    with_opbd: bool = True,
    with_iban: bool = True,
    with_dt_tm: bool = False,
    dbit: bool = False,
    nested_stmt: bool = False,
) -> str:
    """Synthetischer CAMT.053-Kontoauszug; ein Statement, ein CLBD-Saldo."""
    ns_attr = f' xmlns="{namespace}"' if namespace else ""
    iban_block = "<Id><IBAN>DE89370400440532013000</IBAN></Id>" if with_iban else \
        "<Id><Othr><Id>ACC-77</Id></Othr></Id>"
    cdt_dbt = "DBIT" if dbit else "CRDT"
    date_block = "<Dt><DtTm>2026-09-10T18:30:00Z</DtTm></Dt>" if with_dt_tm else \
        "<Dt><Dt>2026-09-10</Dt></Dt>"
    opbd = (
        "<Bal><Tp><CdOrPrtry><Cd>OPBD</Cd></CdOrPrtry></Tp>"
        "<Amt Ccy='EUR'>1000.00</Amt><CdtDbtInd>CRDT</CdtDbtInd>"
        "<Dt><Dt>2026-08-31</Dt></Dt></Bal>"
    ) if with_opbd else ""
    clbd = (
        "<Bal><Tp><CdOrPrtry><Cd>CLBD</Cd></CdOrPrtry></Tp>"
        "<Amt Ccy='EUR'>1234.56</Amt>"
        f"<CdtDbtInd>{cdt_dbt}</CdtDbtInd>{date_block}</Bal>"
    ) if with_clbd else ""
    stmt = (
        "<Stmt><Id>STMT-001</Id>"
        f"<Acct>{iban_block}<Ccy>EUR</Ccy></Acct>"
        f"{opbd}{clbd}"
        "</Stmt>"
    )
    if nested_stmt:
        body = f"<BkToCstmrStmt><GrpHdr><MsgId>M1</MsgId></GrpHdr>{stmt}</BkToCstmrStmt>"
    else:
        body = stmt
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f"<Document{ns_attr}>{body}</Document>"
    )


@pytest.fixture
def steuer_home(tmp_path):
    """Kanonische BACH-Verzeichnisstruktur mit echtem Schema; Handler zeigt darauf."""
    (tmp_path / "data").mkdir()
    db_path = tmp_path / "data" / "bach.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    conn.close()
    return tmp_path, db_path


@pytest.fixture
def camt_file(tmp_path):
    path = tmp_path / "auszug.xml"
    path.write_text(camt_xml(), encoding="utf-8")
    return path


class TestParseBalances:
    """CamtParser.parse_balances liefert den accounts_core-Contract."""

    def test_contract_shape_matches_accounts_core_docstring(self, camt_file):
        from tools.steuer.camt_parser import CamtParser

        balances = CamtParser(camt_file).parse_balances()
        assert len(balances) == 1
        bal = balances[0]
        assert set(bal) == {"iban", "balance", "currency", "date"}
        assert bal["iban"] == "DE89370400440532013000"
        assert bal["balance"] == 1234.56
        assert bal["currency"] == "EUR"
        assert bal["date"] == "2026-09-10"

    def test_opbd_ignored_clbd_wins_last_one_counts(self, tmp_path):
        """OPBD (Oeffnungssaldo) zaehlt nicht; bei mehreren CLBD zaehlt das letzte."""
        path = tmp_path / "auszug.xml"
        second_clbd = (
            "<Bal><Tp><CdOrPrtry><Cd>CLBD</Cd></CdOrPrtry></Tp>"
            "<Amt Ccy='EUR'>99.00</Amt><CdtDbtInd>CRDT</CdtDbtInd>"
            "<Dt><Dt>2026-09-12</Dt></Dt></Bal>"
        )
        path.write_text(
            camt_xml().replace("</Stmt>", f"{second_clbd}</Stmt>"),
            encoding="utf-8",
        )
        from tools.steuer.camt_parser import CamtParser

        balances = CamtParser(path).parse_balances()
        assert len(balances) == 1
        assert balances[0]["balance"] == 99.00
        assert balances[0]["date"] == "2026-09-12"

    def test_dbit_negative_and_dtTm_date_part(self, tmp_path):
        """DBIT-Saldo wird negiert; DtTm liefert den Datumsteil (YYYY-MM-DD)."""
        path = tmp_path / "auszug.xml"
        path.write_text(camt_xml(dbit=True, with_dt_tm=True), encoding="utf-8")
        from tools.steuer.camt_parser import CamtParser

        balances = CamtParser(path).parse_balances()
        assert balances[0]["balance"] == -1234.56
        assert balances[0]["date"] == "2026-09-10"

    def test_without_clbd_returns_empty_not_opening_balance(self, tmp_path):
        """Nur OPBD: kein Salden-Eintrag statt falschem Oeffnungssaldo."""
        path = tmp_path / "auszug.xml"
        path.write_text(camt_xml(with_clbd=False), encoding="utf-8")
        from tools.steuer.camt_parser import CamtParser

        assert CamtParser(path).parse_balances() == []

    def test_without_iban_yields_unknown_sentinel(self, tmp_path):
        """Ohne IBAN: UNKNOWN, damit accounts_core mit Warnung ueberspringt."""
        path = tmp_path / "auszug.xml"
        path.write_text(camt_xml(with_iban=False), encoding="utf-8")
        from tools.steuer.camt_parser import CamtParser

        balances = CamtParser(path).parse_balances()
        assert balances[0]["iban"] == "UNKNOWN"

    def test_namespace_autodetection_for_other_camt_version(self, tmp_path):
        """Ns-Anpassung wie in parse(): auch camt.053.001.08-Dateien funktionieren."""
        path = tmp_path / "auszug.xml"
        path.write_text(
            camt_xml(namespace="urn:iso:std:iso:20022:tech:xsd:camt.053.001.08"),
            encoding="utf-8",
        )
        from tools.steuer.camt_parser import CamtParser

        balances = CamtParser(path).parse_balances()
        assert balances[0]["balance"] == 1234.56


class TestCamtImportEndToEnd:
    """_import_camt -> parse_balances -> AccountStore.persist_camt_balances -> bank_accounts."""

    def test_update_existing_and_insert_new(self, steuer_home, camt_file):
        home, db_path = steuer_home
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO bank_accounts (name, iban, balance) "
            "VALUES ('Mein Giro', 'DE89 3704 0044 0532 0130 00', 0.0)"
        )
        conn.commit()
        conn.close()

        ok, msg = SteuerHandler(home).handle("import", ["camt", str(camt_file)])

        assert ok is True
        assert "aktualisiert" in msg
        assert "neu angelegt" not in msg  # bekannte IBAN -> UPDATE, kein Duplikat
        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            "SELECT name, iban, balance, balance_date FROM bank_accounts"
        ).fetchall()
        conn.close()
        assert rows == [("Mein Giro", "DE89 3704 0044 0532 0130 00", 1234.56, "2026-09-10")]

    def test_insert_unknown_iban_creates_masked_camt_import_account(self, steuer_home, camt_file):
        home, db_path = steuer_home
        ok, msg = SteuerHandler(home).handle("import", ["camt", str(camt_file)])
        assert ok is True
        conn = sqlite3.connect(db_path)
        name, iban, balance = conn.execute(
            "SELECT name, iban, balance FROM bank_accounts"
        ).fetchone()
        conn.close()
        assert name.startswith("CAMT-Import")
        assert name.endswith("3000")  # maskiert: nur letzte 4 Zeichen sichtbar
        assert "3000" in name and "*" in name
        assert iban == "DE89370400440532013000"
        assert balance == 1234.56

    def test_dry_run_shows_salden_and_writes_nothing(self, steuer_home, camt_file):
        home, db_path = steuer_home
        ok, msg = SteuerHandler(home).handle(
            "import", ["camt", str(camt_file)], dry_run=True
        )
        assert ok is True
        assert "[DRY-RUN]" in msg
        assert "DE89370400440532013000: 1234.56 EUR (2026-09-10)" in msg
        conn = sqlite3.connect(db_path)
        count = conn.execute("SELECT COUNT(*) FROM bank_accounts").fetchone()[0]
        conn.close()
        assert count == 0

    def test_no_clbd_surfaces_accounts_core_warn_and_writes_nothing(
        self, steuer_home, tmp_path
    ):
        home, db_path = steuer_home
        path = tmp_path / "ohne_clbd.xml"
        path.write_text(camt_xml(with_clbd=False), encoding="utf-8")

        ok, msg = SteuerHandler(home).handle("import", ["camt", str(path)])

        assert ok is True
        assert "Keine Salden" in msg
        conn = sqlite3.connect(db_path)
        count = conn.execute("SELECT COUNT(*) FROM bank_accounts").fetchone()[0]
        conn.close()
        assert count == 0

    def test_unknown_iban_surfaces_skip_warning(self, steuer_home, tmp_path):
        home, db_path = steuer_home
        path = tmp_path / "ohne_iban.xml"
        path.write_text(camt_xml(with_iban=False), encoding="utf-8")

        ok, msg = SteuerHandler(home).handle("import", ["camt", str(path)])

        assert ok is True
        assert "ohne IBAN übersprungen" in msg
        conn = sqlite3.connect(db_path)
        count = conn.execute("SELECT COUNT(*) FROM bank_accounts").fetchone()[0]
        conn.close()
        assert count == 0


class TestWelle3Waechter:
    """Waechter gegen Rueckfall in die tote Kette (D-013-Regressionsschutz)."""

    def test_camt_parser_exposes_parse_balances(self):
        """Der D-013-Produzent existiert im oeffentlichen Baum (tote-Kette-Waechter).

        Vor Welle 3 fehlte die Methode im oeffentlichen Baum, und hasattr-Fallbacks
        liessen den Saldenimport lautlos leer laufen. Ohne diesen Test waere das
        nicht wieder aufgefallen.
        """
        from tools.steuer.camt_parser import CamtParser

        assert callable(getattr(CamtParser, "parse_balances", None))

    def test_steuer_calls_parse_balances_directly_no_hasattr_fallback(self):
        """steuer.py ruft parse_balances() direkt -- kein hasattr-Toleranz-Fallback.

        Ein 'if hasattr(...)' haette die tote Kette 2026 erneut verschleiert:
        bei fehlender Methode laeuft der Import still ohne Salden weiter.
        """
        text = (BACH_ROOT / "hub" / "steuer.py").read_text(encoding="utf-8")
        assert not re.search(r"parse_balances\(\)\s*if\s*hasattr", text), (
            "hasattr-Fallback ueber parse_balances ist zurueckgekehrt -- "
            "die Kette darf nicht lautlos degenerieren duerfen"
        )
        assert re.search(r"parser\.parse_balances\(\)", text), (
            "steuer.py muss parse_balances() direkt aufrufen"
        )

    def test_camt_parser_is_pure_xml_producer(self):
        """camt_parser.py darf weder sqlite importieren noch bank_accounts nennen.

        Der accounts_core-Contract: Der Produzent parst XML und uebergibt Dicts;
        Persistenz lebt ausschliesslich in accounts_core.AccountStore.
        """
        text = (BACH_ROOT / "tools" / "steuer" / "camt_parser.py").read_text(
            encoding="utf-8"
        )
        assert "sqlite" not in text.lower()
        assert "bank_accounts" not in text
        assert not RAW_SQL_RE.search(text)

    def test_guarded_files_include_camt_parser(self):
        """camt_parser.py steht im rohen-SQL-Waechter, nicht nur server.py/steuer.py."""
        assert (BACH_ROOT / "tools" / "steuer" / "camt_parser.py") in GUARDED_FILES
