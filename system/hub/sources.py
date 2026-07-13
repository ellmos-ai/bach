# SPDX-License-Identifier: MIT
"""
Sources Handler - Kontextquellen-System
========================================

Zentrale Registry fuer alle Wissensquellen mit konfigurierbaren Triggern.

Befehle:
  --sources status              Alle Quellen anzeigen
  --sources toggle <id>         Quelle an/aus
  --sources inject <id>         Injektion an/aus
  --sources get <id> [query]    Inhalt abrufen
  --sources search <text>       Wort-Trigger pruefen
  --sources contacts <query>    Hilfsquelle finden
  --sources problems            Fehler-Log pruefen
"""
import json
import sqlite3
from pathlib import Path
from typing import Tuple, List, Dict, Any
from .base import BaseHandler


class SourcesHandler(BaseHandler):
    """Handler fuer --sources Operationen."""
    
    def __init__(self, base_path: Path):
        super().__init__(base_path)
        self.config_file = base_path / "data" / "context_sources.json"
        self.db_path = self._canonical_db
        self.help_dir = base_path / "help"
        self._config = None
    
    @property
    def profile_name(self) -> str:
        return "sources"
    
    @property
    def target_file(self) -> Path:
        return self.config_file
    
    def get_operations(self) -> dict:
        return {
            "status": "Alle Quellen anzeigen",
            "toggle": "Quelle an/aus (--sources toggle <id>)",
            "inject": "Injektion an/aus (--sources inject <id>)",
            "get": "Inhalt abrufen (--sources get <id> [query])",
            "search": "Wort-Trigger pruefen (--sources search <text>)",
            "contacts": "Hilfsquelle finden (--sources contacts <query>)",
            "problems": "Fehler-Log pruefen"
        }
    
    @property
    def config(self) -> Dict[str, Any]:
        """Laedt Konfiguration (cached)."""
        if self._config is None:
            if self.config_file.exists():
                with open(self.config_file, "r", encoding="utf-8") as f:
                    self._config = json.load(f)
            else:
                self._config = {"sources": {}}
        return self._config
    
    def _save_config(self):
        """Speichert Konfiguration."""
        with open(self.config_file, "w", encoding="utf-8") as f:
            json.dump(self._config, f, indent=2, ensure_ascii=False)
    
    def handle(self, operation: str, args: list, dry_run: bool = False) -> Tuple[bool, str]:
        """Verarbeitet Sources-Anfragen."""
        
        if operation == "status" or not operation:
            return self._status()
        
        elif operation == "toggle":
            if not args:
                return False, "Usage: --sources toggle <source_id>"
            return self._toggle(args[0], "enabled")
        
        elif operation == "inject":
            if not args:
                return False, "Usage: --sources inject <source_id>"
            return self._toggle(args[0], "injection_enabled")
        
        elif operation == "get":
            if not args:
                return False, "Usage: --sources get <source_id> [query]"
            source_id = args[0]
            query = " ".join(args[1:]) if len(args) > 1 else None
            return self._get(source_id, query)
        
        elif operation == "search":
            if not args:
                return False, "Usage: --sources search <text>"
            return self._search(" ".join(args))
        
        elif operation == "contacts":
            query = " ".join(args) if args else None
            return self._contacts(query)
        
        elif operation == "problems":
            return self._problems()
        
        else:
            return self._status()
    
    def _status(self) -> Tuple[bool, str]:
        """Zeigt Status aller Quellen."""
        sources = self.config.get("sources", {})
        
        lines = []
        lines.append("=" * 50)
        lines.append("KONTEXTQUELLEN-STATUS")
        lines.append("=" * 50)
        
        # Nach Gewicht sortieren
        sorted_sources = sorted(
            sources.items(), 
            key=lambda x: x[1].get("weight", 0), 
            reverse=True
        )
        
        for source_id, data in sorted_sources:
            enabled = "✓" if data.get("enabled", False) else "✗"
            inject = "📍" if data.get("injection_enabled", False) else "  "
            weight = data.get("weight", 0)
            name = data.get("name", source_id)
            
            lines.append(f"  [{enabled}]{inject} {name:20} (W:{weight})")
            
            # Trigger anzeigen
            word_triggers = data.get("word_triggers", [])
            if word_triggers:
                lines.append(f"       Wort: {', '.join(word_triggers[:5])}")
        
        lines.append("")
        lines.append("Legende: ✓=aktiv, ✗=inaktiv, 📍=Auto-Inject")
        lines.append("Befehle: --sources toggle/inject <id>")
        
        return True, "\n".join(lines)
    
    def _toggle(self, source_id: str, field: str) -> Tuple[bool, str]:
        """Schaltet eine Quelle oder deren Injektion um."""
        sources = self.config.get("sources", {})
        
        if source_id not in sources:
            available = ", ".join(sources.keys())
            return False, f"Quelle '{source_id}' nicht gefunden.\nVerfuegbar: {available}"
        
        current = sources[source_id].get(field, False)
        sources[source_id][field] = not current
        self._save_config()
        
        status = "aktiviert" if not current else "deaktiviert"
        field_name = "Quelle" if field == "enabled" else "Injektion"
        
        return True, f"[OK] {field_name} '{source_id}' {status}"
    
    def _get(self, source_id: str, query: str = None) -> Tuple[bool, str]:
        """Ruft Inhalt einer Quelle ab."""
        sources = self.config.get("sources", {})
        
        if source_id not in sources:
            return False, f"Quelle '{source_id}' nicht gefunden."
        
        # Je nach Quelle unterschiedliche Inhalte
        if source_id == "lessons_learned":
            return self._get_lessons(query)
        elif source_id == "strategies":
            return self._get_strategies(query)
        elif source_id == "best_practices":
            return self._get_practices(query)
        elif source_id == "help":
            return self._get_help(query)
        elif source_id == "changelog":
            return self._get_changelog()
        elif source_id == "problems":
            return self._problems()
        else:
            return True, f"Quelle '{source_id}' hat keinen direkten Inhalt."
    
    def _get_lessons(self, query: str = None) -> Tuple[bool, str]:
        """Laedt Lessons Learned."""
        lessons_file = self.help_dir / "lessons.txt"
        if not lessons_file.exists():
            return True, "Keine Lessons gefunden."
        
        content = lessons_file.read_text(encoding="utf-8")
        
        if query:
            # Filtern nach Query
            lines = [l for l in content.split("\n") if query.lower() in l.lower()]
            return True, "\n".join(lines) if lines else f"Keine Lessons zu '{query}'"
        
        return True, content[:2000]  # Max 2000 Zeichen
    
    def _get_strategies(self, query: str = None) -> Tuple[bool, str]:
        """Laedt Strategien."""
        strategies = {
            "blockiert": "Ueberspringen und spaeter zurueckkommen ist OK. Andere Aufgabe waehlen.",
            "komplex": "In kleine Schritte zerlegen. Jeder Schritt max 15 Minuten.",
            "unklar": "Erst verstehen, dann fixen. Fragen stellen statt raten.",
            "muede": "Pause machen. Kleine Erfolge feiern. Nicht perfekt sein muessen.",
            "default": "Erst verstehen, dann fixen."
        }
        
        if query and query.lower() in strategies:
            return True, f"[STRATEGIE] {strategies[query.lower()]}"
        
        lines = ["STRATEGIEN:", ""]
        for key, value in strategies.items():
            if key != "default":
                lines.append(f"  {key}: {value}")
        
        return True, "\n".join(lines)
    
    def _get_practices(self, query: str = None) -> Tuple[bool, str]:
        """Laedt Best Practices."""
        practices_file = self.help_dir / "practices.txt"
        if not practices_file.exists():
            return True, "Keine Best Practices gefunden."
        
        content = practices_file.read_text(encoding="utf-8")
        
        if query:
            lines = [l for l in content.split("\n") if query.lower() in l.lower()]
            return True, "\n".join(lines) if lines else f"Keine Practices zu '{query}'"
        
        return True, content[:2000]
    
    def _get_help(self, query: str = None) -> Tuple[bool, str]:
        """Laedt Hilfe-Datei."""
        if query:
            help_file = self.help_dir / f"{query}.txt"
            if help_file.exists():
                return True, help_file.read_text(encoding="utf-8")[:3000]
        
        # Liste verfuegbarer Hilfe
        files = list(self.help_dir.glob("*.txt"))
        names = [f.stem for f in files]
        return True, f"Verfuegbare Hilfe: {', '.join(sorted(names))}"
    
    def _get_changelog(self) -> Tuple[bool, str]:
        """Laedt Changelog aus SKILL.md."""
        skill_file = self.base_path / "SKILL.md"
        if not skill_file.exists():
            return True, "Kein Changelog gefunden."
        
        content = skill_file.read_text(encoding="utf-8")
        
        # Changelog-Sektion extrahieren
        if "## Changelog" in content:
            start = content.index("## Changelog")
            changelog = content[start:start+1500]
            return True, changelog
        
        return True, "Changelog nicht gefunden in SKILL.md"
    
    def _search(self, text: str) -> Tuple[bool, str]:
        """Prueft welche Quellen durch Text getriggert werden."""
        sources = self.config.get("sources", {})
        text_lower = text.lower()
        
        triggered = []
        for source_id, data in sources.items():
            if not data.get("enabled", False):
                continue
            
            triggers = data.get("word_triggers", [])
            matches = [t for t in triggers if t.lower() in text_lower]
            
            if matches:
                triggered.append({
                    "source": source_id,
                    "name": data.get("name", source_id),
                    "matches": matches,
                    "weight": data.get("weight", 0)
                })
        
        if not triggered:
            return True, f"Keine Quellen getriggert durch: '{text}'"
        
        # Nach Gewicht sortieren
        triggered.sort(key=lambda x: x["weight"], reverse=True)
        
        lines = [f"GETRIGGERTE QUELLEN fuer '{text}':", ""]
        for t in triggered:
            lines.append(f"  [{t['weight']}] {t['name']}: {', '.join(t['matches'])}")
        
        return True, "\n".join(lines)
    
    def _contacts(self, query: str = None) -> Tuple[bool, str]:
        """Findet passende Kontakte in bach.db."""
        import sqlite3

        if not self.db_path.exists():
            return False, "Datenbank nicht gefunden (data/bach.db)"

        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
        except Exception as e:
            return False, f"DB-Verbindungsfehler: {e}"

        try:
            if not query:
                # Kategorien-Uebersicht
                rows = conn.execute(
                    "SELECT category, COUNT(*) as cnt FROM contacts "
                    "WHERE is_active = 1 GROUP BY category ORDER BY cnt DESC"
                ).fetchall()
                lines = ["KONTAKTE (bach.db):", ""]
                total = 0
                for r in rows:
                    lines.append(f"  {r['category'] or 'ohne'}: {r['cnt']} Eintraege")
                    total += r['cnt']
                lines.append(f"\nGesamt: {total} aktive Kontakte")
                lines.append("Suche: bach sources contacts <query>")
                conn.close()
                return True, "\n".join(lines)

            # Volltextsuche
            q = f"%{query}%"
            rows = conn.execute(
                "SELECT name, category, subcategory, organization, phone, email, notes "
                "FROM contacts WHERE is_active = 1 AND ("
                "  name LIKE ? OR category LIKE ? OR subcategory LIKE ? "
                "  OR organization LIKE ? OR notes LIKE ? OR tags LIKE ?"
                ") ORDER BY name LIMIT 15",
                (q, q, q, q, q, q)
            ).fetchall()
            conn.close()

            if not rows:
                return True, f"Keine Kontakte gefunden fuer '{query}'"

            lines = [f"KONTAKTE fuer '{query}':", ""]
            for r in rows:
                cat = r['subcategory'] or r['category'] or ''
                org = f" ({r['organization']})" if r['organization'] else ''
                lines.append(f"  {r['name']}{org} [{cat}]")
                if r['phone']:
                    lines.append(f"    Tel: {r['phone']}")
                if r['email']:
                    lines.append(f"    Mail: {r['email']}")

            return True, "\n".join(lines)

        except Exception as e:
            conn.close()
            return False, f"Kontakt-Suche fehlgeschlagen: {e}"
    
    def _problems(self) -> Tuple[bool, str]:
        """Prueft auf aktive Probleme."""
        problems = []
        
        # 1. Log-Dateien auf Fehler pruefen
        logs_dir = self.base_path / "data" / "logs"
        if logs_dir.exists():
            for log_file in logs_dir.glob("*.log"):
                try:
                    content = log_file.read_text(encoding="utf-8", errors="ignore")
                    error_lines = [l for l in content.split("\n") 
                                  if "error" in l.lower() or "exception" in l.lower()]
                    if error_lines:
                        problems.append({
                            "source": log_file.name,
                            "count": len(error_lines),
                            "last": error_lines[-1][:80]
                        })
                except (OSError, UnicodeDecodeError):
                    pass

        # 2. Blockierte Tasks
        try:
            from ..handlers.base import BaseHandler
            import sqlite3
            db_path = self._canonical_db
            if db_path.exists():
                conn = sqlite3.connect(db_path)
                cursor = conn.execute(
                    "SELECT COUNT(*) FROM tasks WHERE status = 'blocked'"
                )
                blocked = cursor.fetchone()[0]
                conn.close()
                if blocked > 0:
                    problems.append({
                        "source": "tasks",
                        "count": blocked,
                        "last": f"{blocked} blockierte Tasks"
                    })
        except (sqlite3.Error, ImportError, OSError):
            pass
        
        if not problems:
            return True, "[OK] Keine aktiven Probleme erkannt."
        
        lines = ["AKTIVE PROBLEME:", "=" * 40]
        for p in problems:
            lines.append(f"\n[{p['source']}] {p['count']} Eintraege")
            lines.append(f"  Letzter: {p['last']}")
        
        return True, "\n".join(lines)
