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

import atexit
import contextlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.parse
import urllib.request
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


# Betriebsmodi: "cloud" = anonymisieren, Cloud-/Abo-Modell; "lokal" = KEINE Anonymisierung,
# ausschliesslich lokales Modell (Daten verlassen den Rechner nicht). Der Modus lokal ist
# fail-closed an lokale Backends gekoppelt, damit Klartext nie an ein Cloud-Backend geht.
MODI = ("cloud", "lokal")
LOCAL_BACKENDS = ("ollama",)
DEFAULT_CLOUD_MODEL = "claude-sonnet-4-6"
DEFAULT_LOCAL_MODEL = "qwen3.8:27b-mlx"  # Mac Studio, Dauer-Worker-Modell


def _is_own_device_host(hostname: str) -> bool:
    """Exakte Allowlist FOERDERBERICHT_ALLOWED_HOSTS (Default: nur localhost) - nie ein Cloud-Ziel."""
    hostname = (hostname or "").strip().lower()
    if hostname.startswith("[") and hostname.endswith("]"):
        hostname = hostname[1:-1]
    if not hostname:
        return False
    for entry in os.environ.get("FOERDERBERICHT_ALLOWED_HOSTS", "localhost,127.0.0.1,::1").split(","):
        if hostname == entry.strip().lower():
            return True
    return False


# --- SSH-Tunnel zum Ollama auf einem eigenen Geraet (z. B. Mac Studio) -----------------------------
# Konfiguration nur ueber Umgebungsvariablen, kein fest eingetragener Host/Benutzer:
#   FOERDERBERICHT_SSH_TUNNEL   Ziel "benutzer@host" (host: exakter Host/IP aus
#                               FOERDERBERICHT_ALLOWED_HOSTS oder ein einteiliger Name aus der
#                               eigenen ssh-config; Default-Hosts: localhost); ohne Wert kein Tunnel
#   FOERDERBERICHT_SSH_KEY      optional: Pfad zum privaten Schluessel
#   FOERDERBERICHT_SSH_REMOTE_PORT  optional, Default 11434
# Der Tunnel wird nur geoeffnet, wenn OLLAMA_HOST nicht gesetzt ist, und nach dem Modellaufruf
# immer wieder geschlossen (auch bei Fehler/Abbruch; unter Windows zusaetzlich per Job-Objekt, damit
# der ssh-Prozess auch bei hartem Ende der Pipeline mitstirbt).
_TUNNEL_TARGET_RE = re.compile(r"^(?:[A-Za-z0-9._-]+@)?(?P<host>[A-Za-z0-9][A-Za-z0-9._-]*)$")
_JOB_HANDLES = []  # Job-Objekt-Handles muessen bis zum Prozessende offen bleiben


def _validate_tunnel_target(target: str) -> str:
    """Prueft das Tunnelziel (keine Optionen, keine Leerzeichen, nur eigene Geraete)."""
    target = (target or "").strip()
    m = _TUNNEL_TARGET_RE.match(target)
    if not m or target.startswith("-"):
        raise PipelineError(f"Ungueltiges Tunnelziel (erwartet benutzer@host): {target!r}")
    host = m.group("host")
    if "." in host or host.replace(".", "").isdigit():
        if not _is_own_device_host(host):
            raise PipelineError(
                f"Tunnelziel {host!r} nicht freigegeben; eigene Geraete in FOERDERBERICHT_ALLOWED_HOSTS "
                "eintragen (exakte Hosts/IPs, kommagetrennt; Default: localhost)."
            )
    return target


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _bind_child_to_kill_on_close_job(proc) -> None:
    """Windows: ssh-Prozess in ein Job-Objekt mit KILL_ON_JOB_CLOSE legen, damit er mit dem
    Elternprozess stirbt (auch bei hartem Beenden). Best effort; andere Systeme: nichts."""
    if os.name != "nt":
        return
    try:
        import ctypes
        from ctypes import wintypes

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [(n, ctypes.c_ulonglong) for n in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class BASIC(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class EXTENDED(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", BASIC), ("IoInfo", IO_COUNTERS),
                        ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        job = k32.CreateJobObjectW(None, None)
        info = EXTENDED()
        info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if job and k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
            if k32.AssignProcessToJobObject(job, int(proc._handle)):
                _JOB_HANDLES.append(job)
    except Exception:  # best effort
        pass


def _tunnel_ready(port: int, proc, timeout_s: float = 45.0) -> None:
    """Wartet, bis der Tunnel antwortet (GET /api/version); bricht ab, wenn ssh vorher endet."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        rc = proc.poll()
        if rc is not None:
            err = ""
            try:
                err = (proc.stderr.read() or b"").decode("utf-8", "replace").strip()[:400] if proc.stderr else ""
            except Exception:
                pass
            raise PipelineError(f"SSH-Tunnel beendet (Exit {rc}): {err or 'keine Meldung'}")
        try:
            with opener.open(f"http://127.0.0.1:{port}/api/version", timeout=3) as resp:
                if resp.status == 200:
                    return
        except OSError:
            pass
        time.sleep(0.5)
    raise PipelineError(f"SSH-Tunnel nicht bereit nach {int(timeout_s)} s (Ollama am Ziel erreichbar?)")


@contextlib.contextmanager
def _ollama_ssh_tunnel(target: str, key: str = None, remote_port: int = 11434):
    """Oeffnet `ssh -N -L 127.0.0.1:<frei>:127.0.0.1:<remote_port> <ziel>` und schliesst ihn sicher."""
    target = _validate_tunnel_target(target)
    port = _free_port()
    cmd = ["ssh", "-N", "-o", "ExitOnForwardFailure=yes", "-o", "BatchMode=yes",
           "-o", "ConnectTimeout=15", "-o", "ServerAliveInterval=30"]
    if key:
        cmd += ["-i", key]
    cmd += ["-L", f"127.0.0.1:{port}:127.0.0.1:{int(remote_port)}", "--", target]
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    else:
        kwargs["start_new_session"] = True
    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.PIPE, **kwargs)
    except FileNotFoundError:
        raise PipelineError("ssh nicht im PATH gefunden (Tunnel zum Modell-Host).")

    def _close():
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                with contextlib.suppress(Exception):
                    proc.wait(timeout=5)

    atexit.register(_close)  # falls der Interpreter vor dem finally endet
    _bind_child_to_kill_on_close_job(proc)
    try:
        _tunnel_ready(port, proc)
        yield f"http://127.0.0.1:{port}"
    finally:
        _close()
        with contextlib.suppress(Exception):
            atexit.unregister(_close)
        with contextlib.suppress(Exception):
            if proc.stderr:
                proc.stderr.close()


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
        llm_backend: str = None,
        model: str = None,
        custom_instructions: str = "",
        auto_cleanup: bool = True,
        modus: str = "cloud",
    ) -> PipelineResult:
        """
        Ein Aufruf = komplette Pipeline von data_roh/ bis output_berichte/.
        Fuer vollautomatische Ausfuehrung (z.B. via .bat oder llmauto).

        modus="cloud" (Default): anonymisieren, Backend claude_code/llmauto/anthropic_sdk.
        modus="lokal": KEINE Anonymisierung, nur lokales Backend (ollama auf localhost);
                       Modell aus `model` bzw. Umgebungsvariable FOERDERBERICHT_LOCAL_MODEL.

        Fuer den Chat/Subagent-Weg nutze stattdessen:
          1. prepare_prompt() -> anonymisierter Prompt (sicher fuer AI)
          2. AI generiert JSON-Response
          3. finish_report(response) -> fertiger Bericht + Cleanup
        """
        # Modus + Backend + Modell festlegen (fail-closed: lokal nie mit Cloud-Backend)
        if modus not in MODI:
            return PipelineResult(step="modus", error=f"Unbekannter Modus: {modus!r} (erlaubt: {', '.join(MODI)})")
        if modus == "lokal":
            llm_backend = llm_backend or "ollama"
            model = model or os.environ.get("FOERDERBERICHT_LOCAL_MODEL", DEFAULT_LOCAL_MODEL)
            if llm_backend not in LOCAL_BACKENDS:
                return PipelineResult(
                    step="modus",
                    error=f"Modus 'lokal' erlaubt nur lokale Backends {LOCAL_BACKENDS}, nicht {llm_backend!r}",
                )
        else:
            llm_backend = llm_backend or "claude_code"
            model = model or DEFAULT_CLOUD_MODEL

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
            anonymize=(modus == "cloud"),
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
        anonymize: bool = True,
    ) -> PipelineResult:
        """
        Phase 1: data_roh/ -> anonymisierter Prompt in data_bundled/prompt.txt

        anonymize=False (Modus lokal): KEINE Anonymisierung, der Prompt enthaelt Klartext und
        darf nur an ein lokales Modell gehen (siehe run_full_pipeline(modus="lokal")).

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
                    "Keine Akte: data_roh enthaelt keine Dateien. Bitte Aktenordner in data_roh/ einlegen."
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

            if not anonymize:
                # Modus lokal: Identitaetsprofil (leeres Mapping) statt Tarnprofil; finish_report()
                # uebersetzt dann nichts zurueck. Bundle direkt aus dem Klientenordner.
                self._prepare_plain(
                    result, data_roh, client_name, geburtsdatum, berichtszeitraum, custom_instructions
                )
                result.success = True
                result.duration_s = time.time() - start_time
                return result

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
            result.tarnname = profile.tarnname if profile.mappings else ""

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

    def _prepare_plain(self, result, data_roh, client_name, geburtsdatum, berichtszeitraum, custom_instructions):
        """Phase 1 ohne Anonymisierung (nur Modus lokal)."""
        from hub._services.document.report_workflow_service import (
            ReportWorkflowService, TempAnonymProfile,
        )
        from hub._services.document.document_pipeline import DocumentPipeline

        result.step = "prompt"
        subdirs = [d for d in sorted(data_roh.iterdir()) if d.is_dir() and not d.name.startswith(".")]
        if subdirs:
            client_dir = subdirs[0]
        elif any(p.is_file() and not p.name.startswith(".") for p in data_roh.iterdir()):
            client_dir = data_roh  # Dateien direkt in data_roh (flacher Fall, wie validate() erlaubt)
        else:
            raise PipelineError("data_roh enthaelt weder Klienten-Ordner noch Dateien")
        workflow = ReportWorkflowService(base_path=self.base_path)
        session = workflow.start_session()
        session.profile = TempAnonymProfile(
            tarnname=client_name, fake_geburtsdatum=geburtsdatum,
            mappings={}, original_name=client_name,
        )
        collector = DocumentPipeline()
        scan = collector.scan_folder(str(client_dir))
        session.bundle = collector.extract_bundle(
            scan.documents, include_extended=True, anonym_profile=None
        )
        bundle = session.bundle
        text = bundle.core_text if hasattr(bundle, "core_text") else ""
        if getattr(bundle, "stufe2_text", ""):
            text += "\n\n=== STUFE 2 ===\n\n" + bundle.stufe2_text
        data_bundled = self.base_path / "data_bundled"
        self._deep_cleanup(data_bundled)
        data_bundled.mkdir(parents=True, exist_ok=True)
        (data_bundled / "bundle.txt").write_text(text, encoding="utf-8")
        prompt = workflow.generate_prompt(
            session, berichtszeitraum=berichtszeitraum, custom_instructions=custom_instructions
        )
        prompt_file = data_bundled / "prompt.txt"
        prompt_file.write_text(prompt, encoding="utf-8")
        (data_bundled / "session_info.json").write_text(json.dumps({
            "modus": "lokal",
            "session_id": session.session_id,
            "tarnname": client_name,
            "original_name": client_name,
            "mappings": {},
            "fake_geburtsdatum": geburtsdatum,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        result.steps_completed.append(f"prompt (lokal, ohne Anonymisierung): {len(prompt)} Zeichen")
        result.output_path = prompt_file

    @staticmethod
    def _ollama_loaded_context(opener, host: str, model: str):
        """Kontextlaenge des bereits geladenen Modells (GET /api/ps) oder None."""
        try:
            with opener.open(urllib.request.Request(host.rstrip("/") + "/api/ps"), timeout=15) as resp:
                for m in json.loads(resp.read().decode("utf-8")).get("models", []):
                    if model in (m.get("name"), m.get("model")):
                        return int(m.get("context_length") or 0) or None
        except (OSError, ValueError):
            pass
        return None

    def _call_ollama(self, prompt: str, model: str) -> str:
        """Lokales Modell ueber Ollama. Ist OLLAMA_HOST nicht gesetzt und FOERDERBERICHT_SSH_TUNNEL
        konfiguriert, wird fuer die Dauer des Aufrufs ein SSH-Tunnel geoeffnet."""
        target = os.environ.get("FOERDERBERICHT_SSH_TUNNEL", "").strip()
        if target and not os.environ.get("OLLAMA_HOST"):
            remote_port = int(os.environ.get("FOERDERBERICHT_SSH_REMOTE_PORT", "11434"))
            with _ollama_ssh_tunnel(target, os.environ.get("FOERDERBERICHT_SSH_KEY") or None, remote_port) as host:
                return self._call_ollama_at(host, prompt, model)
        return self._call_ollama_at(os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434"), prompt, model)

    def _call_ollama_at(self, host: str, prompt: str, model: str) -> str:
        """Ollama-Aufruf gegen `host`. Nur Hosts aus FOERDERBERICHT_ALLOWED_HOSTS, nie ein Cloud-Modell/Proxy."""
        if "://" not in host:
            host = "http://" + host
        if not _is_own_device_host(urllib.parse.urlparse(host).hostname):
            raise PipelineError(
                "Backend 'ollama' (Modus lokal) erlaubt nur Hosts aus FOERDERBERICHT_ALLOWED_HOSTS "
                "(Default: localhost), nicht: " + str(urllib.parse.urlparse(host).hostname)
            )
        low = model.lower()
        if low.endswith(":cloud") or low.endswith("-cloud") or low.startswith("claude"):
            raise PipelineError(f"Modell {model!r} ist kein lokales Modell (Modus lokal).")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # kein Proxy
        # Ist das Modell schon geladen (z. B. von einem Dauer-Worker), MUSS dessen Kontext
        # uebernommen werden: ein anderer num_ctx laedt das Modell neu und verdraengt den Worker.
        loaded_ctx = self._ollama_loaded_context(opener, host, model)
        env_ctx = os.environ.get("FOERDERBERICHT_NUM_CTX")
        num_ctx = int(env_ctx) if env_ctx else (loaded_ctx or 12288)
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "think": False,
            "options": {"num_ctx": num_ctx, "num_predict": 6000, "temperature": 0.2},
        }
        if loaded_ctx:
            # Residenz des geladenen Modells nicht verkuerzen (Ollama-Default waere 5 min)
            payload["keep_alive"] = os.environ.get("FOERDERBERICHT_KEEP_ALIVE", "30m")
        req = urllib.request.Request(
            host.rstrip("/") + "/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with opener.open(req, timeout=3600) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except OSError as e:
            raise PipelineError(f"Ollama nicht erreichbar ({host}): {e}")
        if data.get("error"):
            raise PipelineError(f"Ollama-Fehler: {data['error']}")
        used = int(data.get("prompt_eval_count") or 0) + int(data.get("eval_count") or 0)
        if data.get("done_reason") == "length":
            raise PipelineError(
                "Antwort unvollstaendig: Ollama hat bei num_predict=6000 abgeschnitten (done_reason=length). "
                "FOERDERBERICHT_NUM_CTX erhoehen oder groesseres Modell/Host waehlen."
            )
        if used >= num_ctx:
            raise PipelineError(
                f"Kontextfenster voll ({used} von {num_ctx} Tokens): Prompt moeglicherweise still gekuerzt "
                "oder Antwort abgeschnitten. FOERDERBERICHT_NUM_CTX erhoehen oder groesseres Modell/Host waehlen."
            )
        content = (data.get("message") or {}).get("content", "").strip()
        try:
            json.loads(content)
        except (ValueError, TypeError):
            raise PipelineError(
                "Antwort ist kein vollstaendiges JSON (vermutlich abgeschnitten oder ungueltig): "
                "FOERDERBERICHT_NUM_CTX erhoehen oder groesseres Modell/Host waehlen."
            )
        return content

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
            backend: "claude_code" (Default), "llmauto", "anthropic_sdk" oder "ollama" (lokal)
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

        elif backend == "ollama":
            return self._call_ollama(prompt, model)

        elif backend in ("claude_code", "llmauto"):
            # Direkter claude-CLI-Aufruf statt ClaudeRunner: (1) "from core.runner"
            # kollidiert mit system/core und schlug mit ImportError fehl, (2) der
            # Runner behandelt allowed_tools=[] als "alle Tools", (3) der Prompt
            # kann das argv-Limit (Windows ~32k Zeichen) sprengen -> per stdin.
            # Das Modell sieht nur den anonymisierten Prompt: keine Tools, keine
            # Hooks/Memory/CLAUDE.md, neutrales Arbeitsverzeichnis.
            import tempfile
            env = os.environ.copy()
            env.pop("CLAUDECODE", None)
            env["PYTHONIOENCODING"] = "utf-8"
            env["CLAUDE_CODE_DISABLE_CLAUDE_MDS"] = "1"
            cmd = [
                "claude", "--model", model, "-p",
                "--tools", "",
                "--setting-sources", "local",
                "--strict-mcp-config",
                "--disable-slash-commands",
            ]
            try:
                proc = subprocess.run(
                    cmd, input=prompt, env=env, capture_output=True,
                    text=True, encoding="utf-8", errors="replace",
                    timeout=600, cwd=tempfile.gettempdir(),
                )
            except FileNotFoundError:
                raise PipelineError("claude CLI nicht im PATH gefunden.")
            except subprocess.TimeoutExpired:
                raise PipelineError("claude CLI Timeout nach 600s.")
            if proc.returncode != 0:
                raise PipelineError(
                    f"claude CLI Fehler (Exit {proc.returncode}): "
                    f"{(proc.stderr or '').strip()[:500]}"
                )
            return proc.stdout.strip()

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
