#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
ContactHandler - Kontaktverwaltung CLI

Operationen:
  list              Alle Kontakte anzeigen
  search <term>     Kontakte durchsuchen
  add "Name"        Neuen Kontakt anlegen
  show <id>         Kontakt-Details
  edit <id>         Kontakt bearbeiten
  delete <id>       Kontakt loeschen (soft-delete)
  birthday          Geburtstage anzeigen
  help              Hilfe anzeigen

Nutzt: bach.db / contacts (Unified DB seit v1.1.84)
Ref: DB_003_KONTAKTDATENBANK_ANALYSE.md
"""

import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Tuple, Optional
from hub.base import BaseHandler


class ContactHandler(BaseHandler):

    VALID_CONTEXTS = ["privat", "beruflich", "versicherung", "finanzen", "arzt", "sonstige"]

    def __init__(self, base_path: Path):
        super().__init__(base_path)
        self.user_db_path = base_path / "data" / "bach.db"  # Unified DB seit v1.1.84

    @property
    def profile_name(self) -> str:
        return "contact"

    @property
    def target_file(self) -> Path:
        return self.user_db_path

    def get_operations(self) -> dict:
        return {
            "list": "Alle Kontakte anzeigen",
            "search": "Kontakte durchsuchen",
            "add": "Neuen Kontakt anlegen",
            "show": "Kontakt-Details anzeigen",
            "edit": "Kontakt bearbeiten",
            "delete": "Kontakt loeschen",
            "birthday": "Geburtstage anzeigen",
            "export": "Kontakte exportieren (CSV/Text/vCard)",
            "help": "Hilfe anzeigen",
        }

    def _get_db(self):
        conn = sqlite3.connect(str(self.user_db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def handle(self, operation: str, args: List[str], dry_run: bool = False) -> Tuple[bool, str]:
        if operation == "list":
            return self._list(args)
        elif operation == "search":
            return self._search(args)
        elif operation == "add":
            return self._add(args)
        elif operation == "show":
            return self._show(args)
        elif operation == "edit":
            return self._edit(args)
        elif operation == "delete":
            return self._delete(args)
        elif operation == "birthday":
            return self._birthday(args)
        elif operation == "export":
            return self._export(args)
        elif operation in ("", "help"):
            return self._help()
        else:
            return False, f"Unbekannte Operation: {operation}\nNutze: bach contact help"

    # ------------------------------------------------------------------
    # LIST - Alle aktiven Kontakte
    # ------------------------------------------------------------------
    def _list(self, args: List[str]) -> Tuple[bool, str]:
        context_filter = self._get_arg(args, "--context") or self._get_arg(args, "-c")
        show_all = "--all" in args

        conn = self._get_db()
        try:
            query = "SELECT * FROM contacts"
            params = []

            if not show_all:
                query += " WHERE is_active = 1"
                if context_filter:
                    query += " AND category = ?"
                    params.append(context_filter)
            elif context_filter:
                query += " WHERE category = ?"
                params.append(context_filter)

            query += " ORDER BY category ASC, name ASC"
            rows = conn.execute(query, params).fetchall()

            if not rows:
                return True, "[CONTACTS] Keine Kontakte gefunden.\nNutze: bach contact add \"Name\" --email x@y.de --context privat"

            lines = [f"[CONTACTS] {len(rows)} Kontakt(e):\n"]
            current_ctx = None

            for r in rows:
                ctx = r["category"] or "sonstige"
                if ctx != current_ctx:
                    current_ctx = ctx
                    lines.append(f"  [{ctx.upper()}]")

                phone_info = r["phone_mobile"] or r["phone"] or ""
                email_info = r["email"] or ""
                company_info = f" @ {r['organization']}" if r["organization"] else ""
                detail = email_info if email_info else phone_info
                if detail and len(detail) > 25:
                    detail = detail[:22] + "..."

                lines.append(
                    f"    [{r['id']:>3}] {r['name']:<30}{company_info}  {detail}"
                )

            return True, "\n".join(lines)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # SEARCH - Freitextsuche ueber Name, Email, Phone, Notes
    # ------------------------------------------------------------------
    def _search(self, args: List[str]) -> Tuple[bool, str]:
        if not args:
            return False, "Usage: bach contact search <suchbegriff>\n\nDurchsucht Name, Email, Telefon, Adresse und Notizen."

        term = " ".join(a for a in args if not a.startswith("-"))
        if not term:
            return False, "Kein Suchbegriff angegeben."

        conn = self._get_db()
        try:
            like = f"%{term}%"
            rows = conn.execute("""
                SELECT * FROM contacts
                WHERE is_active = 1
                  AND (name LIKE ? OR email LIKE ? OR phone LIKE ?
                       OR phone_mobile LIKE ? OR organization LIKE ?
                       OR notes LIKE ? OR position LIKE ? OR tags LIKE ?)
                ORDER BY name ASC
            """, (like, like, like, like, like, like, like, like)).fetchall()

            if not rows:
                return True, f"[CONTACTS] Keine Treffer fuer \"{term}\"."

            lines = [f"[CONTACTS] {len(rows)} Treffer fuer \"{term}\":\n"]
            for r in rows:
                ctx = (r["category"] or "sonstige").upper()
                detail = r["email"] or r["phone_mobile"] or r["phone"] or ""
                lines.append(
                    f"  [{r['id']:>3}] {r['name']:<30} ({ctx}) {detail}"
                )

            return True, "\n".join(lines)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # ADD - Neuen Kontakt anlegen
    # ------------------------------------------------------------------
    def _add(self, args: List[str]) -> Tuple[bool, str]:
        if not args:
            return False, (
                "Usage: bach contact add \"Name\" [Optionen]\n\n"
                "Optionen:\n"
                "  --context, -c   Kontext (privat|beruflich|versicherung|finanzen|arzt|sonstige)\n"
                "  --email, -e     E-Mail\n"
                "  --phone, -p     Telefon (Festnetz)\n"
                "  --mobile, -m    Mobil\n"
                "  --address, -a   Adresse\n"
                "  --birthday, -b  Geburtstag (DD.MM.YYYY oder YYYY-MM-DD)\n"
                "  --company       Firma/Organisation\n"
                "  --position      Position/Rolle\n"
                "  --tags          Tags (kommagetrennt)\n"
                "  --note          Notiz"
            )

        # Name = erster Arg der kein Flag ist
        name = None
        for a in args:
            if not a.startswith("-"):
                name = a
                break

        if not name:
            return False, "Kein Name angegeben. Usage: bach contact add \"Max Mustermann\""

        context = self._get_arg(args, "--context") or self._get_arg(args, "-c") or "privat"
        email = self._get_arg(args, "--email") or self._get_arg(args, "-e")
        phone = self._get_arg(args, "--phone") or self._get_arg(args, "-p")
        mobile = self._get_arg(args, "--mobile") or self._get_arg(args, "-m")
        address = self._get_arg(args, "--address") or self._get_arg(args, "-a")
        birthday_str = self._get_arg(args, "--birthday") or self._get_arg(args, "-b")
        company = self._get_arg(args, "--company")
        position = self._get_arg(args, "--position")
        tags = self._get_arg(args, "--tags")
        note = self._get_arg(args, "--note")

        # Birthday parsen
        birthday = None
        if birthday_str:
            birthday = self._parse_date(birthday_str)
            if not birthday:
                return False, f"Ungueliges Datumsformat: {birthday_str}\nErwartet: DD.MM.YYYY oder YYYY-MM-DD"

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        conn = self._get_db()
        try:
            cursor = conn.execute("""
                INSERT INTO contacts
                (name, category, email, phone, phone_mobile, street, birthday, organization, position, tags, notes, is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            """, (
                name, context, email, phone, mobile, address,
                birthday, company, position, tags, note, now, now,
            ))
            conn.commit()
            cid = cursor.lastrowid
            return True, f"[OK] Kontakt #{cid} erstellt: {name} ({context})"
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # SHOW - Kontakt-Details
    # ------------------------------------------------------------------
    def _show(self, args: List[str]) -> Tuple[bool, str]:
        ids, _ = self._parse_ids(args)
        if not ids:
            return False, "Usage: bach contact show <id>"

        conn = self._get_db()
        try:
            row = conn.execute("SELECT * FROM contacts WHERE id = ?", (ids[0],)).fetchone()
            if not row:
                return False, f"Kontakt {ids[0]} nicht gefunden"

            lines = [
                f"=== KONTAKT {row['id']} ===",
                f"Name:        {row['name']}",
                f"Kategorie:   {row['category'] or '---'}",
                f"Organisation:{row['organization'] or '---'}",
                f"Position:    {row['position'] or '---'}",
                f"E-Mail:      {row['email'] or '---'}",
                f"Telefon:     {row['phone'] or '---'}",
                f"Mobil:       {row['phone_mobile'] or '---'}",
                f"Adresse:     {row['street'] or '---'}",
                f"Geburtstag:  {self._format_birthday(row['birthday'])}",
                f"Tags:        {row['tags'] or '---'}",
                f"Aktiv:       {'Ja' if row['is_active'] else 'Nein'}",
                f"Erstellt:    {(row['created_at'] or '---')[:16]}",
                f"Aktualisiert:{(row['updated_at'] or '---')[:16]}",
            ]
            if row["notes"]:
                lines.append(f"\nNotizen:\n{row['notes']}")

            return True, "\n".join(lines)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # EDIT - Kontakt bearbeiten
    # ------------------------------------------------------------------
    def _edit(self, args: List[str]) -> Tuple[bool, str]:
        ids, rest = self._parse_ids(args)
        if not ids:
            return False, (
                "Usage: bach contact edit <id> [Felder]\n\n"
                "Felder:\n"
                "  --name          Name aendern\n"
                "  --context, -c   Kontext\n"
                "  --email, -e     E-Mail\n"
                "  --phone, -p     Telefon\n"
                "  --mobile, -m    Mobil\n"
                "  --address, -a   Adresse\n"
                "  --birthday, -b  Geburtstag\n"
                "  --company       Firma/Organisation\n"
                "  --position      Position/Rolle\n"
                "  --tags          Tags (kommagetrennt)\n"
                "  --note          Notiz (ergaenzt bestehende)"
            )

        cid = ids[0]
        conn = self._get_db()
        try:
            row = conn.execute("SELECT * FROM contacts WHERE id = ?", (cid,)).fetchone()
            if not row:
                return False, f"Kontakt {cid} nicht gefunden"

            updates = {}

            name = self._get_arg(rest, "--name")
            if name:
                updates["name"] = name

            context = self._get_arg(rest, "--context") or self._get_arg(rest, "-c")
            if context:
                updates["category"] = context

            email = self._get_arg(rest, "--email") or self._get_arg(rest, "-e")
            if email:
                updates["email"] = email

            phone = self._get_arg(rest, "--phone") or self._get_arg(rest, "-p")
            if phone:
                updates["phone"] = phone

            mobile = self._get_arg(rest, "--mobile") or self._get_arg(rest, "-m")
            if mobile:
                updates["phone_mobile"] = mobile

            address = self._get_arg(rest, "--address") or self._get_arg(rest, "-a")
            if address:
                updates["street"] = address

            birthday_str = self._get_arg(rest, "--birthday") or self._get_arg(rest, "-b")
            if birthday_str:
                birthday = self._parse_date(birthday_str)
                if not birthday:
                    return False, f"Ungueltiges Datumsformat: {birthday_str}"
                updates["birthday"] = birthday

            company = self._get_arg(rest, "--company")
            if company:
                updates["organization"] = company

            position = self._get_arg(rest, "--position")
            if position:
                updates["position"] = position

            tags = self._get_arg(rest, "--tags")
            if tags:
                updates["tags"] = tags

            note = self._get_arg(rest, "--note")
            if note:
                old_notes = row["notes"] or ""
                stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
                updates["notes"] = f"{old_notes}\n[{stamp}] {note}".strip()

            if not updates:
                return False, "Keine Aenderungen angegeben.\nNutze: bach contact edit <id> --email neue@mail.de"

            updates["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            set_clause = ", ".join(f"{k} = ?" for k in updates)
            params = list(updates.values()) + [cid]
            conn.execute(f"UPDATE contacts SET {set_clause} WHERE id = ?", params)
            conn.commit()

            changed = ", ".join(k for k in updates if k != "updated_at")
            return True, f"[OK] Kontakt #{cid} aktualisiert: {changed}"
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # DELETE - Soft-Delete (is_active = 0)
    # ------------------------------------------------------------------
    def _delete(self, args: List[str]) -> Tuple[bool, str]:
        ids, _ = self._parse_ids(args)
        if not ids:
            return False, "Usage: bach contact delete <id>"

        conn = self._get_db()
        try:
            row = conn.execute("SELECT * FROM contacts WHERE id = ?", (ids[0],)).fetchone()
            if not row:
                return False, f"Kontakt {ids[0]} nicht gefunden"

            if not row["is_active"]:
                return True, f"Kontakt #{ids[0]} ({row['name']}) ist bereits inaktiv."

            conn.execute(
                "UPDATE contacts SET is_active = 0, updated_at = ? WHERE id = ?",
                (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), ids[0])
            )
            conn.commit()
            return True, f"[OK] Kontakt #{ids[0]} deaktiviert: {row['name']}"
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # BIRTHDAY - Geburtstage anzeigen
    # ------------------------------------------------------------------
    def _birthday(self, args: List[str]) -> Tuple[bool, str]:
        days = 30  # Default: naechste 30 Tage
        for a in args:
            try:
                days = int(a)
                break
            except ValueError:
                pass

        conn = self._get_db()
        try:
            rows = conn.execute("""
                SELECT * FROM contacts
                WHERE is_active = 1 AND birthday IS NOT NULL AND birthday != ''
                ORDER BY name ASC
            """).fetchall()

            if not rows:
                return True, "[CONTACTS] Keine Kontakte mit Geburtstag hinterlegt."

            today = datetime.now()
            upcoming = []

            for r in rows:
                try:
                    bday = datetime.strptime(r["birthday"], "%Y-%m-%d")
                except (ValueError, TypeError):
                    continue

                # Naechster Geburtstag in diesem oder naechstem Jahr
                this_year_bday = bday.replace(year=today.year)
                if this_year_bday.date() < today.date():
                    this_year_bday = bday.replace(year=today.year + 1)

                diff = (this_year_bday.date() - today.date()).days
                if diff <= days:
                    age = this_year_bday.year - bday.year
                    upcoming.append((diff, r, this_year_bday, age))

            upcoming.sort(key=lambda x: x[0])

            if not upcoming:
                return True, f"[CONTACTS] Keine Geburtstage in den naechsten {days} Tagen."

            lines = [f"[CONTACTS] Geburtstage (naechste {days} Tage):\n"]
            for diff, r, bday_date, age in upcoming:
                date_str = bday_date.strftime("%d.%m.")
                if diff == 0:
                    marker = "*** HEUTE ***"
                elif diff == 1:
                    marker = "morgen"
                elif diff <= 7:
                    marker = f"in {diff} Tagen"
                else:
                    marker = f"in {diff} Tagen"

                lines.append(
                    f"  [{r['id']:>3}] {date_str} {r['name']:<30} wird {age}  ({marker})"
                )

            return True, "\n".join(lines)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # EXPORT - Kontakte exportieren
    # ------------------------------------------------------------------
    def _export(self, args: List[str]) -> Tuple[bool, str]:
        """
        Exportiert Kontakte als CSV, Text oder vCard 3.0.

        Optionen:
            --type aerzte/arzt    Nur Arzt-Kontakte
            --type beruflich      Nur berufliche Kontakte
            --type versicherung   Nur Versicherungs-Kontakte
            --format csv|txt|vcard  Exportformat (default: txt)
            --file <pfad>         Speichern in Datei
        """
        context_filter = self._get_arg(args, "--type") or self._get_arg(args, "-t")
        export_format = self._get_arg(args, "--format") or self._get_arg(args, "-f") or "txt"
        output_file = self._get_arg(args, "--file") or self._get_arg(args, "-o")

        # Kontext-Alias
        if context_filter in ("aerzte", "arzt", "\u00e4rzte"):
            context_filter = "arzt"

        # vCard export uses the unified contacts table
        if export_format.lower() == "vcard":
            return self._export_vcard(context_filter, output_file)

        conn = self._get_db()
        try:
            query = "SELECT * FROM contacts WHERE is_active = 1"
            params = []

            if context_filter:
                query += " AND category = ?"
                params.append(context_filter)

            query += " ORDER BY category ASC, name ASC"
            rows = conn.execute(query, params).fetchall()

            if not rows:
                return True, f"[EXPORT] Keine Kontakte gefunden" + (f" fuer Kontext '{context_filter}'" if context_filter else "")

            # Export formatieren
            if export_format.lower() == "csv":
                output = self._format_csv(rows)
            else:
                output = self._format_text(rows)

            # In Datei speichern oder ausgeben
            if output_file:
                try:
                    with open(output_file, 'w', encoding='utf-8') as f:
                        f.write(output)
                    return True, f"[EXPORT] {len(rows)} Kontakte exportiert nach: {output_file}"
                except Exception as e:
                    return False, f"[ERROR] Schreiben fehlgeschlagen: {e}"
            else:
                header = f"[EXPORT] {len(rows)} Kontakte"
                if context_filter:
                    header += f" (Kontext: {context_filter})"
                header += f" ({export_format.upper()}):\n"
                return True, header + "\n" + output

        finally:
            conn.close()

    def _export_vcard(self, category_filter: Optional[str], output_file: Optional[str]) -> Tuple[bool, str]:
        """Exportiert Kontakte aus der unified contacts-Tabelle als vCard 3.0."""
        conn = self._get_db()
        try:
            query = "SELECT * FROM contacts WHERE is_active = 1"
            params = []

            if category_filter:
                query += " AND category = ?"
                params.append(category_filter)

            query += " ORDER BY category ASC, name ASC"
            rows = conn.execute(query, params).fetchall()

            if not rows:
                return True, f"[EXPORT] Keine Kontakte gefunden" + (f" fuer Kategorie '{category_filter}'" if category_filter else "")

            output = self._format_vcard(rows)

            if output_file:
                try:
                    with open(output_file, 'w', encoding='utf-8') as f:
                        f.write(output)
                    return True, f"[EXPORT] {len(rows)} Kontakte als vCard exportiert nach: {output_file}"
                except Exception as e:
                    return False, f"[ERROR] Schreiben fehlgeschlagen: {e}"
            else:
                header = f"[EXPORT] {len(rows)} Kontakte"
                if category_filter:
                    header += f" (Kategorie: {category_filter})"
                header += " (VCARD):\n"
                return True, header + "\n" + output

        finally:
            conn.close()

    def _format_csv(self, rows) -> str:
        """Formatiert Kontakte als CSV."""
        lines = ["Name;Telefon;Mobil;Email;Firma;Adresse;Kontext;Tags;Notiz"]
        for r in rows:
            line = ";".join([
                r["name"] or "",
                r["phone"] or "",
                r["phone_mobile"] or "",
                r["email"] or "",
                r["organization"] or "",
                (r["street"] or "").replace("\n", " "),
                r["category"] or "",
                r["tags"] or "",
                (r["notes"] or "").replace("\n", " ").replace(";", ",")
            ])
            lines.append(line)
        return "\n".join(lines)

    def _format_text(self, rows) -> str:
        """Formatiert Kontakte als lesbaren Text."""
        lines = []
        current_ctx = None

        for r in rows:
            ctx = r["category"] or "sonstige"
            if ctx != current_ctx:
                current_ctx = ctx
                lines.append(f"\n=== {ctx.upper()} ===")

            lines.append(f"\n{r['name']}")
            if r["phone"]:
                lines.append(f"  Tel:    {r['phone']}")
            if r["phone_mobile"]:
                lines.append(f"  Mobil:  {r['mobile']}")
            if r["email"]:
                lines.append(f"  Email:  {r['email']}")
            if r["organization"]:
                lines.append(f"  Firma:  {r['organization']}")
            if r["position"]:
                lines.append(f"  Position: {r['position']}")
            if r["street"]:
                addr = r["street"].replace("\n", ", ")
                lines.append(f"  Adresse: {addr}")
            if r["notes"]:
                note = r["notes"][:100] + "..." if len(r["notes"] or "") > 100 else r["notes"]
                lines.append(f"  Notiz:  {note}")

        return "\n".join(lines)

    def _format_vcard(self, rows) -> str:
        """Formatiert Kontakte aus der unified contacts-Tabelle als vCard 3.0."""
        vcards = []

        for r in rows:
            lines = []
            lines.append("BEGIN:VCARD")
            lines.append("VERSION:3.0")

            first = r["first_name"] or ""
            last = r["last_name"] or ""

            # Fallback: wenn first/last leer, aus name splitten
            if not first and not last:
                name = r["name"] or ""
                parts = name.strip().split(None, 1)
                if len(parts) == 2:
                    first, last = parts[0], parts[1]
                elif len(parts) == 1:
                    first = parts[0]

            lines.append(f"N:{self._vcard_escape(last)};{self._vcard_escape(first)};;;")
            fn = f"{first} {last}".strip() or (r["name"] or "")
            lines.append(f"FN:{self._vcard_escape(fn)}")

            if r["organization"]:
                lines.append(f"ORG:{self._vcard_escape(r['organization'])}")

            if r["position"]:
                lines.append(f"TITLE:{self._vcard_escape(r['position'])}")

            if r["phone"]:
                lines.append(f"TEL;TYPE=HOME:{self._vcard_escape(r['phone'])}")
            if r["phone_mobile"]:
                lines.append(f"TEL;TYPE=CELL:{self._vcard_escape(r['phone_mobile'])}")
            if r["phone_work"]:
                lines.append(f"TEL;TYPE=WORK:{self._vcard_escape(r['phone_work'])}")

            if r["email"]:
                lines.append(f"EMAIL;TYPE=HOME:{self._vcard_escape(r['email'])}")
            if r["email_work"]:
                lines.append(f"EMAIL;TYPE=WORK:{self._vcard_escape(r['email_work'])}")

            # Adresse: ADR;TYPE=HOME:;;Street;City;;ZIP;Country
            street = r["street"] or ""
            city = r["city"] or ""
            zip_code = r["zip_code"] or ""
            country = r["country"] or ""
            if street or city or zip_code or country:
                lines.append(
                    f"ADR;TYPE=HOME:;;{self._vcard_escape(street)};{self._vcard_escape(city)};;{self._vcard_escape(zip_code)};{self._vcard_escape(country)}"
                )

            if r["birthday"]:
                lines.append(f"BDAY:{r['birthday']}")

            if r["website"]:
                lines.append(f"URL:{self._vcard_escape(r['website'])}")

            if r["notes"]:
                lines.append(f"NOTE:{self._vcard_escape(r['notes'])}")

            lines.append("END:VCARD")
            vcards.append("\n".join(lines))

        return "\n".join(vcards)

    @staticmethod
    def _vcard_escape(value: str) -> str:
        """Escapt Sonderzeichen fuer vCard 3.0."""
        if not value:
            return ""
        # vCard 3.0 escaping: backslash, semicolon, comma, newline
        value = value.replace("\\", "\\\\")
        value = value.replace(";", "\\;")
        value = value.replace(",", "\\,")
        value = value.replace("\n", "\\n")
        value = value.replace("\r", "")
        return value

    # ------------------------------------------------------------------
    # HELP
    # ------------------------------------------------------------------
    def _help(self) -> Tuple[bool, str]:
        return True, """CONTACT - Kontaktverwaltung
==========================

BEFEHLE:
  bach contact list              Alle Kontakte anzeigen
  bach contact list --all        Inkl. inaktive
  bach contact list -c privat    Nach Kontext filtern
  bach contact search Max        Freitextsuche
  bach contact add "Name"        Neuer Kontakt
  bach contact add "Max" --email max@web.de --context privat --mobile 0171...
  bach contact add "Lisa" --company "SAP SE" --position "Teamlead" --tags dev,it
  bach contact show <id>         Details anzeigen
  bach contact edit <id>         Kontakt bearbeiten
  bach contact edit 5 --email neu@mail.de --company "Neue Firma" --note "Gewechselt"
  bach contact delete <id>       Kontakt deaktivieren
  bach contact birthday          Geburtstage (30 Tage)
  bach contact birthday 90       Geburtstage (90 Tage)
  bach contact export            Alle Kontakte exportieren
  bach contact export --type aerzte        Nur Arzt-Kontakte
  bach contact export --type beruflich     Nur berufliche Kontakte
  bach contact export --format csv         Als CSV exportieren
  bach contact export --format vcard       Als vCard 3.0 exportieren
  bach contact export --format vcard --file kontakte.vcf  vCard in Datei
  bach contact export --file kontakte.csv  In Datei speichern

KONTEXTE:
  privat, beruflich, versicherung, finanzen, arzt, sonstige

DATENBANK: bach.db / contacts + contacts (Unified DB seit v1.1.84)"""

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

    def _format_birthday(self, birthday: Optional[str]) -> str:
        """Formatiert Geburtstag fuer Anzeige."""
        if not birthday:
            return "---"
        try:
            dt = datetime.strptime(birthday, "%Y-%m-%d")
            today = datetime.now()
            age_bday = dt.replace(year=today.year)
            if age_bday.date() < today.date():
                age = today.year - dt.year
            else:
                age = today.year - dt.year - 1
            return f"{dt.strftime('%d.%m.%Y')} ({age} Jahre)"
        except (ValueError, TypeError):
            return birthday
