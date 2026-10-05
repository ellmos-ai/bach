#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
bank_matcher.py - CAMT-Banktransaktionen gegen Steuer-Posten matchen.

Aufruf (u.a. durch tools/inbox_watcher.py):
    tools/steuer/bank_matcher.py <camt_xml> [--user NAME] [--jahr YYYY]
    tools/steuer/bank_matcher.py --resolve [--user NAME]

Ablauf:
    1. CAMT-XML via camt_parser.CamtParser parsen.
    2. Jede Transaktion erhaelt einen stabilen Hash (tx_hash) -> idempotent:
       bereits bekannte Transaktionen (jeder Status) werden uebersprungen.
    3. Matching gegen offene Steuer-Posten (steuer_posten ohne bank_referenz):
       - MATCHED  (conf 1.0): Betrag exakt (<= 0.01) UND Rechnungssteller
                              (lower) als Substring in Partner+Zweck UND
                              Datumsabstand <= Toleranz (Default 5 Tage)
       - PARTIAL  (conf 0.7): Betrag +/- 1 % UND Partner-Substring
                  (conf 0.6): nur Betrag exakt (Datum ok)
                  (conf 0.5): nur Partner-Substring (Datum ok oder kein Tx-Datum)
       - UNMATCHED (conf 0.0): nichts davon
    4. Aktive Regeln (steuer_bank_match_regeln) koennen einen PARTIAL-Match
       direkt zu MATCHED (conf 0.9) heben.
    5. Ergebnis in steuer_bank_matches persistieren; bei MATCHED wird
       zusaetzlich steuer_posten.bank_referenz = tx_hash gesetzt
       (ausser bei --dry-run).
    6. PARTIAL-Matches koennen interaktiv via --resolve aufgeloest werden.

Benötigte Migration: data/schema/migrations/051_steuer_bank_matches.sql
    (ausfuehren mit: bach update migrations run)
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

try:
    # Direktaufruf: python tools/steuer/bank_matcher.py ...
    from camt_parser import CamtParser
except ImportError:  # Import als Modul aus dem Projekt-Root heraus
    from tools.steuer.camt_parser import CamtParser

try:
    from hub.bach_paths import BACH_DB
except ImportError:  # Direktaufruf: System-Root nicht in sys.path
    _SYSTEM_ROOT = next(
        p for p in Path(__file__).resolve().parents
        if (p / "hub" / "bach_paths.py").exists()
    )
    sys.path.insert(0, str(_SYSTEM_ROOT))
    from hub.bach_paths import BACH_DB

DB_PATH = Path(BACH_DB)

STATUS_MATCHED = "MATCHED"
STATUS_PARTIAL = "PARTIAL"
STATUS_UNMATCHED = "UNMATCHED"


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def tx_hash_of(tx: dict) -> str:
    """Erzeugt den stabilen 16-stelligen Hash-Schluessel einer Transaktion."""
    basis = "|".join([
        str(tx.get("datum", "")),
        str(tx.get("betrag", 0.0)),
        str(tx.get("typ", "")),
        str(tx.get("partner", "")),
        str(tx.get("zweck", "")),
    ])
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


def parse_datum(wert: str | None) -> datetime | None:
    """Parst 'YYYY-MM-DD' (oder ISO-Praefix) nach datetime; None bei Fehlschlag."""
    if not wert:
        return None
    try:
        return datetime.strptime(str(wert).strip()[:10], "%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def datum_diff_tage(a: datetime | None, b: datetime | None) -> int | None:
    """Absolute Differenz in Tagen; None, wenn eines der Daten fehlt."""
    if a is None or b is None:
        return None
    return abs((a - b).days)


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    """Prueft, ob eine Tabelle in der Datenbank existiert."""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,),
    ).fetchone()
    return row is not None


def column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    """Prueft, ob eine Spalte in einer Tabelle existiert (robust gg. Alt-Schemata)."""
    cols = [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]
    return column in cols


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

def lade_kandidaten(conn: sqlite3.Connection, username: str, steuerjahr: int,
                    mit_bank_ref: bool) -> list[sqlite3.Row]:
    """Laedt offene Steuer-Posten (ohne bank_referenz) als Match-Kandidaten."""
    sql = (
        "SELECT id, datum, rechnungssteller, bezeichnung, brutto, dokument_id "
        "FROM steuer_posten WHERE username = ? AND steuerjahr = ?"
    )
    if mit_bank_ref:
        sql += " AND (bank_referenz IS NULL OR bank_referenz = '')"
    return conn.execute(sql, (username, steuerjahr)).fetchall()


def match_tx(tx: dict, kandidaten: list[sqlite3.Row], toleranz: int = 5
             ) -> tuple[str, float, sqlite3.Row | None]:
    """
    Matcht eine Transaktion gegen die Kandidatenliste.

    Rueckgabe: (status, confidence, posten-oder-None).
    """
    text = f"{tx.get('partner', '')} {tx.get('zweck', '')}".lower()
    betrag = float(tx.get("betrag") or 0.0)
    tx_datum = parse_datum(tx.get("datum"))

    best: tuple[str, float, sqlite3.Row | None] = (STATUS_UNMATCHED, 0.0, None)
    for k in kandidaten:
        brutto = float(k["brutto"] or 0.0)
        betrag_exakt = abs(brutto - betrag) <= 0.01
        betrag_nah = brutto != 0 and abs(brutto - betrag) / abs(brutto) <= 0.01
        steller = (k["rechnungssteller"] or "").strip().lower()
        partner_ok = bool(steller) and steller in text
        diff = datum_diff_tage(tx_datum, parse_datum(k["datum"]))
        datum_ok = diff is not None and diff <= toleranz

        if betrag_exakt and partner_ok and datum_ok:
            return (STATUS_MATCHED, 1.0, k)

        cand: tuple[str, float, sqlite3.Row | None] | None = None
        if betrag_nah and partner_ok:
            cand = (STATUS_PARTIAL, 0.7, k)
        elif betrag_exakt and datum_ok:
            cand = (STATUS_PARTIAL, 0.6, k)
        elif partner_ok and (datum_ok or tx_datum is None):
            cand = (STATUS_PARTIAL, 0.5, k)

        if cand is not None and cand[1] > best[1]:
            best = cand
    return best


def lade_regeln(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Laedt aktive Match-Regeln; leere Liste, falls Tabelle fehlt."""
    try:
        return conn.execute(
            "SELECT * FROM steuer_bank_match_regeln WHERE aktiv = 1"
        ).fetchall()
    except sqlite3.Error:
        return []


def regel_trifft(regel: sqlite3.Row, tx: dict, posten: sqlite3.Row | None) -> bool:
    """
    Prueft, ob eine Regel auf Transaktion (und ggf. Posten) zutrifft.

    partner_pattern: Substring (case-insensitiv) in Partner+Zweck; leer = egal.
    betrag_min/betrag_max: Betragsfenster; NULL = egal.
    datum_toleranz: max. Abstand Tx- zu Posten-Datum in Tagen (nur geprueft,
        wenn beide Daten parsebar sind).
    Eine Regel ohne jedes Kriterium trifft nie.
    """
    text = f"{tx.get('partner', '')} {tx.get('zweck', '')}".lower()
    betrag = float(tx.get("betrag") or 0.0)
    hat_kriterium = False

    pattern = (regel["partner_pattern"] or "").strip().lower()
    if pattern:
        hat_kriterium = True
        if pattern not in text:
            return False
    if regel["betrag_min"] is not None:
        hat_kriterium = True
        if betrag < float(regel["betrag_min"]):
            return False
    if regel["betrag_max"] is not None:
        hat_kriterium = True
        if betrag > float(regel["betrag_max"]):
            return False
    if not hat_kriterium:
        return False

    if posten is not None:
        tol = regel["datum_toleranz"]
        diff = datum_diff_tage(parse_datum(tx.get("datum")), parse_datum(posten["datum"]))
        if diff is not None and tol is not None and diff > int(tol):
            return False
    return True


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

def importiere(conn: sqlite3.Connection, camt_xml: str, username: str,
               steuerjahr: int, toleranz: int, dry_run: bool) -> dict:
    """Parst das CAMT-XML, matcht alle Transaktionen und persistiert das Ergebnis."""
    txs = CamtParser(camt_xml).parse()
    stats: dict = {
        "total": len(txs),
        STATUS_MATCHED: 0,
        STATUS_PARTIAL: 0,
        STATUS_UNMATCHED: 0,
        "SKIPPED": 0,
        "partials": [],  # Liste von (tx, posten_id, confidence) fuer den Report
    }

    mit_bank_ref = column_exists(conn, "steuer_posten", "bank_referenz")
    kandidaten = lade_kandidaten(conn, username, steuerjahr, mit_bank_ref)
    regeln = lade_regeln(conn)
    camt_name = Path(camt_xml).name

    for tx in txs:
        th = tx_hash_of(tx)
        bekannt = conn.execute(
            "SELECT id FROM steuer_bank_matches WHERE tx_hash = ?", (th,)
        ).fetchone()
        if bekannt:
            stats["SKIPPED"] += 1
            continue

        status, conf, posten = match_tx(tx, kandidaten, toleranz)

        regel_id = None
        if status == STATUS_PARTIAL:
            for regel in regeln:
                if regel_trifft(regel, tx, posten):
                    status, conf, regel_id = STATUS_MATCHED, 0.9, regel["id"]
                    break

        posten_id = posten["id"] if posten is not None else None
        dokument_id = posten["dokument_id"] if posten is not None else None

        if status == STATUS_MATCHED and posten_id is not None:
            # Verhindert Doppelzuordnung desselben Postens in diesem Lauf.
            kandidaten = [k for k in kandidaten if k["id"] != posten_id]

        if not dry_run:
            conn.execute(
                """
                INSERT OR IGNORE INTO steuer_bank_matches
                    (tx_hash, camt_datei, datum, betrag, typ, partner, zweck,
                     username, steuerjahr, dokument_id, posten_id,
                     status, confidence, regel_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (th, camt_name, str(tx.get("datum", "")),
                 float(tx.get("betrag") or 0.0), str(tx.get("typ", "")),
                 str(tx.get("partner", "")), str(tx.get("zweck", "")),
                 username, steuerjahr, dokument_id, posten_id,
                 status, conf, regel_id),
            )
            if status == STATUS_MATCHED and posten_id is not None and mit_bank_ref:
                conn.execute(
                    "UPDATE steuer_posten SET bank_referenz = ? WHERE id = ?",
                    (th, posten_id),
                )

        stats[status] += 1
        if status == STATUS_PARTIAL:
            stats["partials"].append((tx, posten_id, conf))

    if not dry_run:
        conn.commit()
    return stats


def report(stats: dict, dry_run: bool) -> None:
    """Gibt die Match-Zusammenfassung auf stdout aus."""
    modus = " (DRY-RUN - keine DB-Aenderungen)" if dry_run else ""
    print(f"=== Bank-Matching Report{modus} ===")
    print(f"Transaktionen gesamt      : {stats['total']}")
    print(f"  MATCHED                 : {stats[STATUS_MATCHED]}")
    print(f"  PARTIAL                 : {stats[STATUS_PARTIAL]}")
    print(f"  UNMATCHED               : {stats[STATUS_UNMATCHED]}")
    print(f"  Uebersprungen (bekannt) : {stats['SKIPPED']}")
    if stats["partials"]:
        print("\n--- PARTIAL-Matches (bitte pruefen, ggf. via --resolve) ---")
        for tx, posten_id, conf in stats["partials"]:
            betrag = float(tx.get("betrag") or 0.0)
            partner = (tx.get("partner") or "")[:30]
            print(f"  {tx.get('datum', ''):<10}  {betrag:>10.2f} EUR  "
                  f"{partner:<30}  Vorschlag Posten #{posten_id} "
                  f"(conf {conf:.2f})")


# ---------------------------------------------------------------------------
# PARTIAL-Aufloesung (interaktiv)
# ---------------------------------------------------------------------------

def resolve_partials(conn: sqlite3.Connection, username: str,
                     mit_bank_ref: bool, dry_run: bool) -> int:
    """
    Zeigt offene PARTIAL-Matches und loest sie interaktiv auf.

    [J/y]: MATCHED (conf 1.0), bank_referenz wird gesetzt.
    [n]  : UNMATCHED, posten_id/dokument_id werden zurueckgesetzt.
    [s]  : ueberspringen (bleibt PARTIAL).
    Bei --dry-run wird nur angezeigt, nichts geaendert und nicht gefragt.

    Rueckgabe: Anzahl entschiedener Matches.
    """
    rows = conn.execute(
        """
        SELECT id, tx_hash, datum, betrag, typ, partner, zweck, posten_id
        FROM steuer_bank_matches
        WHERE status = 'PARTIAL' AND username = ?
        ORDER BY datum, id
        """,
        (username,),
    ).fetchall()
    if not rows:
        print(f"Keine offenen PARTIAL-Matches fuer User '{username}'.")
        return 0

    print(f"{len(rows)} PARTIAL-Match(es) offen fuer User '{username}'.\n")
    entschieden = 0
    for r in rows:
        posten = None
        if r["posten_id"] is not None:
            posten = conn.execute(
                "SELECT id, datum, rechnungssteller, bezeichnung, brutto "
                "FROM steuer_posten WHERE id = ?",
                (r["posten_id"],),
            ).fetchone()

        print("-" * 64)
        betrag = float(r["betrag"] or 0.0)
        print(f"Tx #{r['id']}  {r['datum']}  {betrag:>10.2f} EUR  {r['typ']}")
        print(f"  Partner: {r['partner']}")
        print(f"  Zweck  : {(r['zweck'] or '')[:80]}")
        if posten is not None:
            p_brutto = float(posten["brutto"] or 0.0)
            print(f"  Vorschlag Posten #{posten['id']}: {posten['datum']}  "
                  f"{p_brutto:>10.2f} EUR  {posten['rechnungssteller']}  "
                  f"({(posten['bezeichnung'] or '')[:40]})")
        else:
            print("  (kein Posten-Vorschlag hinterlegt)")

        if dry_run:
            continue

        antwort = input("  [J] bestaetigen / [n] ablehnen / [s] ueberspringen: "
                        ).strip().lower()
        if antwort in ("j", "y"):
            conn.execute(
                "UPDATE steuer_bank_matches SET status = 'MATCHED', "
                "confidence = 1.0, updated_at = datetime('now') WHERE id = ?",
                (r["id"],),
            )
            if mit_bank_ref and r["posten_id"] is not None:
                conn.execute(
                    "UPDATE steuer_posten SET bank_referenz = ? WHERE id = ?",
                    (r["tx_hash"], r["posten_id"]),
                )
            entschieden += 1
        elif antwort == "n":
            conn.execute(
                "UPDATE steuer_bank_matches SET status = 'UNMATCHED', "
                "confidence = 0.0, posten_id = NULL, dokument_id = NULL, "
                "updated_at = datetime('now') WHERE id = ?",
                (r["id"],),
            )
            entschieden += 1
        # alles andere: ueberspringen

    if not dry_run:
        conn.commit()
        print(f"\n{entschieden} PARTIAL-Match(es) aufgeloest.")
    return entschieden


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    """CLI-Einstieg. Rueckgabe: Exit-Code (0 ok, 2 Dateifehler, 3 Schemafehler)."""
    ap = argparse.ArgumentParser(
        description="CAMT-Banktransaktionen gegen steuer_posten matchen.",
    )
    ap.add_argument("camt_xml", nargs="?",
                    help="Pfad zur CAMT-053-XML-Datei (entbehrlich bei reinem --resolve)")
    ap.add_argument("--user", default=getpass.getuser(),
                    help="Benutzername (Default: OS-Benutzer)")
    ap.add_argument("--jahr", type=int, default=datetime.now().year,
                    help="Steuerjahr (Default: aktuelles Jahr)")
    ap.add_argument("--toleranz", type=int, default=5,
                    help="Datumstoleranz in Tagen (Default: 5)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Nur analysieren, keine DB-Aenderungen")
    ap.add_argument("--resolve", action="store_true",
                    help="Offene PARTIAL-Matches interaktiv aufloesen")
    args = ap.parse_args(argv)

    if not args.camt_xml and not args.resolve:
        ap.error("camt_xml fehlt (oder --resolve angeben).")

    if args.camt_xml and not Path(args.camt_xml).is_file():
        print(f"FEHLER: CAMT-Datei nicht gefunden: {args.camt_xml}", file=sys.stderr)
        return 2
    if not DB_PATH.is_file():
        print(f"FEHLER: Datenbank nicht gefunden: {DB_PATH}", file=sys.stderr)
        return 2

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        if not table_exists(conn, "steuer_bank_matches"):
            print("FEHLER: Tabelle 'steuer_bank_matches' fehlt. "
                  "Zuerst Migration ausfuehren: bach update migrations run",
                  file=sys.stderr)
            return 3
        mit_bank_ref = column_exists(conn, "steuer_posten", "bank_referenz")

        if args.camt_xml:
            stats = importiere(conn, args.camt_xml, args.user, args.jahr,
                               args.toleranz, args.dry_run)
            report(stats, args.dry_run)
        if args.resolve:
            resolve_partials(conn, args.user, mit_bank_ref, args.dry_run)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())