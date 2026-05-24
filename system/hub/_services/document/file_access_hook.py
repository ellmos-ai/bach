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
File Access Hook - Proaktive Anonymisierung für Chatbot/LLM
============================================================

WICHTIG: Dieses Modul stellt sicher, dass der Chatbot/LLM NIEMALS
echte Klientennamen sieht. Alle Zugriffe werden automatisch auf
anonymisierte Bundles umgeleitet.

PROAKTIVER WORKFLOW (für "neue Akte"):
    from file_access_hook import scan_new_clients

    # Chatbot ruft auf wenn "neue Akte" gemeldet wird
    # → Scannt data/, erstellt automatisch Bundles
    # → Gibt NUR client_id + tarnname zurück
    # → Chatbot sieht NIEMALS echte Namen

    new_clients = scan_new_clients(password="...")
    # Returns: [{"client_id": "K_XXX", "tarnname": "Max Müller", "files": 12}]

SICHERER ZUGRIFF (für existierende Akten):
    from file_access_hook import list_all_clients, get_client_data

    # Alle Klienten auflisten (nur anonymisiert)
    clients = list_all_clients()
    # Returns: [{"client_id": "K_XXX", "tarnname": "..."}]

    # Daten für einen Klienten abrufen (per client_id!)
    data = get_client_data("K_XXX")

VERBOTEN:
    - Direkter Zugriff auf data/ Ordner
    - Lesen von Ordnernamen in data/
    - Jeglicher Zugriff der echte Namen exponieren könnte

Version: 2.0.0
Erstellt: 2026-02-05
Aktualisiert: 2026-02-05 - Proaktiver Mechanismus
"""

import json
import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

# Pfade ermitteln
_current = Path(__file__).resolve()
_hub_dir = _current.parent.parent.parent  # system/hub/
_services_dir = _hub_dir / "_services"
_bach_root = _hub_dir.parent.parent  # BACH/

# Foerderplaner-Verzeichnisse (neue Ordnernamen seit Pipeline-Refactoring)
_foerderplaner = _bach_root / "user" / "documents" / "foerderplaner" / "Berichte"
DATA_DIR = _foerderplaner / "data_roh"
BUNDLES_DIR = _foerderplaner / "data_ano"
OUTPUT_DIR = _foerderplaner / "output_berichte"

# DEPRECATED: AnonymizedWorkflow wurde entfernt (duplizierte Logik).
# Die Anonymisierung wird jetzt ueber report_workflow_service.py / foerderbericht_pipeline.py gesteuert.
WORKFLOW_AVAILABLE = False


def _resolve_document_key_password(password: Optional[str] = None) -> str:
    """Liest das Dokument-Schlüsselpasswort ohne hart kodierten Default."""
    return password or os.environ.get("BACH_DOCUMENT_KEY_PASSWORD", "")


class FileAccessHook:
    """
    Hook für sicheren Dateizugriff auf Klientendaten.

    Leitet alle Zugriffe auf data/ automatisch auf bundles/ um,
    sodass nur anonymisierte Daten gelesen werden.
    """

    def __init__(self, data_dir: Path = None, bundles_dir: Path = None):
        """
        Initialisiert den Hook.

        Args:
            data_dir: Ordner mit echten Klientendaten
            bundles_dir: Ordner mit anonymisierten Bundles
        """
        self.data_dir = Path(data_dir) if data_dir else DATA_DIR
        self.bundles_dir = Path(bundles_dir) if bundles_dir else BUNDLES_DIR

        # Cache für Profil-Mappings
        self._profile_cache: Dict[str, dict] = {}
        self._cache_loaded = False

    def _load_profiles(self) -> None:
        """Lädt alle Profil-Mappings aus den .profil.json Dateien."""
        if self._cache_loaded:
            return

        self._profile_cache.clear()

        if not self.data_dir.exists():
            self._cache_loaded = True
            return

        for folder in self.data_dir.iterdir():
            if not folder.is_dir():
                continue

            profil_path = folder / ".profil.json"
            if profil_path.exists():
                try:
                    profil = json.loads(profil_path.read_text(encoding="utf-8"))
                    client_id = profil.get("client_id")
                    tarnname = profil.get("tarnname", "")

                    if client_id:
                        self._profile_cache[folder.name] = {
                            "client_id": client_id,
                            "tarnname": tarnname,
                            "folder_name": folder.name,
                            "profil_path": str(profil_path)
                        }
                except Exception:
                    pass

        self._cache_loaded = True

    def invalidate_cache(self) -> None:
        """Invalidiert den Profil-Cache (nach Bundle-Erstellung aufrufen)."""
        self._cache_loaded = False
        self._profile_cache.clear()

    def get_profile_for_klient(self, klient_name: str) -> Optional[dict]:
        """
        Findet das Profil für einen Klienten.

        Args:
            klient_name: Name oder Teil des Klienten-Ordners

        Returns:
            Profil-Dict oder None
        """
        self._load_profiles()

        # Exakter Match
        if klient_name in self._profile_cache:
            return self._profile_cache[klient_name]

        # Teilstring-Suche (case-insensitive)
        name_lower = klient_name.lower()
        for folder_name, profil in self._profile_cache.items():
            if name_lower in folder_name.lower():
                return profil

        return None

    def get_bundle_path(self, klient_name: str) -> Optional[Path]:
        """
        Gibt den Bundle-Pfad für einen Klienten zurück.

        Args:
            klient_name: Name des Klienten

        Returns:
            Path zum Bundle oder None wenn nicht vorhanden
        """
        profil = self.get_profile_for_klient(klient_name)
        if not profil:
            return None

        bundle_path = self.bundles_dir / profil["client_id"]
        if bundle_path.exists():
            return bundle_path

        return None

    def translate_path(self, original_path: Union[str, Path]) -> Path:
        """
        Übersetzt einen Pfad von data/ zu bundles/.

        Wenn der Pfad auf einen Klienten-Ordner in data/ zeigt,
        wird er auf das entsprechende Bundle umgeleitet.

        Args:
            original_path: Originaler Dateipfad

        Returns:
            Übersetzter Pfad (Bundle) oder Original wenn keine Übersetzung nötig
        """
        path = Path(original_path)

        # Prüfen ob Pfad in data/ liegt
        try:
            relative = path.relative_to(self.data_dir)
        except ValueError:
            # Pfad ist nicht in data/ - keine Umleitung nötig
            return path

        # Klienten-Ordner ermitteln (erster Teil des relativen Pfads)
        parts = relative.parts
        if not parts:
            return path

        klient_folder = parts[0]
        profil = self.get_profile_for_klient(klient_folder)

        if not profil:
            # Kein Profil gefunden - Original zurückgeben
            return path

        # Bundle-Pfad konstruieren
        bundle_path = self.bundles_dir / profil["client_id"]

        if not bundle_path.exists():
            return path

        # Rest des Pfades anhängen
        if len(parts) > 1:
            rest = Path(*parts[1:])
            # In core/ suchen
            core_path = bundle_path / "core" / rest
            if core_path.exists():
                return core_path

            # Dateiname mit Tarnnamen suchen
            original_stem = rest.stem
            original_suffix = rest.suffix

            # Suche nach anonymisierter Version
            for file in (bundle_path / "core").rglob(f"*{original_suffix}"):
                # Prüfen ob Dateiname dem Tarnname entspricht
                if profil["tarnname"] and profil["tarnname"].split()[0] in file.stem:
                    return file

        return bundle_path / "core"

    def get_safe_content(
        self,
        klient_name: str,
        filename: str = None,
        include_extended: bool = False
    ) -> str:
        """
        Liest Inhalte sicher aus dem anonymisierten Bundle.

        WICHTIG: Diese Methode gibt NUR anonymisierte Inhalte zurück.
        Der Chatbot sieht nur Tarnnamen, niemals echte Namen.

        Args:
            klient_name: Name des Klienten
            filename: Optionaler Dateiname (sonst alle Dateien)
            include_extended: Auch extended/ einbeziehen

        Returns:
            Anonymisierter Textinhalt
        """
        bundle_path = self.get_bundle_path(klient_name)
        if not bundle_path:
            return f"[FEHLER] Kein Bundle gefunden für: {klient_name}"

        # Ordner zum Lesen
        folders = [bundle_path / "core"]
        if include_extended and (bundle_path / "extended").exists():
            folders.append(bundle_path / "extended")

        # Unterstützte Dateitypen
        supported = {".txt", ".md", ".docx", ".pdf", ".xlsx", ".xls"}

        all_content = []

        for folder in folders:
            if not folder.exists():
                continue

            for filepath in sorted(folder.rglob("*")):
                if not filepath.is_file():
                    continue
                if filepath.suffix.lower() not in supported:
                    continue
                if filepath.name.startswith(".") or filepath.name.startswith("_"):
                    continue
                if "output" in filepath.parts:
                    continue

                # Wenn Dateiname angegeben, filtern
                if filename and filename.lower() not in filepath.name.lower():
                    continue

                # Text extrahieren
                text = self._extract_text(filepath)
                if text.strip():
                    rel_path = filepath.relative_to(bundle_path)
                    all_content.append(f"--- Quelle: {rel_path} ---\n{text}")

        if not all_content:
            return "[KEINE DATEN] Keine passenden Dokumente im Bundle gefunden."

        return "\n\n".join(all_content)

    def _extract_text(self, filepath: Path) -> str:
        """Extrahiert Text aus einer Datei."""
        suffix = filepath.suffix.lower()

        try:
            if suffix in {".txt", ".md"}:
                return filepath.read_text(encoding="utf-8")

            elif suffix == ".docx":
                try:
                    from docx import Document
                    doc = Document(str(filepath))
                    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
                except ImportError:
                    return f"[python-docx nicht installiert]"

            elif suffix == ".pdf":
                # pypdf (MIT) primaer
                try:
                    from pypdf import PdfReader
                    reader = PdfReader(str(filepath))
                    text = []
                    for page in reader.pages:
                        text.append(page.extract_text() or "")
                    result = "\n".join(text)
                    if result.strip():
                        return result
                except ImportError:
                    pass
                except Exception:
                    pass
                # Fallback: pdfplumber (MIT)
                try:
                    import pdfplumber
                    text = []
                    with pdfplumber.open(str(filepath)) as pdf:
                        for page in pdf.pages:
                            text.append(page.extract_text() or "")
                    result = "\n".join(text)
                    if result.strip():
                        return result
                except ImportError:
                    pass
                except Exception:
                    pass
                # Optional: PyMuPDF (AGPL)
                try:
                    import fitz  # PyMuPDF optional
                    doc = fitz.open(str(filepath))
                    text = []
                    for page in doc:
                        text.append(page.get_text())
                    doc.close()
                    return "\n".join(text)
                except ImportError:
                    return "[PDF-Extraktion: pypdf, pdfplumber und PyMuPDF nicht installiert]"

            elif suffix in {".xlsx", ".xls"}:
                try:
                    import openpyxl
                    wb = openpyxl.load_workbook(str(filepath), data_only=True)
                    text = []
                    for sheet in wb.worksheets:
                        text.append(f"[Tabelle: {sheet.title}]")
                        for row in sheet.iter_rows(values_only=True):
                            cells = [str(c) if c is not None else "" for c in row]
                            if any(cells):
                                text.append(" | ".join(cells))
                    wb.close()
                    return "\n".join(text)
                except ImportError:
                    return f"[openpyxl nicht installiert]"

            return ""

        except Exception as e:
            return f"[FEHLER beim Lesen: {e}]"

    def list_available_files(self, klient_name: str) -> List[dict]:
        """
        Listet alle verfügbaren Dateien im Bundle auf.

        Args:
            klient_name: Name des Klienten

        Returns:
            Liste von Datei-Infos (nur anonymisierte Namen)
        """
        bundle_path = self.get_bundle_path(klient_name)
        if not bundle_path:
            return []

        files = []
        for filepath in sorted(bundle_path.rglob("*")):
            if not filepath.is_file():
                continue
            if filepath.name.startswith("."):
                continue
            if "output" in filepath.parts:
                continue

            rel_path = filepath.relative_to(bundle_path)
            files.append({
                "name": filepath.name,
                "path": str(rel_path),
                "size": filepath.stat().st_size,
                "type": filepath.suffix.lower()
            })

        return files

    def get_tarnname(self, klient_name: str) -> Optional[str]:
        """
        Gibt den Tarnnamen für einen Klienten zurück.

        Der Chatbot sollte immer den Tarnnamen verwenden,
        niemals den echten Namen.

        Args:
            klient_name: Echter Klientenname

        Returns:
            Tarnname oder None
        """
        profil = self.get_profile_for_klient(klient_name)
        if profil:
            return profil.get("tarnname")
        return None

    # ═══════════════════════════════════════════════════════════════
    # PROAKTIVE METHODEN - Automatische Bundle-Erstellung
    # ═══════════════════════════════════════════════════════════════

    def _count_files_in_folder(self, folder: Path) -> int:
        """Zählt Dateien in einem Ordner (ohne echte Namen zu exponieren)."""
        count = 0
        try:
            for item in folder.rglob("*"):
                if item.is_file() and not item.name.startswith("."):
                    count += 1
        except Exception:
            pass
        return count

    def scan_for_new_clients(self, password: str) -> List[dict]:
        """
        PROAKTIV: Scannt data/ nach neuen Akten und erstellt automatisch Bundles.

        WICHTIG: Diese Methode gibt NIEMALS echte Namen zurück!
        Sie erstellt automatisch Bundles für alle Ordner ohne .profil.json
        und gibt nur client_id + tarnname zurück.

        Args:
            password: Passwort für die Schlüssel-Verschlüsselung

        Returns:
            Liste von neuen Klienten: [{"client_id": "K_XXX", "tarnname": "...", "files": N, "new": True}]
        """
        if not WORKFLOW_AVAILABLE:
            return [{"error": "AnonymizedWorkflow nicht verfügbar"}]

        if not self.data_dir.exists():
            return []

        workflow = AnonymizedWorkflow(self.data_dir, self.bundles_dir)
        new_clients = []

        # Alle Ordner in data/ durchgehen
        for folder in self.data_dir.iterdir():
            if not folder.is_dir():
                continue
            if folder.name.startswith(".") or folder.name.startswith("_"):
                continue

            profil_path = folder / ".profil.json"

            # Neuer Klient = kein Profil vorhanden
            if not profil_path.exists():
                try:
                    # Bundle automatisch erstellen
                    # WICHTIG: folder.name wird NICHT an den Chatbot zurückgegeben!
                    bundle_info = workflow.create_or_update_bundle(
                        klient_ordner=folder.name,
                        password=password,
                        force_recreate=False
                    )

                    new_clients.append({
                        "client_id": bundle_info.client_id,
                        "tarnname": bundle_info.tarnname,
                        "files": bundle_info.files_count,
                        "new": True
                    })
                except Exception as e:
                    # Fehler protokollieren, aber keinen echten Namen zeigen
                    new_clients.append({
                        "client_id": None,
                        "tarnname": None,
                        "error": f"Bundle-Erstellung fehlgeschlagen: {str(e)}",
                        "new": True
                    })

        # Cache invalidieren damit neue Profile geladen werden
        self.invalidate_cache()

        return new_clients

    def list_all_clients_safe(self) -> List[dict]:
        """
        Listet ALLE Klienten auf - aber NUR mit anonymisierten Daten.

        WICHTIG: Gibt NIEMALS echte Namen zurück!

        Returns:
            Liste: [{"client_id": "K_XXX", "tarnname": "...", "has_bundle": True/False}]
        """
        self._load_profiles()

        clients = []
        for folder_name, profil in self._profile_cache.items():
            client_id = profil.get("client_id")
            tarnname = profil.get("tarnname", "Unbekannt")

            # Prüfen ob Bundle existiert
            bundle_exists = (self.bundles_dir / client_id).exists() if client_id else False

            clients.append({
                "client_id": client_id,
                "tarnname": tarnname,
                "has_bundle": bundle_exists
            })

        return clients

    def get_client_data_by_id(self, client_id: str) -> dict:
        """
        Gibt Klientendaten per client_id zurück (NICHT per echtem Namen!).

        WICHTIG: Der Chatbot sollte IMMER diese Methode verwenden,
        nicht get_klient_context() mit echtem Namen!

        Args:
            client_id: Die anonyme Client-ID (z.B. "K_CE2E70")

        Returns:
            Dict mit anonymisierten Daten
        """
        # Bundle-Pfad direkt aus client_id
        bundle_path = self.bundles_dir / client_id
        if not bundle_path.exists():
            return {
                "found": False,
                "error": f"Kein Bundle gefunden für: {client_id}"
            }

        # Tarnname aus Profil-Cache suchen
        tarnname = None
        self._load_profiles()
        for folder_name, profil in self._profile_cache.items():
            if profil.get("client_id") == client_id:
                tarnname = profil.get("tarnname")
                break

        if not tarnname:
            tarnname = "Unbekannt"

        # Dateien im Bundle zählen
        files = []
        for filepath in sorted(bundle_path.rglob("*")):
            if not filepath.is_file():
                continue
            if filepath.name.startswith("."):
                continue
            if "output" in filepath.parts:
                continue

            rel_path = filepath.relative_to(bundle_path)
            files.append({
                "name": filepath.name,
                "path": str(rel_path),
                "type": filepath.suffix.lower()
            })

        # Content extrahieren (anonymisiert)
        content = self._get_bundle_content(bundle_path)

        return {
            "found": True,
            "client_id": client_id,
            "tarnname": tarnname,
            "files": files,
            "file_count": len(files),
            "content": content,
            "content_length": len(content),
            "note": f"Alle Daten anonymisiert. Klient heißt im Bericht '{tarnname}'."
        }

    def _get_bundle_content(self, bundle_path: Path) -> str:
        """Extrahiert Text aus einem Bundle (intern)."""
        folders = [bundle_path / "core"]
        if (bundle_path / "extended").exists():
            folders.append(bundle_path / "extended")

        supported = {".txt", ".md", ".docx", ".pdf", ".xlsx", ".xls"}
        all_content = []

        for folder in folders:
            if not folder.exists():
                continue

            for filepath in sorted(folder.rglob("*")):
                if not filepath.is_file():
                    continue
                if filepath.suffix.lower() not in supported:
                    continue
                if filepath.name.startswith(".") or filepath.name.startswith("_"):
                    continue
                if "output" in filepath.parts:
                    continue

                text = self._extract_text(filepath)
                if text.strip():
                    rel_path = filepath.relative_to(bundle_path)
                    all_content.append(f"--- Quelle: {rel_path} ---\n{text}")

        return "\n\n".join(all_content) if all_content else "[KEINE DATEN]"

    def ensure_all_bundles_exist(self, password: str) -> dict:
        """
        Stellt sicher, dass für ALLE Akten in data/ Bundles existieren.

        PROAKTIV: Sollte aufgerufen werden BEVOR der Chatbot
        irgendetwas über Klienten erfährt.

        Args:
            password: Passwort für Schlüssel-Verschlüsselung

        Returns:
            {"processed": N, "new": N, "errors": N, "clients": [...]}
        """
        new_clients = self.scan_for_new_clients(password)

        # Auch existierende Klienten auflisten
        all_clients = self.list_all_clients_safe()

        return {
            "processed": len(all_clients),
            "new": len([c for c in new_clients if c.get("new") and not c.get("error")]),
            "errors": len([c for c in new_clients if c.get("error")]),
            "clients": all_clients
        }


# ═══════════════════════════════════════════════════════════════
# CONVENIENCE FUNCTIONS (für einfache Nutzung)
# ═══════════════════════════════════════════════════════════════

# Globale Hook-Instanz
_hook = None

def get_hook() -> FileAccessHook:
    """Gibt die globale Hook-Instanz zurück."""
    global _hook
    if _hook is None:
        _hook = FileAccessHook()
    return _hook


def get_safe_path(path: Union[str, Path]) -> Path:
    """
    Übersetzt einen Pfad sicher auf das anonymisierte Bundle.

    Verwendung:
        # Statt: open("data/Mustermann, Max/doc.docx")
        open(get_safe_path("data/Mustermann, Max/doc.docx"))
    """
    return get_hook().translate_path(path)


def read_safe_file(klient_name: str, filename: str = None) -> str:
    """
    Liest Klientendaten sicher aus dem anonymisierten Bundle.

    Verwendung:
        # Alle Dateien für einen Klienten (nur Tarnnamen sichtbar)
        content = read_safe_file("Mustermann, Max")

        # Spezifische Datei
        content = read_safe_file("Mustermann, Max", "Beobachtungen.docx")
    """
    return get_hook().get_safe_content(klient_name, filename)


def get_tarnname(klient_name: str) -> Optional[str]:
    """
    Gibt den Tarnnamen für einen Klienten zurück.

    Der Chatbot sollte diesen Namen verwenden, nicht den echten.
    """
    return get_hook().get_tarnname(klient_name)


def list_klient_files(klient_name: str) -> List[dict]:
    """Listet alle verfügbaren Dateien für einen Klienten auf."""
    return get_hook().list_available_files(klient_name)


def refresh_cache() -> None:
    """Aktualisiert den Profil-Cache (nach neuen Bundles aufrufen)."""
    get_hook().invalidate_cache()


# ═══════════════════════════════════════════════════════════════
# PROAKTIVE FUNKTIONEN (für Chatbot - NIEMALS echte Namen!)
# ═══════════════════════════════════════════════════════════════

def scan_new_clients(password: Optional[str] = None) -> List[dict]:
    """
    HAUPTFUNKTION FÜR CHATBOT: Scannt nach neuen Akten.

    Wenn der User sagt "neue Akte eingestellt", rufe DIESE Funktion auf!
    Sie erstellt automatisch Bundles und gibt NUR anonymisierte Daten zurück.

    Args:
        password: Passwort für Verschlüsselung. Falls nicht gesetzt, wird
            BACH_DOCUMENT_KEY_PASSWORD aus der Umgebung gelesen.

    Returns:
        Liste neuer Klienten: [{"client_id": "K_XXX", "tarnname": "...", "files": N}]
        Der Chatbot sieht NIEMALS echte Namen!
    """
    resolved_password = _resolve_document_key_password(password)
    if WORKFLOW_AVAILABLE and not resolved_password:
        return [{
            "error": (
                "Kein Dokument-Schlüsselpasswort gesetzt. "
                "Nutze den Parameter password oder BACH_DOCUMENT_KEY_PASSWORD."
            )
        }]
    return get_hook().scan_for_new_clients(resolved_password)


def list_all_clients() -> List[dict]:
    """
    Listet alle Klienten auf - NUR mit client_id und tarnname.

    WICHTIG: Gibt NIEMALS echte Namen zurück!
    """
    return get_hook().list_all_clients_safe()


def get_client_data(client_id: str) -> dict:
    """
    Gibt Daten für einen Klienten zurück - per client_id, NICHT per echtem Namen!

    Args:
        client_id: Die anonyme ID (z.B. "K_CE2E70")

    Returns:
        Anonymisierte Daten inkl. Tarnname und Dokumenten-Inhalt
    """
    return get_hook().get_client_data_by_id(client_id)


def ensure_bundles(password: Optional[str] = None) -> dict:
    """
    Stellt sicher, dass alle Akten anonymisiert sind.

    Sollte VOR jedem Zugriff auf Klientendaten aufgerufen werden.
    """
    resolved_password = _resolve_document_key_password(password)
    if WORKFLOW_AVAILABLE and not resolved_password:
        return {
            "processed": 0,
            "new": 0,
            "errors": 1,
            "clients": [],
            "error": (
                "Kein Dokument-Schlüsselpasswort gesetzt. "
                "Nutze den Parameter password oder BACH_DOCUMENT_KEY_PASSWORD."
            ),
        }
    return get_hook().ensure_all_bundles_exist(resolved_password)


# ═══════════════════════════════════════════════════════════════
# LEGACY CHATBOT INTEGRATION (DEPRECATED - nutze stattdessen obige Funktionen!)
# ═══════════════════════════════════════════════════════════════

def get_klient_context(klient_name: str) -> dict:
    """
    Gibt den vollständigen Kontext für einen Klienten zurück.

    Für den Chatbot: Alle Informationen sind anonymisiert.
    Der Chatbot sieht nur den Tarnnamen und anonymisierte Dokumente.

    Args:
        klient_name: Echter oder Teil des Klientennamens

    Returns:
        Dict mit Kontext (tarnname, files, content)
    """
    hook = get_hook()
    profil = hook.get_profile_for_klient(klient_name)

    if not profil:
        return {
            "found": False,
            "error": f"Kein Profil gefunden für: {klient_name}",
            "hint": "Bitte zuerst ein Bundle erstellen mit: workflow.create_or_update_bundle()"
        }

    tarnname = profil.get("tarnname", "Unbekannt")
    files = hook.list_available_files(klient_name)
    content = hook.get_safe_content(klient_name)

    return {
        "found": True,
        "tarnname": tarnname,
        "client_id": profil.get("client_id"),
        "files": files,
        "file_count": len(files),
        "content": content,
        "content_length": len(content),
        "note": f"Alle Daten sind anonymisiert. Verwende '{tarnname}' statt echtem Namen."
    }


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

def main():
    """CLI für den File Access Hook."""
    import argparse

    parser = argparse.ArgumentParser(description="File Access Hook - Sichere Dateizugriffe")
    subparsers = parser.add_subparsers(dest="command")

    # translate
    trans_p = subparsers.add_parser("translate", help="Pfad übersetzen")
    trans_p.add_argument("path", help="Original-Pfad")

    # read
    read_p = subparsers.add_parser("read", help="Sichere Datei lesen")
    read_p.add_argument("klient", help="Klientenname")
    read_p.add_argument("--file", "-f", help="Dateiname (optional)")

    # list
    list_p = subparsers.add_parser("list", help="Dateien auflisten")
    list_p.add_argument("klient", help="Klientenname")

    # context
    ctx_p = subparsers.add_parser("context", help="Vollständigen Kontext abrufen")
    ctx_p.add_argument("klient", help="Klientenname")

    # tarnname
    tarn_p = subparsers.add_parser("tarnname", help="Tarnnamen abrufen")
    tarn_p.add_argument("klient", help="Klientenname")

    args = parser.parse_args()

    if args.command == "translate":
        result = get_safe_path(args.path)
        print(f"Original: {args.path}")
        print(f"Sicher:   {result}")

    elif args.command == "read":
        content = read_safe_file(args.klient, args.file)
        print(content[:3000])
        if len(content) > 3000:
            print(f"\n... ({len(content)} Zeichen insgesamt)")

    elif args.command == "list":
        files = list_klient_files(args.klient)
        if not files:
            print("Keine Dateien gefunden")
        else:
            print(f"Dateien ({len(files)}):")
            for f in files:
                print(f"  {f['path']} ({f['size']} bytes)")

    elif args.command == "context":
        ctx = get_klient_context(args.klient)
        if ctx.get("found"):
            print(f"Tarnname: {ctx['tarnname']}")
            print(f"Client-ID: {ctx['client_id']}")
            print(f"Dateien: {ctx['file_count']}")
            print(f"Inhalt: {ctx['content_length']} Zeichen")
            print(f"\nHinweis: {ctx['note']}")
        else:
            print(f"[FEHLER] {ctx['error']}")
            print(f"Tipp: {ctx.get('hint', '')}")

    elif args.command == "tarnname":
        tarn = get_tarnname(args.klient)
        if tarn:
            print(f"Tarnname für '{args.klient}': {tarn}")
        else:
            print(f"Kein Tarnname gefunden für: {args.klient}")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
