# SPDX-License-Identifier: MIT
"""
NoteSpace Handler - BACH-eigenes NoteSpaceLLM (On-Board)
========================================================

Festes, mitgeliefertes BACH-Modul: ein privater NotebookLM-Klon fuer
Dokument-Analyse und Report-Generierung. Eigenstaendige BACH-Version,
unabhaengig vom internen Quellprojekt.

--notespace status        Modul-Status, Ollama-Bindung, Datenpfad, Dependencies
--notespace gui           Desktop-GUI starten (PySide6, lokales System)
--notespace cli "frage"   Headless RAG-Query (Phase 2, noch nicht implementiert)

Bindung:
- LLM/Embeddings: BACHs globale Ollama-Config (data/ollama_config.json)
- Daten (Projekte/Vektor-DB/Output): data/notespace/  (gitignored, user-spezifisch)

Vendored aus einem internen NoteSpaceLLM-Quellstand (siehe
tools/notespace/PROVENANCE.md).
"""
import sys
import json
import subprocess
from pathlib import Path
from typing import List, Tuple

from .base import BaseHandler


class NoteSpaceHandler(BaseHandler):
    """Handler fuer --notespace Operationen."""

    @property
    def profile_name(self) -> str:
        return "notespace"

    @property
    def target_file(self) -> Path:
        return self.base_path / "tools" / "notespace"

    # --- Pfade -------------------------------------------------------------

    def _module_dir(self) -> Path:
        """Vendored App-Verzeichnis."""
        return self.base_path / "tools" / "notespace"

    def _data_dir(self) -> Path:
        """User-spezifischer Datenpfad (gitignored)."""
        return self.base_path / "data" / "notespace"

    def _ollama_config_path(self) -> Path:
        return self.base_path / "data" / "ollama_config.json"

    # --- Helpers -----------------------------------------------------------

    def _read_ollama_config(self) -> dict:
        """Liest BACHs globale Ollama-Config (Fallback: localhost-Defaults)."""
        defaults = {
            "base_url": "http://localhost:11434",
            "model": "llama3.2",
            "embedding_model": "nomic-embed-text",
        }
        path = self._ollama_config_path()
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                defaults.update({k: v for k, v in cfg.items() if v})
            except Exception:
                pass
        return defaults

    def _sync_ollama_config(self) -> None:
        """Bindet die NoteSpace-App fest an BACHs globale Ollama-Config.

        Provider/Modell/URL/Embedding folgen data/ollama_config.json. Bereits
        vorhandene Profile bleiben erhalten. Zum Aendern: data/ollama_config.json
        editieren (eine Quelle der Wahrheit, gitignored).
        """
        cfg = self._read_ollama_config()
        config_dir = self._data_dir() / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        config_file = config_dir / "config.json"

        data = {}
        if config_file.exists():
            try:
                with open(config_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = {}

        data["llm_provider"] = "ollama"
        data["llm_model"] = cfg.get("model", "llama3.2")
        data["ollama_base_url"] = cfg.get("base_url", "http://localhost:11434")
        data["ollama_api_key"] = data.get("ollama_api_key", "")
        data["embedding_model"] = cfg.get("embedding_model", "nomic-embed-text")
        data.setdefault("active_profile", "")
        data.setdefault("profiles", {})

        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def _check_deps(self) -> dict:
        """Prueft optionale Laufzeit-Abhaengigkeiten der App."""
        import importlib
        deps = {
            "PySide6": "GUI",
            "fitz": "PDF (PyMuPDF)",
            "chromadb": "Vektor-DB",
            "langchain": "RAG",
            "langchain_ollama": "RAG-Ollama",
            "langchain_chroma": "RAG-Chroma",
        }
        result = {}
        for mod, label in deps.items():
            try:
                importlib.import_module(mod)
                result[mod] = (True, label)
            except Exception:
                result[mod] = (False, label)
        return result

    def _module_installed(self) -> bool:
        return (self._module_dir() / "main.py").exists()

    # --- Operations --------------------------------------------------------

    def get_operations(self) -> dict:
        return {
            "status": "Modul-Status, Ollama-Bindung, Datenpfad, Dependencies",
            "gui": "Desktop-GUI starten (PySide6, lokales System)",
            "cli": "Headless RAG-Query (Phase 2, noch nicht implementiert)",
        }

    def handle(self, operation: str, args: List[str], dry_run: bool = False) -> Tuple[bool, str]:
        if operation == "gui":
            return self._gui(dry_run)
        elif operation == "cli":
            return self._cli(args, dry_run)
        else:
            return self._status()

    def _status(self) -> Tuple[bool, str]:
        cfg = self._read_ollama_config()
        deps = self._check_deps()
        installed = self._module_installed()

        out = []
        out.append("")
        out.append("[NOTESPACE] BACH On-Board NoteSpaceLLM")
        out.append("=" * 50)
        out.append(f"  Modul installiert: {'JA' if installed else 'NEIN (tools/notespace/ fehlt)'}")
        out.append(f"  Datenpfad:         {self._data_dir()}")
        out.append("")
        out.append("  Ollama-Bindung (BACHs globale Config):")
        out.append(f"    URL:        {cfg['base_url']}")
        out.append(f"    Modell:     {cfg.get('model', '?')}")
        out.append(f"    Embedding:  {cfg.get('embedding_model', 'nomic-embed-text')}")
        out.append("")
        out.append("  Dependencies:")
        for mod, (ok, label) in deps.items():
            out.append(f"    [{'OK ' if ok else 'XX '}] {mod:<18} {label}")
        out.append("")
        if not installed:
            out.append("  Hinweis: App-Code noch nicht vendored. Erst nach Vendoring nutzbar.")
        else:
            out.append("  Befehle:")
            out.append("    bach notespace gui    - Desktop-GUI starten")
        return True, "\n".join(out)

    def _gui(self, dry_run: bool = False) -> Tuple[bool, str]:
        if not self._module_installed():
            return False, ("[NOTESPACE] Modul-Code fehlt (tools/notespace/main.py).\n"
                           "Vendoring noch nicht abgeschlossen.")

        deps = self._check_deps()
        if not deps["PySide6"][0]:
            return False, ("[NOTESPACE] PySide6 fehlt - GUI nicht startbar.\n"
                           "  pip install PySide6")

        main_py = self._module_dir() / "main.py"
        data_dir = self._data_dir()
        data_dir.mkdir(parents=True, exist_ok=True)

        if dry_run:
            return True, f"[DRY-RUN] Wuerde GUI starten: {main_py}"

        # Backend fest an BACHs globale Ollama-Config binden
        self._sync_ollama_config()

        # App im eigenen Prozess starten; Datenbasis via Env isoliert.
        import os
        env = dict(os.environ)
        env["BACH_NOTESPACE_HOME"] = str(data_dir)
        env["PYTHONIOENCODING"] = "utf-8"
        try:
            subprocess.Popen([sys.executable, str(main_py)], env=env, cwd=str(self._module_dir()))
            return True, f"[NOTESPACE] GUI gestartet (Daten: {data_dir})"
        except Exception as e:
            return False, f"[NOTESPACE] Start fehlgeschlagen: {e}"

    def _cli(self, args: List[str], dry_run: bool = False) -> Tuple[bool, str]:
        return False, ("[NOTESPACE] Headless-CLI-Query ist Phase 2 und noch nicht "
                       "implementiert.\nAktuell verfuegbar: bach notespace gui")
