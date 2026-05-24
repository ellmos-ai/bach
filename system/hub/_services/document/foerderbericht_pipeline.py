#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Foerderbericht End-to-End Pipeline.
Version: 1.0.0
Erstellt: 2026-03-11

Orchestriert bestehende Services zu einer vollautomatischen Pipeline:
data_roh/ -> data_ano/ -> data_bundled/ -> output_berichte/

Standardwege (kein API-Key noetig):
  - Chat/Subagent: "Erstelle Foerderbericht" in Claude Code Session
  - Desktop .bat: Foerderbericht_Pipeline.bat (3x ENTER fuer Auto-Detect)
  - llmauto Chain: bach chain start foerderbericht
  - CLI: bach bericht pipeline

Abhaengigkeiten (alle BACH-intern):
  - ReportWorkflowService (report_workflow_service.py)
  - DocumentAnonymizer / AnonymProfile (anonymizer_service.py)
  - DocumentPipeline (document_pipeline.py)
  - ClaudeRunner (tools/llmauto/core/runner.py)
"""

import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict


# ═══════════════════════════════════════════════════════════════
# Datenklassen
# ═══════════════════════════════════════════════════════════════

@dataclass
class PipelineResult:
    """Ergebnis eines Pipeline-Durchlaufs."""
    success: bool = False
    step: str = "init"
    output_path: Optional[Path] = None
    tarnname: str = ""
    error: str = ""
    duration_s: float = 0.0
    steps_completed: List[str] = field(default_factory=list)


class PipelineError(Exception):
    """Fehler innerhalb der Pipeline."""
    pass


# ═══════════════════════════════════════════════════════════════
# Pipeline-Orchestrator
# ═══════════════════════════════════════════════════════════════

class FoerderberichtPipeline:
    """
    End-to-End Pipeline: data_roh -> output_berichte in einem Aufruf.

    Ordnerstruktur unter .../Berichte/:
        data_roh/         <- Echte Klientendaten (manuell einlegen)
        data_ano/         <- Anonymisierte Einzeldateien
        data_bundled/     <- Gebundener Text + Prompt + LLM-Response
        output_berichte/  <- Fertiger Bericht (de-anonymisiert, Endprodukt)
    """

    FOLDER_NAMES = ["data_roh", "data_ano", "data_bundled", "output_berichte"]

    def __init__(self, base_path=None):
        """
        Args:
            base_path: Basis-Ordner (.../Berichte/). Wird aus bach_paths ermittelt
                       falls nicht angegeben.
        """
        if base_path:
            self.base_path = Path(base_path)
        else:
            try:
                from hub.bach_paths import get_path
                self.base_path = get_path("berichte")
            except ImportError:
                # Fallback: Relativ zu dieser Datei
                self.base_path = (
                    Path(__file__).resolve().parent.parent.parent.parent
                    / "user" / "documents" / "foerderplaner" / "Berichte"
                )

        self._ensure_folders()
        self._migrate_if_needed()

    # ─────────────────────────────────────────────────────────────
    # Haupt-Methode (Vollautomatisch, z.B. via .bat oder llmauto)
    # ─────────────────────────────────────────────────────────────

    def run_full_pipeline(
        self,
        client_name: str = None,
        geburtsdatum: str = None,
        berichtszeitraum: str = "01.01.2025 - 31.12.2025",
        parent_names: list = None,
        client_address: str = None,
        additional_terms: list = None,
        whitelist: list = None,
        llm_backend: str = "claude_code",
        model: str = "claude-sonnet-4-6",
        custom_instructions: str = "",
        auto_cleanup: bool = True,
    ) -> PipelineResult:
        """
        Ein Aufruf = komplette Pipeline von data_roh/ bis output_berichte/.
        Fuer vollautomatische Ausfuehrung (z.B. via .bat oder llmauto).

        Fuer den Chat/Subagent-Weg nutze stattdessen:
          1. prepare_prompt() -> anonymisierter Prompt (sicher fuer AI)
          2. AI generiert JSON-Response
          3. finish_report(response) -> fertiger Bericht + Cleanup
        """
        # Phase 1: Vorbereitung
        result = self.prepare_prompt(
            client_name=client_name,
            geburtsdatum=geburtsdatum,
            berichtszeitraum=berichtszeitraum,
            parent_names=parent_names,
            client_address=client_address,
            additional_terms=additional_terms,
            whitelist=whitelist,
            custom_instructions=custom_instructions,
        )
        if not result.success:
            return result

        # Phase 2: LLM aufrufen (vollautomatisch via ClaudeRunner o.ae.)
        start_llm = time.time()
        try:
            result.step = "llm"
            prompt_file = self.base_path / "data_bundled" / "prompt.txt"
            prompt = prompt_file.read_text(encoding="utf-8")
            llm_response = self._call_llm(prompt, llm_backend, model)
            from hub._services.document.report_workflow_service import ReportWorkflowService
            workflow = ReportWorkflowService(base_path=self.base_path)
            llm_response = workflow.sanitize_llm_response(llm_response)
            response_file = self.base_path / "data_bundled" / "llm_response.txt"
            response_file.write_text(llm_response, encoding="utf-8")
            result.steps_completed.append(f"llm: {len(llm_response)} Zeichen Response")
        except Exception as e:
            result.success = False
            result.error = f"Fehler in 'llm': {e}"
            self._resume_onedrive()
            # Lock entfernen bei LLM-Fehler
            lock_file = self.base_path / ".pipeline_lock"
            if lock_file.exists():
                try:
                    lock_file.unlink()
                except Exception:
                    pass
            return result

        # Phase 3: Finalisierung
        result = self.finish_report(
            llm_response=llm_response,
            auto_cleanup=auto_cleanup,
            _result=result,
        )
        result.duration_s += (time.time() - start_llm)
        return result

    # ─────────────────────────────────────────────────────────────
    # Phase 1: Vorbereitung (Kein AI-Zugriff auf Rohdaten)
    # ─────────────────────────────────────────────────────────────

    def prepare_prompt(
        self,
        client_name: str = None,
        geburtsdatum: str = None,
        berichtszeitraum: str = "01.01.2025 - 31.12.2025",
        parent_names: list = None,
        client_address: str = None,
        additional_terms: list = None,
        whitelist: list = None,
        custom_instructions: str = "",
    ) -> PipelineResult:
        """
        Phase 1: data_roh/ -> anonymisierter Prompt in data_bundled/prompt.txt

        Laeuft komplett OHNE AI-Beteiligung. Kein LLM sieht Rohdaten.
        Nach Abschluss liegt der anonymisierte Prompt bereit fuer die AI.

        Returns:
            PipelineResult (prompt_path zeigt auf data_bundled/prompt.txt)
        """
        result = PipelineResult()
        start_time = time.time()

        # Lock-Datei: Verhindert parallele Durchlaeufe
        lock_file = self.base_path / ".pipeline_lock"
        if lock_file.exists():
            raise PipelineError(
                "Pipeline laeuft bereits (Lock-Datei gefunden). "
                "Falls fehlerhaft: .pipeline_lock in Berichte/ loeschen."
            )

        self._pause_onedrive()

        try:
            lock_file.write_text(
                f"Gestartet: {datetime.now().isoformat()}\n", encoding="utf-8"
            )

            # --- Schritt 1: Validierung ---
            result.step = "validierung"
            data_roh = self.base_path / "data_roh"
            files = [f for f in data_roh.rglob("*") if f.is_file() and not f.name.startswith(".")]
            if not files:
                raise PipelineError(
                    "Keine Akte vorhanden. Bitte Aktenordner in data_roh/ einlegen."
                )
            result.steps_completed.append(f"validierung: {len(files)} Dateien gefunden")

            # Prüfe: Nur EIN Klienten-Ordner erlaubt
            subdirs = [d for d in data_roh.iterdir() if d.is_dir() and not d.name.startswith(".")]
            if len(subdirs) > 1:
                raise PipelineError(
                    f"Nur EIN Klienten-Ordner erlaubt in data_roh/, gefunden: {len(subdirs)}. "
                    f"Ordner: {', '.join(d.name for d in subdirs)}"
                )

            # --- Schritt 1b: Name + Geburtsdatum auto-detect ---
            if not client_name:
                client_name = self._detect_client_name(data_roh)
            if not geburtsdatum:
                geburtsdatum = self._detect_geburtsdatum(data_roh, client_name)

            # --- Schritt 2: Session + Profil ---
            result.step = "profil"
            from hub._services.document.report_workflow_service import ReportWorkflowService
            workflow = ReportWorkflowService(base_path=self.base_path)
            session = workflow.start_session()

            # Dateien direkt registrieren (NICHT kopieren -- sie liegen bereits in data_roh/)
            session.status = "importing"
            session.input_files = list(data_roh.rglob("*"))

            profile = workflow.create_temp_profile(
                session, client_name, geburtsdatum,
                additional_terms=additional_terms,
                whitelist=whitelist,
                scan_folder=data_roh,
                parent_names=parent_names,
                client_address=client_address,
            )
            result.tarnname = profile.tarnname
            result.steps_completed.append(f"profil: Tarnname={profile.tarnname}")

            # --- Schritt 3: Anonymisierung -> data_ano ---
            result.step = "anonymisierung"
            # anonymize_to_bundles schreibt direkt nach data_ano/
            anon_result = workflow.anonymize_to_bundles(session)

            data_ano = self.base_path / "data_ano"
            ano_count = len(list(data_ano.rglob("*"))) if data_ano.exists() else 0
            result.steps_completed.append(
                f"anonymisierung: {ano_count} Dateien, "
                f"{getattr(anon_result, 'core_count', '?')} CORE"
            )

            # --- Schritt 4: Text buendeln -> data_bundled ---
            result.step = "bundling"
            bundle = workflow.extract_bundle_text(session)
            data_bundled = self.base_path / "data_bundled"
            self._deep_cleanup(data_bundled)
            data_bundled.mkdir(parents=True, exist_ok=True)

            bundle_file = data_bundled / "bundle.txt"
            bundle_text = ""
            if hasattr(bundle, 'core_text'):
                bundle_text = bundle.core_text
                if hasattr(bundle, 'stufe2_text') and bundle.stufe2_text:
                    bundle_text += "\n\n=== STUFE 2 ===\n\n" + bundle.stufe2_text
            bundle_file.write_text(bundle_text, encoding="utf-8")
            result.steps_completed.append(f"bundling: {len(bundle_text)} Zeichen")

            # --- Schritt 5: Prompt generieren ---
            result.step = "prompt"
            prompt = workflow.generate_prompt(
                session,
                berichtszeitraum=berichtszeitraum,
                custom_instructions=custom_instructions,
            )
            prompt_file = data_bundled / "prompt.txt"
            prompt_file.write_text(prompt, encoding="utf-8")
            result.steps_completed.append(f"prompt: {len(prompt)} Zeichen")

            # Session-Info speichern (fuer finish_report)
            import json
            session_info = {
                "session_id": session.session_id,
                "tarnname": profile.tarnname,
                "original_name": profile.original_name,
                "mappings": profile.mappings,
                "fake_geburtsdatum": profile.fake_geburtsdatum,
            }
            session_file = data_bundled / "session_info.json"
            session_file.write_text(
                json.dumps(session_info, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )

            result.output_path = prompt_file
            result.success = True

        except Exception as e:
            result.success = False
            result.error = f"Fehler in '{result.step}': {e}"

        result.duration_s = time.time() - start_time
        # OneDrive bleibt pausiert bis finish_report fertig ist
        # (wird in finish_report oder bei Fehler fortgesetzt)
        if not result.success:
            self._resume_onedrive()
            # Lock bei Fehler entfernen
            lock_file = self.base_path / ".pipeline_lock"
            if lock_file.exists():
                try:
                    lock_file.unlink()
                except Exception:
                    pass
        return result

    # ─────────────────────────────────────────────────────────────
    # Phase 3: Finalisierung (nach LLM-Antwort)
    # ─────────────────────────────────────────────────────────────

    def finish_report(
        self,
        llm_response: str = None,
        auto_cleanup: bool = True,
        _result: PipelineResult = None,
    ) -> PipelineResult:
        """
        Phase 3: LLM-Response -> de-anonymisierter Bericht + Cleanup.

        Liest die Session-Info aus data_bundled/session_info.json,
        de-anonymisiert die JSON-Response und generiert den Word-Bericht.

        Args:
            llm_response: LLM-Antwort (JSON). Falls None, wird aus
                          data_bundled/llm_response.txt gelesen.
            auto_cleanup: Zwischenordner nach Erfolg leeren
            _result: Internes PipelineResult (fuer run_full_pipeline)

        Returns:
            PipelineResult mit Output-Pfad
        """
        import json

        result = _result or PipelineResult()
        start_time = time.time()
        data_bundled = self.base_path / "data_bundled"

        try:
            # LLM-Response laden falls nicht uebergeben
            if not llm_response:
                response_file = data_bundled / "llm_response.txt"
                if not response_file.exists():
                    raise PipelineError(
                        "Keine LLM-Response gefunden. "
                        "Speichere die Antwort als data_bundled/llm_response.txt"
                    )
                llm_response = response_file.read_text(encoding="utf-8")

            # Session-Info laden
            session_file = data_bundled / "session_info.json"
            if not session_file.exists():
                raise PipelineError(
                    "Keine Session-Info gefunden. Bitte zuerst prepare_prompt() ausfuehren."
                )
            session_info = json.loads(session_file.read_text(encoding="utf-8"))

            # Session + Profil rekonstruieren
            result.step = "bericht"
            from hub._services.document.report_workflow_service import (
                ReportWorkflowService, TempAnonymProfile, WorkflowSession
            )
            workflow = ReportWorkflowService(base_path=self.base_path)

            profile = TempAnonymProfile(
                tarnname=session_info["tarnname"],
                fake_geburtsdatum=session_info["fake_geburtsdatum"],
                mappings=session_info["mappings"],
                original_name=session_info["original_name"],
            )
            session = WorkflowSession(
                session_id=session_info["session_id"],
                status="generating",
                profile=profile,
            )
            result.tarnname = profile.tarnname

            # Word-Bericht generieren (de-anonymisiert)
            clean_report = workflow.generate_report(
                session, llm_response, auto_deanonymize=True
            )
            if clean_report:
                output_dir = self.base_path / "output_berichte"
                clean_dest = output_dir / Path(clean_report).name
                if Path(clean_report).resolve() != clean_dest.resolve():
                    shutil.copy2(str(clean_report), str(clean_dest))
                result.output_path = clean_dest
                result.steps_completed.append("bericht: erstellt")

            # Cleanup
            if auto_cleanup:
                result.step = "cleanup"
                self._cleanup_pipeline(session, workflow)
                result.steps_completed.append("cleanup: erledigt")

            result.success = True

        except Exception as e:
            result.success = False
            result.error = f"Fehler in '{result.step}': {e}"

        finally:
            self._resume_onedrive()
            # Lock-Datei entfernen
            lock_file = self.base_path / ".pipeline_lock"
            if lock_file.exists():
                try:
                    lock_file.unlink()
                except Exception:
                    pass

        result.duration_s += (time.time() - start_time)
        return result

    # ─────────────────────────────────────────────────────────────
    # LLM-Integration
    # ─────────────────────────────────────────────────────────────

    def _call_llm(self, prompt: str, backend: str, model: str) -> str:
        """
        LLM aufrufen ueber verschiedene Backends.

        Standardwege (kein API-Key noetig):
          - claude_code: ClaudeRunner subprocess (Default)
          - llmauto: Ueber das llmauto Chain-System

        Optionaler Weg (braucht ANTHROPIC_API_KEY):
          - anthropic_sdk: Direkter API-Aufruf

        Args:
            prompt: Der vollstaendige Prompt
            backend: "claude_code" (Default), "llmauto" oder "anthropic_sdk"
            model: Modellname

        Returns:
            LLM-Antwort als String

        Raises:
            PipelineError: Bei Fehlern
        """
        if backend == "anthropic_sdk":
            try:
                import anthropic
                client = anthropic.Anthropic()
                response = client.messages.create(
                    model=model,
                    max_tokens=8000,
                    messages=[{"role": "user", "content": prompt}],
                )
                return response.content[0].text
            except ImportError:
                raise PipelineError(
                    "anthropic SDK nicht installiert. pip install anthropic"
                )

        elif backend in ("claude_code", "llmauto"):
            try:
                # ClaudeRunner aus tools/llmauto importieren
                llmauto_path = str(
                    Path(__file__).resolve().parent.parent.parent.parent
                    / "tools" / "llmauto"
                )
                if llmauto_path not in sys.path:
                    sys.path.insert(0, llmauto_path)
                from core.runner import ClaudeRunner

                runner = ClaudeRunner(
                    model=model,
                    permission_mode="dontAsk",
                    allowed_tools=[],
                    timeout=600,
                )
                run_result = runner.run(prompt)
                if not run_result.get("success"):
                    raise PipelineError(
                        f"ClaudeRunner Fehler: {run_result.get('stderr', 'unbekannt')}"
                    )
                return run_result.get("output", "")
            except ImportError:
                raise PipelineError(
                    "ClaudeRunner nicht gefunden. "
                    "Pruefe tools/llmauto/core/runner.py"
                )

        else:
            raise PipelineError(f"Unbekanntes LLM-Backend: {backend}")

    # ─────────────────────────────────────────────────────────────
    # Auto-Detect (Name + Geburtsdatum aus Ordnerstruktur)
    # ─────────────────────────────────────────────────────────────

    def _detect_client_name(self, data_roh: Path) -> str:
        """
        Ermittelt den Klientennamen aus dem Ordnernamen in data_roh/.

        Erwartet: data_roh/<Nachname, Vorname>/ oder data_roh/<Vorname Nachname>/
        Falls nur lose Dateien: Fallback auf Ordnernamen-Heuristik.

        WICHTIG: Diese Methode laeuft lokal im Pipeline-Prozess.
        Der Name wird NIEMALS an die AI zurueckgegeben -- nur der Tarnname.
        """
        # Suche den ersten Unterordner (= Klienten-Akte)
        subdirs = [
            d for d in data_roh.iterdir()
            if d.is_dir() and not d.name.startswith(".")
        ]

        if subdirs:
            folder_name = subdirs[0].name
            # Format "Nachname, Vorname" -> "Vorname Nachname"
            if ", " in folder_name:
                parts = folder_name.split(", ", 1)
                return f"{parts[1].strip()} {parts[0].strip()}"
            return folder_name

        # Fallback: Lose Dateien in data_roh/ -> Name aus Dateinamen raten
        # z.B. "Protokoll_MaxMustermann.docx"
        raise PipelineError(
            "Kein Klienten-Ordner in data_roh/ gefunden. "
            "Bitte die Akte als Ordner (z.B. 'Nachname, Vorname') einlegen."
        )

    def _detect_geburtsdatum(self, data_roh: Path, client_name: str) -> str:
        """
        Versucht das Geburtsdatum aus dem Aktendeckblatt zu extrahieren.
        Fallback: Platzhalter '01.01.2010'.

        WICHTIG: Laeuft lokal, Ergebnis wird NICHT an die AI weitergegeben.
        """
        import re

        # Suche Aktendeckblatt in data_roh/
        for filepath in data_roh.rglob("*"):
            if not filepath.is_file():
                continue
            name_lower = filepath.name.lower()
            if "aktendeckblatt" in name_lower or "stammdaten" in name_lower:
                try:
                    text = ""
                    if filepath.suffix.lower() in (".txt", ".md"):
                        text = filepath.read_text(encoding="utf-8", errors="replace")
                    elif filepath.suffix.lower() == ".docx":
                        try:
                            from docx import Document
                            doc = Document(str(filepath))
                            text = "\n".join(p.text for p in doc.paragraphs)
                        except Exception:
                            pass

                    if text:
                        # Geburtsdatum-Pattern: DD.MM.YYYY
                        match = re.search(
                            r"(?:geb(?:oren|urtsdatum)?|geboren am|geb\.?\s*:?)\s*"
                            r"(\d{1,2}\.\d{1,2}\.\d{4})",
                            text, re.IGNORECASE
                        )
                        if match:
                            return match.group(1)
                except Exception:
                    pass

        # Fallback
        return "01.01.2010"

    # ─────────────────────────────────────────────────────────────
    # Cleanup & Migration
    # ─────────────────────────────────────────────────────────────

    def _cleanup_pipeline(self, session=None, workflow=None):
        """Zwischenordner leeren nach erfolgreichem Durchlauf."""
        # Aktive Pipeline-Ordner leeren (NICHT output_berichte!)
        for folder_name in ["data_roh", "data_ano", "data_bundled"]:
            folder = self.base_path / folder_name
            self._deep_cleanup(folder)
            folder.mkdir(parents=True, exist_ok=True)

        # Legacy-Ordner komplett entfernen (werden nicht mehr gebraucht)
        for legacy in ["data", "output", "bundles"]:
            legacy_path = self.base_path / legacy
            if legacy_path.exists():
                try:
                    shutil.rmtree(legacy_path)
                except Exception:
                    pass

        # Workflow-interne Ordner aufraumen
        if workflow and session:
            try:
                workflow.cleanup(session)
            except Exception:
                pass

    def _ensure_folders(self):
        """Neue Ordnerstruktur sicherstellen."""
        for name in self.FOLDER_NAMES:
            (self.base_path / name).mkdir(parents=True, exist_ok=True)

    def _migrate_if_needed(self):
        """
        Alte Ordnerstruktur -> Neue (einmalig, idempotent).

        Migriert:
          data/   -> data_roh/
          output/ -> output_berichte/
        """
        marker = self.base_path / ".migrated_v2"
        if marker.exists():
            return

        # data/ -> data_roh/
        old_data = self.base_path / "data"
        if old_data.exists():
            for item in old_data.iterdir():
                if not item.name.startswith("."):
                    dest = self.base_path / "data_roh" / item.name
                    if not dest.exists():
                        try:
                            shutil.move(str(item), str(dest))
                        except Exception:
                            pass

        # output/ -> output_berichte/
        old_output = self.base_path / "output"
        if old_output.exists():
            for item in old_output.iterdir():
                dest = self.base_path / "output_berichte" / item.name
                if not dest.exists():
                    try:
                        shutil.move(str(item), str(dest))
                    except Exception:
                        pass

        # Leere Legacy-Ordner entfernen
        for legacy in ["data", "output", "bundles"]:
            legacy_path = self.base_path / legacy
            if legacy_path.exists():
                try:
                    if not any(legacy_path.iterdir()):
                        legacy_path.rmdir()
                except Exception:
                    pass

        marker.write_text(
            f"Migriert am {datetime.now().isoformat()}\n",
            encoding="utf-8"
        )

    def _deep_cleanup(self, folder: Path):
        """Ordner leeren aber behalten."""
        if not folder.exists():
            return
        for item in folder.iterdir():
            try:
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()
            except PermissionError:
                # OneDrive Lock-Retry
                time.sleep(2)
                try:
                    if item.is_dir():
                        shutil.rmtree(item)
                    else:
                        item.unlink()
                except Exception:
                    pass

    # ─────────────────────────────────────────────────────────────
    # OneDrive Sync-Steuerung
    # ─────────────────────────────────────────────────────────────

    @staticmethod
    def _find_onedrive_exe() -> Optional[str]:
        """Findet OneDrive.exe auf dem System."""
        candidates = [
            os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\OneDrive\OneDrive.exe"),
            r"C:\Program Files\Microsoft OneDrive\OneDrive.exe",
            r"C:\Program Files (x86)\Microsoft OneDrive\OneDrive.exe",
        ]
        for path in candidates:
            if os.path.exists(path):
                return path
        return None

    def _pause_onedrive(self):
        """Stoppt OneDrive sauber via /shutdown (kein Explorer-Fenster)."""
        self._onedrive_paused = False
        try:
            exe = self._find_onedrive_exe()
            if exe:
                subprocess.run(
                    [exe, "/shutdown"],
                    timeout=10,
                    capture_output=True,
                )
                time.sleep(3)  # Warten bis vollstaendig beendet
                self._onedrive_paused = True
                print("[INFO] OneDrive gestoppt (/shutdown)")
            else:
                print("[INFO] OneDrive.exe nicht gefunden, ueberspringe Stopp")
        except Exception as e:
            print(f"[WARN] OneDrive-Stopp fehlgeschlagen: {e}")

    def _resume_onedrive(self):
        """Startet OneDrive im Hintergrund via /background (kein Explorer-Fenster)."""
        if not getattr(self, '_onedrive_paused', False):
            return
        try:
            exe = self._find_onedrive_exe()
            if exe:
                kwargs = {}
                if sys.platform == "win32":
                    kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
                else:
                    kwargs["start_new_session"] = True
                subprocess.Popen([exe, "/background"], **kwargs)
                print("[INFO] OneDrive gestartet (/background)")
        except Exception as e:
            print(f"[WARN] OneDrive-Start fehlgeschlagen: {e}")
        finally:
            self._onedrive_paused = False
