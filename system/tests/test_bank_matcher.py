"""Tests für tools/steuer/bank_matcher.py (BACH-Task #1397).

Deckt ab:
- Hilfsfunktionen (tx_hash_of, parse_datum, datum_diff_tage)
- Matching-Logik MATCHED / PARTIAL (0.7/0.6/0.5) / UNMATCHED inkl. Vorzeichen-
  Semantik der Beträge (DBIT ist negativ; Exakt-Match nur bei gleichem Vorzeichen)
- Regeln (regel_trifft) inkl. PARTIAL -> MATCHED (confidence 0.9) im Import
- importiere(): INSERT in steuer_bank_matches, bank_referenz-Update,
  Idempotenz via tx_hash UNIQUE (SKIPPED), dry-run

Der CAMT-Parser wird bei den importiere-Tests per Monkeypatch ersetzt
(bm.CamtParser), damit hier ausschließlich Matching/DB-Seite geprüft wird.
"""

import sqlite3
import sys
from pathlib import Path

import pytest

BACH_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(BACH_ROOT))
sys.path.insert(0, str(BACH_ROOT / "tools" / "steuer"))  # wegen camt_parser-Import

import tools.steuer.bank_matcher as bm


SCHEMA = """
CREATE TABLE steuer_posten (
    id INTEGER PRIMARY KEY,
    username TEXT,
    steuerjahr INTEGER,
    datum TEXT,
    rechnungssteller TEXT,
    bezeichnung TEXT,
    brutto REAL,
    dokument_id INTEGER,
    bank_referenz TEXT
);
CREATE TABLE steuer_bank_match_regeln (
    id INTEGER PRIMARY KEY,
    name TEXT,
    partner_pattern TEXT,
    betrag_min REAL,
    betrag_max REAL,
    datum_toleranz INTEGER DEFAULT 5,
    aktiv INTEGER DEFAULT 1,
    created_at TEXT
);
CREATE TABLE steuer_bank_matches (
    id INTEGER PRIMARY KEY,
    tx_hash TEXT UNIQUE,
    camt_datei TEXT,
    datum TEXT,
    betrag REAL,
    typ TEXT,
    partner TEXT,
    zweck TEXT,
    username TEXT,
    steuerjahr INTEGER,
    dokument_id INTEGER,
    posten_id INTEGER,
    status TEXT,
    confidence REAL,
    regel_id INTEGER,
    created_at TEXT,
    updated_at TEXT
);
"""


def make_tx(**kw):
    """Standard-Transaktion: DBIT (negativ), passt auf den Standard-Posten."""
    tx = {
        "datum": "2025-03-02",
        "betrag": -99.90,
        "typ": "DBIT",
        "partner": "ACME GMBH",
        "zweck": "RE 2025-123",
    }
    tx.update(kw)
    return tx


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    yield c
    c.close()


def insert_posten(conn, **kw):
    felder = {
        "username": "u",
        "steuerjahr": 2025,
        "datum": "2025-03-01",
        "rechnungssteller": "Acme GmbH",
        "bezeichnung": "Beratung",
        "brutto": -99.90,
        "dokument_id": None,
        "bank_referenz": None,
    }
    felder.update(kw)
    cur = conn.execute(
        "INSERT INTO steuer_posten (username, steuerjahr, datum,"
        " rechnungssteller, bezeichnung, brutto, dokument_id, bank_referenz)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (
            felder["username"], felder["steuerjahr"], felder["datum"],
            felder["rechnungssteller"], felder["bezeichnung"],
            felder["brutto"], felder["dokument_id"], felder["bank_referenz"],
        ),
    )
    conn.commit()
    return cur.lastrowid


def lade_posten_rows(conn):
    return conn.execute("SELECT * FROM steuer_posten").fetchall()


def insert_regel(conn, **kw):
    felder = {
        "name": "r",
        "partner_pattern": None,
        "betrag_min": None,
        "betrag_max": None,
        "datum_toleranz": None,
        "aktiv": 1,
    }
    felder.update(kw)
    cur = conn.execute(
        "INSERT INTO steuer_bank_match_regeln (name, partner_pattern,"
        " betrag_min, betrag_max, datum_toleranz, aktiv) VALUES (?,?,?,?,?,?)",
        (
            felder["name"], felder["partner_pattern"], felder["betrag_min"],
            felder["betrag_max"], felder["datum_toleranz"], felder["aktiv"],
        ),
    )
    conn.commit()
    return cur.lastrowid


def regel_row(conn, rid):
    return conn.execute(
        "SELECT * FROM steuer_bank_match_regeln WHERE id=?", (rid,)
    ).fetchone()


# ---------------------------------------------------------------- tx_hash_of

def test_tx_hash_of_16_zeichen_und_stabil():
    tx = make_tx()
    h1 = bm.tx_hash_of(tx)
    h2 = bm.tx_hash_of(dict(tx))
    assert h1 == h2
    assert len(h1) == 16


def test_tx_hash_of_reagiert_auf_betrag():
    assert bm.tx_hash_of(make_tx(betrag=-99.90)) != bm.tx_hash_of(make_tx(betrag=-50.0))


# --------------------------------------------------------------- parse_datum

@pytest.mark.parametrize("wert", [None, "", "x", "31.02.2025"])
def test_parse_datum_ungueltig_liefert_none(wert):
    assert bm.parse_datum(wert) is None


def test_parse_datum_iso():
    d = bm.parse_datum("2025-03-01")
    assert d is not None
    assert (d.year, d.month, d.day) == (2025, 3, 1)


def test_parse_datum_mit_uhrzeit_suffix():
    d = bm.parse_datum("2025-03-01T10:00:00")
    assert d is not None
    assert (d.year, d.month, d.day) == (2025, 3, 1)


# ----------------------------------------------------------- datum_diff_tage

def test_datum_diff_tage_absolut():
    a = bm.parse_datum("2025-03-01")
    b = bm.parse_datum("2025-03-05")
    assert bm.datum_diff_tage(a, b) == 4
    assert bm.datum_diff_tage(b, a) == 4


def test_datum_diff_tage_none_wenn_einer_fehlt():
    a = bm.parse_datum("2025-03-01")
    assert bm.datum_diff_tage(a, None) is None
    assert bm.datum_diff_tage(None, a) is None


# ----------------------------------------------------------------- match_tx

def test_match_tx_matched(conn):
    insert_posten(conn)
    status, conf, posten = bm.match_tx(make_tx(), lade_posten_rows(conn))
    assert status == bm.STATUS_MATCHED
    assert conf == pytest.approx(1.0)
    assert posten is not None
    assert posten["rechnungssteller"] == "Acme GmbH"


def test_match_tx_partial_06_betrag_exakt_und_datum(conn):
    insert_posten(conn)
    # Betrag exakt + Datum nah, Partner fremd -> 0.6
    status, conf, posten = bm.match_tx(make_tx(partner="FREMD AG"), lade_posten_rows(conn))
    assert status == bm.STATUS_PARTIAL
    assert conf == pytest.approx(0.6)
    assert posten is not None


def test_match_tx_partial_07_betrag_nah_und_partner(conn):
    insert_posten(conn)
    # ~1 % Abweichung (0.9/99.9 <= 0.01) + Partner, Datum weit weg -> 0.7
    status, conf, _ = bm.match_tx(
        make_tx(betrag=-99.0, datum="2025-09-09"), lade_posten_rows(conn)
    )
    assert status == bm.STATUS_PARTIAL
    assert conf == pytest.approx(0.7)


def test_match_tx_partial_05_nur_partner(conn):
    insert_posten(conn)
    # Nur Partner (+ Datum nah), Betrag weder exakt noch nah -> 0.5
    status, conf, _ = bm.match_tx(make_tx(betrag=-50.0), lade_posten_rows(conn))
    assert status == bm.STATUS_PARTIAL
    assert conf == pytest.approx(0.5)


def test_match_tx_unmatched(conn):
    insert_posten(conn)
    status, conf, posten = bm.match_tx(
        make_tx(partner="FREMD AG", betrag=-50.0), lade_posten_rows(conn)
    )
    assert status == bm.STATUS_UNMATCHED
    assert conf == 0.0
    assert posten is None


def test_match_tx_betrag_vergleich_mit_vorzeichen(conn):
    # +99.90 ist NICHT exakt zu brutto -99.90 -> kein MATCHED (nur Partner+Datum = 0.5)
    insert_posten(conn)
    status, conf, _ = bm.match_tx(make_tx(betrag=99.90), lade_posten_rows(conn))
    assert status == bm.STATUS_PARTIAL
    assert conf == pytest.approx(0.5)


# -------------------------------------------------------------- regel_trifft

def test_regel_trifft_leere_regel_false(conn):
    r = regel_row(conn, insert_regel(conn))  # alle Kriterien NULL
    assert not bm.regel_trifft(r, make_tx(), None)


def test_regel_trifft_partner_pattern(conn):
    r = regel_row(conn, insert_regel(conn, partner_pattern="acme"))
    assert bm.regel_trifft(r, make_tx(), None)
    assert not bm.regel_trifft(r, make_tx(partner="FREMD AG"), None)


def test_regel_trifft_betrag_grenzen_mit_vorzeichen(conn):
    r = regel_row(conn, insert_regel(conn, betrag_min=-100.0, betrag_max=0.0))
    assert bm.regel_trifft(r, make_tx(), None)                    # -99.9 im Intervall
    assert not bm.regel_trifft(r, make_tx(betrag=-150.0), None)   # unter min
    assert not bm.regel_trifft(r, make_tx(betrag=5.0), None)      # über max


def test_regel_trifft_datum_toleranz(conn):
    insert_posten(conn)  # Posten-Datum 2025-03-01, Tx 2025-03-02 -> diff 1
    posten = lade_posten_rows(conn)[0]
    tx = make_tx()
    r0 = regel_row(conn, insert_regel(conn, partner_pattern="acme", datum_toleranz=0))
    assert not bm.regel_trifft(r0, tx, posten)
    r5 = regel_row(conn, insert_regel(conn, partner_pattern="acme", datum_toleranz=5))
    assert bm.regel_trifft(r5, tx, posten)


def test_regel_trifft_ohne_posten_keine_datumspruefung(conn):
    r = regel_row(conn, insert_regel(conn, partner_pattern="acme", datum_toleranz=0))
    assert bm.regel_trifft(r, make_tx(), None)


# ---------------------------------------------------------------- importiere

@pytest.fixture
def camt_datei(tmp_path):
    p = tmp_path / "kontoauszug.camt"
    p.write_text("<dummy/>", encoding="utf-8")
    return p


def patch_parser(monkeypatch, txs):
    """Ersetzt bm.CamtParser: parse() liefert die übergebenen Transaktionen."""
    class _FakeParser:
        def __init__(self, pfad):
            self.pfad = pfad

        def parse(self):
            return [dict(t) for t in txs]

    monkeypatch.setattr(bm, "CamtParser", _FakeParser)


def count_matches(conn):
    return conn.execute("SELECT COUNT(*) AS c FROM steuer_bank_matches").fetchone()["c"]


def test_importiere_matched_end_to_end(conn, camt_datei, monkeypatch):
    pid = insert_posten(conn, brutto=-99.90, datum="2025-03-01",
                        rechnungssteller="Acme GmbH", dokument_id=42)
    tx = make_tx()
    patch_parser(monkeypatch, [tx])

    stats = bm.importiere(conn, str(camt_datei), "u", 2025, 5, False)

    assert stats["total"] == 1
    assert stats["MATCHED"] == 1
    assert stats["SKIPPED"] == 0

    row = conn.execute("SELECT * FROM steuer_bank_matches").fetchone()
    assert row["status"] == bm.STATUS_MATCHED
    assert row["confidence"] == pytest.approx(1.0)
    assert row["posten_id"] == pid
    assert row["dokument_id"] == 42
    assert row["username"] == "u"
    assert row["steuerjahr"] == 2025
    assert row["camt_datei"] == camt_datei.name
    assert row["betrag"] == pytest.approx(-99.90)
    assert row["tx_hash"] == bm.tx_hash_of(tx)

    # bank_referenz-Rückverweis am Posten (Spalte existiert in der Fixture)
    posten = conn.execute("SELECT * FROM steuer_posten WHERE id=?", (pid,)).fetchone()
    assert posten["bank_referenz"] == bm.tx_hash_of(tx)


def test_importiere_idempotent_zweitlauf_skipped(conn, camt_datei, monkeypatch):
    insert_posten(conn)
    patch_parser(monkeypatch, [make_tx()])
    bm.importiere(conn, str(camt_datei), "u", 2025, 5, False)
    stats2 = bm.importiere(conn, str(camt_datei), "u", 2025, 5, False)
    assert stats2["total"] == 1
    assert stats2["SKIPPED"] == 1
    assert stats2["MATCHED"] == 0
    assert count_matches(conn) == 1


def test_importiere_dry_run_schreibt_nichts(conn, camt_datei, monkeypatch):
    insert_posten(conn)
    patch_parser(monkeypatch, [make_tx()])
    stats = bm.importiere(conn, str(camt_datei), "u", 2025, 5, True)
    assert stats["MATCHED"] == 1
    assert count_matches(conn) == 0


def test_importiere_partial_wird_per_regel_gematcht(conn, camt_datei, monkeypatch):
    pid = insert_posten(conn)  # brutto -99.90, Datum 2025-03-01
    rid = insert_regel(conn, name="Fremd-Regel", partner_pattern="fremd",
                       datum_toleranz=10)
    # Betrag exakt + Datum nah, Partner fremd -> zunächst PARTIAL 0.6,
    # Regel "fremd" trifft -> MATCHED 0.9 mit regel_id
    patch_parser(monkeypatch, [make_tx(partner="FREMD AG")])
    stats = bm.importiere(conn, str(camt_datei), "u", 2025, 5, False)
    assert stats["MATCHED"] == 1
    row = conn.execute("SELECT * FROM steuer_bank_matches").fetchone()
    assert row["status"] == bm.STATUS_MATCHED
    assert row["confidence"] == pytest.approx(0.9)
    assert row["regel_id"] == rid
    assert row["posten_id"] == pid


def test_importiere_partial_ohne_regel(conn, camt_datei, monkeypatch):
    insert_posten(conn)
    # Betrag exakt + Datum nah, Partner fremd, keine Regel -> PARTIAL 0.6
    patch_parser(monkeypatch, [make_tx(partner="FREMD AG")])
    stats = bm.importiere(conn, str(camt_datei), "u", 2025, 5, False)
    assert stats["PARTIAL"] == 1
    assert len(stats["partials"]) == 1
    row = conn.execute("SELECT * FROM steuer_bank_matches").fetchone()
    assert row["status"] == bm.STATUS_PARTIAL
    assert row["regel_id"] is None


def test_importiere_unmatched(conn, camt_datei, monkeypatch):
    insert_posten(conn)
    patch_parser(monkeypatch, [make_tx(partner="FREMD AG", betrag=-12.34,
                                       datum="2025-08-01")])
    stats = bm.importiere(conn, str(camt_datei), "u", 2025, 5, False)
    assert stats["UNMATCHED"] == 1
    row = conn.execute("SELECT * FROM steuer_bank_matches").fetchone()
    assert row["status"] == bm.STATUS_UNMATCHED
    assert row["posten_id"] is None
    assert row["dokument_id"] is None
