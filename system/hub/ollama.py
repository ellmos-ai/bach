# SPDX-License-Identifier: MIT
"""
Ollama Handler - Lokale AI-Interaktion
======================================

--ollama status           Ollama-Server Status pruefen
--ollama ask "prompt"     Anfrage an Ollama senden
    --model=NAME          Modell waehlen (default: llama3.2)
--ollama models           Verfuegbare Modelle auflisten
--ollama embed "text"     Embedding erstellen

Refactored: 2026-01-23 - Nutzt jetzt tools/ollama_client.py
"""
import json
import os
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
            "set_num_ctx": "num_ctx eines Modells setzen",
            "recommend_num_ctx": "num_ctx-Empfehlung fuer ein Modell ermitteln"
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
        elif operation == "set_num_ctx":
            return self._set_num_ctx(args, dry_run)
        elif operation == "recommend_num_ctx":
            return self._recommend_num_ctx(args, dry_run)
        else:
            return self._status()
    
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
            config = self._load_num_ctx_config()
            models_config = config.get("models")
            if not isinstance(models_config, dict):
                models_config = {}
            model_entry = models_config.get(model)
            num_ctx = model_entry.get("num_ctx") if isinstance(model_entry, dict) else None
            if not (type(num_ctx) is int and num_ctx > 0):
                recommended = model_entry.get("num_ctx_recommended") if isinstance(model_entry, dict) else None
                num_ctx = recommended if type(recommended) is int and recommended > 0 else None
            if num_ctx is None:
                env_num_ctx = os.environ.get("OLLAMA_NUM_CTX") or os.environ.get("OLLAMA_NUM_CFG")
                if env_num_ctx:
                    try:
                        num_ctx = int(env_num_ctx)
                    except (TypeError, ValueError):
                        num_ctx = None
            if num_ctx is None:
                response = self.client.generate(prompt, model=model)
            else:
                response = self.client.generate(prompt, model=model, num_ctx=num_ctx)
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
    
    def _load_num_ctx_config(self) -> dict:
        """Laedt die num_ctx-Konfiguration (ollama_config.json)."""
        try:
            with open(self.target_file, "r", encoding="utf-8") as file:
                config = json.load(file)
        except (OSError, ValueError):
            return {}
        if not isinstance(config, dict):
            return {}
        return config

    def set_num_ctx(self, model: str, num_ctx: int = None, num_ctx_recommended: int = None, num_ctx_advice: int = None) -> tuple:
        """Setzt num_ctx / num_ctx_recommended / num_ctx_advice fuer ein Modell in der Config."""
        if not model:
            return False, "Fehler: Ollama set_num_ctx benoetigt ein Modell"
        config = self._load_num_ctx_config()
        models = config.setdefault("models", {})
        entry = models.setdefault(model, {})
        if num_ctx is not None:
            entry["num_ctx"] = num_ctx
        if num_ctx_recommended is not None:
            entry["num_ctx_recommended"] = num_ctx_recommended
        if num_ctx_advice is not None:
            entry["num_ctx_advice"] = num_ctx_advice
        self.target_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.target_file, "w", encoding="utf-8") as file:
            json.dump(config, file, indent=2, ensure_ascii=False)
        details = []
        if num_ctx is not None:
            details.append(f"num_ctx={num_ctx}")
        if num_ctx_recommended is not None:
            details.append(f"num_ctx_recommended={num_ctx_recommended}")
        if num_ctx_advice is not None:
            details.append(f"num_ctx_advice={num_ctx_advice}")
        return True, "Ollama num_ctx fuer '{}' gespeichert: {}".format(model, ", ".join(details))

    def _recommend_num_ctx(self, args: list, dry_run: bool = False) -> tuple:
        """Ermittelt eine num_ctx-Empfehlung fuer ein Modell und legt sie ab.

        Vermessen werden Modellgroesse und freier Arbeitsspeicher; ein LLM-Rat
        via --num-ctx-advice gewinnt ueber die Vermessung.
        """
        if not args:
            return False, ("Fehler: Ollama recommend_num_ctx benoetigt ein Modell\n"
                           "Usage: ollama recommend_num_ctx <modell> [--num-ctx-advice 16384]")
        model = args[0]
        advice = None
        rest = args[1:]
        index = 0
        while index < len(rest):
            arg = rest[index]
            if arg == "--num-ctx-advice":
                index += 1
                if index >= len(rest):
                    return False, "Fehler: Ollama --num-ctx-advice benoetigt einen Wert"
                raw = rest[index]
            elif arg.startswith("--num-ctx-advice="):
                raw = arg.split("=", 1)[1]
            else:
                return False, "Fehler: Ollama recommend_num_ctx kennt das Argument '{}' nicht".format(arg)
            try:
                advice = int(raw)
            except (TypeError, ValueError):
                return False, "Fehler: Ollama num_ctx_advice muss eine ganze Zahl sein"
            if not 512 <= advice <= 262144:
                return False, "Fehler: Ollama num_ctx_advice muss zwischen 512 und 262144 liegen"
            index += 1
        try:
            client = self.client
        except ImportError:
            return False, "Fehler: OllamaClient nicht verfuegbar"
        try:
            import psutil
        except ImportError:
            return False, "Fehler: psutil nicht verfuegbar"
        memory = psutil.virtual_memory()
        total_bytes = int(memory.total)
        available_bytes = int(memory.available)
        size_bytes = None
        try:
            entries = client.list_models()
            for entry in entries:
                if getattr(entry, "name", None) == model:
                    size_bytes = int(float(getattr(entry, "size_gb", 0.0)) * 1024 ** 3)
                    break
        except Exception as e:
            return False, "Fehler: Modellliste nicht lesbar ({})".format(e)
        if size_bytes is None:
            return False, "Fehler: Modell '{}' nicht gefunden".format(model)
        recommendation = None
        for candidate in (8192, 16384, 32768):
            required_bytes = size_bytes + candidate * 64 * 1024 + int(1.5 * 1024 ** 3)
            if available_bytes - required_bytes < 4 * 1024 ** 3:
                break
            recommendation = candidate
        if advice is not None:
            recommendation = advice
        if recommendation is None:
            return False, ("Fehler: Kein num_ctx-Kandidat passt in den freien Arbeitsspeicher "
                           "(verfuegbar: {:.1f} GiB, Modell: {:.1f} GiB)".format(
                               available_bytes / 1024.0 ** 3, size_bytes / 1024.0 ** 3))
        report = ("num_ctx-Empfehlung fuer '{}': {} Token. Arbeitsspeicher: {:.1f} GiB total, "
                  "{:.1f} GiB verfuegbar; Modellgroesse: {:.1f} GiB. Uebergabeschwelle: {} Token "
                  "(~80 % des Fensters).").format(
                      model, recommendation, total_bytes / 1024.0 ** 3,
                      available_bytes / 1024.0 ** 3, size_bytes / 1024.0 ** 3,
                      int(recommendation * 0.8))
        if advice is not None:
            report += " LLM-Rat (--num-ctx-advice={}) gewinnt ueber die Vermessung.".format(advice)
        if dry_run:
            return True, "[DRY-RUN] " + report
        _, saved = self.set_num_ctx(model, num_ctx_recommended=recommendation, num_ctx_advice=advice)
        return True, report + " " + saved

    def _set_num_ctx(self, args: list, dry_run: bool = False) -> tuple:
        """CLI: ollama set_num_ctx <modell> [--num-ctx N] [--num-ctx-recommended N]."""
        if not args:
            return False, (
                "Fehler: Ollama set_num_ctx benoetigt ein Modell\n"
                "Usage: ollama set_num_ctx <modell> [--num-ctx 8192] [--num-ctx-recommended 16384]"
            )
        model = args[0]
        num_ctx = None
        num_ctx_recommended = None
        for arg in args[1:]:
            if arg.startswith("--num-ctx-recommended="):
                try:
                    num_ctx_recommended = int(arg.split("=", 1)[1])
                except (TypeError, ValueError):
                    return False, "Fehler: Ollama num_ctx_recommended muss eine ganze Zahl sein"
            elif arg.startswith("--num-ctx="):
                try:
                    num_ctx = int(arg.split("=", 1)[1])
                except (TypeError, ValueError):
                    return False, "Fehler: Ollama num_ctx muss eine ganze Zahl sein"
        if num_ctx is None and num_ctx_recommended is None:
            return False, (
                "Fehler: Ollama set_num_ctx benoetigt --num-ctx oder --num-ctx-recommended\n"
                "Usage: ollama set_num_ctx <modell> [--num-ctx 8192] [--num-ctx-recommended 16384]"
            )
        for value in (num_ctx, num_ctx_recommended):
            if value is not None and not (512 <= value <= 262144):
                return False, "Fehler: Ollama num_ctx muss zwischen 512 und 262144 liegen"
        if dry_run:
            details = []
            if num_ctx is not None:
                details.append(f"num_ctx={num_ctx}")
            if num_ctx_recommended is not None:
                details.append(f"num_ctx_recommended={num_ctx_recommended}")
            return True, "[DRY-RUN] Wuerde Ollama num_ctx fuer '{}' setzen: {}".format(model, ", ".join(details))
        return self.set_num_ctx(model, num_ctx=num_ctx, num_ctx_recommended=num_ctx_recommended)

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
