#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.py — Kernlogik des steuer-assistent Moduls
================================================

PRIVAT — nicht veröffentlichen (rechtliche Prüfung ausstehend).

Extrahiert aus BACH agents/_experts/steuer/ (MIT).
Eigener SQLite-Store; kein Zugriff auf bach.db.

Copyright (c) 2026 ellmos / BACH Contributors — MIT License
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import re
import sqlite3
import stat
import sys
import tempfile
import zipfile
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Store-Pfad (userneutral)
# ---------------------------------------------------------------------------

def _store_path(cli_override: str | None = None) -> Path:
    """Gibt einen aufgelösten Store-Pfad im Benutzerverzeichnis zurück."""
    configured = cli_override or os.environ.get("STEUER_ASSISTENT_DB")
    raw_path = Path(configured).expanduser() if configured else Path.home() / ".steuer-assistent" / "steuer.db"
    path = raw_path.resolve(strict=False)
    _require_user_path(path, "Der Store")
    return path


def _require_user_path(path: Path, label: str) -> Path:
    """Verhindert, dass sensible Daten ausserhalb des Benutzerprofils landen."""
    home = Path.home().resolve(strict=False)
    try:
        path.resolve(strict=False).relative_to(home)
    except ValueError as exc:
        raise ValueError(f"{label} muss im Benutzerverzeichnis liegen.") from exc
    return path


def _validate_iso_date(value: str) -> str:
    if not isinstance(value, str) or len(value) != 10:
        raise ValueError("Datum muss ein gültiges ISO-Datum YYYY-MM-DD sein.")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("Datum muss ein gültiges ISO-Datum YYYY-MM-DD sein.") from exc
    if parsed.isoformat() != value:
        raise ValueError("Datum muss ein gültiges ISO-Datum YYYY-MM-DD sein.")
    return value


def _validate_year(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("Jahr muss eine vierstellige Ganzzahl sein.")
    try:
        date(value, 1, 1)
    except ValueError as exc:
        raise ValueError("Jahr muss eine vierstellige Ganzzahl sein.") from exc
    if value < 1000:
        raise ValueError("Jahr muss eine vierstellige Ganzzahl sein.")
    return value


def _money_to_cents(value: object) -> tuple[int, float]:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Betrag muss eine positive Zahl mit höchstens zwei Nachkommastellen sein.") from exc
    if not amount.is_finite() or amount <= 0 or amount.as_tuple().exponent < -2:
        raise ValueError("Betrag muss eine positive Zahl mit höchstens zwei Nachkommastellen sein.")
    cents = int(amount * 100)
    if cents > 9_223_372_036_854_775_807:
        raise ValueError("Betrag überschreitet den unterstützten Wertebereich.")
    return cents, cents / 100


def _optional_text(value: Optional[str], *, max_length: int) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if "\x00" in text or len(text) > max_length:
        raise ValueError(f"Text darf höchstens {max_length} Zeichen und kein NUL-Zeichen enthalten.")
    return text


def _csv_safe(value: object) -> object:
    """Neutralisiert Formeleinstiege beim Oeffnen der CSV in Tabellenkalkulationen."""
    if not isinstance(value, str):
        return value
    if value[:1] in ("\t", "\r", "\n") or value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS werbungskosten_kategorien (
    kategorie    TEXT PRIMARY KEY,
    beschreibung TEXT,
    aktiv         INTEGER NOT NULL DEFAULT 1 CHECK (aktiv IN (0, 1))
);

CREATE TABLE IF NOT EXISTS belege (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    nummer      TEXT NOT NULL UNIQUE,
    datum       TEXT NOT NULL CHECK (datum GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    kategorie   TEXT NOT NULL,
    betrag_eur  REAL NOT NULL,
    betrag_cent INTEGER NOT NULL CHECK (betrag_cent > 0),
    notiz       TEXT,
    beleg_datei TEXT,
    erstellt_am TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (kategorie) REFERENCES werbungskosten_kategorien(kategorie)
);

CREATE TABLE IF NOT EXISTS beleg_sequences (
    tag        TEXT PRIMARY KEY,
    last_value INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS export_runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    jahr          INTEGER NOT NULL,
    datei         TEXT NOT NULL,
    erzeugt_am    TEXT NOT NULL DEFAULT (datetime('now')),
    anzahl_belege INTEGER NOT NULL,
    summe_eur     REAL NOT NULL,
    summe_cent    INTEGER NOT NULL
);
"""

_KATEGORIEN_SEED = [
    ("Arbeitsmittel",  "Vom Nutzer erfasste Arbeitsmittel", 1),
    ("Fahrtkosten",    "Vom Nutzer erfasste berufliche Fahrten", 1),
    ("Fortbildung",    "Vom Nutzer erfasste Fortbildungen", 1),
    ("Homeoffice",     "Vom Nutzer erfasste Homeoffice-Aufwendungen", 1),
    ("Kommunikation",  "Vom Nutzer erfasste berufliche Kommunikation", 1),
    ("Sonstiges",      "Vom Nutzer sonstig erfasste Werbungskosten", 1),
]


# ---------------------------------------------------------------------------
# SteuerAssistent
# ---------------------------------------------------------------------------

class SteuerAssistent:
    """Private Beleg-Arbeitsunterlage ohne Steuerberatung oder ELSTER-Übermittlung."""

    def __init__(self, db_path: str | Path | None = None):
        self.db_path = _store_path(str(db_path) if db_path else None)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.db_path.parent, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
        except OSError:
            pass
        self._conn: sqlite3.Connection | None = None

    # ------------------------------------------------------------------
    # Verbindung
    # ------------------------------------------------------------------

    def connect(self) -> sqlite3.Connection:
        if self._conn is None:
            conn = sqlite3.connect(str(self.db_path), timeout=5.0)
            try:
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA busy_timeout = 5000")
                conn.execute("PRAGMA foreign_keys = ON")
                conn.execute("PRAGMA secure_delete = ON")
                conn.execute("PRAGMA trusted_schema = OFF")
                self._conn = conn
                self._init_schema()
                try:
                    os.chmod(self.db_path, stat.S_IRUSR | stat.S_IWUSR)
                except OSError:
                    pass
            except Exception:
                conn.close()
                self._conn = None
                raise
        return self._conn

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "SteuerAssistent":
        self.connect()
        return self

    def __exit__(self, *_) -> None:
        self.close()

    def _init_schema(self) -> None:
        conn = self._conn
        conn.executescript(_SCHEMA)

        columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(belege)").fetchall()
        }
        if "betrag_cent" not in columns:
            conn.execute("ALTER TABLE belege ADD COLUMN betrag_cent INTEGER")
        conn.execute(
            "UPDATE belege SET betrag_cent = CAST(ROUND(betrag_eur * 100) AS INTEGER) "
            "WHERE betrag_cent IS NULL"
        )

        category_columns = {
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info(werbungskosten_kategorien)"
            ).fetchall()
        }
        if "aktiv" not in category_columns:
            conn.execute(
                "ALTER TABLE werbungskosten_kategorien "
                "ADD COLUMN aktiv INTEGER NOT NULL DEFAULT 1"
            )

        export_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(export_runs)").fetchall()
        }
        if "summe_cent" not in export_columns:
            conn.execute("ALTER TABLE export_runs ADD COLUMN summe_cent INTEGER")
        conn.execute(
            "UPDATE export_runs SET summe_cent = CAST(ROUND(summe_eur * 100) AS INTEGER) "
            "WHERE summe_cent IS NULL"
        )

        # Die Seed-Texte enthalten bewusst keine Aussage zur Abziehbarkeit.
        conn.executemany(
            """
            INSERT INTO werbungskosten_kategorien (kategorie, beschreibung, aktiv)
            VALUES (?, ?, ?)
            ON CONFLICT(kategorie) DO UPDATE SET
                beschreibung = excluded.beschreibung,
                aktiv = excluded.aktiv
            """,
            _KATEGORIEN_SEED,
        )

        # Bestehende Nummern initialisieren die monotone Tagessequenz.
        maxima: dict[str, int] = {}
        for row in conn.execute("SELECT nummer FROM belege"):
            match = re.fullmatch(r"B-(\d{8})-(\d+)", row["nummer"])
            if match:
                tag, raw_seq = match.groups()
                maxima[tag] = max(maxima.get(tag, 0), int(raw_seq))
        for tag, last_value in maxima.items():
            conn.execute(
                """
                INSERT INTO beleg_sequences (tag, last_value) VALUES (?, ?)
                ON CONFLICT(tag) DO UPDATE SET
                    last_value = MAX(beleg_sequences.last_value, excluded.last_value)
                """,
                (tag, last_value),
            )
        conn.commit()

    # ------------------------------------------------------------------
    # Beleg-Nummer (B-YYYYMMDD-NNN)
    # ------------------------------------------------------------------

    @staticmethod
    def _reserve_beleg_nummer(conn: sqlite3.Connection, datum: str) -> str:
        tag = datum.replace("-", "")
        conn.execute(
            "INSERT OR IGNORE INTO beleg_sequences (tag, last_value) VALUES (?, 0)",
            (tag,),
        )
        conn.execute(
            "UPDATE beleg_sequences SET last_value = last_value + 1 WHERE tag = ?",
            (tag,),
        )
        seq = conn.execute(
            "SELECT last_value FROM beleg_sequences WHERE tag = ?", (tag,)
        ).fetchone()[0]
        return f"B-{tag}-{seq:03d}"

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def add_beleg(
        self,
        kategorie: str,
        betrag_eur: object,
        datum: Optional[str] = None,
        notiz: Optional[str] = None,
        beleg_datei: Optional[str] = None,
    ) -> dict:
        """Erfasst eine vom Nutzer eingeordnete private Belegposition."""
        if datum is None:
            datum = date.today().isoformat()
        datum = _validate_iso_date(datum)
        cents, normalized_eur = _money_to_cents(betrag_eur)
        kategorie = str(kategorie).strip()
        notiz = _optional_text(notiz, max_length=4000)

        conn = self.connect()
        known = conn.execute(
            "SELECT 1 FROM werbungskosten_kategorien WHERE kategorie = ? AND aktiv = 1",
            (kategorie,),
        ).fetchone()
        if not known:
            raise ValueError("Unbekannte Kategorie. Bitte eine vordefinierte Kategorie verwenden.")

        stored_receipt: Optional[str] = None
        if beleg_datei:
            try:
                receipt = Path(beleg_datei).expanduser().resolve(strict=True)
            except OSError as exc:
                raise ValueError("Die Beleg-Datei muss eine vorhandene Datei sein.") from exc
            _require_user_path(receipt, "Die Beleg-Datei")
            if not receipt.is_file():
                raise ValueError("Die Beleg-Datei muss eine vorhandene Datei sein.")
            stored_receipt = str(receipt.relative_to(Path.home().resolve(strict=False)))

        conn.execute("BEGIN IMMEDIATE")
        try:
            nummer = self._reserve_beleg_nummer(conn, datum)
            conn.execute(
                """
                INSERT INTO belege
                    (nummer, datum, kategorie, betrag_eur, betrag_cent, notiz, beleg_datei)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (nummer, datum, kategorie, normalized_eur, cents, notiz, stored_receipt),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        return {
            "nummer": nummer,
            "datum": datum,
            "kategorie": kategorie,
            "betrag_eur": normalized_eur,
            "notiz": notiz,
        }

    def list_belege(
        self,
        jahr: Optional[int] = None,
        kategorie: Optional[str] = None,
    ) -> list[dict]:
        conn = self.connect()
        sql = "SELECT * FROM belege WHERE 1=1"
        params: list = []
        if jahr is not None:
            jahr = _validate_year(jahr)
            sql += " AND strftime('%Y', datum) = ?"
            params.append(str(jahr))
        if kategorie:
            sql += " AND kategorie = ?"
            params.append(kategorie)
        sql += " ORDER BY datum ASC"
        rows = conn.execute(sql, params).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["betrag_eur"] = item["betrag_cent"] / 100
            result.append(item)
        return result

    def get_beleg(self, nummer: str) -> Optional[dict]:
        conn = self.connect()
        row = conn.execute("SELECT * FROM belege WHERE nummer = ?", (nummer,)).fetchone()
        if not row:
            return None
        item = dict(row)
        item["betrag_eur"] = item["betrag_cent"] / 100
        return item

    def delete_beleg(self, nummer: str) -> bool:
        conn = self.connect()
        cur = conn.execute("DELETE FROM belege WHERE nummer = ?", (nummer,))
        conn.commit()
        return cur.rowcount > 0

    # ------------------------------------------------------------------
    # Werbungskosten-Aggregation
    # ------------------------------------------------------------------

    def werbungskosten(self, jahr: int) -> dict:
        """Aggregiert die vom Nutzer als Werbungskosten erfassten Positionen."""
        jahr = _validate_year(jahr)
        conn = self.connect()
        unknown = conn.execute(
            """
            SELECT COUNT(*)
            FROM belege b
            LEFT JOIN werbungskosten_kategorien k ON b.kategorie = k.kategorie
            WHERE strftime('%Y', b.datum) = ?
              AND (k.kategorie IS NULL OR k.aktiv != 1)
            """,
            (str(jahr),),
        ).fetchone()[0]
        if unknown:
            raise ValueError(
                "Der Datenbestand enthält unbekannte Kategorien; Aggregation wurde abgebrochen."
            )
        rows = conn.execute(
            """
            SELECT b.kategorie, SUM(b.betrag_cent) AS summe_cent, COUNT(*) AS anzahl
            FROM belege b
            JOIN werbungskosten_kategorien k ON b.kategorie = k.kategorie
            WHERE strftime('%Y', b.datum) = ? AND k.aktiv = 1
            GROUP BY b.kategorie
            ORDER BY summe_cent DESC
            """,
            (str(jahr),),
        ).fetchall()
        categories = [
            {
                "kategorie": row["kategorie"],
                "summe": row["summe_cent"] / 100,
                "anzahl": row["anzahl"],
            }
            for row in rows
        ]
        total_cents = sum(row["summe_cent"] for row in rows)
        return {
            "jahr": jahr,
            "gesamt_eur": total_cents / 100,
            "kategorien": categories,
        }

    # ------------------------------------------------------------------
    # Export-Bundle (private Arbeitsunterlage, kein amtliches Format)
    # ------------------------------------------------------------------

    def export_steuerunterlagen(self, jahr: int, out_path: str | Path | None = None) -> Path:
        """Erstellt ein lokales ZIP als private Arbeitsunterlage."""
        jahr = _validate_year(jahr)
        if out_path is None:
            out_path = self.db_path.parent / f"STEUER_UNTERLAGEN_{jahr}.zip"
        out_path = Path(out_path).expanduser().resolve(strict=False)
        _require_user_path(out_path, "Der Export")
        if out_path.suffix.lower() != ".zip":
            raise ValueError("Der Exportpfad muss auf .zip enden.")
        if out_path.exists():
            raise FileExistsError(f"Exportdatei existiert bereits: {out_path.name}")
        out_path.parent.mkdir(parents=True, exist_ok=True)

        belege = self.list_belege(jahr=jahr)
        agg = self.werbungskosten(jahr)

        # CSV
        csv_buf = io.StringIO()
        writer = csv.DictWriter(
            csv_buf,
            fieldnames=["nummer", "datum", "kategorie", "betrag_eur", "notiz"],
            extrasaction="ignore",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(
            {key: _csv_safe(value) for key, value in beleg.items()}
            for beleg in belege
        )

        # Zusammenfassung
        lines = [
            f"PRIVATE ARBEITSUNTERLAGE: ERFASSTE WERBUNGSKOSTEN {jahr}",
            "=" * 60,
            "",
        ]
        for k in agg["kategorien"]:
            lines.append(f"  {k['kategorie']:<20} {k['anzahl']:>3} Belege   {k['summe']:>9.2f} EUR")
        lines += ["", f"  {'GESAMT':<20} {sum(k['anzahl'] for k in agg['kategorien']):>3} Belege   {agg['gesamt_eur']:>9.2f} EUR"]
        lines += [
            "",
            "Die Einordnung stammt vom Nutzer und ist keine steuerliche Prüfung.",
            f"Erzeugt: {datetime.now().isoformat(timespec='seconds')}",
        ]
        summary = "\n".join(lines)

        notice = (
            "PRIVATE STEUER-ARBEITSUNTERLAGE\n"
            "================================\n\n"
            "Dieses ZIP ist kein ELSTER- oder Finanzamt-Übermittlungsformat und nicht zur direkten Übermittlung bestimmt.\n"
            "Es führt ausschließlich die vom Nutzer erfassten Angaben auf.\n"
            "Es ersetzt weder Steuerberatung noch die Prüfung der Abziehbarkeit.\n"
            "Für eine elektronische Abgabe oder Belegnachreichung sind die offiziellen ELSTER-Wege zu verwenden.\n"
        )

        temp_name: Optional[str] = None
        try:
            with tempfile.NamedTemporaryFile(
                prefix=".steuer-export-",
                suffix=".tmp",
                dir=out_path.parent,
                delete=False,
            ) as handle:
                temp_name = handle.name

            with zipfile.ZipFile(temp_name, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("HINWEIS.txt", notice)
                zf.writestr(f"belege_{jahr}.csv", "\ufeff" + csv_buf.getvalue())
                zf.writestr(f"zusammenfassung_{jahr}.txt", summary)

            with open(temp_name, "r+b") as handle:
                os.fsync(handle.fileno())

            # Hardlink-Publikation ist auf demselben Dateisystem atomar und
            # scheitert, wenn der Zielname zwischenzeitlich angelegt wurde.
            try:
                os.link(temp_name, out_path)
            except FileExistsError as exc:
                raise FileExistsError(
                    f"Exportdatei existiert bereits: {out_path.name}"
                ) from exc
            except OSError as exc:
                raise RuntimeError(
                    "Der Export konnte auf diesem Dateisystem nicht atomar veröffentlicht werden."
                ) from exc
            conn = self.connect()
            try:
                conn.execute(
                    """
                    INSERT INTO export_runs
                        (jahr, datei, anzahl_belege, summe_eur, summe_cent)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        jahr,
                        out_path.name,
                        len(belege),
                        agg["gesamt_eur"],
                        int(agg["gesamt_eur"] * 100),
                    ),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                out_path.unlink(missing_ok=True)
                raise
        finally:
            if temp_name:
                Path(temp_name).unlink(missing_ok=True)
        return out_path

    def export_finanzamt(self, jahr: int, out_path: str | Path | None = None) -> Path:
        """Rueckwaertskompatibler Alias; erzeugt ebenfalls nur eine Arbeitsunterlage."""
        return self.export_steuerunterlagen(jahr, out_path)

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def status(self) -> dict:
        conn = self.connect()
        total = conn.execute("SELECT COUNT(*) FROM belege").fetchone()[0]
        exporte = conn.execute("SELECT COUNT(*) FROM export_runs").fetchone()[0]
        return {
            "db_path": str(self.db_path),
            "anzahl_belege": total,
            "anzahl_exporte": exporte,
        }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="steuer-assistent",
        description="Private Beleg-Arbeitsunterlage (keine Steuerberatung)",
    )
    parser.add_argument(
        "--store",
        help="SQLite-Datenbank im Benutzerverzeichnis (überschreibt STEUER_ASSISTENT_DB)",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # add
    p_add = sub.add_parser("add", help="Beleg hinzufügen")
    p_add.add_argument("--kategorie", required=True)
    p_add.add_argument("--betrag", required=True, help="Positiver Euro-Betrag mit maximal zwei Nachkommastellen")
    p_add.add_argument("--datum", help="ISO-Datum (Standard: heute)")
    p_add.add_argument("--notiz")
    p_add.add_argument("--datei", help="Pfad zur Beleg-Datei (lokal)")

    # list
    p_list = sub.add_parser("list", help="Belege anzeigen")
    p_list.add_argument("--jahr", type=int)
    p_list.add_argument("--kategorie")
    p_list.add_argument(
        "--mit-notiz",
        action="store_true",
        help="Vertrauliche Notiz explizit mit ausgeben",
    )

    # werbungskosten
    p_wb = sub.add_parser("werbungskosten", help="Werbungskosten aggregieren")
    p_wb.add_argument("--jahr", type=int, default=date.today().year)

    # export
    p_exp = sub.add_parser("export", help="Private Steuer-Arbeitsunterlage exportieren")
    p_exp.add_argument("--jahr", type=int, default=date.today().year)
    p_exp.add_argument(
        "--out",
        help="ZIP im Benutzerverzeichnis (Standard: ~/.steuer-assistent/STEUER_UNTERLAGEN_<jahr>.zip)",
    )

    # status
    p_status = sub.add_parser("status", help="Store-Status anzeigen")
    p_status.add_argument(
        "--mit-pfad",
        action="store_true",
        help="Vertraulichen absoluten Store-Pfad explizit mit ausgeben",
    )

    args = parser.parse_args(argv)

    try:
        with SteuerAssistent(db_path=args.store) as sa:
            if args.cmd == "add":
                b = sa.add_beleg(
                    kategorie=args.kategorie,
                    betrag_eur=args.betrag,
                    datum=args.datum,
                    notiz=args.notiz,
                    beleg_datei=args.datei,
                )
                print(f"Beleg {b['nummer']} hinzugefügt: {b['betrag_eur']:.2f} EUR ({b['kategorie']})")

            elif args.cmd == "list":
                belege = sa.list_belege(jahr=args.jahr, kategorie=args.kategorie)
                if not belege:
                    print("Keine Belege gefunden.")
                else:
                    for beleg in belege:
                        line = (
                            f"  {beleg['nummer']}  {beleg['datum']}  "
                            f"{beleg['kategorie']:<20}  {beleg['betrag_eur']:>8.2f} EUR"
                        )
                        if args.mit_notiz:
                            line += f"  {beleg['notiz'] or ''}"
                        print(line)

            elif args.cmd == "werbungskosten":
                agg = sa.werbungskosten(args.jahr)
                print(f"\nVom Nutzer erfasste Werbungskosten {agg['jahr']}")
                print("-" * 50)
                for k in agg["kategorien"]:
                    print(f"  {k['kategorie']:<22} {k['anzahl']:>3} Belege   {k['summe']:>9.2f} EUR")
                print("-" * 50)
                print(f"  {'GESAMT':<22} {sum(k['anzahl'] for k in agg['kategorien']):>3} Belege   {agg['gesamt_eur']:>9.2f} EUR\n")

            elif args.cmd == "export":
                out = sa.export_steuerunterlagen(args.jahr, out_path=args.out)
                print(f"Private Arbeitsunterlage erstellt: {out.name}")

            elif args.cmd == "status":
                status = sa.status()
                if args.mit_pfad:
                    print(f"  Store     : {status['db_path']}")
                print(f"  Belege    : {status['anzahl_belege']}")
                print(f"  Exporte   : {status['anzahl_exporte']}")
    except (ValueError, FileExistsError, RuntimeError) as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 2
    except (OSError, sqlite3.Error):
        print("Fehler: Lokaler Datei- oder Datenbankzugriff fehlgeschlagen.", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
