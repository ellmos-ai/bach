#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
LiteraturHandler - Literaturverwaltung CLI (INT01)

Portiert aus LitZentrum Standalone. Verwaltet Quellen, Zitate,
Zusammenfassungen und bietet 5 Zitationsstile + BibTeX-Export.

Operationen:
  add               Quelle hinzufuegen
  list              Quellen auflisten
  search            Quellen durchsuchen
  show              Quelle im Detail anzeigen
  edit              Quelle bearbeiten
  delete            Quelle loeschen
  quote             Zitat hinzufuegen
  quotes            Zitate einer Quelle anzeigen
  cite              Zitation formatieren (APA/MLA/Chicago/DIN/Harvard)
  export            BibTeX-Export
  summary           Zusammenfassung hinzufuegen/anzeigen
  stats             Statistik
  help              Hilfe anzeigen

Nutzt: bach.db / lit_sources, lit_quotes, lit_tasks, lit_summaries
"""

import json
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import List, Tuple
from hub.base import BaseHandler


class LiteraturHandler(BaseHandler):

    def __init__(self, base_path: Path):
        super().__init__(base_path)
        self.db_path = self._canonical_db

    @property
    def profile_name(self) -> str:
        return "literatur"

    @property
    def target_file(self) -> Path:
        return self.db_path

    def get_operations(self) -> dict:
        return {
            "add": "Quelle hinzufuegen: add \"Titel\" --author \"Name\" --year 2024",
            "list": "Quellen auflisten [--type TYPE] [--status STATUS] [--limit N]",
            "search": "Suchen: search \"Begriff\"",
            "show": "Detail: show <id>",
            "edit": "Bearbeiten: edit <id> --field wert",
            "delete": "Loeschen: delete <id>",
            "quote": "Zitat hinzufuegen: quote <source_id> \"Text\" --page 42",
            "quotes": "Zitate anzeigen: quotes <source_id>",
            "cite": "Zitation: cite <id> [--style apa|mla|chicago|din|harvard] [--page N]",
            "export": "BibTeX-Export: export [--ids 1,2,3] [--all]",
            "summary": "Zusammenfassung: summary <source_id> [\"Text\"] [--type full]",
            "stats": "Statistik ueber die Literaturdatenbank",
            "help": "Hilfe anzeigen",
        }

    def _get_db(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def handle(self, operation: str, args: List[str], dry_run: bool = False) -> Tuple[bool, str]:
        op = operation.lower().replace("_", "-")

        if op == "add":
            return self._add(args, dry_run)
        elif op == "list":
            return self._list(args)
        elif op == "search" and args:
            return self._search(args)
        elif op == "show" and args:
            return self._show(args)
        elif op == "edit" and args:
            return self._edit(args, dry_run)
        elif op == "delete" and args:
            return self._delete(args, dry_run)
        elif op == "quote":
            return self._quote(args, dry_run)
        elif op == "quotes" and args:
            return self._quotes(args)
        elif op == "cite" and args:
            return self._cite(args)
        elif op == "export":
            return self._export(args)
        elif op == "summary":
            return self._summary(args, dry_run)
        elif op == "stats":
            return self._stats()
        elif op == "help":
            return self._help()
        else:
            return self._help()

    # ================================================================
    # ARGS PARSER
    # ================================================================

    @staticmethod
    def _parse_flag(args: list, flag: str, default=None):
        """Extrahiert --flag wert aus args. Returns (wert, remaining_args)."""
        for i, a in enumerate(args):
            if a == flag and i + 1 < len(args):
                val = args[i + 1]
                remaining = args[:i] + args[i + 2:]
                return val, remaining
        return default, args

    @staticmethod
    def _has_flag(args: list, flag: str) -> tuple:
        """Prueft ob --flag gesetzt ist. Returns (bool, remaining_args)."""
        if flag in args:
            remaining = [a for a in args if a != flag]
            return True, remaining
        return False, args

    # ================================================================
    # ADD - Quelle hinzufuegen
    # ================================================================

    def _add(self, args: list, dry_run: bool) -> Tuple[bool, str]:
        if not args:
            return False, "Usage: bach literatur add \"Titel\" [--author \"Name\"] [--year 2024] [--type article] [--journal \"...\"] [--doi \"...\"]"

        # Flags parsen
        author, args = self._parse_flag(args, "--author")
        year, args = self._parse_flag(args, "--year")
        stype, args = self._parse_flag(args, "--type")
        journal, args = self._parse_flag(args, "--journal")
        doi, args = self._parse_flag(args, "--doi")
        publisher, args = self._parse_flag(args, "--publisher")
        isbn, args = self._parse_flag(args, "--isbn")
        url, args = self._parse_flag(args, "--url")
        tags, args = self._parse_flag(args, "--tags")
        lang, args = self._parse_flag(args, "--lang")

        # Titel = restliche Argumente
        title = " ".join(args).strip('"\'')
        if not title:
            return False, "Fehler: Titel ist erforderlich."

        # Autoren als JSON-Array
        authors_json = None
        if author:
            # Mehrere Autoren mit ; trennen
            authors_list = [a.strip() for a in author.split(";")]
            authors_json = json.dumps(authors_list)

        # Tags als JSON-Array
        tags_json = None
        if tags:
            tags_list = [t.strip() for t in tags.split(",")]
            tags_json = json.dumps(tags_list)

        if dry_run:
            return True, f"[DRY RUN] Wuerde Quelle anlegen: {title}"

        conn = self._get_db()
        try:
            conn.execute(
                """INSERT INTO lit_sources
                   (title, authors, year, source_type, journal, publisher,
                    doi, isbn, url, tags, language)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (title, authors_json,
                 int(year) if year else None,
                 stype or "article",
                 journal, publisher, doi, isbn, url,
                 tags_json,
                 lang or "de")
            )
            conn.commit()
            sid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            return True, f"Quelle #{sid} angelegt: {title}"
        finally:
            conn.close()

    # ================================================================
    # LIST - Quellen auflisten
    # ================================================================

    def _list(self, args: list) -> Tuple[bool, str]:
        stype, args = self._parse_flag(args, "--type")
        status, args = self._parse_flag(args, "--status")
        limit, args = self._parse_flag(args, "--limit")

        limit_n = int(limit) if limit else 20

        conn = self._get_db()
        try:
            where = []
            params = []
            if stype:
                where.append("source_type = ?")
                params.append(stype)
            if status:
                where.append("read_status = ?")
                params.append(status)

            clause = f"WHERE {' AND '.join(where)}" if where else ""
            rows = conn.execute(
                f"SELECT id, title, authors, year, source_type, read_status "
                f"FROM lit_sources {clause} ORDER BY id DESC LIMIT ?",
                params + [limit_n]
            ).fetchall()

            if not rows:
                return True, "Keine Quellen vorhanden."

            total = conn.execute(f"SELECT COUNT(*) FROM lit_sources {clause}", params).fetchone()[0]

            lines = [f"LITERATUR ({total} Quellen)", "=" * 50, ""]
            for r in rows:
                authors = self._format_author_short(r["authors"])
                year = r["year"] or "o.J."
                status_icon = {"unread": " ", "reading": "~", "read": "+", "archived": "x"}.get(r["read_status"], " ")
                lines.append(f"  [{status_icon}] #{r['id']:3d}  {authors} ({year}): {r['title'][:60]}")

            if total > limit_n:
                lines.append(f"\n  ... {total - limit_n} weitere (--limit {total})")

            return True, "\n".join(lines)
        finally:
            conn.close()

    # ================================================================
    # SEARCH - Quellen durchsuchen
    # ================================================================

    def _search(self, args: list) -> Tuple[bool, str]:
        query = " ".join(args).strip('"\'')
        if not query:
            return False, "Usage: bach literatur search \"Suchbegriff\""

        conn = self._get_db()
        try:
            pattern = f"%{query}%"
            rows = conn.execute(
                """SELECT id, title, authors, year, source_type
                   FROM lit_sources
                   WHERE title LIKE ? OR authors LIKE ? OR tags LIKE ?
                         OR abstract LIKE ? OR notes LIKE ?
                   ORDER BY year DESC LIMIT 30""",
                (pattern, pattern, pattern, pattern, pattern)
            ).fetchall()

            if not rows:
                return True, f"Keine Treffer fuer '{query}'."

            lines = [f"Suche: '{query}' — {len(rows)} Treffer", "-" * 40, ""]
            for r in rows:
                authors = self._format_author_short(r["authors"])
                year = r["year"] or "o.J."
                lines.append(f"  #{r['id']:3d}  {authors} ({year}): {r['title'][:60]}")

            return True, "\n".join(lines)
        finally:
            conn.close()

    # ================================================================
    # SHOW - Quellen-Detail
    # ================================================================

    def _show(self, args: list) -> Tuple[bool, str]:
        try:
            sid = int(args[0])
        except (ValueError, IndexError):
            return False, "Usage: bach literatur show <id>"

        conn = self._get_db()
        try:
            row = conn.execute("SELECT * FROM lit_sources WHERE id = ?", (sid,)).fetchone()
            if not row:
                return False, f"Quelle #{sid} nicht gefunden."

            lines = [f"QUELLE #{sid}", "=" * 50]
            lines.append(f"  Titel:      {row['title']}")
            lines.append(f"  Autoren:    {self._format_author_display(row['authors'])}")
            lines.append(f"  Jahr:       {row['year'] or 'k.A.'}")
            lines.append(f"  Typ:        {row['source_type']}")

            if row["journal"]:
                lines.append(f"  Journal:    {row['journal']}")
            if row["publisher"]:
                lines.append(f"  Verlag:     {row['publisher']}")
            if row["volume"]:
                vol = row["volume"]
                if row["issue"]:
                    vol += f"({row['issue']})"
                lines.append(f"  Band:       {vol}")
            if row["pages"]:
                lines.append(f"  Seiten:     {row['pages']}")
            if row["doi"]:
                lines.append(f"  DOI:        {row['doi']}")
            if row["isbn"]:
                lines.append(f"  ISBN:       {row['isbn']}")
            if row["url"]:
                lines.append(f"  URL:        {row['url']}")

            lines.append(f"  Status:     {row['read_status']}")
            if row["rating"]:
                lines.append(f"  Bewertung:  {'*' * row['rating']}")
            if row["tags"]:
                lines.append(f"  Tags:       {self._format_tags(row['tags'])}")
            if row["abstract"]:
                abstract = row["abstract"][:200]
                if len(row["abstract"]) > 200:
                    abstract += "..."
                lines.append(f"  Abstract:   {abstract}")
            if row["notes"]:
                lines.append(f"  Notizen:    {row['notes'][:200]}")

            lines.append(f"  Erfasst:    {row['created_at']}")

            # Zitate zaehlen
            q_count = conn.execute(
                "SELECT COUNT(*) FROM lit_quotes WHERE source_id = ?", (sid,)
            ).fetchone()[0]
            s_count = conn.execute(
                "SELECT COUNT(*) FROM lit_summaries WHERE source_id = ?", (sid,)
            ).fetchone()[0]
            if q_count:
                lines.append(f"  Zitate:     {q_count}")
            if s_count:
                lines.append(f"  Zusammenf.: {s_count}")

            return True, "\n".join(lines)
        finally:
            conn.close()

    # ================================================================
    # EDIT - Quelle bearbeiten
    # ================================================================

    def _edit(self, args: list, dry_run: bool) -> Tuple[bool, str]:
        try:
            sid = int(args[0])
        except (ValueError, IndexError):
            return False, "Usage: bach literatur edit <id> --title \"Neuer Titel\" [--author \"...\"] [--year N] ..."

        remaining = args[1:]
        if not remaining:
            return False, "Keine Aenderungen angegeben. Optionen: --title, --author, --year, --type, --journal, --doi, --status, --rating, --tags, --notes"

        FIELD_MAP = {
            "--title": "title",
            "--author": "authors",
            "--year": "year",
            "--type": "source_type",
            "--journal": "journal",
            "--publisher": "publisher",
            "--doi": "doi",
            "--isbn": "isbn",
            "--url": "url",
            "--status": "read_status",
            "--rating": "rating",
            "--tags": "tags",
            "--notes": "notes",
            "--abstract": "abstract",
            "--lang": "language",
            "--pdf": "pdf_path",
        }

        updates = {}
        i = 0
        while i < len(remaining):
            flag = remaining[i]
            if flag in FIELD_MAP and i + 1 < len(remaining):
                db_field = FIELD_MAP[flag]
                value = remaining[i + 1]
                # Spezialbehandlung
                if flag == "--author":
                    authors_list = [a.strip() for a in value.split(";")]
                    value = json.dumps(authors_list)
                elif flag == "--tags":
                    tags_list = [t.strip() for t in value.split(",")]
                    value = json.dumps(tags_list)
                elif flag in ("--year", "--rating"):
                    value = int(value)
                updates[db_field] = value
                i += 2
            else:
                i += 1

        if not updates:
            return False, "Keine gueltigen Felder erkannt."

        if dry_run:
            return True, f"[DRY RUN] Wuerde Quelle #{sid} aktualisieren: {list(updates.keys())}"

        conn = self._get_db()
        try:
            row = conn.execute("SELECT id FROM lit_sources WHERE id = ?", (sid,)).fetchone()
            if not row:
                return False, f"Quelle #{sid} nicht gefunden."

            set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
            conn.execute(
                f"UPDATE lit_sources SET {set_clause}, updated_at = datetime('now') WHERE id = ?",
                list(updates.values()) + [sid]
            )
            conn.commit()
            return True, f"Quelle #{sid} aktualisiert: {', '.join(updates.keys())}"
        finally:
            conn.close()

    # ================================================================
    # DELETE - Quelle loeschen
    # ================================================================

    def _delete(self, args: list, dry_run: bool) -> Tuple[bool, str]:
        try:
            sid = int(args[0])
        except (ValueError, IndexError):
            return False, "Usage: bach literatur delete <id>"

        conn = self._get_db()
        try:
            row = conn.execute("SELECT title FROM lit_sources WHERE id = ?", (sid,)).fetchone()
            if not row:
                return False, f"Quelle #{sid} nicht gefunden."

            if dry_run:
                return True, f"[DRY RUN] Wuerde Quelle #{sid} loeschen: {row['title']}"

            # CASCADE loescht auch quotes, tasks, summaries
            conn.execute("DELETE FROM lit_sources WHERE id = ?", (sid,))
            conn.commit()
            return True, f"Quelle #{sid} geloescht: {row['title']}"
        finally:
            conn.close()

    # ================================================================
    # QUOTE - Zitat hinzufuegen
    # ================================================================

    def _quote(self, args: list, dry_run: bool) -> Tuple[bool, str]:
        if len(args) < 2:
            return False, 'Usage: bach literatur quote <source_id> "Zitat-Text" [--page 42] [--type direct|indirect|paraphrase]'

        try:
            source_id = int(args[0])
        except ValueError:
            return False, "Erste Angabe muss die Quellen-ID sein."

        # Flags parsen (vor Text-Zusammenbau)
        remaining = args[1:]
        page, remaining = self._parse_flag(remaining, "--page")
        qtype, remaining = self._parse_flag(remaining, "--type")
        comment, remaining = self._parse_flag(remaining, "--comment")
        tags, remaining = self._parse_flag(remaining, "--tags")

        text = " ".join(remaining).strip('"\'')
        if not text:
            return False, "Zitat-Text ist erforderlich."

        if dry_run:
            return True, f"[DRY RUN] Wuerde Zitat zu Quelle #{source_id} hinzufuegen."

        conn = self._get_db()
        try:
            # Quelle pruefen
            src = conn.execute("SELECT title FROM lit_sources WHERE id = ?", (source_id,)).fetchone()
            if not src:
                return False, f"Quelle #{source_id} nicht gefunden."

            tags_json = None
            if tags:
                tags_json = json.dumps([t.strip() for t in tags.split(",")])

            conn.execute(
                """INSERT INTO lit_quotes
                   (source_id, quote_type, text, page, comment, tags)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (source_id,
                 qtype or "direct",
                 text,
                 int(page) if page else None,
                 comment,
                 tags_json)
            )
            conn.commit()
            qid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

            page_info = f" (S. {page})" if page else ""
            return True, f"Zitat #{qid} zu '{src['title']}'{page_info} hinzugefuegt."
        finally:
            conn.close()

    # ================================================================
    # QUOTES - Zitate einer Quelle anzeigen
    # ================================================================

    def _quotes(self, args: list) -> Tuple[bool, str]:
        try:
            source_id = int(args[0])
        except (ValueError, IndexError):
            return False, "Usage: bach literatur quotes <source_id>"

        conn = self._get_db()
        try:
            src = conn.execute("SELECT title FROM lit_sources WHERE id = ?", (source_id,)).fetchone()
            if not src:
                return False, f"Quelle #{source_id} nicht gefunden."

            rows = conn.execute(
                "SELECT * FROM lit_quotes WHERE source_id = ? ORDER BY page, id",
                (source_id,)
            ).fetchall()

            if not rows:
                return True, f"Keine Zitate fuer '{src['title']}'."

            lines = [f"ZITATE aus: {src['title']}", "-" * 50, ""]
            for r in rows:
                type_icon = {"direct": '"', "indirect": "~", "paraphrase": ">"}.get(r["quote_type"], "?")
                page_str = f" [S. {r['page']}]" if r["page"] else ""
                lines.append(f"  {type_icon} #{r['id']}{page_str}: {r['text'][:120]}")
                if r["comment"]:
                    lines.append(f"    Kommentar: {r['comment'][:80]}")

            lines.append(f"\n{len(rows)} Zitat(e) gesamt.")
            return True, "\n".join(lines)
        finally:
            conn.close()

    # ================================================================
    # CITE - Zitation formatieren
    # ================================================================

    def _cite(self, args: list) -> Tuple[bool, str]:
        try:
            sid = int(args[0])
        except (ValueError, IndexError):
            return False, "Usage: bach literatur cite <id> [--style apa|mla|chicago|din|harvard] [--page N]"

        remaining = args[1:]
        style, remaining = self._parse_flag(remaining, "--style")
        page, remaining = self._parse_flag(remaining, "--page")

        style = style or "apa"
        page_n = int(page) if page else None

        conn = self._get_db()
        try:
            row = conn.execute("SELECT * FROM lit_sources WHERE id = ?", (sid,)).fetchone()
            if not row:
                return False, f"Quelle #{sid} nicht gefunden."

            from hub._services.literatur.citation_formatter import format_citation, STYLES
            try:
                result = format_citation(dict(row), style, page_n)
            except ValueError as e:
                return False, str(e)

            lines = [
                f"Stil: {style.upper()}",
                f"Vollzitat:  {result['full']}",
                f"Inline:     {result['inline']}",
            ]
            return True, "\n".join(lines)
        finally:
            conn.close()

    # ================================================================
    # EXPORT - BibTeX-Export
    # ================================================================

    def _export(self, args: list) -> Tuple[bool, str]:
        ids_str, args = self._parse_flag(args, "--ids")
        export_all, args = self._has_flag(args, "--all")
        out_file, args = self._parse_flag(args, "--out")

        conn = self._get_db()
        try:
            if ids_str:
                id_list = [int(x.strip()) for x in ids_str.split(",")]
                placeholders = ",".join("?" * len(id_list))
                rows = conn.execute(
                    f"SELECT * FROM lit_sources WHERE id IN ({placeholders})",
                    id_list
                ).fetchall()
            elif export_all:
                rows = conn.execute("SELECT * FROM lit_sources").fetchall()
            else:
                # Default: letzte 50
                rows = conn.execute(
                    "SELECT * FROM lit_sources ORDER BY id DESC LIMIT 50"
                ).fetchall()

            if not rows:
                return True, "Keine Quellen zum Exportieren."

            from hub._services.literatur.citation_formatter import export_bibtex
            bibtex = export_bibtex([dict(r) for r in rows])

            if out_file:
                out_path = Path(out_file)
                out_path.write_text(bibtex, encoding="utf-8")
                return True, f"BibTeX exportiert: {out_path} ({len(rows)} Eintraege)"

            return True, bibtex
        finally:
            conn.close()

    # ================================================================
    # SUMMARY - Zusammenfassung
    # ================================================================

    def _summary(self, args: list, dry_run: bool) -> Tuple[bool, str]:
        if not args:
            return False, 'Usage: bach literatur summary <source_id> ["Text"] [--type full|chapter|section|abstract]'

        try:
            source_id = int(args[0])
        except ValueError:
            return False, "Erste Angabe muss die Quellen-ID sein."

        remaining = args[1:]

        # Wenn keine weiteren Args: Zusammenfassungen anzeigen
        if not remaining:
            return self._show_summaries(source_id)

        # Sonst: Zusammenfassung hinzufuegen
        stype, remaining = self._parse_flag(remaining, "--type")
        title, remaining = self._parse_flag(remaining, "--title")
        pages, remaining = self._parse_flag(remaining, "--pages")

        content = " ".join(remaining).strip('"\'')
        if not content:
            return self._show_summaries(source_id)

        if dry_run:
            return True, f"[DRY RUN] Wuerde Zusammenfassung zu Quelle #{source_id} hinzufuegen."

        conn = self._get_db()
        try:
            src = conn.execute("SELECT title FROM lit_sources WHERE id = ?", (source_id,)).fetchone()
            if not src:
                return False, f"Quelle #{source_id} nicht gefunden."

            conn.execute(
                """INSERT INTO lit_summaries
                   (source_id, title, content, summary_type, pages)
                   VALUES (?, ?, ?, ?, ?)""",
                (source_id,
                 title or f"Zusammenfassung ({stype or 'full'})",
                 content,
                 stype or "full",
                 pages)
            )
            conn.commit()
            return True, f"Zusammenfassung zu '{src['title']}' hinzugefuegt."
        finally:
            conn.close()

    def _show_summaries(self, source_id: int) -> Tuple[bool, str]:
        conn = self._get_db()
        try:
            src = conn.execute("SELECT title FROM lit_sources WHERE id = ?", (source_id,)).fetchone()
            if not src:
                return False, f"Quelle #{source_id} nicht gefunden."

            rows = conn.execute(
                "SELECT * FROM lit_summaries WHERE source_id = ? ORDER BY id",
                (source_id,)
            ).fetchall()

            if not rows:
                return True, f"Keine Zusammenfassungen fuer '{src['title']}'."

            lines = [f"ZUSAMMENFASSUNGEN: {src['title']}", "-" * 50, ""]
            for r in rows:
                lines.append(f"  #{r['id']} [{r['summary_type']}] {r['title'] or ''}")
                if r["pages"]:
                    lines.append(f"    Seiten: {r['pages']}")
                # Inhalt gekuerzt
                content = r["content"][:300]
                if len(r["content"]) > 300:
                    content += "..."
                lines.append(f"    {content}")
                lines.append("")

            return True, "\n".join(lines)
        finally:
            conn.close()

    # ================================================================
    # STATS - Statistik
    # ================================================================

    def _stats(self) -> Tuple[bool, str]:
        conn = self._get_db()
        try:
            total = conn.execute("SELECT COUNT(*) FROM lit_sources").fetchone()[0]
            if total == 0:
                return True, "Literaturdatenbank ist leer. Starte mit: bach literatur add \"Titel\" --author \"Name\""

            by_type = conn.execute(
                "SELECT source_type, COUNT(*) as cnt FROM lit_sources GROUP BY source_type ORDER BY cnt DESC"
            ).fetchall()
            by_status = conn.execute(
                "SELECT read_status, COUNT(*) as cnt FROM lit_sources GROUP BY read_status ORDER BY cnt DESC"
            ).fetchall()
            quotes_total = conn.execute("SELECT COUNT(*) FROM lit_quotes").fetchone()[0]
            summaries_total = conn.execute("SELECT COUNT(*) FROM lit_summaries").fetchone()[0]
            year_range = conn.execute(
                "SELECT MIN(year), MAX(year) FROM lit_sources WHERE year IS NOT NULL"
            ).fetchone()

            lines = ["LITERATUR-STATISTIK", "=" * 50, ""]
            lines.append(f"  Quellen gesamt:    {total}")
            lines.append(f"  Zitate gesamt:     {quotes_total}")
            lines.append(f"  Zusammenfassungen: {summaries_total}")

            if year_range[0]:
                lines.append(f"  Zeitraum:          {year_range[0]} - {year_range[1]}")

            lines.append("")
            lines.append("  Nach Typ:")
            for r in by_type:
                lines.append(f"    {r['source_type']:15s} {r['cnt']:3d}")

            lines.append("")
            lines.append("  Nach Status:")
            for r in by_status:
                lines.append(f"    {r['read_status']:15s} {r['cnt']:3d}")

            return True, "\n".join(lines)
        finally:
            conn.close()

    # ================================================================
    # HELP
    # ================================================================

    def _help(self) -> Tuple[bool, str]:
        lines = [
            "LITERATURVERWALTUNG", "=" * 50, "",
            "QUELLEN VERWALTEN",
            '  bach literatur add "Titel" --author "Name" --year 2024',
            "  bach literatur list [--type article|book] [--status unread|read]",
            '  bach literatur search "Begriff"',
            "  bach literatur show <id>",
            '  bach literatur edit <id> --title "Neu" --year 2025',
            "  bach literatur delete <id>",
            "",
            "ZITATE",
            '  bach literatur quote <source_id> "Zitat-Text" --page 42',
            "  bach literatur quotes <source_id>",
            "",
            "ZITATION & EXPORT",
            "  bach literatur cite <id> [--style apa|mla|chicago|din|harvard] [--page N]",
            "  bach literatur export [--ids 1,2,3] [--all] [--out refs.bib]",
            "",
            "ZUSAMMENFASSUNGEN",
            '  bach literatur summary <source_id> "Text" [--type full|chapter]',
            "  bach literatur summary <source_id>              (anzeigen)",
            "",
            "UEBERSICHT",
            "  bach literatur stats",
            "",
            "ZITATIONSSTILE: apa (Standard), mla, chicago, din, harvard",
            "QUELLTYPEN: article, book, chapter, thesis, conference, website, other",
            "LESESTATUS: unread, reading, read, archived",
        ]
        return True, "\n".join(lines)

    # ================================================================
    # HILFSFUNKTIONEN
    # ================================================================

    @staticmethod
    def _format_author_short(authors_field) -> str:
        """Formatiert Autoren kurz: 'Smith et al.' oder 'Smith & Doe'."""
        if not authors_field:
            return "Unbekannt"
        try:
            authors = json.loads(authors_field) if isinstance(authors_field, str) else authors_field
        except (json.JSONDecodeError, TypeError):
            return str(authors_field)

        if not isinstance(authors, list) or not authors:
            return str(authors_field)

        first = authors[0]
        # Nachname extrahieren
        if "," in first:
            name = first.split(",")[0].strip()
        else:
            parts = first.strip().split()
            name = parts[-1] if parts else first

        if len(authors) == 1:
            return name
        elif len(authors) == 2:
            return f"{name} & {authors[1].split(',')[0].strip() if ',' in authors[1] else authors[1].strip().split()[-1]}"
        else:
            return f"{name} et al."

    @staticmethod
    def _format_author_display(authors_field) -> str:
        """Formatiert Autoren fuer Detail-Ansicht."""
        if not authors_field:
            return "Unbekannt"
        try:
            authors = json.loads(authors_field) if isinstance(authors_field, str) else authors_field
        except (json.JSONDecodeError, TypeError):
            return str(authors_field)

        if isinstance(authors, list):
            return "; ".join(authors)
        return str(authors)

    @staticmethod
    def _format_tags(tags_field) -> str:
        """Formatiert Tags aus JSON-String."""
        if not tags_field:
            return ""
        try:
            tags = json.loads(tags_field) if isinstance(tags_field, str) else tags_field
        except (json.JSONDecodeError, TypeError):
            return str(tags_field)

        if isinstance(tags, list):
            return ", ".join(tags)
        return str(tags)
