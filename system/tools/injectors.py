#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Tool: injectors
Version: 1.0.0
Author: BACH Team
Created: 2026-02-04
Updated: 2026-02-04
Anthropic-Compatible: True

VERSIONS-HINWEIS: Prüfe auf neuere Versionen mit: bach tools version injectors

Description:
    [Beschreibung hinzufügen]

Usage:
    python injectors.py [args]
"""

__version__ = "1.0.0"
__author__ = "BACH Team"

"""
Injector System - Automatische Hilfe und Kontext
================================================

Injektoren die Claude kognitiv entlasten:
- StrategyInjector: Hilfreiche Gedanken bei Trigger-Wörtern
- ContextInjector: Auto-Kontext bei Stichwörtern
- TimeInjector: Regelmäßige Zeit-Updates
- BetweenInjector: Auto-Erinnerungen nach Task-Done

v1.1.75: Cooldown-Feature - Injektoren werden nach Anzeige X Min stumm geschaltet
"""
import re
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple


class InjectorConfig:
    """Konfiguration für Injektoren."""
    
    def __init__(self, config_file: Path):
        self.config_file = config_file
        self.config = self._load()
    
    def _load(self) -> dict:
        """Lädt Konfiguration."""
        default = {
            "strategy_injector": True,    # AN - mit Selbst-Deaktivierungs-Hinweis
            "context_injector": True,     # Default AN - hilft bei Konventionen
            "time_injector": True,        # Default AN - Zeitgefuehl ermoeglichen
            "between_injector": True,     # Default AN - sehr nuetzlich
            "timebeat_interval": 60,      # Sekunden (1 Min)
        }
        
        if self.config_file.exists():
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    default.update(loaded.get("injectors", {}))
            except (json.JSONDecodeError, OSError):
                pass
        
        return default
    
    def save(self):
        """Speichert Konfiguration."""
        try:
            full_config = {}
            if self.config_file.exists():
                with open(self.config_file, "r", encoding="utf-8") as f:
                    full_config = json.load(f)
            
            full_config["injectors"] = self.config
            
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(full_config, f, ensure_ascii=False, indent=2)
        except (json.JSONDecodeError, OSError):
            pass
    
    def toggle(self, injector: str) -> bool:
        """Schaltet Injektor um."""
        if injector in self.config:
            self.config[injector] = not self.config[injector]
            self.save()
            return self.config[injector]
        return False
    
    def is_enabled(self, injector: str) -> bool:
        """Prüft ob Injektor aktiv."""
        return self.config.get(injector, False)


class StrategyInjector:
    """
    Injiziert hilfreiche Gedanken basierend auf Trigger-Wörtern.
    
    Beispiele:
    - "Fehler" + entspannte Situation → "Fehler sind wichtige Informationen"
    - "komplex" → "In kleine Schritte zerlegen"
    - "blockiert" → "Überspringen und später zurückkommen"
    """
    
    # Strategie-Map: Trigger → Hilfreicher Gedanke
    STRATEGIES = {
        # Fehler-Handling
        ("fehler", "error", "bug", "kaputt"): [
            "Fehler sind wertvolle Informationen, nicht Versagen.",
            "Erst verstehen, dann fixen.",
        ],
        
        # Komplexität
        ("komplex", "kompliziert", "schwierig", "gross"): [
            "In kleine Schritte zerlegen (~5 Min pro Schritt).",
            "Was ist der kleinste erste Schritt?",
        ],
        
        # Blockade
        ("blockiert", "blocked", "stuck", "komme nicht weiter"): [
            "Überspringen und später zurückkommen ist OK.",
            "Frage an User in chat.json notieren.",
        ],
        
        # Zeit-Druck
        ("wenig zeit", "schnell", "eilt", "dringend"): [
            "Qualität vor Geschwindigkeit.",
            "Lieber weniger aber richtig.",
        ],
        
        # Unsicherheit
        ("unsicher", "weiss nicht", "vielleicht", "unklar"): [
            "Bei Unklarheit: Nachfragen statt raten.",
            "Annahmen explizit dokumentieren.",
        ],
        
        # Erfolg
        ("fertig", "geschafft", "done", "erledigt"): [
            "Gut gemacht! Kurz durchatmen.",
            "Between-Tasks Check nicht vergessen.",
        ],
    }
    
    @classmethod
    def check(cls, text: str, context: dict = None) -> Optional[str]:
        """
        Prüft Text auf Trigger und gibt passende Strategie zurück.
        
        Args:
            text: Zu prüfender Text
            context: Optional - Zusätzlicher Kontext (Zeit, Memory-Status, etc.)
        
        Returns:
            Hilfreicher Gedanke oder None
        """
        text_lower = text.lower()
        
        for triggers, strategies in cls.STRATEGIES.items():
            if any(t in text_lower for t in triggers):
                # Kontext-abhängige Auswahl
                if context and context.get("time_remaining", 999) > 5:
                    # Viel Zeit übrig → entspanntere Strategie
                    msg = strategies[0]
                else:
                    msg = strategies[-1]
                return f"[STRATEGIE] {msg}"

        return None


class ContextInjector:
    """
    Erkennt Stichwörter und bietet Kontext-Suche an.

    Nicht aggressiv - nur Hinweis dass Kontext verfügbar ist.
    """

    # Triggers aus DB (v1.1.80)
    _cache = None
    _last_load = None
    _ttl_sec = 300
    base_path = None
    _session_triggered = set() # v1.1.82: IDs der Themen-Pakete die bereits gefeuert haben

    # Trigger-Woerter die Kontext-Suche vorschlagen (Hardcoded Fallback)
    CONTEXT_TRIGGERS = {
        # === SYSTEM-KONTEXT ===
        "encoding": "Encoding-Probleme? bach c_encoding_fixer <datei>",
        "pfad": "Pfad-Fragen? --help dirs",
        "json": "JSON-Probleme? bach c_json_repair <datei>",
        "memory": "Memory-Fragen? --help memory",
        "task": "Task-System? --help tasks",
        "fehler": "Bekannte Fehler? --help lessons",
        "letzte session": "Letzte Session? --context recent 1",

        # === DOMAIN-TOOLS (Die Haende der LLMs) ===

        # OCR & Dokumenten-Verarbeitung
        "ocr": "OCR-Tools: tools/c_ocr_engine.py (Tesseract+PyMuPDF), skills/_services/document/ocr_service.py",
        "texterkennung": "OCR-Tools: tools/c_ocr_engine.py (Tesseract+PyMuPDF), skills/_services/document/ocr_service.py",
        "pdf text": "PDF-Text: tools/c_ocr_engine.py --pdf <datei> | skills/_services/document/pdf_service.py",
        "bild text": "Bild-OCR: tools/c_ocr_engine.py <bild> (Tesseract)",
        "scan": "Scanner: tools/folder_diff_scanner.py | skills/_services/document/scanner_service.py",
        "dokument suche": "Dokument-Suche: tools/doc_search.py --search <begriff>",
        "dokument finden": "Dokument-Suche: tools/doc_search.py --search <begriff>",
        "datei suchen": "Dokument-Suche: tools/doc_search.py --search <begriff> | --folders (registrierte Ordner)",

        # Daten-Import & Export
        "import": "Data-Import: tools/data_importer.py --csv/--json <datei> --table <tabelle> (Schema-Erkennung, Duplikate, Rollback)",
        "csv import": "CSV-Import: tools/data_importer.py --csv <datei> --table <tabelle> --dry-run",
        "json import": "JSON-Import: tools/data_importer.py --json <datei> --table <tabelle>",
        "daten importieren": "Data-Import: tools/data_importer.py (--list-tables, --describe, --csv, --json, --history, --rollback)",
        "export": "Exporte: bach steuer export --format vorsorge | tools/data_importer.py --history",
        "ordner ueberwachen": "Folder-Scanner: tools/folder_diff_scanner.py <ordner> (Diff-Erkennung, Hash-Vergleich)",
        "neue dateien": "Folder-Scanner: tools/folder_diff_scanner.py <ordner> --unprocessed",

        # Versicherungen & Finanzen
        "versicherung": "Versicherungs-Verwaltung: bach versicherung status | bach versicherung list/check/fristen",
        "insurance": "Versicherungs-Verwaltung: bach versicherung status | bach versicherung list/check/fristen",
        "fixkosten": "Fixkosten: bach haushalt fixkosten | bach.db fin_contracts",
        "abo": "Abo-Verwaltung: bach abo list/check/export",
        "steuer": "Steuer-Tools: bach steuer status/beleg/posten/export | Steuer-Workflow",

        # Gesundheit
        "gesundheit": "Gesundheit: bach gesundheit diagnosen/medikamente/labor/termine | bach.db health_*",
        "arzt": "Gesundheit: bach gesundheit termine --upcoming | diagnosen",
        "medikament": "Medikamente: bach gesundheit medikamente | bach.db health_medications",

        # Kontakte
        "kontakt": "Kontakte: bach contact list/search/add | bach.db contacts",
        "kontakte": "Kontakte: bach contact list/search/add/birthday | bach.db contacts",

        # Haushalt
        "haushalt": "Haushalt: bach haushalt due/routinen/kalender/fixkosten/insurance-check/einkauf",
        "routine": "Routinen: bach haushalt due (faellige Aufgaben) | routinen (alle)",
        "einkauf": "Einkaufsliste: bach haushalt einkauf",

        # Lebenslauf
        "lebenslauf": "CV-Generator: tools/cv_generator.py (ASCII-CV aus Ordnerstruktur + DB)",
        "cv": "CV-Generator: tools/cv_generator.py (ASCII-CV aus Ordnerstruktur + DB)",
        "bewerbung": "CV-Generator: tools/cv_generator.py | user/bewerbungsexperte/",

        # MCP
        "mcp": "MCP-Server: tools/mcp_server.py (6 Tools, 5 Resources fuer IDE-Integration)",

        # === CODE-TOOLS ===

        # Python-Bearbeitung
        "python bearbeiten": "Python-Editor: bach python_cli_editor <datei> --show-all",
        "python editieren": "Python-Editor: bach python_cli_editor <datei> --show-all",
        "klasse bearbeiten": "Python-Editor: bach python_cli_editor <datei> --show-all",
        "methode bearbeiten": "Python-Editor: bach python_cli_editor <datei> --show-all",
        "funktion bearbeiten": "Python-Editor: bach python_cli_editor <datei> --show-all",
        "code struktur": "Python-Editor: bach python_cli_editor <datei> --show-all",
        "imports anzeigen": "Python-Editor: bach python_cli_editor <datei> --show-imports",

        # Code-Analyse
        "code analysieren": "Code-Analyse: bach code_analyzer <datei>",
        "analyse code": "Code-Analyse: bach code_analyzer <datei>",
        "dead code": "Code-Analyse: bach code_analyzer <datei>",

        # Encoding/Formatierung
        "encoding problem": "Encoding-Fix: bach c_encoding_fixer <datei>",
        "umlaute kaputt": "Encoding-Fix: bach c_encoding_fixer <datei>",
        "utf-8": "Encoding-Fix: bach c_encoding_fixer <datei>",
        "emoji": "Emoji-Scanner: bach c_emoji_scanner <datei>",
        "einrueckung": "Indent-Check: bach c_indent_checker <datei>",
        "indent": "Indent-Check: bach c_indent_checker <datei>",

        # Import-Handling
        "imports sortieren": "Import-Organizer: bach c_import_organizer <datei>",
        "import problem": "Import-Diagnose: bach c_import_diagnose <datei>",
        "import fehlt": "Import-Diagnose: bach c_import_diagnose <datei>",

        # Datei-Operationen
        "datei aufteilen": "Python-Cutter: bach c_pycutter <datei>",
        "datei splitten": "Python-Cutter: bach c_pycutter <datei>",
        "zu gross": "Python-Cutter: bach c_pycutter <datei> (fuer Python-Dateien)",
        "sqlite anzeigen": "SQLite-Viewer: bach c_sqlite_viewer <db>",
        "datenbank anzeigen": "SQLite-Viewer: bach c_sqlite_viewer <db>",
        "datenbank": "DB-Tools: tools/data_importer.py (Import) | bach c_sqlite_viewer (View) | bach db query (SQL)",

        # Konvertierung
        "markdown zu pdf": "MD-to-PDF: bach c_md_to_pdf <datei>",
        "md to pdf": "MD-to-PDF: bach c_md_to_pdf <datei>",
        "format konvertieren": "Konverter: bach c_universal_converter <datei>",
        "konvertieren": "Konverter: bach c_universal_converter <datei>",

        # Suche & Discovery
        "tool finden": "Tool-Empfehlung: bach tool suggest 'beschreibung'",
        "welches tool": "Tool-Empfehlung: bach tool suggest 'beschreibung'",
        "tool suchen": "Tool-Suche: bach tools search <begriff>",
        "gibt es ein tool": "Tool-Suche: bach tools search <begriff> | bach tool suggest 'beschreibung'",

        # === ERSTELLUNG & KONVENTIONEN ===

        # Tool-Erstellung
        "neues tool": "ERST PRUEFEN: bach tools search <begriff> | Tool-Benennung: --help naming",
        "tool erstellen": "ERST PRUEFEN: bach tools search <begriff> | Tool-Benennung: --help naming",
        "python tool": "ERST PRUEFEN: bach tools search <begriff> | Tool-Benennung: --help naming",
        "neues script": "ERST PRUEFEN: bach tools search <begriff> | Tool-Benennung: --help naming",

        # Konzept-Erstellung
        "konzept": "Konzepte lokal ablegen! --help practices (ARCHITEKTUR-PRINZIPIEN)",
        "concept": "Konzepte lokal ablegen! --help practices (ARCHITEKTUR-PRINZIPIEN)",
        "entwurf": "Konzepte lokal ablegen! --help practices (ARCHITEKTUR-PRINZIPIEN)",

        # Datei-Erstellung
        "neue datei": "Namenskonventionen: --help naming + --help formats",
        "datei erstellen": "Namenskonventionen: --help naming + --help formats",

        # Agent-Erstellung
        "neuer agent": "Agent-Konzept in agents/ ablegen! --help practices",
        "agent erstellen": "Agent-Konzept in agents/ ablegen! --help practices",

        # Architektur
        "architektur": "Diagramme: docs/ARCHITECTURE_DIAGRAMS.md | --help practices",
        "prinzipien": "Architektur-Prinzipien: --help practices",
        "regeln": "Regelwerk-Index: --help practices",

        # === SKILLS & STRATEGIE ===

        # Förderplaner
        "foerderplan": "Förderplaner: agents/_experts/foerderplaner/ | GUI: /bericht",
        "bericht status": "Bericht-Status: agents/_experts/foerderplaner/ | GUI: /bericht",
        
        # System-Analyse
        "system analyse": "Analyze-System: skills/_services/analyze-system.md (System Thinking, Bottlenecks)",
        "bottleneck": "Analyze-System: skills/_services/analyze-system.md (System Thinking, Bottlenecks)",
        
        # Brainstorming/Entscheidung
        "brainstorm": "Brainstorming: skills/_services/brainstorm.md (Methoden: SCAMPER, 6-Hats)",
        "ideen finden": "Brainstorming: skills/_services/brainstorm.md | bach tool suggest 'kreativ'",
        "entscheidung": "Decision-Support: skills/_services/decide.md (Matrix, SWOT, RICE)",
        "dilemma": "Decision-Support: skills/_services/decide.md",

        # Wiki & Lernen
        "quiz": "Wiki-Quizzer: agents/_experts/wikiquizzer | Interaktives Lernen aus Wiki",
        "lernen": "Wiki-Quizzer: agents/_experts/wikiquizzer | Interaktives Lernen",

        # Prompting
        "prompt erstellen": "Prompt-Generator: skills/_services/prompt_generator/ | Meta-Prompts",
        "system prompt": "Prompt-Generator: skills/_services/prompt_generator/ | Optimierung",

        # === PARTNER & KOMMUNIKATION ===
        "partner": "Partner: bach partner list/status/delegate | bach msg send <partner> <text>",
        "nachricht": "Nachrichten: bach msg ping --from <partner> | bach msg send <partner> <text>",
        "gemini": "Gemini-Partner: bach msg send gemini <text> | partners/gemini/outbox/",
        "claude": "Claude-Partner: bach msg send claude <text> | partners/claude/outbox/",
        "delegation": "Delegation: bach partner delegate 'Task' --to=<partner>",

        # === BACKUP & WARTUNG ===
        "backup": "Backup: bach backup create [--to-nas] | bach backup list | python system/tools/backup_manager.py restore backup latest",
        "wartung": "Wartung: bach --maintain heal/registry/skills/docs",

        # === WORKFLOWS (Metakognition: WANN/WIE koordinieren) ===

        # System-Workflows
        "bug": "Bugfix-Workflow: skills/workflows/bugfix-protokoll.md (strukturierte Fehlerkorrektur)",
        "fehlerkorrektur": "Bugfix-Workflow: skills/workflows/bugfix-protokoll.md",
        "cli befehl": "CLI-Aenderung: skills/workflows/cli-aenderung-checkliste.md",
        "neues projekt": "Projekt-Aufnahme: skills/workflows/projekt-aufnahme.md",
        "integration": "Anschluss-Analyse: skills/workflows/system-anschlussanalyse.md",
        "aufraeumen": "System-Cleanup: skills/workflows/system-aufraeumen.md",
        "kartieren": "System-Mapping: skills/workflows/system-mapping.md",
        "synopse": "System-Synopse: skills/workflows/system-synopse.md",
        "testverfahren": "Test-Workflow: skills/workflows/system-testverfahren.md",
        "ordner flachen": "Ordner-Flattening: skills/workflows/ordner-flattening.md",

        # Dokumentations-Workflows
        "doku analyse": "Docs-Analyse: skills/workflows/docs-analyse.md",
        "help pruefen": "Help-Forensic: skills/workflows/help-forensic.md (Recurring: 14d)",
        "wiki schreiben": "Wiki-Author: skills/workflows/wiki-author.md (Recurring: 21d)",
        "umbenennen": "Rename-Workflow: skills/workflows/migrate-rename.md (sichere Umbenennung mit Wrapper)",

        # Partner-Workflows
        "gemini delegieren": "Delegation: skills/workflows/gemini-delegation.md",
        "google drive": "Google-Drive: skills/workflows/google-drive.md",

        # Analyse-Workflows
        "skill abdeckung": "Skill-Coverage: skills/workflows/skill-abdeckungsanalyse.md",
        "dokumente zusammenfuehren": "Synthese: skills/workflows/synthese.md",

        # Steuer-Workflows
        "beleg scan": "Steuer-Beleg-Scan: skills/workflows/steuer-beleg-scan.md",
        "fahrtkosten": "Fahrtkosten+Homeoffice: skills/workflows/steuer-fahrtkosten-homeoffice.md",
        "homeoffice": "Fahrtkosten+Homeoffice: skills/workflows/steuer-fahrtkosten-homeoffice.md",
        "finanzamt": "Finanzamt-Export: skills/workflows/steuer-finanzamt-export.md",
        "sonderausgaben": "Sonderausgaben: skills/workflows/steuer-sonderausgaben-erfassen.md",
        "werbungskosten": "Werbungskosten: skills/workflows/steuer-werbungskosten-erfassen.md",

        # Entwicklungszyklus & Usecases
        "entwicklung": "Dev-Zyklus: skills/workflows/dev-zyklus.md (8 Phasen) | --help dev",
        "dev zyklus": "Dev-Zyklus: skills/workflows/dev-zyklus.md (8 Phasen) | --help dev",
        "feature wunsch": "Dev-Zyklus Phase 1: Feature-Wuensche -> --help dev",
        "usecase": "Usecases: --help usecase (Feature-Tests + Anforderungen) | Phase 8 Dev-Zyklus",
        "feature test": "Usecases: --help usecase (End-to-End Validierung)",

        # Workflow-Suche
        "workflow": "Workflows: --help workflow (25 verfuegbar) | skills/workflows/",
        "ablauf": "Workflows: --help workflow (25 verfuegbar) | skills/workflows/",
        "prozess": "Workflows: --help workflow (25 verfuegbar) | skills/workflows/",
    }
    
    @classmethod
    def check(cls, text: str) -> Optional[str]:
        """Prüft ob Kontext-Hinweis hilfreich wäre."""
        text_lower = text.lower()
        
        # Cache-Logik (v1.1.80)
        now = datetime.now()
        if cls._cache is None or cls._last_load is None or (now - cls._last_load).total_seconds() > cls._ttl_sec:
            cls._refresh_cache()
            
        for trigger, data in cls._cache.items():
            if trigger in text_lower:
                # v1.1.82: Themen-Pakete nur einmal pro Session
                if data.get('source') == 'theme':
                    if data['id'] in cls._session_triggered:
                        continue
                    cls._session_triggered.add(data['id'])
                    # Wir speichern den Session-Status NICHT persistent, 
                    # da bach.py pro Aufruf neu startet.
                    # TODO: Fuer dauerhafte Prozesse (GUI/Daemon) ist das OK.
                    # Fuer CLI-Aufrufe brauchen wir ein File-basiertes Tracking.
                    cls._mark_session_usage(data['id'])

                # v1.1.81: Usage tracking
                if data.get('id'):
                    cls._mark_usage(data['id'])
                    
                return f"[KONTEXT] {data['hint']}"
        
        return None

    @classmethod
    def _refresh_cache(cls):
        """Lädt Triggers aus DB oder nutzt hardcoded Fallback."""
        cls._last_load = datetime.now()
        
        # Fallback laden (v1.1.82: Mit ID und Source)
        cls._cache = {t: {'id': None, 'hint': h, 'source': 'manual'} for t, h in cls.CONTEXT_TRIGGERS.items()}
        
        if not cls.base_path:
            return
            
        db_path = cls.base_path / "data" / "bach.db"
        if not db_path.exists():
            return
            
        try:
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            # Triggers aus DB laden
            rows = conn.execute("SELECT id, trigger_phrase, hint_text, source FROM context_triggers WHERE is_active = 1").fetchall()
            if rows:
                # Wenn DB Daten hat, nutzen wir diese
                cls._cache = {r['trigger_phrase']: {'id': r['id'], 'hint': r['hint_text'], 'source': r['source']} for r in rows}
            conn.close()
        except Exception:
            pass

        # v1.1.82: Session-Usage laden
        cls._load_session_usage()

    @classmethod
    def _mark_usage(cls, trigger_id: int):
        """Aktualisiert usage_count und last_used in der DB (v1.1.81)."""
        if not cls.base_path:
            return
        db_path = cls.base_path / "data" / "bach.db"
        try:
            conn = sqlite3.connect(str(db_path))
            conn.execute("""
                UPDATE context_triggers 
                SET usage_count = usage_count + 1, 
                    last_used = datetime('now')
                WHERE id = ?
            """, (trigger_id,))
            conn.commit()
            conn.close()
        except Exception:
            pass

    @classmethod
    def _load_session_usage(cls):
        """Lädt bereits gefeuerte Themen-Pakete der aktuellen Session (v1.1.82)."""
        if not cls.base_path: return
        import json
        session_file = cls.base_path / "data" / ".session_themes"
        if session_file.exists():
            try:
                # Wir löschen das File wenn es älter als 12 Stunden ist (neue Session)
                mtime = datetime.fromtimestamp(session_file.stat().st_mtime)
                if (datetime.now() - mtime).total_seconds() > 12 * 3600:
                    session_file.unlink()
                    cls._session_triggered = set()
                    return
                
                cls._session_triggered = set(json.loads(session_file.read_text()))
            except (OSError, ValueError, json.JSONDecodeError):
                cls._session_triggered = set()

    @classmethod
    def _mark_session_usage(cls, trigger_id: int):
        """Speichert gefeuertes Themen-Paket persistent (v1.1.82)."""
        if not cls.base_path: return
        import json
        cls._session_triggered.add(trigger_id)
        session_file = cls.base_path / "data" / ".session_themes"
        try:
            session_file.write_text(json.dumps(list(cls._session_triggered), ensure_ascii=False))
        except OSError:
            pass

        
        # v1.1.82: Session-Usage laden
        cls._load_session_usage()


class ToolInjector:
    """
    Erinnert an verfuegbare Tools bei Session-Start und Task-Beginn.

    Tools sind die Haende der LLMs - ohne Erinnerung werden sie vergessen
    und unnoetig neu erstellt.
    """

    # Tool-Kategorien mit wichtigsten Tools
    TOOL_CATEGORIES = {
        "OCR & Dokumente": [
            "tools/c_ocr_engine.py - Tesseract + PyMuPDF OCR",
            "tools/doc_search.py - Dokumentensuche (DB + Dateisystem)",
            "skills/_services/document/scanner_service.py - Inbox-Scanner",
            "skills/_services/document/ocr_service.py - OCR-Service",
        ],
        "Daten-Import/Export": [
            "tools/data_importer.py - Generischer CSV/JSON Import (Schema-Erkennung, Rollback)",
            "tools/folder_diff_scanner.py - Ordner-Ueberwachung mit Diff",
        ],
        "Domain-Handler (bach CLI)": [
            "bach steuer - Steuer (status, beleg, posten, export)",
            "bach haushalt - Haushalt (due, routinen, fixkosten, insurance-check, einkauf)",
            "bach gesundheit - Gesundheit (diagnosen, medikamente, labor, termine)",
            "bach contact - Kontakte (list, search, add, birthday)",
            "bach abo - Abos (list, check, export)",
        ],
        "Generatoren": [
            "tools/cv_generator.py - Lebenslauf aus Ordnerstruktur + DB",
            "tools/mcp_server.py - MCP-Server fuer IDE-Integration",
        ],
    }

    @classmethod
    def get_startup_reminder(cls, base_path: Path = None) -> str:
        """Gibt Tool-Uebersicht fuer Session-Start zurueck.

        Liest registrierte Tools aus bach.db und ergaenzt mit Kategorien.
        Tool-Hilfe: docs/help/tools/<toolname>.txt
        """
        lines = ["[VERFUEGBARE TOOLS - Deine Haende]"]

        # Versuche aktuelle Tool-Anzahl aus DB zu lesen
        tool_count = 0
        if base_path:
            try:
                import sqlite3
                db = base_path / "data" / "bach.db"
                if db.exists():
                    conn = sqlite3.connect(str(db))
                    tool_count = conn.execute(
                        "SELECT COUNT(*) FROM tools WHERE is_available = 1"
                    ).fetchone()[0]
                    conn.close()
            except Exception:
                pass

        if tool_count:
            lines.append(f"  {tool_count} Tools in bach.db registriert")

        for category, tools in cls.TOOL_CATEGORIES.items():
            lines.append(f"  {category}:")
            for tool in tools:
                lines.append(f"    - {tool}")

        lines.append("")
        lines.append("  Tool-Suche:   bach tools search <begriff>")
        lines.append("  Tool-Hilfe:   docs/help/tools/<toolname>.txt (100+ Hilfe-Dateien)")
        lines.append("  Tool-DB:      bach tools list (alle registrierten Tools)")
        lines.append("  Empfehlung:   bach tool suggest '<beschreibung>'")
        return "\n".join(lines)

    @classmethod
    def check_before_create(cls, text: str) -> Optional[str]:
        """Warnt bevor ein neues Tool erstellt wird das evtl. schon existiert."""
        text_lower = text.lower()
        create_signals = ["erstelle", "create", "neues tool", "schreibe ein script",
                          "baue ein", "implementiere ein tool", "write a tool",
                          "new script", "neues script"]
        if any(s in text_lower for s in create_signals):
            return ("[TOOL-CHECK] Bevor du ein neues Tool erstellst:\n"
                    "  1. bach tools search <begriff>  (DB-Suche)\n"
                    "  2. bach tool suggest '<beschreibung>'  (Empfehlung)\n"
                    "  3. Pruefe tools/ und skills/_services/ Ordner\n"
                    "  Tools sind die Haende der LLMs - Duplikate vermeiden!")
        return None


class BetweenInjector:
    """
    Automatische Between-Tasks Erinnerung nach Task-Done.
    
    Erkennt:
    - Task wurde als done markiert
    - Session-Ende (dann KEINE Erinnerung)
    """
    
    @classmethod
    def check_task_done(cls, last_command: str, session_ending: bool = False) -> Optional[str]:
        """
        Prüft ob Between-Tasks Erinnerung nötig.
        
        Args:
            last_command: Letzter ausgeführter Befehl
            session_ending: True wenn Session bald endet
        
        Returns:
            Erinnerung oder None
        """
        # Task done erkannt?
        if "done" not in last_command.lower():
            return None
        
        # Session endet? Dann keine Erinnerung
        if session_ending:
            return None
        
        return """[BETWEEN-TASKS]
1. Zeit-Check: Noch im Limit?
2. Memory OK? (--memory size)
3. Nächste Aufgabe oder Shutdown?

Tipp: --status für Übersicht"""


class TimeInjector:
    """
    Regelmäßige Zeit-Updates (Timebeat).

    Delegiert nun an tools.time_system.TimeManager (TIME-07 Migration).
    Ergänzt den Timebeat um ungelesene Nachrichten.
    """

    def __init__(self, interval: int = 60, base_path: Path = None):
        self.interval = interval
        self.base_path = base_path
        
        # TIME-07: Nutzung des TimeManagers
        self.manager = None
        if base_path:
            try:
                from tools.time_system import TimeManager
                self.manager = TimeManager(base_path)
                # Sync Interval aus InjectorConfig
                self.manager.set_interval(interval)
            except (ImportError, AttributeError):
                pass

    def check(self) -> Optional[str]:
        """Prüft ob Timebeat fällig (via TimeManager)."""
        if not self.manager:
            return None

        # 1. Clock Check (TimeManager entscheidet ob Zeit ist)
        clock_msg = self.manager.clock.check()
        
        if clock_msg:
            # Wenn Clock feuert, bauen wir den vollen Beat
            # Wir nutzen nicht clock_msg direkt, sondern bauen den 
            # Context-reichen Beat zusammen.
            
            lines = [clock_msg] # "[CLOCK] HH:MM"

            # Timer & Countdown Infos
            timer_disp = self.manager.timer.get_display()
            if timer_disp:
                lines.append(f"[TIMER] {timer_disp}")
                
            cd_disp = self.manager.countdown.get_display()
            if cd_disp:
                lines.append(f"[COUNTDOWN] {cd_disp}")

            # Abgelaufene Countdowns prüfen
            expired = self.manager.countdown.check_expired()
            for name, cmd in expired:
                lines.append(f"[!] Countdown '{name}' ABGELAUFEN!")
                if cmd:
                    lines.append(f"    Trigger: {cmd}")

            # Nachrichten Check (Legacy Feature von TimeInjector)
            msg_info = self._check_messages()
            if msg_info:
                lines.append(msg_info)

            return "\n".join(lines)

        return None

    def _check_messages(self) -> Optional[str]:
        """Prüft ungelesene Nachrichten für den aktiven Partner."""
        if not self.base_path:
            return None
        
        try:
            import sqlite3
            
            # Aktiven Partner aus partner_presence holen
            bach_db = self.base_path / "data" / "bach.db"
            if not bach_db.exists():
                return None
            
            conn = sqlite3.connect(str(bach_db))
            row = conn.execute("""
                SELECT partner_name FROM partner_presence 
                WHERE status = 'online' 
                ORDER BY clocked_in DESC LIMIT 1
            """).fetchone()
            conn.close()
            
            if not row:
                return None
            
            partner = row[0]
            
            # Ungelesene Nachrichten zählen
            bach_db = self.base_path / "data" / "bach.db"
            if not bach_db.exists():
                return None

            conn = sqlite3.connect(str(bach_db))
            conn.row_factory = sqlite3.Row
            msgs = conn.execute("""
                SELECT id, sender, body FROM messages
                WHERE status = 'unread' AND recipient = ?
                ORDER BY created_at DESC LIMIT 3
            """, (partner,)).fetchall()
            conn.close()
            
            if not msgs:
                return None
            
            # Nachrichten formatieren
            lines = [f"[NEUE NACHRICHTEN] {len(msgs)} fuer {partner.upper()}:"]
            for m in msgs[:2]:  # Max 2 anzeigen
                preview = (m['body'] or '')[:50].replace('\n', ' ')
                lines.append(f"  [{m['id']}] {m['sender']}: {preview}...")
            lines.append("  --> bach msg ping --from " + partner)
            
            return "\n".join(lines)
        except Exception:
            return None


class TaskAssigner:
    """
    Automatische Aufgaben-Zuweisung.
    
    "Gib mir eine Aufgabe für X Minuten" → Passende Aufgabe
    """
    
    def __init__(self, tasks_file: Path):
        self.tasks_file = tasks_file
    
    def assign(self, max_minutes: int = 5) -> Optional[dict]:
        """
        Weist passende Aufgabe zu.
        
        Args:
            max_minutes: Maximale geschätzte Zeit
        
        Returns:
            Task-Dict oder None
        """
        if not self.tasks_file.exists():
            return None
        
        try:
            with open(self.tasks_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            tasks = data.get("tasks", [])
            open_tasks = [t for t in tasks if t.get("status") == "open"]
            
            if not open_tasks:
                return None
            
            # Nach Priorität sortieren
            prio_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
            sorted_tasks = sorted(open_tasks, 
                                 key=lambda t: prio_order.get(t.get("priority", "medium"), 2))
            
            # Zeit-Schätzung (grob nach Beschreibungslänge)
            for task in sorted_tasks:
                desc_len = len(task.get("description", task.get("task", "")))
                estimated_min = max(2, min(15, desc_len / 50))
                
                if estimated_min <= max_minutes:
                    task["estimated_minutes"] = estimated_min
                    return task
            
            # Fallback: Erste Aufgabe
            sorted_tasks[0]["estimated_minutes"] = max_minutes
            return sorted_tasks[0]

        except (json.JSONDecodeError, OSError):
            return None
    
    def decompose(self, task: dict) -> List[dict]:
        """
        Zerlegt große Aufgabe in Teilschritte.
        
        Returns:
            Liste von Sub-Tasks
        """
        description = task.get("description", task.get("task", ""))
        
        # Einfache Heuristik: Nach Punkten/Schritten aufteilen
        steps = []
        
        # Suche nach nummerierten Schritten
        numbered = re.findall(r'\d+[.)]\s*([^.!?\n]+)', description)
        if numbered:
            for i, step in enumerate(numbered, 1):
                steps.append({
                    "step": i,
                    "description": step.strip(),
                    "estimated_minutes": 3
                })
        else:
            # Fallback: In 3 generische Schritte teilen
            steps = [
                {"step": 1, "description": "Verstehen & Planen", "estimated_minutes": 2},
                {"step": 2, "description": "Implementieren", "estimated_minutes": 5},
                {"step": 3, "description": "Testen & Dokumentieren", "estimated_minutes": 3},
            ]
        
        return steps


class CooldownManager:
    """
    Verwaltet Cooldowns fuer Injektoren.

    Nach Anzeige wird ein Injektor fuer X Minuten stumm geschaltet.
    Default: 2 Minuten (konfigurierbar pro Injektor)

    v1.1.75: Neu eingefuehrt
    """

    # Default-Cooldowns in Sekunden
    DEFAULT_COOLDOWNS = {
        "strategy": 120,   # 2 Min - Strategien sollen nicht nerven
        "context": 60,     # 1 Min - Kontext-Hinweise etwas oefter OK
        "between": 180,    # 3 Min - Between-Checks seltener
        "tool_warn": 300,  # 5 Min - Tool-Warnung selten
    }

    def __init__(self, base_path: Path):
        self.base_path = base_path
        self._state_file = base_path / "data" / ".injector_cooldowns"
        self._cooldowns = self._load_state()

    def _load_state(self) -> dict:
        """Laedt Cooldown-State aus Datei."""
        if self._state_file.exists():
            try:
                return json.loads(self._state_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        return {}

    def _save_state(self) -> None:
        """Speichert Cooldown-State."""
        try:
            self._state_file.parent.mkdir(parents=True, exist_ok=True)
            self._state_file.write_text(
                json.dumps(self._cooldowns, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
        except OSError:
            pass

    def is_on_cooldown(self, injector_name: str) -> bool:
        """
        Prueft ob Injektor noch im Cooldown ist.

        Args:
            injector_name: Name des Injektors (strategy, context, between, tool_warn)

        Returns:
            True wenn Cooldown aktiv (= nicht anzeigen)
        """
        last_shown = self._cooldowns.get(injector_name)
        if not last_shown:
            return False

        try:
            last_dt = datetime.fromisoformat(last_shown)
            cooldown_sec = self.DEFAULT_COOLDOWNS.get(injector_name, 120)
            return datetime.now() < last_dt + timedelta(seconds=cooldown_sec)
        except (ValueError, TypeError):
            return False

    def mark_shown(self, injector_name: str) -> None:
        """
        Markiert Injektor als gerade angezeigt (startet Cooldown).

        Args:
            injector_name: Name des Injektors
        """
        self._cooldowns[injector_name] = datetime.now().isoformat()
        self._save_state()

    def get_remaining(self, injector_name: str) -> int:
        """
        Gibt verbleibende Cooldown-Zeit in Sekunden zurueck.

        Returns:
            Sekunden oder 0 wenn kein Cooldown
        """
        last_shown = self._cooldowns.get(injector_name)
        if not last_shown:
            return 0

        try:
            last_dt = datetime.fromisoformat(last_shown)
            cooldown_sec = self.DEFAULT_COOLDOWNS.get(injector_name, 120)
            remaining = (last_dt + timedelta(seconds=cooldown_sec) - datetime.now()).total_seconds()
            return max(0, int(remaining))
        except (ValueError, TypeError):
            return 0


# Haupt-Interface
class InjectorSystem:
    """Zentrales Interface für alle Injektoren."""
    
    def __init__(self, base_path: Path):
        self.base_path = base_path
        ContextInjector.base_path = base_path  # Kontext für DB-Zugriff
        self.config = InjectorConfig(base_path / "config.json")
        self.time_injector = TimeInjector(self.config.config.get("timebeat_interval", 60), base_path)
        self.task_assigner = TaskAssigner(base_path / "DATA" / "tasks.json")
        self.cooldown = CooldownManager(base_path)  # v1.1.75: Cooldown-Management
        self._tool_reminder_shown = False

    def process(self, text: str, context: dict = None) -> List[str]:
        """
        Verarbeitet Text durch alle aktiven Injektoren.

        v1.1.75: Mit Cooldown-Pruefung - Injektoren werden nach Anzeige
                 fuer X Minuten stumm geschaltet.

        Returns:
            Liste von Injektionen (kann leer sein)
        """
        injections = []

        # Strategy Injector (Cooldown: 2 Min)
        if self.config.is_enabled("strategy_injector"):
            if not self.cooldown.is_on_cooldown("strategy"):
                strategy = StrategyInjector.check(text, context)
                if strategy:
                    injections.append(strategy)
                    self.cooldown.mark_shown("strategy")

        # Context Injector (Cooldown: 1 Min)
        if self.config.is_enabled("context_injector"):
            if not self.cooldown.is_on_cooldown("context"):
                ctx = ContextInjector.check(text)
                if ctx:
                    injections.append(ctx)
                    self.cooldown.mark_shown("context")

        # Tool Injector - warnt vor Tool-Duplikaten (Cooldown: 5 Min)
        if self.config.is_enabled("context_injector"):
            if not self.cooldown.is_on_cooldown("tool_warn"):
                tool_warn = ToolInjector.check_before_create(text)
                if tool_warn:
                    injections.append(tool_warn)
                    self.cooldown.mark_shown("tool_warn")

        # Time Injector (hat eigenen Intervall-Mechanismus, kein extra Cooldown)
        if self.config.is_enabled("time_injector"):
            time = self.time_injector.check()
            if time:
                injections.append(time)

        return injections

    def get_tool_reminder(self) -> Optional[str]:
        """Gibt Tool-Erinnerung fuer Session-Start zurueck (einmalig)."""
        if not self._tool_reminder_shown:
            self._tool_reminder_shown = True
            return ToolInjector.get_startup_reminder(self.base_path)
        return None
    
    def check_between(self, last_command: str, session_ending: bool = False) -> Optional[str]:
        """Prüft Between-Tasks Erinnerung (mit Cooldown: 3 Min)."""
        if self.config.is_enabled("between_injector"):
            if not self.cooldown.is_on_cooldown("between"):
                result = BetweenInjector.check_task_done(last_command, session_ending)
                if result:
                    self.cooldown.mark_shown("between")
                return result
        return None
    
    def assign_task(self, max_minutes: int = 5) -> Tuple[bool, str]:
        """Weist Aufgabe zu."""
        task = self.task_assigner.assign(max_minutes)
        
        if not task:
            return False, "Keine passende Aufgabe gefunden."
        
        result = f"""[AUFGABE ZUGEWIESEN]
ID: {task.get('id', '?')}
Task: {task.get('task', '')[:60]}
Priorität: {task.get('priority', 'medium')}
Geschätzt: ~{task.get('estimated_minutes', '?')} Min

Zu komplex? Nutze: --task decompose {task.get('id', '')}"""
        
        return True, result
    
    def decompose_task(self, task_id: str) -> Tuple[bool, str]:
        """Zerlegt Aufgabe."""
        # Task laden
        tasks_file = self.base_path / "DATA" / "tasks.json"
        if not tasks_file.exists():
            return False, "Keine Tasks-Datei"
        
        try:
            with open(tasks_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            task = None
            for t in data.get("tasks", []):
                if t.get("id") == task_id:
                    task = t
                    break
            
            if not task:
                return False, f"Task {task_id} nicht gefunden"
            
            steps = self.task_assigner.decompose(task)
            
            result = f"[AUFGABE ZERLEGT: {task_id}]\n\n"
            for step in steps:
                result += f"  {step['step']}. {step['description']} (~{step['estimated_minutes']} Min)\n"
            
            return True, result
            
        except Exception as e:
            return False, f"Fehler: {e}"
    
    def toggle(self, injector: str) -> Tuple[bool, str]:
        """Schaltet Injektor um."""
        valid = ["strategy_injector", "context_injector", "time_injector", "between_injector"]
        
        if injector not in valid:
            return False, f"Unbekannter Injektor. Verfügbar: {', '.join(valid)}"
        
        new_state = self.config.toggle(injector)
        status = "AN" if new_state else "AUS"
        
        return True, f"{injector}: {status}"
    
    def status(self) -> str:
        """Zeigt Status aller Injektoren inkl. Cooldown-Info."""
        lines = ["[INJEKTOR-STATUS]", ""]

        # Mapping: config key -> cooldown key
        cooldown_map = {
            "strategy_injector": "strategy",
            "context_injector": "context",
            "between_injector": "between",
        }

        for key, value in self.config.config.items():
            if key.endswith("_injector"):
                status = "AN" if value else "AUS"
                name = key.replace("_injector", "").title()

                # Cooldown-Info hinzufuegen
                cd_key = cooldown_map.get(key)
                if cd_key:
                    remaining = self.cooldown.get_remaining(cd_key)
                    if remaining > 0:
                        status += f" (Cooldown: {remaining}s)"

                lines.append(f"  {name:12} {status}")

        lines.append("")
        lines.append("Toggle: --inject toggle <name>")
        lines.append("Cooldowns: strategy=2min, context=1min, between=3min")

        return "\n".join(lines)
