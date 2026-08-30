#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests fuer SteuerHandler

Testet: Properties, Helpers, Init/List/Profile/Watch (Filesystem),
        Posten CRUD, Beleg-Ops, Check, Export (DB-basiert)
"""

import sys
import sqlite3
import pytest
from pathlib import Path
from datetime import datetime

BACH_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(BACH_ROOT))

from hub.steuer import SteuerHandler

SCHEMA_SQL = (BACH_ROOT / "data" / "schema" / "schema_steuer.sql").read_text(encoding="utf-8")


@pytest.fixture
def tmp_steuer(tmp_path):
    """Erstellt eine minimale Steuer-Umgebung (Filesystem + DB)."""
    system_dir = tmp_path / "system"
    system_dir.mkdir()
    (system_dir / "help").mkdir()
    (system_dir / "help" / "steuer.txt").write_text("STEUER HILFE", encoding="utf-8")

    user_dir = tmp_path / "user" / "steuer"
    user_dir.mkdir(parents=True)
    (user_dir / "profile").mkdir()
    (user_dir / "watch").mkdir()

    db_path = tmp_path / "bach.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(SCHEMA_SQL)
    # Spalten die per steuer_sync._ensure_schema() hinzugefuegt werden
    for col in ["anbieter TEXT", "bemerkung TEXT", "updated_at TEXT", "dist_type INTEGER DEFAULT 0"]:
        try:
            conn.execute(f"ALTER TABLE steuer_dokumente ADD COLUMN {col}")
        except sqlite3.OperationalError:
            pass
    conn.execute(
        "INSERT INTO steuer_profile (username, name, beruf) VALUES (?, ?, ?)",
        ("user", "Test User", "Entwickler"),
    )
    conn.commit()
    conn.close()

    return system_dir, db_path


@pytest.fixture
def handler(tmp_steuer):
    system_dir, db_path = tmp_steuer
    h = SteuerHandler(system_dir)
    h.db_path = db_path
    h.steuer_dir = system_dir.parent / "user" / "steuer"
    h.profile_dir = h.steuer_dir / "profile"
    h.watch_dir = h.steuer_dir / "watch"
    return h


@pytest.fixture
def seeded_handler(tmp_steuer):
    """Handler mit Testdaten in DB."""
    system_dir, db_path = tmp_steuer
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    conn.execute(
        "INSERT INTO steuer_dokumente (id, username, steuerjahr, dateiname, status, anbieter) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (1, "user", 2025, "Otto_2025-02-05_Rechnung.pdf", "ERFASST", "Otto"),
    )
    conn.execute(
        "INSERT INTO steuer_dokumente (id, username, steuerjahr, dateiname, status, anbieter) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (2, "user", 2025, "Amazon_2025-03-10_Rechnung.pdf", "NICHT_ERFASST", "Amazon"),
    )
    conn.execute(
        "INSERT INTO steuer_posten "
        "(username, steuerjahr, dokument_id, postennr, bezeichnung, datum, brutto, netto, "
        "liste, anteil, absetzbar_brutto, absetzbar_netto, rechnungssteller, dateiname) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("user", 2025, 1, 1, "Fachbuch Python", "2025-02-05", 39.99, 33.61,
         "WERBUNGSKOSTEN", 1.0, 39.99, 33.61, "Otto", "Otto_2025-02-05_Rechnung.pdf"),
    )
    conn.execute(
        "INSERT INTO steuer_posten "
        "(username, steuerjahr, dokument_id, postennr, bezeichnung, datum, brutto, netto, "
        "liste, anteil, absetzbar_brutto, absetzbar_netto, rechnungssteller, dateiname) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("user", 2025, 1, 2, "USB Kabel", "2025-02-05", 9.99, 8.39,
         "GEMISCHTE", 0.5, 4.995, 4.195, "Otto", "Otto_2025-02-05_Rechnung.pdf"),
    )
    conn.execute(
        "INSERT INTO steuer_posten "
        "(username, steuerjahr, dokument_id, postennr, bezeichnung, datum, brutto, netto, "
        "liste, anteil, absetzbar_brutto, absetzbar_netto, rechnungssteller, dateiname) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("user", 2025, 1, 3, "Handyhuelle", "2025-02-05", 15.00, 12.60,
         "VERWORFEN", 0.0, 0.0, 0.0, "Otto", "Otto_2025-02-05_Rechnung.pdf"),
    )
    conn.commit()
    conn.close()

    h = SteuerHandler(system_dir)
    h.db_path = db_path
    h.steuer_dir = system_dir.parent / "user" / "steuer"
    h.profile_dir = h.steuer_dir / "profile"
    h.watch_dir = h.steuer_dir / "watch"
    return h


# ================================================================
# PROPERTIES
# ================================================================

class TestProperties:
    def test_profile_name(self, handler):
        assert handler.profile_name == "steuer"

    def test_target_file(self, handler):
        assert handler.target_file == handler.steuer_dir

    def test_operations(self, handler):
        ops = handler.get_operations()
        assert "status" in ops
        assert "posten" in ops
        assert "beleg" in ops
        assert "export" in ops
        assert "check" in ops
        assert "eigenbeleg" in ops


# ================================================================
# HELPERS
# ================================================================

class TestHelpers:
    def test_parse_posten_id_valid(self):
        assert SteuerHandler._parse_posten_id("42-3") == (42, 3)
        assert SteuerHandler._parse_posten_id("1-1") == (1, 1)

    def test_parse_posten_id_invalid(self):
        assert SteuerHandler._parse_posten_id("abc") is None
        assert SteuerHandler._parse_posten_id("42") is None
        assert SteuerHandler._parse_posten_id("a-b") is None

    def test_calc_jahresbeitrag_monatlich(self, handler):
        assert handler._calc_jahresbeitrag(100.0, "monatlich") == 1200.0

    def test_calc_jahresbeitrag_quartalsweise(self, handler):
        assert handler._calc_jahresbeitrag(300.0, "quartalsweise") == 1200.0

    def test_calc_jahresbeitrag_halbjaehrlich(self, handler):
        assert handler._calc_jahresbeitrag(600.0, "halbjaehrlich") == 1200.0

    def test_calc_jahresbeitrag_jaehrlich(self, handler):
        assert handler._calc_jahresbeitrag(1200.0, "jaehrlich") == 1200.0

    def test_calc_jahresbeitrag_none(self, handler):
        assert handler._calc_jahresbeitrag(None, "monatlich") == 0.0

    def test_calc_jahresbeitrag_default(self, handler):
        assert handler._calc_jahresbeitrag(100.0, None) == 1200.0


# ================================================================
# ROUTING
# ================================================================

class TestRouting:
    def test_help(self, handler):
        ok, msg = handler.handle("help", [])
        assert ok
        assert "STEUER" in msg

    def test_unknown_op_falls_through_to_status(self, handler):
        ok, msg = handler.handle("nonexistent", [])
        assert ok
        assert "STEUER" in msg


# ================================================================
# CAMT.053 IMPORT
# ================================================================

class TestCamtImport:
    def test_dry_run_uses_public_parser_and_reads_one_transaction(
        self, handler, tmp_path
    ):
        camt_path = tmp_path / "statement.xml"
        camt_path.write_text(
            """<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02">
  <BkToCstmrStmt><Stmt>
    <Acct><Id><IBAN>DE001234</IBAN></Id></Acct>
    <Ntry>
      <Amt Ccy="EUR">12.34</Amt><CdtDbtInd>CRDT</CdtDbtInd>
      <BookgDt><Dt>2026-08-26</Dt></BookgDt>
      <NtryDtls><TxDtls><RltdPties><Dbtr><Nm>Test GmbH</Nm></Dbtr></RltdPties>
        <RmtInf><Ustrd>Testzahlung</Ustrd></RmtInf>
      </TxDtls></NtryDtls>
    </Ntry>
  </Stmt></BkToCstmrStmt>
</Document>
""",
            encoding="utf-8",
        )

        ok, msg = handler.handle("import", ["camt", str(camt_path)], dry_run=True)

        assert ok is True
        assert "[DRY-RUN] Würde 1 Transaktionen" in msg
        assert "keine Salden gefunden" in msg

    def test_external_entity_is_rejected(self, handler, tmp_path):
        camt_path = tmp_path / "entity.xml"
        camt_path.write_text(
            """<?xml version="1.0"?>
<!DOCTYPE Document [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02">
  <BkToCstmrStmt><Stmt><Acct><Id><IBAN>&xxe;</IBAN></Id></Acct></Stmt></BkToCstmrStmt>
</Document>
""",
            encoding="utf-8",
        )

        ok, msg = handler.handle("import", ["camt", str(camt_path)], dry_run=True)

        assert ok is False
        assert "Fehler beim Import" in msg

# ================================================================
# INIT YEAR
# ================================================================

class TestInitYear:
    def test_no_args(self, handler):
        ok, msg = handler.handle("init", [])
        assert not ok
        assert "fehlt" in msg.lower()

    def test_invalid_year(self, handler):
        ok, msg = handler.handle("init", ["abc"])
        assert not ok
        assert "Ungueltig" in msg

    def test_short_year(self, handler):
        ok, msg = handler.handle("init", ["25"])
        assert not ok

    def test_success(self, handler):
        ok, msg = handler.handle("init", ["2025"])
        assert ok
        assert "2025" in msg
        year_dir = handler.steuer_dir / "2025"
        assert year_dir.exists()
        assert (year_dir / "Werbungskosten" / "belege" / "_bundles").exists()

    def test_duplicate_year(self, handler):
        handler.handle("init", ["2025"])
        ok, msg = handler.handle("init", ["2025"])
        assert not ok
        assert "existiert" in msg

    def test_dry_run(self, handler):
        ok, msg = handler.handle("init", ["2025"], dry_run=True)
        assert ok
        assert "DRY-RUN" in msg
        assert not (handler.steuer_dir / "2025").exists()

    def test_minimal_files_created(self, handler):
        handler.handle("init", ["2025"])
        wk = handler.steuer_dir / "2025" / "Werbungskosten"
        assert (wk / "WERBUNGSKOSTEN.txt").exists()
        assert (wk / "GEMISCHTE_POSTEN.txt").exists()


# ================================================================
# PROFILE
# ================================================================

class TestProfile:
    def test_profile_list_empty(self, handler):
        ok, msg = handler.handle("profile", ["list"])
        assert ok

    def test_profile_list_with_data(self, handler):
        (handler.profile_dir / "test.txt").write_text("Testprofil", encoding="utf-8")
        ok, msg = handler.handle("profile", ["list"])
        assert ok
        assert "test" in msg.lower()


# ================================================================
# WATCH
# ================================================================

class TestWatch:
    def test_watch_list_empty(self, handler):
        ok, msg = handler.handle("watch", ["list"])
        assert ok
        assert "Keine" in msg

    def test_watch_add_no_path(self, handler):
        ok, msg = handler.handle("watch", ["add"])
        assert not ok
        assert "fehlt" in msg.lower()

    def test_watch_add_nonexistent(self, handler):
        ok, msg = handler.handle("watch", ["add", "/no/such/path"])
        assert not ok
        assert "existiert nicht" in msg

    def test_watch_add_success(self, handler, tmp_path):
        watch_path = tmp_path / "inbox"
        watch_path.mkdir()
        ok, msg = handler.handle("watch", ["add", str(watch_path)])
        assert ok
        assert "hinzugefuegt" in msg

    def test_watch_add_duplicate(self, handler, tmp_path):
        watch_path = tmp_path / "inbox"
        watch_path.mkdir()
        handler.handle("watch", ["add", str(watch_path)])
        ok, msg = handler.handle("watch", ["add", str(watch_path)])
        assert not ok
        assert "bereits" in msg

    def test_watch_remove(self, handler, tmp_path):
        watch_path = tmp_path / "inbox"
        watch_path.mkdir()
        handler.handle("watch", ["add", str(watch_path)])
        ok, msg = handler.handle("watch", ["remove", str(watch_path)])
        assert ok
        assert "entfernt" in msg

    def test_watch_remove_nonexistent(self, handler):
        ok, msg = handler.handle("watch", ["remove", "/no/such/path"])
        assert not ok

    def test_watch_list_after_add(self, handler, tmp_path):
        watch_path = tmp_path / "inbox"
        watch_path.mkdir()
        handler.handle("watch", ["add", str(watch_path)])
        ok, msg = handler.handle("watch", ["list"])
        assert ok
        assert "AKTIV" in msg


# ================================================================
# SCAN
# ================================================================

class TestScan:
    def test_scan_no_watches(self, handler):
        ok, msg = handler.handle("scan", [])
        assert ok
        assert "Keine aktiven" in msg

    def test_scan_with_files(self, handler, tmp_path):
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        (inbox / "rechnung.pdf").write_text("dummy", encoding="utf-8")
        (inbox / "beleg.jpg").write_text("dummy", encoding="utf-8")
        (inbox / "readme.txt").write_text("dummy", encoding="utf-8")
        handler.handle("watch", ["add", str(inbox)])
        ok, msg = handler.handle("scan", [])
        assert ok
        assert "Dokumente" in msg
        assert "rechnung.pdf" in msg


# ================================================================
# LIST
# ================================================================

class TestList:
    def test_list_no_year(self, handler):
        ok, msg = handler.handle("list", [])
        assert ok

    def test_list_with_year(self, handler):
        handler.handle("init", ["2025"])
        ok, msg = handler.handle("list", ["--jahr", "2025"])
        assert ok
        assert "LISTEN" in msg
        assert "2025" in msg

    def test_list_specific_not_found(self, handler):
        handler.handle("init", ["2025"])
        ok, msg = handler.handle("list", ["--liste", "NONEXISTENT", "--jahr", "2025"])
        assert not ok
        assert "nicht gefunden" in msg


# ================================================================
# POSTEN - LIST
# ================================================================

class TestPostenList:
    def test_empty(self, handler):
        ok, msg = handler.handle("posten", ["list"])
        assert ok
        assert "Keine" in msg

    def test_with_data(self, seeded_handler):
        ok, msg = seeded_handler.handle("posten", ["list"])
        assert ok
        assert "Fachbuch" in msg
        assert "USB Kabel" in msg

    def test_filter_liste_w(self, seeded_handler):
        ok, msg = seeded_handler.handle("posten", ["list", "--liste", "W"])
        assert ok
        assert "Fachbuch" in msg
        assert "USB Kabel" not in msg

    def test_filter_liste_g(self, seeded_handler):
        ok, msg = seeded_handler.handle("posten", ["list", "--liste", "G"])
        assert ok
        assert "USB Kabel" in msg
        assert "Fachbuch" not in msg

    def test_filter_belegnr(self, seeded_handler):
        ok, msg = seeded_handler.handle("posten", ["list", "--belegnr", "1"])
        assert ok
        assert "Fachbuch" in msg

    def test_filter_steller(self, seeded_handler):
        ok, msg = seeded_handler.handle("posten", ["list", "--steller", "Otto"])
        assert ok
        assert "Fachbuch" in msg

    def test_limit(self, seeded_handler):
        ok, msg = seeded_handler.handle("posten", ["list", "--limit", "1"])
        assert ok
        assert "1 Eintraege" in msg


# ================================================================
# POSTEN - SHOW
# ================================================================

class TestPostenShow:
    def test_no_id(self, handler):
        ok, msg = handler.handle("posten", ["show"])
        assert not ok
        assert "fehlt" in msg.lower()

    def test_invalid_id(self, handler):
        ok, msg = handler.handle("posten", ["show", "abc"])
        assert not ok

    def test_nonexistent(self, seeded_handler):
        ok, msg = seeded_handler.handle("posten", ["show", "99-99"])
        assert not ok
        assert "nicht gefunden" in msg

    def test_success(self, seeded_handler):
        ok, msg = seeded_handler.handle("posten", ["show", "1-1"])
        assert ok
        assert "Fachbuch Python" in msg
        assert "39.99" in msg
        assert "WERBUNGSKOSTEN" in msg

    def test_direct_id_routing(self, seeded_handler):
        ok, msg = seeded_handler.handle("posten", ["1-1"])
        assert ok
        assert "Fachbuch Python" in msg


# ================================================================
# POSTEN - ADD
# ================================================================

class TestPostenAdd:
    def test_no_belegnr(self, handler):
        ok, msg = handler.handle("posten", ["add"])
        assert not ok
        assert "Belegnummer fehlt" in msg

    def test_missing_bezeichnung(self, handler):
        ok, msg = handler.handle("posten", ["add", "--belegnr", "1"])
        assert not ok
        assert "erforderlich" in msg

    def test_beleg_not_found(self, seeded_handler):
        ok, msg = seeded_handler.handle("posten", [
            "add", "--belegnr", "999", "--bezeichnung", "Test", "--brutto", "10"
        ])
        assert not ok
        assert "nicht gefunden" in msg

    def test_success(self, seeded_handler):
        ok, msg = seeded_handler.handle("posten", [
            "add", "--belegnr", "1", "--bezeichnung", "Neuer Posten",
            "--brutto", "25.50", "--liste", "W"
        ])
        assert ok
        assert "erstellt" in msg
        assert "1-4" in msg

        conn = sqlite3.connect(str(seeded_handler.db_path))
        row = conn.execute(
            "SELECT * FROM steuer_posten WHERE dokument_id=1 AND postennr=4"
        ).fetchone()
        conn.close()
        assert row is not None

    def test_dry_run(self, seeded_handler):
        ok, msg = seeded_handler.handle("posten", [
            "add", "--belegnr", "1", "--bezeichnung", "Test",
            "--brutto", "10", "--liste", "W"
        ], dry_run=True)
        assert ok
        assert "DRY-RUN" in msg

    def test_comma_brutto(self, seeded_handler):
        ok, msg = seeded_handler.handle("posten", [
            "add", "--belegnr", "1", "--bezeichnung", "Komma-Test",
            "--brutto", "12,50", "--liste", "W"
        ])
        assert ok
        assert "12.50" in msg


# ================================================================
# POSTEN - EDIT
# ================================================================

class TestPostenEdit:
    def test_no_id(self, handler):
        ok, msg = handler.handle("posten", ["edit"])
        assert not ok
        assert "fehlt" in msg.lower()

    def test_no_changes(self, seeded_handler):
        ok, msg = seeded_handler.handle("posten", ["edit", "1-1"])
        assert not ok
        assert "Keine Aenderungen" in msg

    def test_nonexistent(self, seeded_handler):
        ok, msg = seeded_handler.handle("posten", ["edit", "99-99", "--bezeichnung", "X"])
        assert not ok
        assert "nicht gefunden" in msg

    def test_edit_bezeichnung(self, seeded_handler):
        ok, msg = seeded_handler.handle("posten", [
            "edit", "1-1", "--bezeichnung", "Neuer Name"
        ])
        assert ok
        assert "aktualisiert" in msg

        conn = sqlite3.connect(str(seeded_handler.db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT bezeichnung FROM steuer_posten WHERE dokument_id=1 AND postennr=1"
        ).fetchone()
        conn.close()
        assert row["bezeichnung"] == "Neuer Name"

    def test_edit_brutto(self, seeded_handler):
        ok, msg = seeded_handler.handle("posten", [
            "edit", "1-1", "--brutto", "50.00"
        ])
        assert ok
        conn = sqlite3.connect(str(seeded_handler.db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT brutto FROM steuer_posten WHERE dokument_id=1 AND postennr=1"
        ).fetchone()
        conn.close()
        assert abs(row["brutto"] - 50.0) < 0.01

    def test_dry_run(self, seeded_handler):
        ok, msg = seeded_handler.handle("posten", [
            "edit", "1-1", "--bezeichnung", "Test"
        ], dry_run=True)
        assert ok
        assert "DRY-RUN" in msg


# ================================================================
# POSTEN - SEARCH
# ================================================================

class TestPostenSearch:
    def test_no_term(self, handler):
        ok, msg = handler.handle("posten", ["search"])
        assert not ok
        assert "Suchbegriff fehlt" in msg

    def test_no_results(self, seeded_handler):
        ok, msg = seeded_handler.handle("posten", ["search", "XXXXXXX"])
        assert ok
        assert "Keine" in msg

    def test_by_bezeichnung(self, seeded_handler):
        ok, msg = seeded_handler.handle("posten", ["search", "Python"])
        assert ok
        assert "Fachbuch" in msg

    def test_by_anbieter(self, seeded_handler):
        ok, msg = seeded_handler.handle("posten", ["search", "Otto"])
        assert ok
        assert "Fachbuch" in msg


# ================================================================
# POSTEN - MOVE
# ================================================================

class TestPostenMove:
    def test_missing_args(self, handler):
        ok, msg = handler.handle("posten", ["move"])
        assert not ok
        assert "fehlen" in msg.lower()

    def test_invalid_liste(self, seeded_handler):
        ok, msg = seeded_handler.handle("posten", ["move", "1-1", "X"])
        assert not ok
        assert "Ungueltige" in msg

    def test_nonexistent(self, seeded_handler):
        ok, msg = seeded_handler.handle("posten", ["move", "99-99", "W"])
        assert not ok
        assert "nicht gefunden" in msg

    def test_move_to_gemischte(self, seeded_handler):
        ok, msg = seeded_handler.handle("posten", ["move", "1-1", "G", "--anteil", "0.7"])
        assert ok
        assert "GEMISCHTE" in msg

        conn = sqlite3.connect(str(seeded_handler.db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT liste, anteil FROM steuer_posten WHERE dokument_id=1 AND postennr=1"
        ).fetchone()
        conn.close()
        assert row["liste"] == "GEMISCHTE"
        assert abs(row["anteil"] - 0.7) < 0.01

    def test_move_to_verworfen(self, seeded_handler):
        ok, msg = seeded_handler.handle("posten", ["move", "1-1", "V"])
        assert ok
        conn = sqlite3.connect(str(seeded_handler.db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT liste, absetzbar_brutto FROM steuer_posten WHERE dokument_id=1 AND postennr=1"
        ).fetchone()
        conn.close()
        assert row["liste"] == "VERWORFEN"
        assert row["absetzbar_brutto"] == 0.0


# ================================================================
# POSTEN - DELETE
# ================================================================

class TestPostenDelete:
    def test_no_id(self, handler):
        ok, msg = handler.handle("posten", ["delete"])
        assert not ok

    def test_nonexistent(self, seeded_handler):
        ok, msg = seeded_handler.handle("posten", ["delete", "99-99", "--force"])
        assert not ok

    def test_requires_force(self, seeded_handler):
        ok, msg = seeded_handler.handle("posten", ["delete", "1-3"])
        assert not ok
        assert "--force" in msg

    def test_success(self, seeded_handler):
        ok, msg = seeded_handler.handle("posten", ["delete", "1-3", "--force"])
        assert ok
        assert "geloescht" in msg
        conn = sqlite3.connect(str(seeded_handler.db_path))
        row = conn.execute(
            "SELECT * FROM steuer_posten WHERE dokument_id=1 AND postennr=3"
        ).fetchone()
        conn.close()
        assert row is None


# ================================================================
# EXPORT
# ================================================================

class TestExport:
    def test_unknown_format(self, handler):
        handler.handle("init", ["2025"])
        ok, msg = handler.handle("export", ["--jahr", "2025", "--format", "xyz"])
        assert ok
        assert "nicht unterstuetzt" in msg

    def test_txt_export(self, handler):
        handler.handle("init", ["2025"])
        ok, msg = handler.handle("export", ["--jahr", "2025", "--format", "txt"])
        assert ok
        assert "TXT-Export" in msg

    def test_csv_export_empty(self, seeded_handler):
        (seeded_handler.steuer_dir / "2025").mkdir(parents=True, exist_ok=True)
        ok, msg = seeded_handler.handle("export", ["--jahr", "2025", "--format", "csv"])
        assert ok


# ================================================================
# CHECK
# ================================================================

class TestCheck:
    def test_check_runs(self, seeded_handler):
        ok, msg = seeded_handler.handle("check", ["--jahr", "2025"])
        assert isinstance(ok, bool)


# ================================================================
# STATUS
# ================================================================

class TestStatus:
    def test_status_basic(self, handler):
        ok, msg = handler.handle("status", [])
        assert ok
        assert "STEUER" in msg

    def test_status_with_year(self, handler):
        handler.handle("init", ["2025"])
        ok, msg = handler.handle("status", ["--jahr", "2025"])
        assert ok
        assert "2025" in msg


# ================================================================
# ENSURE ACTIVE YEAR
# ================================================================

class TestEnsureActiveYear:
    def test_auto_creates_year(self, handler):
        ok, year = handler._ensure_active_year("2025")
        assert ok
        assert year == "2025"
        assert (handler.steuer_dir / "2025").exists()

    def test_existing_year(self, handler):
        handler.handle("init", ["2025"])
        ok, year = handler._ensure_active_year("2025")
        assert ok
        assert year == "2025"

    def test_fallback_to_latest(self, handler):
        handler.handle("init", ["2024"])
        ok, year = handler._ensure_active_year("2023")
        assert ok
        assert year == "2024"
