#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Copyright (c) 2026 BACH Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

"""
VersicherungHandler - Versicherungsverwaltung CLI

Operationen:
  list              Alle Versicherungen anzeigen
  show <id>         Versicherung-Details
  add               Neue Versicherung anlegen
  edit <id>         Versicherung bearbeiten
  delete <id>       Versicherung loeschen (soft-delete via Status)
  status            Dashboard mit Statistiken
  fristen           Kuendigungsfristen anzeigen
  check             Portfolio-Analyse
  claim add         Schadenfall erfassen
  claim list        Schadenfaelle anzeigen
  help              Hilfe anzeigen

Nutzt: bach.db / fin_insurances, fin_insurance_claims, insurance_types
"""

import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Tuple, Optional
from hub.base import BaseHandler


class VersicherungHandler(BaseHandler):

    VALID_STATUS = ["aktiv", "gekuendigt", "beitragsfrei", "ruhend"]
    VALID_ZAHLWEISEN = ["monatlich", "quartalsweise", "halbjaehrlich", "jaehrlich"]

    def __init__(self, base_path: Path):
        super().__init__(base_path)
        self.user_db_path = self._canonical_db

    @property
    def profile_name(self) -> str:
        return "versicherung"

    @property
    def target_file(self) -> Path:
        return self.user_db_path

    def get_operations(self) -> dict:
        return {
            "list": "Alle Versicherungen anzeigen",
            "show": "Versicherung-Details anzeigen",
            "add": "Neue Versicherung anlegen",
            "edit": "Versicherung bearbeiten",
            "delete": "Versicherung deaktivieren (Status -> gekuendigt)",
            "status": "Dashboard mit Statistiken",
            "fristen": "Kuendigungsfristen anzeigen",
            "check": "Portfolio-Analyse",
            "claim": "Schadenfaelle verwalten (add/list)",
            "help": "Hilfe anzeigen",
        }

    def _get_db(self):
        conn = sqlite3.connect(str(self.user_db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def handle(self, operation: str, args: List[str], dry_run: bool = False) -> Tuple[bool, str]:
        if operation == "list":
            return self._list(args)
        elif operation == "show":
            return self._show(args)
        elif operation == "add":
            return self._add(args)
        elif operation == "edit":
            return self._edit(args)
        elif operation == "delete":
            return self._delete(args)
        elif operation == "status":
            return self._status(args)
        elif operation == "fristen":
            return self._fristen(args)
        elif operation == "check":
            return self._check(args)
        elif operation == "claim":
            return self._claim(args)
        elif operation in ("", "help"):
            return self._help()
        else:
            return False, f"Unbekannte Operation: {operation}\nNutze: bach versicherung help"

    # ------------------------------------------------------------------
    # Hilfsmethoden
    # ------------------------------------------------------------------
    def _parse_ids(self, args: List[str]) -> Tuple[List[int], List[str]]:
        ids = []
        rest = []
        for arg in args:
            try:
                ids.append(int(arg))
            except ValueError:
                rest.append(arg)
        return ids, rest

    def _get_arg(self, args: List[str], flag: str) -> Optional[str]:
        for i, a in enumerate(args):
            if a == flag and i + 1 < len(args):
                return args[i + 1]
            if a.startswith(flag + "="):
                return a[len(flag) + 1:]
        return None

    def _parse_date(self, date_str: str) -> Optional[str]:
        """Parse DD.MM.YYYY oder YYYY-MM-DD zu YYYY-MM-DD."""
        for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(date_str, fmt)
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                continue
        return None

    def _format_date(self, date_str: Optional[str]) -> str:
        """Formatiert YYYY-MM-DD zu DD.MM.YYYY fuer Anzeige."""
        if not date_str:
            return "---"
        try:
            dt = datetime.strptime(date_str[:10], "%Y-%m-%d")
            return dt.strftime("%d.%m.%Y")
        except (ValueError, TypeError):
            return date_str

    def _calc_monthly(self, beitrag: Optional[float], zahlweise: Optional[str]) -> float:
        """Berechnet monatlichen Beitrag aus Beitrag + Zahlweise."""
        if not beitrag:
            return 0.0
        zw = (zahlweise or "monatlich").lower()
        if zw == "jaehrlich":
            return beitrag / 12
        elif zw == "quartalsweise":
            return beitrag / 3
        elif zw == "halbjaehrlich":
            return beitrag / 6
        return beitrag  # monatlich

    def _calc_yearly(self, beitrag: Optional[float], zahlweise: Optional[str]) -> float:
        """Berechnet jaehrlichen Beitrag aus Beitrag + Zahlweise."""
        if not beitrag:
            return 0.0
        zw = (zahlweise or "monatlich").lower()
        if zw == "monatlich":
            return beitrag * 12
        elif zw == "quartalsweise":
            return beitrag * 4
        elif zw == "halbjaehrlich":
            return beitrag * 2
        return beitrag  # jaehrlich

    # ------------------------------------------------------------------
    # LIST - Alle Versicherungen
    # ------------------------------------------------------------------
    def _list(self, args: List[str]) -> Tuple[bool, str]:
        sparte_filter = self._get_arg(args, "--sparte") or self._get_arg(args, "-s")
        status_filter = self._get_arg(args, "--status")
        show_all = "--all" in args

        conn = self._get_db()
        try:
            query = "SELECT * FROM fin_insurances"
            params = []
            conditions = []

            if not show_all and not status_filter:
                conditions.append("status = 'aktiv'")

            if status_filter:
                conditions.append("status = ?")
                params.append(status_filter)

            if sparte_filter:
                conditions.append("sparte = ?")
                params.append(sparte_filter)

            if conditions:
                query += " WHERE " + " AND ".join(conditions)

            query += " ORDER BY sparte ASC, anbieter ASC"
            rows = conn.execute(query, params).fetchall()

            if not rows:
                msg = "[VERSICHERUNG] Keine Versicherungen gefunden."
                if not show_all:
                    msg += "\nNutze --all fuer alle (inkl. gekuendigte)."
                return True, msg

            lines = [f"[VERSICHERUNG] {len(rows)} Versicherung(en):\n"]
            current_sparte = None
            total_monthly = 0.0

            for r in rows:
                sparte = r["sparte"] or "Sonstige"
                if sparte != current_sparte:
                    current_sparte = sparte
                    lines.append(f"  [{sparte.upper()}]")

                monthly = self._calc_monthly(r["beitrag"], r["zahlweise"])
                total_monthly += monthly

                status_mark = ""
                if r["status"] != "aktiv":
                    status_mark = f" ({r['status']})"

                beitrag_str = f"{r['beitrag']:.2f} EUR" if r["beitrag"] else "---"
                zw_str = f"/{r['zahlweise']}" if r["zahlweise"] else ""

                lines.append(
                    f"    [{r['id']:>3}] {r['anbieter']:<25} {beitrag_str:>12}{zw_str:<14}{status_mark}"
                )
                if r["tarif_name"]:
                    lines.append(f"          Tarif: {r['tarif_name']}")

            lines.append("")
            lines.append(f"  Gesamt monatlich: {total_monthly:.2f} EUR")
            lines.append(f"  Gesamt jaehrlich: {total_monthly * 12:.2f} EUR")

            return True, "\n".join(lines)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # SHOW - Versicherung-Details
    # ------------------------------------------------------------------
    def _show(self, args: List[str]) -> Tuple[bool, str]:
        ids, _ = self._parse_ids(args)
        if not ids:
            return False, "Usage: bach versicherung show <id>"

        conn = self._get_db()
        try:
            row = conn.execute("SELECT * FROM fin_insurances WHERE id = ?", (ids[0],)).fetchone()
            if not row:
                return False, f"Versicherung {ids[0]} nicht gefunden."

            monthly = self._calc_monthly(row["beitrag"], row["zahlweise"])
            yearly = self._calc_yearly(row["beitrag"], row["zahlweise"])

            lines = [
                f"=== VERSICHERUNG #{row['id']} ===",
                f"Anbieter:        {row['anbieter']}",
                f"Tarif:           {row['tarif_name'] or '---'}",
                f"Police-Nr:       {row['police_nr'] or '---'}",
                f"Sparte:          {row['sparte']}",
                f"Status:          {row['status'] or '---'}",
                f"",
                f"--- TERMINE ---",
                f"Beginn:          {self._format_date(row['beginn_datum'])}",
                f"Ablauf:          {self._format_date(row['ablauf_datum'])}",
                f"Kuendigung bis:  {self._format_date(row['naechste_kuendigung'])}",
                f"Kuendigungsfrist:{row['kuendigungsfrist_monate'] or '---'} Monate",
                f"Verlaengerung:   {row['verlaengerung_monate'] or '---'} Monate",
                f"",
                f"--- FINANZEN ---",
                f"Beitrag:         {row['beitrag']:.2f} EUR" if row["beitrag"] else "Beitrag:         ---",
                f"Zahlweise:       {row['zahlweise'] or '---'}",
                f"Monatlich:       {monthly:.2f} EUR",
                f"Jaehrlich:       {yearly:.2f} EUR",
                f"Steuer-Typ:      {row['steuer_relevant_typ'] or '---'}",
                f"",
                f"--- SONSTIGES ---",
                f"Ordner:          {row['ordner_pfad'] or '---'}",
                f"Erstellt:        {(row['created_at'] or '---')[:16]}",
                f"Aktualisiert:    {(row['updated_at'] or '---')[:16]}",
            ]
            if row["notizen"]:
                lines.append(f"\nNotizen:\n{row['notizen']}")

            # Schadenfaelle anzeigen
            claims = conn.execute(
                "SELECT * FROM fin_insurance_claims WHERE insurance_id = ? ORDER BY schadensdatum DESC",
                (ids[0],)
            ).fetchall()
            if claims:
                lines.append(f"\n--- SCHADENFAELLE ({len(claims)}) ---")
                for c in claims:
                    datum = self._format_date(c["schadensdatum"])
                    betrag = f"{c['betrag_gezahlt']:.2f} EUR" if c["betrag_gezahlt"] else "---"
                    lines.append(
                        f"  [{c['id']:>3}] {datum}  {c['status']:<10}  {betrag:>10}  {c['beschreibung'] or ''}"
                    )

            return True, "\n".join(lines)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # ADD - Neue Versicherung
    # ------------------------------------------------------------------
    def _add(self, args: List[str]) -> Tuple[bool, str]:
        anbieter = self._get_arg(args, "--anbieter") or self._get_arg(args, "-a")
        sparte = self._get_arg(args, "--sparte") or self._get_arg(args, "-s")
        beitrag_str = self._get_arg(args, "--beitrag") or self._get_arg(args, "-b")

        if not anbieter or not sparte:
            return False, (
                "Usage: bach versicherung add --anbieter \"X\" --sparte \"Y\" [Optionen]\n\n"
                "Pflichtfelder:\n"
                "  --anbieter, -a   Versicherungsanbieter (z.B. \"Allianz\")\n"
                "  --sparte, -s     Sparte (z.B. Haftpflicht, BU, KFZ, Hausrat, PKV)\n\n"
                "Optionen:\n"
                "  --beitrag, -b    Beitrag in EUR (z.B. 45.90)\n"
                "  --zahlweise, -z  monatlich|quartalsweise|halbjaehrlich|jaehrlich (Default: monatlich)\n"
                "  --police, -p     Police-Nummer\n"
                "  --tarif          Tarifname\n"
                "  --beginn         Beginn-Datum (DD.MM.YYYY)\n"
                "  --ablauf         Ablauf-Datum (DD.MM.YYYY)\n"
                "  --kuendigung     Naechste Kuendigungsmoeglichkeit (DD.MM.YYYY)\n"
                "  --frist          Kuendigungsfrist in Monaten (Default: 3)\n"
                "  --steuer         Steuer-Typ (Basisvorsorge|Sonstige_Vorsorge)\n"
                "  --ordner         Pfad zu Unterlagen\n"
                "  --note           Notiz"
            )

        beitrag = None
        if beitrag_str:
            try:
                beitrag = float(beitrag_str.replace(",", "."))
            except ValueError:
                return False, f"Ungueltiger Beitrag: {beitrag_str}\nErwartet: Zahl (z.B. 45.90)"

        zahlweise = self._get_arg(args, "--zahlweise") or self._get_arg(args, "-z") or "monatlich"
        if zahlweise not in self.VALID_ZAHLWEISEN:
            return False, f"Ungueltige Zahlweise: {zahlweise}\nErlaubt: {', '.join(self.VALID_ZAHLWEISEN)}"

        police = self._get_arg(args, "--police") or self._get_arg(args, "-p")
        tarif = self._get_arg(args, "--tarif")
        beginn_str = self._get_arg(args, "--beginn")
        ablauf_str = self._get_arg(args, "--ablauf")
        kuendigung_str = self._get_arg(args, "--kuendigung")
        frist_str = self._get_arg(args, "--frist")
        steuer = self._get_arg(args, "--steuer")
        ordner = self._get_arg(args, "--ordner")
        note = self._get_arg(args, "--note")

        beginn = self._parse_date(beginn_str) if beginn_str else None
        ablauf = self._parse_date(ablauf_str) if ablauf_str else None
        kuendigung = self._parse_date(kuendigung_str) if kuendigung_str else None

        frist = 3
        if frist_str:
            try:
                frist = int(frist_str)
            except ValueError:
                return False, f"Ungueltige Kuendigungsfrist: {frist_str}\nErwartet: Ganzzahl (Monate)"

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        conn = self._get_db()
        try:
            cursor = conn.execute("""
                INSERT INTO fin_insurances
                (anbieter, tarif_name, police_nr, sparte, status,
                 beginn_datum, ablauf_datum, kuendigungsfrist_monate,
                 naechste_kuendigung, beitrag, zahlweise,
                 steuer_relevant_typ, ordner_pfad, notizen,
                 created_at, updated_at)
                VALUES (?, ?, ?, ?, 'aktiv', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                anbieter, tarif, police, sparte,
                beginn, ablauf, frist,
                kuendigung, beitrag, zahlweise,
                steuer, ordner, note,
                now, now,
            ))
            conn.commit()
            ins_id = cursor.lastrowid

            monthly = self._calc_monthly(beitrag, zahlweise)
            beitrag_info = f" ({beitrag:.2f} EUR/{zahlweise})" if beitrag else ""
            return True, f"[OK] Versicherung #{ins_id} erstellt: {anbieter} / {sparte}{beitrag_info}"
        except sqlite3.IntegrityError as e:
            if "police_nr" in str(e):
                return False, f"Police-Nummer '{police}' existiert bereits!"
            return False, f"Datenbankfehler: {e}"
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # EDIT - Versicherung bearbeiten
    # ------------------------------------------------------------------
    def _edit(self, args: List[str]) -> Tuple[bool, str]:
        ids, rest = self._parse_ids(args)
        if not ids:
            return False, (
                "Usage: bach versicherung edit <id> [Felder]\n\n"
                "Felder:\n"
                "  --anbieter, -a   Anbieter\n"
                "  --sparte, -s     Sparte\n"
                "  --beitrag, -b    Beitrag in EUR\n"
                "  --zahlweise, -z  Zahlweise\n"
                "  --police, -p     Police-Nummer\n"
                "  --tarif          Tarifname\n"
                "  --status         Status (aktiv|gekuendigt|beitragsfrei|ruhend)\n"
                "  --beginn         Beginn-Datum (DD.MM.YYYY)\n"
                "  --ablauf         Ablauf-Datum (DD.MM.YYYY)\n"
                "  --kuendigung     Naechste Kuendigung (DD.MM.YYYY)\n"
                "  --frist          Kuendigungsfrist (Monate)\n"
                "  --steuer         Steuer-Typ\n"
                "  --ordner         Ordner-Pfad\n"
                "  --note           Notiz (ergaenzt bestehende)"
            )

        ins_id = ids[0]
        conn = self._get_db()
        try:
            row = conn.execute("SELECT * FROM fin_insurances WHERE id = ?", (ins_id,)).fetchone()
            if not row:
                return False, f"Versicherung {ins_id} nicht gefunden."

            updates = {}

            anbieter = self._get_arg(rest, "--anbieter") or self._get_arg(rest, "-a")
            if anbieter:
                updates["anbieter"] = anbieter

            sparte = self._get_arg(rest, "--sparte") or self._get_arg(rest, "-s")
            if sparte:
                updates["sparte"] = sparte

            beitrag_str = self._get_arg(rest, "--beitrag") or self._get_arg(rest, "-b")
            if beitrag_str:
                try:
                    updates["beitrag"] = float(beitrag_str.replace(",", "."))
                except ValueError:
                    return False, f"Ungueltiger Beitrag: {beitrag_str}"

            zahlweise = self._get_arg(rest, "--zahlweise") or self._get_arg(rest, "-z")
            if zahlweise:
                if zahlweise not in self.VALID_ZAHLWEISEN:
                    return False, f"Ungueltige Zahlweise: {zahlweise}\nErlaubt: {', '.join(self.VALID_ZAHLWEISEN)}"
                updates["zahlweise"] = zahlweise

            police = self._get_arg(rest, "--police") or self._get_arg(rest, "-p")
            if police:
                updates["police_nr"] = police

            tarif = self._get_arg(rest, "--tarif")
            if tarif:
                updates["tarif_name"] = tarif

            status = self._get_arg(rest, "--status")
            if status:
                if status not in self.VALID_STATUS:
                    return False, f"Ungueltiger Status: {status}\nErlaubt: {', '.join(self.VALID_STATUS)}"
                updates["status"] = status

            beginn_str = self._get_arg(rest, "--beginn")
            if beginn_str:
                beginn = self._parse_date(beginn_str)
                if not beginn:
                    return False, f"Ungueltiges Datum: {beginn_str}"
                updates["beginn_datum"] = beginn

            ablauf_str = self._get_arg(rest, "--ablauf")
            if ablauf_str:
                ablauf = self._parse_date(ablauf_str)
                if not ablauf:
                    return False, f"Ungueltiges Datum: {ablauf_str}"
                updates["ablauf_datum"] = ablauf

            kuendigung_str = self._get_arg(rest, "--kuendigung")
            if kuendigung_str:
                kuendigung = self._parse_date(kuendigung_str)
                if not kuendigung:
                    return False, f"Ungueltiges Datum: {kuendigung_str}"
                updates["naechste_kuendigung"] = kuendigung

            frist_str = self._get_arg(rest, "--frist")
            if frist_str:
                try:
                    updates["kuendigungsfrist_monate"] = int(frist_str)
                except ValueError:
                    return False, f"Ungueltige Frist: {frist_str}"

            steuer = self._get_arg(rest, "--steuer")
            if steuer:
                updates["steuer_relevant_typ"] = steuer

            ordner = self._get_arg(rest, "--ordner")
            if ordner:
                updates["ordner_pfad"] = ordner

            note = self._get_arg(rest, "--note")
            if note:
                old_notes = row["notizen"] or ""
                stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
                updates["notizen"] = f"{old_notes}\n[{stamp}] {note}".strip()

            if not updates:
                return False, "Keine Aenderungen angegeben.\nNutze: bach versicherung edit <id> --beitrag 50.00"

            updates["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            set_clause = ", ".join(f"{k} = ?" for k in updates)
            params = list(updates.values()) + [ins_id]
            conn.execute(f"UPDATE fin_insurances SET {set_clause} WHERE id = ?", params)
            conn.commit()

            changed = ", ".join(k for k in updates if k != "updated_at")
            return True, f"[OK] Versicherung #{ins_id} aktualisiert: {changed}"
        except sqlite3.IntegrityError as e:
            if "police_nr" in str(e):
                return False, f"Police-Nummer existiert bereits!"
            return False, f"Datenbankfehler: {e}"
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # DELETE - Versicherung deaktivieren (Status -> gekuendigt)
    # ------------------------------------------------------------------
    def _delete(self, args: List[str]) -> Tuple[bool, str]:
        ids, _ = self._parse_ids(args)
        if not ids:
            return False, "Usage: bach versicherung delete <id>"

        conn = self._get_db()
        try:
            row = conn.execute("SELECT * FROM fin_insurances WHERE id = ?", (ids[0],)).fetchone()
            if not row:
                return False, f"Versicherung {ids[0]} nicht gefunden."

            if row["status"] == "gekuendigt":
                return True, f"Versicherung #{ids[0]} ({row['anbieter']} / {row['sparte']}) ist bereits gekuendigt."

            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            conn.execute(
                "UPDATE fin_insurances SET status = 'gekuendigt', updated_at = ? WHERE id = ?",
                (now, ids[0])
            )
            conn.commit()
            return True, f"[OK] Versicherung #{ids[0]} gekuendigt: {row['anbieter']} / {row['sparte']}"
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # STATUS - Dashboard mit Statistiken
    # ------------------------------------------------------------------
    def _status(self, args: List[str]) -> Tuple[bool, str]:
        conn = self._get_db()
        try:
            # Alle Versicherungen zaehlen
            total = conn.execute("SELECT COUNT(*) FROM fin_insurances").fetchone()[0]
            aktiv = conn.execute("SELECT COUNT(*) FROM fin_insurances WHERE status = 'aktiv'").fetchone()[0]
            gekuendigt = conn.execute("SELECT COUNT(*) FROM fin_insurances WHERE status = 'gekuendigt'").fetchone()[0]
            sonstige = total - aktiv - gekuendigt

            # Aktive Versicherungen fuer Kostenberechnung
            rows = conn.execute("""
                SELECT sparte, beitrag, zahlweise, steuer_relevant_typ
                FROM fin_insurances WHERE status = 'aktiv'
                ORDER BY sparte
            """).fetchall()

            total_monthly = 0.0
            by_sparte = {}
            steuer_basis = 0.0
            steuer_sonst = 0.0

            for r in rows:
                monthly = self._calc_monthly(r["beitrag"], r["zahlweise"])
                total_monthly += monthly
                sparte = r["sparte"] or "Sonstige"
                by_sparte[sparte] = by_sparte.get(sparte, 0) + monthly

                yearly = self._calc_yearly(r["beitrag"], r["zahlweise"])
                if r["steuer_relevant_typ"] == "Basisvorsorge":
                    steuer_basis += yearly
                elif r["steuer_relevant_typ"] == "Sonstige_Vorsorge":
                    steuer_sonst += yearly

            # Offene Schadenfaelle
            open_claims = conn.execute(
                "SELECT COUNT(*) FROM fin_insurance_claims WHERE status = 'offen'"
            ).fetchone()[0]

            # Fristen in naechsten 90 Tagen
            today = datetime.now().strftime("%Y-%m-%d")
            future = (datetime.now() + timedelta(days=90)).strftime("%Y-%m-%d")
            upcoming = conn.execute("""
                SELECT COUNT(*) FROM fin_insurances
                WHERE status = 'aktiv' AND naechste_kuendigung IS NOT NULL
                  AND naechste_kuendigung BETWEEN ? AND ?
            """, (today, future)).fetchone()[0]

            lines = [
                "=== VERSICHERUNGS-DASHBOARD ===",
                "",
                f"  Versicherungen gesamt: {total}",
                f"    Aktiv:               {aktiv}",
                f"    Gekuendigt:          {gekuendigt}",
            ]
            if sonstige > 0:
                lines.append(f"    Sonstige:            {sonstige}")

            lines.extend([
                "",
                f"  Kosten monatlich:      {total_monthly:>8.2f} EUR",
                f"  Kosten jaehrlich:      {total_monthly * 12:>8.2f} EUR",
                "",
            ])

            if by_sparte:
                lines.append("  AUFTEILUNG NACH SPARTE:")
                for sparte, cost in sorted(by_sparte.items(), key=lambda x: -x[1]):
                    pct = (cost / total_monthly * 100) if total_monthly > 0 else 0
                    bar = "#" * int(pct / 5)
                    lines.append(f"    {sparte:<22} {cost:>8.2f} EUR/Mo  ({pct:>3.0f}%) {bar}")
                lines.append("")

            lines.append("  STEUERLICHE ABSETZBARKEIT:")
            lines.append(f"    Basisvorsorge:     {steuer_basis:>8.2f} EUR/Jahr (voll absetzbar)")
            lines.append(f"    Sonstige Vorsorge: {steuer_sonst:>8.2f} EUR/Jahr (max 1.900 EUR)")
            if steuer_sonst > 1900:
                diff = steuer_sonst - 1900
                lines.append(f"    [!] Hoechstbetrag um {diff:.2f} EUR ueberschritten!")
            lines.append("")

            if open_claims > 0:
                lines.append(f"  [!] Offene Schadenfaelle: {open_claims}")
            if upcoming > 0:
                lines.append(f"  [i] Kuendigungsfristen (90 Tage): {upcoming}")
                lines.append(f"      -> bach versicherung fristen")
            lines.append("")

            return True, "\n".join(lines)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # FRISTEN - Kuendigungsfristen anzeigen
    # ------------------------------------------------------------------
    def _fristen(self, args: List[str]) -> Tuple[bool, str]:
        tage_str = self._get_arg(args, "--tage") or self._get_arg(args, "-t")
        tage = 90
        if tage_str:
            try:
                tage = int(tage_str)
            except ValueError:
                return False, f"Ungueltiger Wert fuer --tage: {tage_str}"

        # Auch als positionaler Arg
        if not tage_str:
            for a in args:
                if not a.startswith("-"):
                    try:
                        tage = int(a)
                        break
                    except ValueError:
                        pass

        conn = self._get_db()
        try:
            today = datetime.now()
            future = today + timedelta(days=tage)

            rows = conn.execute("""
                SELECT id, anbieter, sparte, naechste_kuendigung,
                       kuendigungsfrist_monate, verlaengerung_monate, beitrag, zahlweise
                FROM fin_insurances
                WHERE status = 'aktiv'
                  AND naechste_kuendigung IS NOT NULL
                ORDER BY naechste_kuendigung ASC
            """).fetchall()

            if not rows:
                return True, "[VERSICHERUNG] Keine Versicherungen mit Kuendigungsfristen hinterlegt."

            upcoming = []
            past = []

            for r in rows:
                try:
                    frist_date = datetime.strptime(r["naechste_kuendigung"][:10], "%Y-%m-%d")
                except (ValueError, TypeError):
                    continue

                diff = (frist_date - today).days

                if diff < 0:
                    past.append((diff, r, frist_date))
                elif diff <= tage:
                    upcoming.append((diff, r, frist_date))

            lines = [f"=== KUENDIGUNGSFRISTEN (naechste {tage} Tage) ===\n"]

            if past:
                lines.append("  [!!] ABGELAUFENE FRISTEN:")
                for diff, r, frist_date in past:
                    date_str = frist_date.strftime("%d.%m.%Y")
                    lines.append(
                        f"    [{r['id']:>3}] {date_str}  {r['anbieter']:<25} {r['sparte']:<15} (vor {abs(diff)} Tagen!)"
                    )
                lines.append("")

            if upcoming:
                lines.append("  BEVORSTEHENDE FRISTEN:")
                for diff, r, frist_date in upcoming:
                    date_str = frist_date.strftime("%d.%m.%Y")
                    monthly = self._calc_monthly(r["beitrag"], r["zahlweise"])

                    if diff == 0:
                        marker = "*** HEUTE ***"
                    elif diff <= 7:
                        marker = f"in {diff} Tagen!"
                    elif diff <= 30:
                        marker = f"in {diff} Tagen"
                    else:
                        marker = f"in {diff} Tagen"

                    lines.append(
                        f"    [{r['id']:>3}] {date_str}  {r['anbieter']:<25} {r['sparte']:<15} {monthly:>6.2f} EUR/Mo  ({marker})"
                    )
                lines.append("")
            else:
                lines.append(f"  Keine Fristen in den naechsten {tage} Tagen.\n")

            lines.append(f"  Gesamt mit Fristen: {len(upcoming) + len(past)}")
            if past:
                lines.append(f"  [!] {len(past)} abgelaufene Frist(en) beachten!")

            return True, "\n".join(lines)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # CHECK - Portfolio-Analyse (aus haushalt.py uebernommen + erweitert)
    # ------------------------------------------------------------------
    def _check(self, args: List[str]) -> Tuple[bool, str]:
        conn = self._get_db()
        try:
            insurances = conn.execute("""
                SELECT id, anbieter, tarif_name, sparte, beitrag, zahlweise,
                       status, steuer_relevant_typ
                FROM fin_insurances WHERE status = 'aktiv'
                ORDER BY sparte
            """).fetchall()

            if not insurances:
                return True, "[VERSICHERUNG] Keine aktiven Versicherungen gefunden."

            lines = [
                "=== VERSICHERUNGS-PORTFOLIO CHECK ===",
                "",
            ]

            # Kosten berechnen
            total_monthly = 0.0
            by_category = {}
            no_cost = []
            for ins in insurances:
                monthly = self._calc_monthly(ins["beitrag"], ins["zahlweise"])
                total_monthly += monthly

                cat = ins["sparte"] or "Sonstige"
                by_category[cat] = by_category.get(cat, 0) + monthly

                if not ins["beitrag"] or ins["beitrag"] == 0:
                    no_cost.append(ins)

            lines.append(f"  Aktive Versicherungen: {len(insurances)}")
            lines.append(f"  Kosten monatlich:      {total_monthly:.2f} EUR")
            lines.append(f"  Kosten jaehrlich:      {total_monthly * 12:.2f} EUR")
            lines.append("")

            # Aufteilung
            lines.append("  AUFTEILUNG:")
            for cat, cost in sorted(by_category.items(), key=lambda x: -x[1]):
                pct = (cost / total_monthly * 100) if total_monthly > 0 else 0
                bar = "#" * int(pct / 5)
                lines.append(f"    {cat:<22} {cost:>8.2f} EUR/Mo  ({pct:>3.0f}%) {bar}")
            lines.append("")

            # Analyse
            warnings = []
            infos = []

            # 1. Fehlende Beitraege
            if no_cost:
                warnings.append(f"{len(no_cost)} Versicherungen ohne Beitragsdaten:")
                for i in no_cost:
                    warnings.append(f"  -> #{i['id']} {i['anbieter']} ({i['sparte']})")
                warnings.append("  Empfehlung: Beitraege nachtragen mit: bach versicherung edit <id> --beitrag X")

            # 2. Mehrfach-Versicherungen
            from collections import Counter
            sparten = [i["sparte"] for i in insurances]
            dups = {s: c for s, c in Counter(sparten).items() if c > 1}
            if dups:
                for s, c in dups.items():
                    items = [i for i in insurances if i["sparte"] == s]
                    total = sum((i["beitrag"] or 0) for i in items)
                    if s == "KFZ":
                        infos.append(f"{c}x {s}-Versicherungen ({total:.2f} EUR/Mo) - Mehrere Fahrzeuge?")
                    else:
                        warnings.append(f"{c}x {s}-Versicherungen - Duplikat pruefen!")

            # 3. Steuer-Check
            steuer_basis = 0.0
            steuer_sonst = 0.0
            for ins in insurances:
                yearly = self._calc_yearly(ins["beitrag"], ins["zahlweise"])
                if ins["steuer_relevant_typ"] == "Basisvorsorge":
                    steuer_basis += yearly
                elif ins["steuer_relevant_typ"] == "Sonstige_Vorsorge":
                    steuer_sonst += yearly

            lines.append("  STEUERLICHE ABSETZBARKEIT:")
            lines.append(f"    Basisvorsorge:     {steuer_basis:>8.2f} EUR/Jahr (voll absetzbar)")
            lines.append(f"    Sonstige Vorsorge: {steuer_sonst:>8.2f} EUR/Jahr (max 1.900 EUR)")
            if steuer_sonst > 1900:
                diff = steuer_sonst - 1900
                warnings.append(f"Hoechstbetrag Sonstige Vorsorge um {diff:.2f} EUR ueberschritten")
                warnings.append(f"  -> {diff:.2f} EUR jaehrlich nicht absetzbar")
            lines.append("")

            # 4. Fehlende wichtige Versicherungen
            wichtige = {
                "Haftpflicht": "Privathaftpflicht schuetzt vor Schadenersatz",
                "Hausrat": "Schuetzt Wohnungsinventar",
                "PKV": "Krankenversicherung ist Pflicht",
            }
            vorhandene = {i["sparte"] for i in insurances}
            for v, desc in wichtige.items():
                if v not in vorhandene:
                    warnings.append(f"Fehlend: {v} - {desc}")

            # 5. Empfehlungen
            empfehlungen = []
            if total_monthly > 800:
                empfehlungen.append("Versicherungskosten hoch (>800 EUR/Mo) - Vergleich empfohlen")
            if "Rechtsschutz" in vorhandene and any(
                i["beitrag"] == 0 for i in insurances if i["sparte"] == "Rechtsschutz"
            ):
                empfehlungen.append("Rechtsschutz: Beitrag unbekannt - ggf. nicht mehr aktiv?")
            if "Risiko-LV" not in vorhandene:
                empfehlungen.append("Risikolebensversicherung fehlt - sinnvoll bei Familie/Kredit")

            # Versicherungstypen-Referenz pruefen
            try:
                types = conn.execute(
                    "SELECT name, priority, when_useful FROM insurance_types WHERE priority <= 2"
                ).fetchall()
                for t in types:
                    if t["name"] not in vorhandene:
                        prio = "Pflicht" if t["priority"] == 1 else "Wichtig"
                        empfehlungen.append(f"{t['name']} ({prio}): {t['when_useful'] or 'Empfohlen'}")
            except Exception:
                pass  # insurance_types Tabelle optional

            # Output
            if warnings:
                lines.append("  [!] WARNUNGEN:")
                for w in warnings:
                    lines.append(f"    ! {w}")
                lines.append("")

            if infos:
                lines.append("  [i] HINWEISE:")
                for i in infos:
                    lines.append(f"    i {i}")
                lines.append("")

            if empfehlungen:
                lines.append("  [*] EMPFEHLUNGEN:")
                for e in empfehlungen:
                    lines.append(f"    * {e}")
                lines.append("")

            # Score
            score = 10
            score -= len(warnings)
            score -= len(no_cost) * 0.5
            score = max(1, min(10, score))
            lines.append(f"  Portfolio-Score: {score:.0f}/10")

            return True, "\n".join(lines)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # CLAIM - Schadenfaelle verwalten
    # ------------------------------------------------------------------
    def _claim(self, args: List[str]) -> Tuple[bool, str]:
        if not args:
            return False, (
                "Usage: bach versicherung claim <add|list> [Optionen]\n\n"
                "  claim add <ins_id> --datum DD.MM.YYYY --beschreibung \"Text\" [--betrag X]\n"
                "  claim list [<ins_id>]"
            )

        sub = args[0]
        rest = args[1:]

        if sub == "add":
            return self._claim_add(rest)
        elif sub == "list":
            return self._claim_list(rest)
        else:
            return False, f"Unbekannte Claim-Operation: {sub}\nNutze: bach versicherung claim add|list"

    def _claim_add(self, args: List[str]) -> Tuple[bool, str]:
        ids, rest = self._parse_ids(args)
        if not ids:
            return False, (
                "Usage: bach versicherung claim add <versicherung_id> [Optionen]\n\n"
                "Pflicht:\n"
                "  --datum, -d        Schadensdatum (DD.MM.YYYY)\n"
                "  --beschreibung     Beschreibung des Schadens\n\n"
                "Optional:\n"
                "  --betrag           Geforderter Betrag\n"
                "  --aktenzeichen     Aktenzeichen der Versicherung"
            )

        ins_id = ids[0]

        conn = self._get_db()
        try:
            # Pruefen ob Versicherung existiert
            ins = conn.execute("SELECT * FROM fin_insurances WHERE id = ?", (ins_id,)).fetchone()
            if not ins:
                return False, f"Versicherung {ins_id} nicht gefunden."

            datum_str = self._get_arg(rest, "--datum") or self._get_arg(rest, "-d")
            beschreibung = self._get_arg(rest, "--beschreibung")
            betrag_str = self._get_arg(rest, "--betrag")
            aktenzeichen = self._get_arg(rest, "--aktenzeichen")

            if not datum_str or not beschreibung:
                return False, "Pflichtfelder: --datum und --beschreibung\nUsage: bach versicherung claim add <id> --datum 01.01.2026 --beschreibung \"Wasserschaden\""

            datum = self._parse_date(datum_str)
            if not datum:
                return False, f"Ungueltiges Datum: {datum_str}\nErwartet: DD.MM.YYYY oder YYYY-MM-DD"

            betrag = None
            if betrag_str:
                try:
                    betrag = float(betrag_str.replace(",", "."))
                except ValueError:
                    return False, f"Ungueltiger Betrag: {betrag_str}"

            cursor = conn.execute("""
                INSERT INTO fin_insurance_claims
                (insurance_id, schadensdatum, beschreibung, status,
                 betrag_gefordert, aktenzeichen_versicherung, created_at)
                VALUES (?, ?, ?, 'offen', ?, ?, CURRENT_TIMESTAMP)
            """, (ins_id, datum, beschreibung, betrag, aktenzeichen))
            conn.commit()
            claim_id = cursor.lastrowid

            return True, (
                f"[OK] Schadenfall #{claim_id} erfasst\n"
                f"  Versicherung: #{ins_id} {ins['anbieter']} / {ins['sparte']}\n"
                f"  Datum:        {self._format_date(datum)}\n"
                f"  Beschreibung: {beschreibung}"
            )
        finally:
            conn.close()

    def _claim_list(self, args: List[str]) -> Tuple[bool, str]:
        ids, _ = self._parse_ids(args)
        ins_filter = ids[0] if ids else None

        conn = self._get_db()
        try:
            if ins_filter:
                rows = conn.execute("""
                    SELECT c.*, i.anbieter, i.sparte
                    FROM fin_insurance_claims c
                    JOIN fin_insurances i ON c.insurance_id = i.id
                    WHERE c.insurance_id = ?
                    ORDER BY c.schadensdatum DESC
                """, (ins_filter,)).fetchall()
            else:
                rows = conn.execute("""
                    SELECT c.*, i.anbieter, i.sparte
                    FROM fin_insurance_claims c
                    JOIN fin_insurances i ON c.insurance_id = i.id
                    ORDER BY c.schadensdatum DESC
                """).fetchall()

            if not rows:
                if ins_filter:
                    return True, f"[VERSICHERUNG] Keine Schadenfaelle fuer Versicherung #{ins_filter}."
                return True, "[VERSICHERUNG] Keine Schadenfaelle erfasst."

            title = f"Schadenfaelle fuer Versicherung #{ins_filter}" if ins_filter else "Alle Schadenfaelle"
            lines = [f"[VERSICHERUNG] {title} ({len(rows)}):\n"]

            for r in rows:
                datum = self._format_date(r["schadensdatum"])
                status = r["status"] or "offen"
                betrag_g = f"{r['betrag_gefordert']:.2f}" if r["betrag_gefordert"] else "---"
                betrag_z = f"{r['betrag_gezahlt']:.2f}" if r["betrag_gezahlt"] else "---"

                status_icon = {"offen": "?", "reguliert": "+", "abgelehnt": "x"}.get(status, " ")

                lines.append(
                    f"  [{r['id']:>3}] [{status_icon}] {datum}  {r['anbieter']:<20} {r['sparte']:<12}  "
                    f"Gefordert: {betrag_g:>8} EUR  Gezahlt: {betrag_z:>8} EUR"
                )
                if r["beschreibung"]:
                    desc = r["beschreibung"][:60] + "..." if len(r["beschreibung"] or "") > 60 else r["beschreibung"]
                    lines.append(f"        {desc}")
                if r["aktenzeichen_versicherung"]:
                    lines.append(f"        AZ: {r['aktenzeichen_versicherung']}")

            # Zusammenfassung
            offen = sum(1 for r in rows if r["status"] == "offen")
            reguliert = sum(1 for r in rows if r["status"] == "reguliert")
            abgelehnt = sum(1 for r in rows if r["status"] == "abgelehnt")
            lines.append(f"\n  Offen: {offen}  Reguliert: {reguliert}  Abgelehnt: {abgelehnt}")

            return True, "\n".join(lines)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # HELP
    # ------------------------------------------------------------------
    def _help(self) -> Tuple[bool, str]:
        return True, """VERSICHERUNG - Versicherungsverwaltung
======================================

BEFEHLE:
  bach versicherung list                    Alle aktiven Versicherungen
  bach versicherung list --all              Inkl. gekuendigte
  bach versicherung list --sparte KFZ       Nach Sparte filtern
  bach versicherung list --status aktiv     Nach Status filtern
  bach versicherung show <id>               Details anzeigen
  bach versicherung add --anbieter "Allianz" --sparte "Haftpflicht" --beitrag 5.90
  bach versicherung add --anbieter "HUK" --sparte "KFZ" --beitrag 89.50 --zahlweise monatlich --police "KFZ-123"
  bach versicherung edit <id> --beitrag 50  Beitrag aendern
  bach versicherung edit <id> --status gekuendigt
  bach versicherung delete <id>             Status -> gekuendigt
  bach versicherung status                  Dashboard mit Statistiken
  bach versicherung fristen                 Kuendigungsfristen (90 Tage)
  bach versicherung fristen --tage 180      Kuendigungsfristen (180 Tage)
  bach versicherung check                   Portfolio-Analyse
  bach versicherung claim add <id> --datum 01.01.2026 --beschreibung "Wasserschaden"
  bach versicherung claim list              Alle Schadenfaelle
  bach versicherung claim list <id>         Schadenfaelle einer Versicherung

STATUS-WERTE:
  aktiv, gekuendigt, beitragsfrei, ruhend

ZAHLWEISEN:
  monatlich, quartalsweise, halbjaehrlich, jaehrlich

SPARTEN (Beispiele):
  Haftpflicht, BU, KFZ, Hausrat, PKV, Rechtsschutz, Risiko-LV, Unfall, Zahnzusatz

DATENBANK: bach.db / fin_insurances, fin_insurance_claims, insurance_types"""
