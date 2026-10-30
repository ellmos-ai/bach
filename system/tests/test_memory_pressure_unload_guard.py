#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Struktur-/Syntaxpruefung fuer den racefreien Modell-Unload-Waechter (Task #2419).

Der Test importiert das Waechter-Modul direkt ueber seinen Dateipfad
(``importlib.util``). Damit wird die komplette Moduldefinition ausgefuehrt —
ein Syntaxfehler schlaegt sofort fehl. Zusaetzlich wird die Syntax des
Hub-Adapters ``host_inference_gate.py`` per ``compile()`` geprueft, ohne ihn zu
importieren (er braucht ``psutil`` und den ``hub``-Paketkontext).

Bewusst ohne ``ast`` und ohne Netz-/Ollama-Zugriff: reine Offline-Pruefung.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SYSTEM_DIR = Path(__file__).resolve().parents[1]
GUARD_PATH = SYSTEM_DIR / "tools" / "maintenance" / "memory_pressure_unload_guard.py"
GATE_PATH = SYSTEM_DIR / "hub" / "_services" / "chat" / "host_inference_gate.py"

EXPECTED_API = (
    "__version__",
    "DEFAULT_BASE_URL",
    "DEFAULT_REQUEST_TIMEOUT_S",
    "DEFAULT_POLL_S",
    "DEFAULT_UNLOAD_TIMEOUT_S",
    "OllamaUnavailable",
    "OllamaResponseError",
    "list_running",
    "loaded_entries",
    "is_unloaded",
    "wait_until_unloaded",
    "unload",
)


def _load_guard_module():
    """Importiert das Waechter-Modul dateipfadbasiert und liefert es zurueck."""
    assert GUARD_PATH.is_file(), f"Waechter-Modul fehlt: {GUARD_PATH}"
    module_name = "memory_pressure_unload_guard_under_test"
    spec = importlib.util.spec_from_file_location(module_name, GUARD_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(module_name, None)
    return module


def test_guard_module_imports_and_exposes_api():
    """Modul laesst sich ausfuehren und bietet die dokumentierte API."""
    module = _load_guard_module()
    missing = [name for name in EXPECTED_API if not hasattr(module, name)]
    assert not missing, f"fehlende API-Symbole: {missing}"


def test_guard_defaults_are_sane():
    """Die Defaults bleiben in plausiblen Grenzen."""
    module = _load_guard_module()
    assert module.__version__ == "1.0.0"
    assert isinstance(module.DEFAULT_BASE_URL, str)
    assert module.DEFAULT_BASE_URL.startswith("http")
    assert 0 < module.DEFAULT_POLL_S <= 5.0
    assert 0 < module.DEFAULT_UNLOAD_TIMEOUT_S <= 300.0
    assert 0 < module.DEFAULT_REQUEST_TIMEOUT_S <= 120.0


def test_guard_normalize_digest_and_matching():
    """Digest-Normalisierung und Eintrags-Matching arbeiten ohne Netz."""
    module = _load_guard_module()

    normalize = getattr(module, "_normalize_digest")
    assert normalize(None) is None
    assert normalize("") is None
    assert normalize("ABC123") == normalize("abc123")

    matches = getattr(module, "_matches")
    entry = {
        "name": "qwen3:8b",
        "model": "qwen3:8b",
        "digest": "abc123",
        "size_vram": 1024,
    }
    assert matches(entry, "qwen3:8b") is True
    assert matches(entry, "qwen3:8b", "abc123") is True
    # Konservative OR-Semantik (Doc: Name **oder** Digest): ein Namens-Treffer
    # bleibt gueltig, auch wenn der erwartete Digest abweicht. Andernfalls
    # wuerde is_unloaded() ein laufendes Modell als entladen melden.
    assert matches(entry, "qwen3:8b", "def456") is True
    # Ein Digest-Treffer allein genuegt ebenfalls, auch bei fremdem Namen.
    assert matches(entry, None, "abc123") is True
    assert matches(entry, "llama3:8b", "abc123") is True
    # Weder Name noch Digest passen.
    assert matches(entry, None, "def456") is False
    assert matches(entry, "llama3:8b") is False


def test_gate_module_syntax_is_valid():
    """Der Hub-Adapter bleibt syntaktisch fehlerfrei (ohne Import)."""
    assert GATE_PATH.is_file(), f"Hub-Adapter fehlt: {GATE_PATH}"
    source = GATE_PATH.read_text(encoding="utf-8")
    compile(source, str(GATE_PATH), "exec")
