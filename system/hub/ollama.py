# SPDX-License-Identifier: MIT
"""
Ollama Handler - Lokale AI-Interaktion
======================================

--ollama status           Ollama-Server Status pruefen
--ollama ask "prompt"     Anfrage an Ollama senden
    --model=NAME          Modell waehlen (default: llama3.2)
--ollama models           Verfuegbare Modelle auflisten
--ollama embed "text"     Embedding erstellen
--ollama ps               Im Speicher gehaltene Modelle auflisten
--ollama unload NAME      Modell racefrei freigeben (ueber Waechter-Modul)

Refactored: 2026-01-23 - Nutzt jetzt tools/ollama_client.py
"""
import sys
import sqlite3
from datetime import datetime
from pathlib import Path
from .base import BaseHandler

# Client importieren
TOOLS_PATH = Path(__file__).parent.parent / "tools" / "ollama"
sys.path.insert(0, str(TOOLS_PATH))
try:
    from ollama_client import OllamaClient, OllamaModel
except ImportError:
    OllamaClient = None
    OllamaModel = None


def _load_unload_guard():
    """Laedt das Waechter-Modul memory_pressure_unload_guard (Sensor/Aktor).

    Reine Fachlogik liegt in system/tools/maintenance/; hier nur Adapter.
    Gibt None zurueck, wenn das Modul nicht ladbar ist.
    """
    root = Path(__file__).resolve().parents[1]  # .../system
    try:
        from tools.maintenance import memory_pressure_unload_guard as guard
        return guard
    except Exception:
        pass
    try:
        import importlib.util

        guard_path = root / "tools" / "maintenance" / "memory_pressure_unload_guard.py"
        if not guard_path.is_file():
            return None
        spec = importlib.util.spec_from_file_location(
            "bach_memory_pressure_unload_guard", guard_path
        )
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        sys.modules.setdefault("bach_memory_pressure_unload_guard", module)
        spec.loader.exec_module(module)
        return module
    except Exception:
        return None


class OllamaHandler(BaseHandler):
    """Handler fuer --ollama Operationen"""
    
    DEFAULT_MODEL = "llama3.2"
    
    def __init__(self, base_path: Path):
        super().__init__(base_path)
        self._client = None
    
    @property
    def client(self) -> 'OllamaClient':
        """Lazy-Loading des OllamaClient."""
        if self._client is None:
            if OllamaClient:
                self._client = OllamaClient()
            else:
                raise ImportError("OllamaClient nicht verfuegbar")
        return self._client
    
    @property
    def profile_name(self) -> str:
        return "ollama"
    
    @property
    def target_file(self) -> Path:
        return self.base_path / "data" / "ollama_config.json"
    
    def get_operations(self) -> dict:
        return {
            "status": "Ollama-Server Status pruefen",
            "ask": "Anfrage an Ollama senden",
            "models": "Verfuegbare Modelle auflisten",
            "embed": "Embedding erstellen",
            "ps": "Im Speicher gehaltene Modelle auflisten",
            "unload": "Modell aus dem Speicher freigeben (racefrei ueber Waechter)"
        }
    
    def handle(self, operation: str, args: list, dry_run: bool = False) -> tuple:
        if operation == "status":
            return self._status()
        elif operation == "models":
            return self._models()
        elif operation == "ask":
            return self._ask(args, dry_run)
        elif operation == "embed":
            return self._embed(args, dry_run)
        elif operation == "ps":
            return self._ps(args)
        elif operation == "unload":
            return self._unload(args, dry_run)
        else:
            return self._status()
    
    def _ps(self, args: list) -> tuple:
        """Sensor: laufende Modelle ueber den Waechter abfragen."""
        guard = _load_unload_guard()
        if guard is None:
            return (False, "Waechter-Modul memory_pressure_unload_guard nicht verfuegbar")
        try:
            running = guard.list_running()
        except Exception as exc:
            return (False, f"Ollama /api/ps nicht abfragbar: {exc}")
        lines = ["[OLLAMA] Im Speicher gehaltene Modelle", "=" * 50]
        if not running:
            lines.append("(keine Modelle geladen)")
        for entry in running:
            lines.append(f"- {entry.get('name')}  vram={entry.get('size_vram')} expires={entry.get('expires_at')}")
        return (True, "\n".join(lines))

    def _unload(self, args: list, dry_run: bool = False) -> tuple:
        """Aktor: Modell freigeben, ohne den OllamaClient zu bemuehen."""
        model = args[0] if args else ""
        if dry_run:
            return (True, f"[DRY-RUN] wuerde Modell freigeben: {model or '(ohne Namen)'}")
        guard = _load_unload_guard()
        if guard is None:
            return (False, "Waechter-Modul memory_pressure_unload_guard nicht verfuegbar")
        try:
            report = guard.unload(model)
        except ValueError as exc:
            return (False, str(exc))
        except Exception as exc:
            return (False, f"Unload fehlgeschlagen: {exc}")
        if report.get("unloaded"):
            return (True, f"Modell {report.get('model')} entladen (verifiziert in {report.get('elapsed_s')}s)")
        return (False, f"Modell {report.get('model')} nach Timeout noch geladen; {report.get('warning') or report.get('done_reason')}")

    def _status(self) -> tuple:
        """Ollama-Server Status pruefen."""
        results = []
        results.append("")
        results.append("[OLLAMA] Server Status")
        results.append("=" * 50)
        
        try:
            status = self.client.get_status()
            if status["online"]:
                results.append(f"  Status: ONLINE")
                results.append(f"  Version: {status['version']}")
                results.append(f"  URL: {self.client.base_url}")
            else:
                results.append(f"  Status: OFFLINE")
                if status['error']:
                    results.append(f"  Fehler: {status['error']}")
        except ImportError:
            results.append("  [FEHLER] OllamaClient nicht verfuegbar")
            results.append("  Fehlende Datei: tools/ollama_client.py")
        except Exception as e:
            results.append(f"  Status: NICHT ERREICHBAR ({e})")
        
        results.append("")
        results.append("  Befehle:")
        results.append("    bach ollama ask 'prompt'    - Anfrage senden")
        results.append("    bach ollama models          - Modelle auflisten")
        
        return True, "\n".join(results)
    
    def _models(self) -> tuple:
        """Verfuegbare Modelle auflisten."""
        results = []
        results.append("")
        results.append("[OLLAMA] Verfuegbare Modelle")
        results.append("=" * 50)
        
        try:
            models = self.client.list_models()
            if models:
                for m in models:
                    results.append(f"  - {m.name} ({m.size_gb:.1f} GB)")
            else:
                results.append("  Keine Modelle installiert.")
                results.append("  -> ollama pull llama3.2")
        except ImportError:
            results.append("  [FEHLER] OllamaClient nicht verfuegbar")
        except Exception as e:
            results.append(f"  Fehler: {e}")
        
        return True, "\n".join(results)
    
    def _telemetry_model_call(self, model: str, success: bool) -> None:
        """OPS-TELEM-001: Modell-Aufruf zaehlen (low-cardinality, fail-silent)."""
        try:
            from core.telemetry import increment
            increment("model_calls", outcome="ok" if success else "error",
                      model=model)
        except Exception:
            pass

    def _ask(self, args: list, dry_run: bool = False) -> tuple:
        """Anfrage an Ollama senden."""
        # Model aus args extrahieren
        model = self.DEFAULT_MODEL
        prompt_parts = []
        
        for arg in args:
            if arg.startswith("--model="):
                model = arg.split("=", 1)[1]
            elif not arg.startswith("--"):
                prompt_parts.append(arg)
        
        prompt = " ".join(prompt_parts)
        
        if not prompt:
            return False, "Fehler: Kein Prompt angegeben\nUsage: bach ollama ask 'Dein Prompt hier'"
        
        if dry_run:
            return True, f"[DRY-RUN] Wuerde senden: '{prompt}' an Modell '{model}'"
        
        results = []
        results.append("")
        results.append(f"[OLLAMA] Anfrage an {model}")
        results.append("=" * 50)
        results.append(f"  Prompt: {prompt[:50]}...")
        results.append("")
        
        try:
            response = self.client.generate(prompt, model=model)
            self._telemetry_model_call(model, bool(getattr(response, "success", False)))
            if response.success:
                results.append("  Antwort:")
                results.append("-" * 50)
                results.append(response.text)
                if response.duration_seconds > 0:
                    results.append(f"\n  [Dauer: {response.duration_seconds:.1f}s | Tokens: {response.total_tokens} ({response.prompt_tokens} in / {response.completion_tokens} out)]")
                
                # Token-Monitoring (P3 Task 298)
                try:
                    import token_monitor
                    token_monitor.log_ollama_usage(response.prompt_tokens, response.completion_tokens)
                except Exception as e:
                    results.append(f"  [MONITOR] Fehler beim Token-Logging: {e}")
            else:
                results.append(f"  Fehler: {response.error}")
        except ImportError:
            results.append("  [FEHLER] OllamaClient nicht verfuegbar")
        except Exception as e:
            self._telemetry_model_call(model, False)
            results.append(f"  Fehler: {e}")
        
        return True, "\n".join(results)
    
    def _embed(self, args: list, dry_run: bool = False) -> tuple:
        """Embedding erstellen."""
        text = " ".join([a for a in args if not a.startswith("--")])
        
        if not text:
            return False, "Fehler: Kein Text angegeben\nUsage: bach ollama embed 'Dein Text'"
        
        if dry_run:
            return True, f"[DRY-RUN] Wuerde Embedding erstellen fuer: '{text[:50]}...'"
        
        results = []
        results.append("")
        results.append("[OLLAMA] Embedding")
        results.append("=" * 50)
        
        try:
            success, embedding = self.client.embed(text)
            if success:
                results.append(f"  Dimensionen: {len(embedding)}")
                results.append(f"  Erste 5 Werte: {embedding[:5]}")
            else:
                results.append("  Fehler beim Erstellen des Embeddings")
        except ImportError:
            results.append("  [FEHLER] OllamaClient nicht verfuegbar")
        except Exception as e:
            results.append(f"  Fehler: {e}")
        
        return True, "\n".join(results)
