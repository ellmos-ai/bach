#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
MediaHandler - Medienverwaltung CLI (INT03)

Portiert aus MediaBrain Standalone. Verwaltet Filme, Serien, Musik,
Podcasts und andere Medien mit Provider-Support und Favoriten/Blacklist.

Operationen:
  add               Medium hinzufuegen
  list              Medien auflisten
  search            Medien durchsuchen
  show              Medium im Detail anzeigen
  edit              Medium bearbeiten
  fav               Favorit setzen/entfernen
  blacklist         Blacklist setzen/entfernen
  open              Medium oeffnen (Browser/App)
  history           Wiedergabe-Historie
  stats             Statistik
  help              Hilfe anzeigen

Nutzt: bach.db / media_items, media_history, media_lists, media_list_items
"""

import json
import sqlite3
import webbrowser
from pathlib import Path
from datetime import datetime
from typing import List, Tuple
from hub.base import BaseHandler


MEDIA_TYPES = ["movie", "series", "music", "clip", "podcast", "audiobook", "document"]
SOURCES = ["netflix", "youtube", "spotify", "disney", "prime", "appletv", "twitch", "local"]

TYPE_ICONS = {
    "movie": "F", "series": "S", "music": "M", "clip": "C",
    "podcast": "P", "audiobook": "A", "document": "D",
}


class MediaHandler(BaseHandler):

    def __init__(self, base_path: Path):
        super().__init__(base_path)
        self.db_path = self._canonical_db

    @property
    def profile_name(self) -> str:
        return "media"

    @property
    def target_file(self) -> Path:
        return self.db_path

    def get_operations(self) -> dict:
        return {
            "add": "Medium hinzufuegen: add \"Titel\" --type movie --source netflix",
            "list": "Medien auflisten [--type TYPE] [--source SOURCE] [--fav] [--limit N]",
            "search": "Suchen: search \"Begriff\"",
            "show": "Detail: show <id>",
            "edit": "Bearbeiten: edit <id> --field wert",
            "fav": "Favorit: fav <id> [--remove]",
            "blacklist": "Blacklist: blacklist <id> [--remove]",
            "open": "Oeffnen: open <id>",
            "history": "Wiedergabe-Historie [--limit N]",
            "stats": "Statistik",
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
        elif op == "fav" and args:
            return self._fav(args, dry_run)
        elif op == "blacklist" and args:
            return self._blacklist(args, dry_run)
        elif op == "open" and args:
            return self._open(args)
        elif op == "history":
            return self._history(args)
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
        for i, a in enumerate(args):
            if a == flag and i + 1 < len(args):
                return args[i + 1], args[:i] + args[i + 2:]
        return default, args

    @staticmethod
    def _has_flag(args: list, flag: str) -> tuple:
        if flag in args:
            return True, [a for a in args if a != flag]
        return False, args

    # ================================================================
    # ADD
    # ================================================================

    def _add(self, args: list, dry_run: bool) -> Tuple[bool, str]:
        if not args:
            return False, 'Usage: bach media add "Titel" [--type movie] [--source netflix] [--url URL] [--artist "..."]'

        mtype, args = self._parse_flag(args, "--type")
        source, args = self._parse_flag(args, "--source")
        url, args = self._parse_flag(args, "--url")
        artist, args = self._parse_flag(args, "--artist")
        album, args = self._parse_flag(args, "--album")
        channel, args = self._parse_flag(args, "--channel")
        season, args = self._parse_flag(args, "--season")
        episode, args = self._parse_flag(args, "--episode")
        rating, args = self._parse_flag(args, "--rating")
        tags, args = self._parse_flag(args, "--tags")
        desc, args = self._parse_flag(args, "--desc")
        local_path, args = self._parse_flag(args, "--path")

        title = " ".join(args).strip('"\'')
        if not title:
            return False, "Fehler: Titel ist erforderlich."

        mtype = mtype or "movie"
        source = source or "local"

        if mtype not in MEDIA_TYPES:
            return False, f"Unbekannter Typ: {mtype}. Verfuegbar: {', '.join(MEDIA_TYPES)}"
        if source not in SOURCES:
            return False, f"Unbekannte Quelle: {source}. Verfuegbar: {', '.join(SOURCES)}"

        tags_json = json.dumps([t.strip() for t in tags.split(",")]) if tags else None
        provider_id = url or local_path or title.lower().replace(" ", "_")

        if dry_run:
            return True, f"[DRY RUN] Wuerde Medium anlegen: {title}"

        conn = self._get_db()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO media_items
                   (title, media_type, source, provider_id, url, description,
                    artist, album, channel, season, episode, rating, tags,
                    local_path)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (title, mtype, source, provider_id, url, desc,
                 artist, album, channel,
                 int(season) if season else None,
                 int(episode) if episode else None,
                 int(rating) if rating else None,
                 tags_json, local_path)
            )
            conn.commit()
            mid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            icon = TYPE_ICONS.get(mtype, "?")
            return True, f"[{icon}] Medium #{mid} angelegt: {title} ({source}/{mtype})"
        finally:
            conn.close()

    # ================================================================
    # LIST
    # ================================================================

    def _list(self, args: list) -> Tuple[bool, str]:
        mtype, args = self._parse_flag(args, "--type")
        source, args = self._parse_flag(args, "--source")
        fav_only, args = self._has_flag(args, "--fav")
        limit, args = self._parse_flag(args, "--limit")

        limit_n = int(limit) if limit else 20

        conn = self._get_db()
        try:
            where = ["blacklist_flag = 0"]
            params = []
            if mtype:
                where.append("media_type = ?")
                params.append(mtype)
            if source:
                where.append("source = ?")
                params.append(source)
            if fav_only:
                where.append("is_favorite = 1")

            clause = f"WHERE {' AND '.join(where)}"
            rows = conn.execute(
                f"SELECT id, title, media_type, source, is_favorite, rating, last_opened_at "
                f"FROM media_items {clause} ORDER BY last_opened_at DESC NULLS LAST, id DESC LIMIT ?",
                params + [limit_n]
            ).fetchall()

            total = conn.execute(f"SELECT COUNT(*) FROM media_items {clause}", params).fetchone()[0]

            if not rows:
                return True, "Keine Medien vorhanden."

            header = "FAVORITEN" if fav_only else "MEDIEN"
            lines = [f"{header} ({total})", "=" * 50, ""]
            for r in rows:
                icon = TYPE_ICONS.get(r["media_type"], "?")
                fav = "*" if r["is_favorite"] else " "
                rating_str = f"{'*' * r['rating']}" if r["rating"] else ""
                lines.append(f"  [{icon}]{fav} #{r['id']:3d}  {r['title'][:45]:<45} {r['source']:>8}  {rating_str}")

            if total > limit_n:
                lines.append(f"\n  ... {total - limit_n} weitere (--limit {total})")

            return True, "\n".join(lines)
        finally:
            conn.close()

    # ================================================================
    # SEARCH
    # ================================================================

    def _search(self, args: list) -> Tuple[bool, str]:
        query = " ".join(args).strip('"\'')
        if not query:
            return False, 'Usage: bach media search "Suchbegriff"'

        conn = self._get_db()
        try:
            pattern = f"%{query}%"
            rows = conn.execute(
                """SELECT id, title, media_type, source, is_favorite
                   FROM media_items
                   WHERE blacklist_flag = 0 AND (title LIKE ? OR artist LIKE ?
                         OR album LIKE ? OR channel LIKE ? OR tags LIKE ? OR description LIKE ?)
                   ORDER BY last_opened_at DESC NULLS LAST LIMIT 30""",
                (pattern, pattern, pattern, pattern, pattern, pattern)
            ).fetchall()

            if not rows:
                return True, f"Keine Treffer fuer '{query}'."

            lines = [f"Suche: '{query}' — {len(rows)} Treffer", "-" * 40, ""]
            for r in rows:
                icon = TYPE_ICONS.get(r["media_type"], "?")
                fav = "*" if r["is_favorite"] else " "
                lines.append(f"  [{icon}]{fav} #{r['id']:3d}  {r['title'][:50]}  ({r['source']})")

            return True, "\n".join(lines)
        finally:
            conn.close()

    # ================================================================
    # SHOW
    # ================================================================

    def _show(self, args: list) -> Tuple[bool, str]:
        try:
            mid = int(args[0])
        except (ValueError, IndexError):
            return False, "Usage: bach media show <id>"

        conn = self._get_db()
        try:
            row = conn.execute("SELECT * FROM media_items WHERE id = ?", (mid,)).fetchone()
            if not row:
                return False, f"Medium #{mid} nicht gefunden."

            icon = TYPE_ICONS.get(row["media_type"], "?")
            lines = [f"[{icon}] MEDIUM #{mid}", "=" * 50]
            lines.append(f"  Titel:      {row['title']}")
            lines.append(f"  Typ:        {row['media_type']}")
            lines.append(f"  Quelle:     {row['source']}")

            if row["artist"]:
                lines.append(f"  Kuenstler:  {row['artist']}")
            if row["album"]:
                lines.append(f"  Album:      {row['album']}")
            if row["channel"]:
                lines.append(f"  Channel:    {row['channel']}")
            if row["season"]:
                ep = f"E{row['episode']}" if row["episode"] else ""
                lines.append(f"  Staffel:    S{row['season']}{ep}")
            if row["url"]:
                lines.append(f"  URL:        {row['url']}")
            if row["local_path"]:
                lines.append(f"  Pfad:       {row['local_path']}")
            if row["description"]:
                lines.append(f"  Beschr.:    {row['description'][:200]}")
            if row["rating"]:
                lines.append(f"  Bewertung:  {'*' * row['rating']}")
            if row["tags"]:
                try:
                    t = json.loads(row["tags"])
                    lines.append(f"  Tags:       {', '.join(t)}")
                except (json.JSONDecodeError, TypeError):
                    pass

            lines.append(f"  Favorit:    {'Ja' if row['is_favorite'] else 'Nein'}")
            if row["blacklist_flag"]:
                lines.append(f"  Blacklist:  Ja (seit {row['blacklisted_at'] or '?'})")
            lines.append(f"  Erfasst:    {row['created_at']}")
            if row["last_opened_at"]:
                lines.append(f"  Zuletzt:    {row['last_opened_at']}")

            # Historie
            history = conn.execute(
                "SELECT opened_at, open_method FROM media_history WHERE media_id = ? ORDER BY opened_at DESC LIMIT 5",
                (mid,)
            ).fetchall()
            if history:
                lines.append("")
                lines.append(f"  LETZTE WIEDERGABEN:")
                for h in history:
                    lines.append(f"    {h['opened_at'][:16]}  ({h['open_method']})")

            return True, "\n".join(lines)
        finally:
            conn.close()

    # ================================================================
    # EDIT
    # ================================================================

    def _edit(self, args: list, dry_run: bool) -> Tuple[bool, str]:
        try:
            mid = int(args[0])
        except (ValueError, IndexError):
            return False, "Usage: bach media edit <id> --title \"Neu\" [--type movie] [--rating 5]"

        remaining = args[1:]
        if not remaining:
            return False, "Keine Aenderungen angegeben."

        FIELD_MAP = {
            "--title": "title", "--type": "media_type", "--source": "source",
            "--url": "url", "--desc": "description", "--artist": "artist",
            "--album": "album", "--channel": "channel", "--season": "season",
            "--episode": "episode", "--rating": "rating", "--tags": "tags",
            "--notes": "notes", "--path": "local_path",
        }

        updates = {}
        i = 0
        while i < len(remaining):
            flag = remaining[i]
            if flag in FIELD_MAP and i + 1 < len(remaining):
                db_field = FIELD_MAP[flag]
                value = remaining[i + 1]
                if flag == "--tags":
                    value = json.dumps([t.strip() for t in value.split(",")])
                elif flag in ("--season", "--episode", "--rating"):
                    value = int(value)
                updates[db_field] = value
                i += 2
            else:
                i += 1

        if not updates:
            return False, "Keine gueltigen Felder."

        if dry_run:
            return True, f"[DRY RUN] Wuerde Medium #{mid} aktualisieren."

        conn = self._get_db()
        try:
            row = conn.execute("SELECT id FROM media_items WHERE id = ?", (mid,)).fetchone()
            if not row:
                return False, f"Medium #{mid} nicht gefunden."

            set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
            conn.execute(
                f"UPDATE media_items SET {set_clause} WHERE id = ?",
                list(updates.values()) + [mid]
            )
            conn.commit()
            return True, f"Medium #{mid} aktualisiert: {', '.join(updates.keys())}"
        finally:
            conn.close()

    # ================================================================
    # FAV
    # ================================================================

    def _fav(self, args: list, dry_run: bool) -> Tuple[bool, str]:
        try:
            mid = int(args[0])
        except (ValueError, IndexError):
            return False, "Usage: bach media fav <id> [--remove]"

        remove, _ = self._has_flag(args, "--remove")

        conn = self._get_db()
        try:
            row = conn.execute("SELECT title, is_favorite FROM media_items WHERE id = ?", (mid,)).fetchone()
            if not row:
                return False, f"Medium #{mid} nicht gefunden."

            new_val = 0 if remove else 1
            if dry_run:
                action = "entfernen" if remove else "setzen"
                return True, f"[DRY RUN] Wuerde Favorit {action}: {row['title']}"

            conn.execute("UPDATE media_items SET is_favorite = ? WHERE id = ?", (new_val, mid))
            conn.commit()

            if remove:
                return True, f"Favorit entfernt: {row['title']}"
            return True, f"Favorit gesetzt: {row['title']}"
        finally:
            conn.close()

    # ================================================================
    # BLACKLIST
    # ================================================================

    def _blacklist(self, args: list, dry_run: bool) -> Tuple[bool, str]:
        try:
            mid = int(args[0])
        except (ValueError, IndexError):
            return False, "Usage: bach media blacklist <id> [--remove]"

        remove, _ = self._has_flag(args, "--remove")

        conn = self._get_db()
        try:
            row = conn.execute("SELECT title, blacklist_flag FROM media_items WHERE id = ?", (mid,)).fetchone()
            if not row:
                return False, f"Medium #{mid} nicht gefunden."

            if dry_run:
                action = "entsperren" if remove else "sperren"
                return True, f"[DRY RUN] Wuerde {row['title']} {action}."

            if remove:
                conn.execute(
                    "UPDATE media_items SET blacklist_flag = 0, blacklisted_at = NULL WHERE id = ?",
                    (mid,)
                )
                conn.commit()
                return True, f"Blacklist entfernt: {row['title']}"
            else:
                conn.execute(
                    "UPDATE media_items SET blacklist_flag = 1, blacklisted_at = datetime('now') WHERE id = ?",
                    (mid,)
                )
                conn.commit()
                return True, f"Gesperrt: {row['title']}"
        finally:
            conn.close()

    # ================================================================
    # OPEN
    # ================================================================

    def _open(self, args: list) -> Tuple[bool, str]:
        try:
            mid = int(args[0])
        except (ValueError, IndexError):
            return False, "Usage: bach media open <id>"

        conn = self._get_db()
        try:
            row = conn.execute("SELECT * FROM media_items WHERE id = ?", (mid,)).fetchone()
            if not row:
                return False, f"Medium #{mid} nicht gefunden."

            if row["blacklist_flag"]:
                return False, f"Medium #{mid} ist gesperrt (Blacklist)."

            open_method = "manual"
            opened = False

            # URL oeffnen
            if row["url"]:
                webbrowser.open(row["url"])
                open_method = "browser"
                opened = True
            elif row["local_path"]:
                import os
                try:
                    os.startfile(row["local_path"])
                    open_method = "local"
                    opened = True
                except Exception as e:
                    return False, f"Konnte Datei nicht oeffnen: {e}"

            # Historie + last_opened aktualisieren
            conn.execute(
                "UPDATE media_items SET last_opened_at = datetime('now') WHERE id = ?",
                (mid,)
            )
            conn.execute(
                "INSERT INTO media_history (media_id, open_method) VALUES (?, ?)",
                (mid, open_method)
            )
            conn.commit()

            if opened:
                return True, f"Geoeffnet: {row['title']} ({open_method})"
            return True, f"Wiedergabe markiert: {row['title']} (keine URL/Pfad hinterlegt)"
        finally:
            conn.close()

    # ================================================================
    # HISTORY
    # ================================================================

    def _history(self, args: list) -> Tuple[bool, str]:
        limit, _ = self._parse_flag(args, "--limit")
        limit_n = int(limit) if limit else 20

        conn = self._get_db()
        try:
            rows = conn.execute(
                """SELECT mh.opened_at, mh.open_method, mi.id, mi.title, mi.media_type, mi.source
                   FROM media_history mh
                   JOIN media_items mi ON mi.id = mh.media_id
                   ORDER BY mh.opened_at DESC LIMIT ?""",
                (limit_n,)
            ).fetchall()

            if not rows:
                return True, "Keine Wiedergabe-Historie vorhanden."

            lines = ["WIEDERGABE-HISTORIE", "=" * 50, ""]
            for r in rows:
                icon = TYPE_ICONS.get(r["media_type"], "?")
                date = (r["opened_at"] or "")[:16]
                lines.append(f"  {date}  [{icon}] #{r['id']:3d}  {r['title'][:40]}  ({r['source']}/{r['open_method']})")

            return True, "\n".join(lines)
        finally:
            conn.close()

    # ================================================================
    # STATS
    # ================================================================

    def _stats(self) -> Tuple[bool, str]:
        conn = self._get_db()
        try:
            total = conn.execute("SELECT COUNT(*) FROM media_items WHERE blacklist_flag = 0").fetchone()[0]
            if total == 0:
                return True, 'Medienbibliothek ist leer. Starte mit: bach media add "Titel" --type movie'

            by_type = conn.execute(
                "SELECT media_type, COUNT(*) as cnt FROM media_items WHERE blacklist_flag = 0 GROUP BY media_type ORDER BY cnt DESC"
            ).fetchall()
            by_source = conn.execute(
                "SELECT source, COUNT(*) as cnt FROM media_items WHERE blacklist_flag = 0 GROUP BY source ORDER BY cnt DESC"
            ).fetchall()
            favs = conn.execute("SELECT COUNT(*) FROM media_items WHERE is_favorite = 1 AND blacklist_flag = 0").fetchone()[0]
            blacklisted = conn.execute("SELECT COUNT(*) FROM media_items WHERE blacklist_flag = 1").fetchone()[0]
            history_count = conn.execute("SELECT COUNT(*) FROM media_history").fetchone()[0]

            lines = ["MEDIEN-STATISTIK", "=" * 50, ""]
            lines.append(f"  Medien gesamt:     {total}")
            lines.append(f"  Favoriten:         {favs}")
            lines.append(f"  Gesperrt:          {blacklisted}")
            lines.append(f"  Wiedergaben:       {history_count}")

            lines.append("")
            lines.append("  Nach Typ:")
            for r in by_type:
                icon = TYPE_ICONS.get(r[0], "?")
                lines.append(f"    [{icon}] {r[0]:15s} {r[1]:3d}")

            lines.append("")
            lines.append("  Nach Quelle:")
            for r in by_source:
                lines.append(f"    {r[0]:15s} {r[1]:3d}")

            return True, "\n".join(lines)
        finally:
            conn.close()

    # ================================================================
    # HELP
    # ================================================================

    def _help(self) -> Tuple[bool, str]:
        lines = [
            "MEDIENVERWALTUNG", "=" * 50, "",
            "MEDIEN VERWALTEN",
            '  bach media add "Titel" --type movie --source netflix --url URL',
            "  bach media list [--type movie|series|music] [--source netflix] [--fav]",
            '  bach media search "Begriff"',
            "  bach media show <id>",
            '  bach media edit <id> --title "Neu" --rating 5',
            "",
            "FAVORITEN & BLACKLIST",
            "  bach media fav <id>              Favorit setzen",
            "  bach media fav <id> --remove     Favorit entfernen",
            "  bach media blacklist <id>        Medium sperren",
            "  bach media blacklist <id> --remove  Sperre aufheben",
            "",
            "WIEDERGABE",
            "  bach media open <id>             Medium oeffnen (Browser/Datei)",
            "  bach media history [--limit N]   Wiedergabe-Historie",
            "",
            "UEBERSICHT",
            "  bach media stats                 Statistik",
            "",
            f"MEDIENTYPEN: {', '.join(MEDIA_TYPES)}",
            f"QUELLEN:     {', '.join(SOURCES)}",
        ]
        return True, "\n".join(lines)
