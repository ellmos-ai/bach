# SPDX-License-Identifier: MIT
"""
Wiki Handler - Wiki-Artikel aus wiki/ anzeigen
===============================================

bach wiki list              Alle Artikel auflisten
bach wiki <thema>           Artikel anzeigen
bach wiki <ordner>/<thema>  Artikel aus Unterordner anzeigen
bach wiki search "keyword"  Artikel durchsuchen
bach wiki folders           Alle Themenordner auflisten

Unterordner-Unterstuetzung (v2.6 Refactoring):
  wiki/foerderung/icf.txt  ->  bach wiki foerderung/icf
  wiki/steuer/elster.txt   ->  bach wiki steuer/elster
"""
from pathlib import Path
import sqlite3
from datetime import datetime
from .base import BaseHandler
from .lang import t
from core.provenance import (
    classify_people_scope,
    classify_privacy,
    format_timestamp,
    truncate_text,
)


class WikiHandler(BaseHandler):
    """Handler fuer wiki Operationen"""

    def __init__(self, base_path: Path):
        super().__init__(base_path)
        # Wiki ist jetzt top-level (v2.6 Refactoring)
        self.wiki_path = base_path / "wiki"

    @property
    def profile_name(self) -> str:
        return "wiki"

    @property
    def target_file(self) -> Path:
        return self.wiki_path

    def get_operations(self) -> dict:
        return {
            "list": t("wiki_list_desc", default="Alle Wiki-Artikel auflisten"),
            "folders": t("wiki_folders_desc", default="Alle Themenordner auflisten"),
            "read": t("wiki_read_desc", default="Artikel anzeigen (Alias: bach wiki read <thema>)"),
            "<thema>": t("wiki_show_desc", default="Artikel zu einem Thema anzeigen"),
            "<ordner>/<thema>": t("wiki_subshow_desc", default="Artikel aus Unterordner (z.B. foerderung/icf)"),
            "search": t("wiki_search_desc", default="Artikel durchsuchen"),
            "provenance": t("wiki_provenance_desc", default="Metadaten, Personenbezug und Privacy-Hinweise anzeigen"),
            "sync": t("wiki_sync_desc", default="Help- und Wiki-Dateien in DB spiegeln (Index aktualisieren)")
        }

    def handle(self, operation: str, args: list, dry_run: bool = False) -> tuple:
        if not self.wiki_path.exists():
            return False, f"Wiki-Ordner nicht gefunden: {self.wiki_path}"

        if operation == "list" or operation is None:
            return self._list()
        elif operation == "folders":
            return self._list_folders()
        elif operation == "sync":
            return self._sync()
        elif operation == "search":
            if not args:
                return False, "Usage: bach wiki search \"keyword\""
            return self._search(" ".join(args))
        elif operation == "provenance":
            return self._provenance(args)
        elif operation == "read":
            if not args:
                return False, "Usage: bach wiki read <thema>"
            return self._show(" ".join(args))
        else:
            # operation ist das Thema (mit oder ohne Unterordner)
            return self._show(operation)

    def _list(self) -> tuple:
        """Alle Wiki-Artikel auflisten (inkl. Unterordner)"""
        # Index-Datei pruefen
        index_file = self.wiki_path / "_index.txt"
        if index_file.exists():
            index_content = index_file.read_text(encoding="utf-8")

            # Unterordner ergaenzen falls vorhanden
            folders = self._get_folders()
            if folders:
                articles_label = t("wiki_articles_label", default="THEMENORDNER")
                article_word = t("wiki_article_word", default="Artikel")
                folder_info = f"\n\n{articles_label}\n------------\n"
                for folder, count in folders:
                    folder_info += f"  {folder}/              ({count} {article_word})\n"
                folder_info += f"\n  {t('wiki_access', default='Abruf')}: bach wiki <ordner>/<thema>\n"
                folder_info += "  z.B.:  bach wiki foerderung/icf"
                return True, f"WIKI-ARTIKEL\n{'='*50}\n\n{index_content}{folder_info}"

            return True, f"WIKI-ARTIKEL\n{'='*50}\n\n{index_content}"

        # Sonst einfache Liste
        articles = list(self.wiki_path.glob("*.txt"))
        results = ["WIKI-ARTIKEL", "=" * 50, ""]

        for article in sorted(articles):
            if article.name.startswith("_"):
                continue
            name = article.stem
            try:
                first_line = article.read_text(encoding="utf-8").split("\n")[0]
                desc = first_line[:50] if first_line else ""
            except (OSError, UnicodeDecodeError):
                desc = ""
            results.append(f"  {name:<20} {desc}")

        # Unterordner
        folders = self._get_folders()
        if folders:
            results.append("")
            results.append("THEMENORDNER")
            results.append("-" * 40)
            for folder, count in folders:
                results.append(f"  {folder}/              ({count} Artikel)")
            results.append("")
            results.append("  Abruf: bach wiki <ordner>/<thema>")

        results.append("")
        results.append(f"Gesamt: {len(articles)} Artikel")
        results.append("Anzeigen: bach wiki <thema>")

        return True, "\n".join(results)

    def _list_folders(self) -> tuple:
        """Alle Themenordner mit ihren Artikeln auflisten"""
        folders = self._get_folders()

        if not folders:
            return True, "Keine Themenordner vorhanden.\n\nThemenordner werden fuer grosse Wissensgebiete angelegt."

        results = ["WIKI-THEMENORDNER", "=" * 50, ""]

        for folder_name, count in folders:
            folder_path = self.wiki_path / folder_name
            results.append(f"{folder_name.upper()}/")
            results.append("-" * 40)

            # Index lesen falls vorhanden
            index_file = folder_path / "_index.txt"
            if index_file.exists():
                try:
                    content = index_file.read_text(encoding="utf-8")
                    # Nur erste Zeilen als Beschreibung
                    lines = content.split("\n")[:5]
                    for line in lines:
                        if line.strip():
                            results.append(f"  {line}")
                except (OSError, UnicodeDecodeError):
                    pass

            # Artikel auflisten
            articles = [f for f in folder_path.glob("*.txt") if not f.name.startswith("_")]
            for article in sorted(articles):
                results.append(f"  - {folder_name}/{article.stem}")

            results.append("")

        results.append(f"Gesamt: {len(folders)} Ordner")
        results.append("Abruf: bach wiki <ordner>/<thema>")

        return True, "\n".join(results)

    def _get_folders(self) -> list:
        """Alle Unterordner mit Artikelanzahl zurueckgeben"""
        folders = []
        for item in self.wiki_path.iterdir():
            if item.is_dir() and not item.name.startswith("_"):
                txt_count = len([f for f in item.glob("*.txt") if not f.name.startswith("_")])
                if txt_count > 0:
                    folders.append((item.name, txt_count))
        return sorted(folders)

    def _read_from_db(self, thema):
        """Versucht Wiki-Artikel aus bach_blobs zu lesen."""
        db_path = self.base_path / "data" / "bach.db"
        if not db_path.exists():
            return None
        try:
            conn = sqlite3.connect(str(db_path))
            # Pfad-Varianten probieren
            if "/" not in thema:
                # Auch in Unterordnern suchen
                cursor = conn.execute(
                    "SELECT path, content FROM bach_blobs WHERE path LIKE ? AND category != 'wiki' LIMIT 1",
                    (f"wiki/%/{thema}.txt",)
                )
            else:
                cursor = conn.execute(
                    "SELECT path, content FROM bach_blobs WHERE path = ?",
                    (f"wiki/{thema}.txt",)
                )
            row = cursor.fetchone()
            conn.close()
            if row:
                return row[1]
            return None
        except Exception:
            return None

    def _show(self, thema: str) -> tuple:
        """Wiki-Artikel anzeigen (unterstuetzt Unterordner)"""
        # Normalisieren: Backslash zu Slash
        thema = thema.replace("\\", "/").lower()

        # DB-Lookup versuchen (SQ044: Wiki-in-DB)
        db_content = self._read_from_db(thema)
        if db_content:
            display_name = thema.upper().replace("/", " / ")
            return True, f"WIKI: {display_name}\n{'='*50}\n\n{db_content}"

        # Unterordner-Pfad?
        if "/" in thema:
            parts = thema.split("/", 1)
            folder = parts[0]
            subtopic = parts[1] if len(parts) > 1 else "_index"

            # Versuche Unterordner-Artikel
            article_path = self.wiki_path / folder / f"{subtopic}.txt"

            if not article_path.exists():
                # Vielleicht ohne .txt?
                article_path = self.wiki_path / folder / subtopic
                if article_path.is_dir():
                    # Es ist ein weiterer Unterordner - zeige dessen Index
                    article_path = article_path / "_index.txt"

            if not article_path.exists():
                # Fallback: Ordner-Index
                folder_index = self.wiki_path / folder / "_index.txt"
                if folder_index.exists():
                    try:
                        content = folder_index.read_text(encoding="utf-8")
                        return True, f"WIKI: {folder.upper()}/ (Index)\n{'='*50}\n\n{content}\n\nArtikel '{subtopic}' nicht gefunden im Ordner."
                    except (OSError, UnicodeDecodeError):
                        pass

                # Fuzzy-Suche im Unterordner
                folder_path = self.wiki_path / folder
                if folder_path.is_dir():
                    matches = list(folder_path.glob(f"*{subtopic}*.txt"))
                    if matches:
                        suggestions = ", ".join(f"{folder}/{m.stem}" for m in matches[:5])
                        return False, f"Artikel '{thema}' nicht gefunden.\nMeintest du: {suggestions}?"

                return False, f"Artikel '{thema}' nicht gefunden.\nVerfuegbar: bach wiki list"
        else:
            # Einfacher Artikel im Hauptordner
            article_path = self.wiki_path / f"{thema}.txt"

            if not article_path.exists():
                # Vielleicht ist es ein Ordner?
                folder_path = self.wiki_path / thema
                if folder_path.is_dir():
                    # Zeige Ordner-Index
                    index_file = folder_path / "_index.txt"
                    if index_file.exists():
                        try:
                            content = index_file.read_text(encoding="utf-8")
                            # Liste auch Artikel
                            articles = [f for f in folder_path.glob("*.txt") if not f.name.startswith("_")]
                            article_list = "\n\nARTIKEL IN DIESEM ORDNER\n------------------------\n"
                            for a in sorted(articles):
                                article_list += f"  bach wiki {thema}/{a.stem}\n"
                            return True, f"WIKI: {thema.upper()}/ (Themenordner)\n{'='*50}\n\n{content}{article_list}"
                        except (OSError, UnicodeDecodeError):
                            pass
                    # Ordner ohne Index - liste nur Artikel
                    articles = [f for f in folder_path.glob("*.txt") if not f.name.startswith("_")]
                    if articles:
                        results = [f"WIKI: {thema.upper()}/ (Themenordner)", "=" * 50, "", "Artikel:"]
                        for a in sorted(articles):
                            results.append(f"  bach wiki {thema}/{a.stem}")
                        return True, "\n".join(results)

            if not article_path.exists():
                # Fuzzy-Suche
                matches = list(self.wiki_path.glob(f"*{thema}*.txt"))
                if matches:
                    suggestions = ", ".join(m.stem for m in matches[:5])
                    return False, f"Artikel '{thema}' nicht gefunden.\nMeintest du: {suggestions}?"
                return False, f"Artikel '{thema}' nicht gefunden.\nVerfuegbar: bach wiki list"

        try:
            content = article_path.read_text(encoding="utf-8")
            display_name = thema.upper().replace("/", " / ")
            return True, f"WIKI: {display_name}\n{'='*50}\n\n{content}"
        except Exception as e:
            return False, f"Fehler beim Lesen: {e}"

    def _get_db_conn(self):
        db_path = self.base_path / "data" / "bach.db"
        if not db_path.exists():
            return None
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _wiki_evidence(self, category: str) -> str:
        if category == "help":
            return "Help-Referenz"
        return "Wiki-Artikel"

    def _fetch_article_metadata(self, thema: str) -> dict | None:
        normalized = thema.replace("\\", "/").lower()

        conn = self._get_db_conn()
        if conn is not None:
            try:
                row = conn.execute(
                    """
                    SELECT path, title, content, category, last_modified, tags, language
                    FROM wiki_articles
                    WHERE path = ?
                    """,
                    (f"wiki/{normalized}.txt",),
                ).fetchone()
                if row is None and "/" not in normalized:
                    row = conn.execute(
                        """
                        SELECT path, title, content, category, last_modified, tags, language
                        FROM wiki_articles
                        WHERE path LIKE ? OR path LIKE ?
                        ORDER BY path
                        LIMIT 1
                        """,
                        (f"wiki/{normalized}.txt", f"wiki/%/{normalized}.txt"),
                    ).fetchone()
                if row:
                    return dict(row)
            finally:
                conn.close()

        file_path = self.wiki_path / f"{normalized}.txt"
        if not file_path.exists() and "/" in normalized:
            folder, subtopic = normalized.split("/", 1)
            file_path = self.wiki_path / folder / f"{subtopic}.txt"
        if not file_path.exists():
            return None

        try:
            content = file_path.read_text(encoding="utf-8")
        except Exception:
            return None

        title = file_path.stem
        first_line = content.splitlines()[0].strip() if content.splitlines() else ""
        if first_line:
            stripped = first_line.lstrip("#-= ").strip()
            if len(stripped) > 2:
                title = stripped

        rel_path = file_path.relative_to(self.base_path).as_posix()
        return {
            "path": rel_path,
            "title": title,
            "content": content,
            "category": "wiki",
            "last_modified": format_timestamp(datetime.fromtimestamp(file_path.stat().st_mtime).isoformat()),
            "tags": None,
            "language": "de",
        }

    def _provenance_entry(self, row: dict) -> list[str]:
        content = row.get("content") or ""
        path = row.get("path") or ""
        category = row.get("category") or "wiki"
        people_scope, scope_reason = classify_people_scope(
            text=content,
            category=category,
            path=path,
        )
        privacy, privacy_hint = classify_privacy(
            text=content,
            category=category,
            path=path,
            people_scope=people_scope,
        )

        return [
            f"  {row.get('path', '-')}",
            f"    Titel: {row.get('title') or '-'}",
            f"    Evidenz: {self._wiki_evidence(category)} | Sprache: {row.get('language') or '-'}",
            f"    Personenbezug: {people_scope} | Privacy: {privacy}",
            f"    Letzte Änderung: {format_timestamp(row.get('last_modified'))}",
            f"    Inhalt: {truncate_text(content)}",
            f"    Hinweis: {scope_reason} {privacy_hint}",
            "",
        ]

    def _provenance(self, args: list) -> tuple:
        """Zeigt heuristische Provenance fuer einen oder mehrere Wiki-Artikel."""
        limit = 5
        article = None

        if args:
            if str(args[0]).isdigit():
                limit = max(1, min(int(args[0]), 20))
            else:
                article = " ".join(args)

        results = [
            "WIKI PROVENANCE (heuristisch)",
            "=" * 60,
            "",
            "Hinweis: Personenbezug und Privacy sind Review-Hilfen, keine harte Policy.",
        ]

        if article:
            row = self._fetch_article_metadata(article)
            if not row:
                return False, f"Artikel '{article}' nicht gefunden."
            results.extend(["", "[ARTIKEL]"])
            results.extend(self._provenance_entry(row))
            return True, "\n".join(results).rstrip()

        conn = self._get_db_conn()
        rows = []
        if conn is not None:
            try:
                rows = conn.execute(
                    """
                    SELECT path, title, content, category, last_modified, tags, language
                    FROM wiki_articles
                    ORDER BY last_modified DESC, path
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = []
            finally:
                conn.close()

        if not rows:
            files = sorted(
                (path for path in self.wiki_path.rglob("*.txt") if not path.name.startswith("_")),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )[:limit]
            for file_path in files:
                data = self._fetch_article_metadata(file_path.relative_to(self.wiki_path).with_suffix("").as_posix())
                if data:
                    rows.append(data)

        if not rows:
            return True, "Keine Wiki-Artikel für Provenance gefunden."

        results.extend(["", "[LETZTE ARTIKEL]"])
        for row in rows:
            if isinstance(row, sqlite3.Row):
                row = dict(row)
            results.extend(self._provenance_entry(row))

        return True, "\n".join(results).rstrip()

    def _fts_search(self, keyword):
        """FTS5-basierte Suche in bach_blobs."""
        db_path = self.base_path / "data" / "bach.db"
        if not db_path.exists():
            return None

        try:
            conn = sqlite3.connect(str(db_path))
            cursor = conn.execute("""
                SELECT path, snippet(bach_blobs_fts, 1, '>>>', '<<<', '...', 32)
                FROM bach_blobs_fts
                WHERE bach_blobs_fts MATCH ?
                ORDER BY rank
                LIMIT 20
            """, (keyword,))
            results = cursor.fetchall()
            conn.close()

            if not results:
                return None

            lines = [f"WIKI-SUCHE (FTS5): {keyword}", "=" * 50, ""]
            for path, snippet_text in results:
                display_name = path.replace("wiki/", "").replace(".txt", "")
                lines.append(f"  {display_name}")
                if snippet_text:
                    lines.append(f"    ...{snippet_text}...")
                lines.append("")
            lines.append(f"{len(results)} Treffer")
            return "\n".join(lines)
        except Exception:
            return None

    def _search(self, keyword: str) -> tuple:
        """Wiki-Artikel durchsuchen (inkl. Unterordner)"""
        # Versuche FTS5 zuerst
        fts_result = self._fts_search(keyword)
        if fts_result:
            return True, fts_result

        # Fallback: Dateisystem-Suche (bestehender Code)
        matches = []
        keyword_lower = keyword.lower()

        # Hauptordner durchsuchen
        for article in self.wiki_path.glob("*.txt"):
            if article.name.startswith("_"):
                continue
            match = self._search_file(article, keyword_lower)
            if match:
                matches.append((article.stem, match))

        # Unterordner durchsuchen (rekursiv)
        for article in self.wiki_path.rglob("*.txt"):
            if article.parent == self.wiki_path:
                continue  # Root-Dateien bereits oben behandelt
            if article.name.startswith("_"):
                continue
            match = self._search_file(article, keyword_lower)
            if match:
                rel = article.relative_to(self.wiki_path).with_suffix("")
                matches.append((rel.as_posix(), match))

        if not matches:
            return True, f"{t('no_results', default='Keine Treffer')} {t('wiki_for', default='fuer')}: {keyword}"

        results = [f"{t('wiki_search_label', default='WIKI-SUCHE')}: {keyword}", "=" * 50, ""]
        for name, context in matches:
            results.append(f"  {name}")
            if context:
                results.append(f"    ...{context}...")
            results.append("")

        results.append(f"{len(matches)} {t('search_results', default='Treffer')}")
        return True, "\n".join(results)

    def _search_file(self, path: Path, keyword_lower: str) -> str:
        """Einzelne Datei durchsuchen, Kontext zurueckgeben"""
        try:
            content = path.read_text(encoding="utf-8").lower()
            if keyword_lower in content or keyword_lower in path.stem.lower():
                idx = content.find(keyword_lower)
                if idx >= 0:
                    return content[max(0, idx-20):idx+len(keyword_lower)+30].replace("\n", " ")
                return ""
        except (OSError, UnicodeDecodeError):
            pass
        return None

    def _sync(self) -> tuple:
        """Spiegelt Help- und Wiki-Dateien in die Datenbank."""
        db_path = self.base_path / "data" / "bach.db"
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        try:
            # Tabelle erstellen (TOWER_OF_BABEL: mit language-Spalte)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS wiki_articles (
                    path TEXT PRIMARY KEY,
                    title TEXT,
                    content TEXT,
                    category TEXT,
                    last_modified TIMESTAMP,
                    tags TEXT,
                    language TEXT DEFAULT 'de'
                )
            """)
            
            count = 0
            
            # 1. Wiki-Dateien (wiki/**/*)
            # Rekursiv alle .txt
            if self.wiki_path.exists():
                for txt_file in self.wiki_path.rglob("*.txt"):
                    if txt_file.name.startswith("_"): continue

                    try:
                        rel_path = txt_file.relative_to(self.base_path).as_posix() # z.B. wiki/foerderung/icf.txt
                        content = txt_file.read_text(encoding="utf-8", errors="ignore")
                        title = txt_file.stem
                        # Versuche Titel aus erster Zeile zu holen
                        lines = content.splitlines()
                        if lines and lines[0].strip():
                            potential_title = lines[0].strip().lstrip("#-= ").strip()
                            if len(potential_title) > 2:
                                title = potential_title
                            
                        cursor.execute("""
                            INSERT OR REPLACE INTO wiki_articles (path, title, content, category, last_modified, language)
                            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, 'de')
                        """, (rel_path, title, content, "wiki"))
                        count += 1
                    except Exception as e:
                        print(f"Fehler bei {txt_file}: {e}")
                
            # 2. Help-Dateien (docs/help/*.txt) - Legacy-Support
            help_dir = self.base_path / "docs" / "help"
            if help_dir.exists():
                # Root help Files
                for txt_file in help_dir.glob("*.txt"):
                    if txt_file.name.startswith("_"): continue
                    
                    try:
                        rel_path = txt_file.relative_to(self.base_path).as_posix()
                        content = txt_file.read_text(encoding="utf-8", errors="ignore")
                        title = txt_file.stem
                        lines = content.splitlines()
                        if lines and lines[0].strip():
                            potential_title = lines[0].strip().lstrip("#-= ").strip()
                            if len(potential_title) > 2:
                                title = potential_title

                        cursor.execute("""
                            INSERT OR REPLACE INTO wiki_articles (path, title, content, category, last_modified, language)
                            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, 'de')
                        """, (rel_path, title, content, "help"))
                        count += 1
                    except Exception as e:
                        print(f"Fehler bei {txt_file}: {e}")

                # Unterordner von Help die NICHT wiki sind (z.B. tools)
                for item in help_dir.iterdir():
                    if item.is_dir() and item.name.lower() != "wiki" and not item.name.startswith("_"):
                        for txt_file in item.glob("*.txt"):
                            if txt_file.name.startswith("_"): continue
                            
                            try:
                                rel_path = txt_file.relative_to(self.base_path).as_posix()
                                content = txt_file.read_text(encoding="utf-8", errors="ignore")
                                title = txt_file.stem
                                lines = content.splitlines()
                                if lines and lines[0].strip():
                                    potential_title = lines[0].strip().lstrip("#-= ").strip()
                                    if len(potential_title) > 2:
                                        title = potential_title
                                    
                                cursor.execute("""
                                    INSERT OR REPLACE INTO wiki_articles (path, title, content, category, last_modified)
                                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                                """, (rel_path, title, content, "help"))
                                count += 1
                            except (OSError, UnicodeDecodeError, sqlite3.Error):
                                pass
                        
            conn.commit()

            # HOOK: Nach wiki_write → Automatische Neuindexierung in unified_search
            # (SQ064 Runde 32 - Hybrid-Suche)
            try:
                from tools.unified_search import UnifiedSearch
                search_engine = UnifiedSearch(db_path=db_path)
                ok, msg = search_engine.index_wiki()
                if ok:
                    return True, f"Synchronisation abgeschlossen. {count} Artikel in DB aktualisiert.\nSuch-Index aktualisiert: {msg}"
                else:
                    return True, f"Synchronisation abgeschlossen. {count} Artikel in DB aktualisiert.\nWARNUNG: Such-Index-Update fehlgeschlagen: {msg}"
            except Exception as hook_error:
                # Hook-Fehler sollten nicht die gesamte Sync-Operation blockieren
                return True, f"Synchronisation abgeschlossen. {count} Artikel in DB aktualisiert.\nWARNUNG: Such-Index-Update fehlgeschlagen: {hook_error}"

        except Exception as e:
            return False, f"Datenbank-Fehler: {e}"
        finally:
            conn.close()
