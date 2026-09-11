#!/usr/bin/env python3
"""
BACH Telegram Chat Runtime
============================

Interaktiver Telegram-Bot mit pluggbarem LLM-Backend.
Nutzt BACH Chat-Runtime für Tool-Use, Sicherheit, Kontext.

Kann mit jedem Backend betrieben werden:
  - Ollama (lokal)
  - OpenAI / OpenAI-kompatibel
  - Anthropic Claude
  - Claude Code CLI / Codex CLI

Konfiguration:
  ~/.config/bach/telegram_chat.json oder Umgebungsvariablen.

Start:
  python -m hub._services.chat.telegram_chat
  # oder direkt:
  python telegram_chat.py
"""
import asyncio
import ipaddress
import json
import logging
import os
import sys
from typing import Any, Dict, List, Optional

os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
import tempfile
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# BACH system path: resolve from this file's location (system/hub/_services/chat/)
_here = Path(__file__).resolve()
_system_dir = str(_here.parents[3])
_root_dir = str(_here.parents[4])
for _p in (_system_dir, _root_dir):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    from telegram import Update
    from telegram.ext import (Application, CommandHandler, MessageHandler,
                              filters, ContextTypes)
except ImportError:
    print("python-telegram-bot nicht installiert: pip install python-telegram-bot")
    sys.exit(1)

try:
    import httpx
except ImportError:
    print("httpx nicht installiert: pip install httpx")
    sys.exit(1)

# BACH imports
try:
    import bach_api
    _memory = bach_api.memory
    _injector = bach_api.injector
    _injector.set_mode("api")
    _bach_app = bach_api.get_app()
    HAS_BACH = True
    print("BACH API geladen")
except Exception as e:
    HAS_BACH = False
    _bach_app = None
    _memory = None
    _injector = None
    print(f"BACH API nicht verfügbar: {e}")

# Chat Runtime + Backend
from hub._services.llm.model_backend import (
    CLIBackend,
    OllamaBackend,
    backend_identifier,
    create_backend,
)
from hub._services.chat.chat_runtime import (
    ChatRuntime,
    ComputeLocked,
    FailedAnswer,
    RUNTIME_BACH_DB,
)
from hub._services.chat.session_store import SQLiteChatSessionStore
from hub._services.chat.slots_config import (
    DEFAULT_CORE_SLOTS,
    DEFAULT_ROLE_PROMPTS,
    DEFAULT_SYSTEM_PROMPT,
    add_worker,
    compose_worker_prompt,
    get_activity_history,
    get_prompt_templates,
    get_slot,
    list_workers,
    load_slots_config,
    record_activity,
    remove_worker,
    reset_prompt_template,
    save_slots_config,
    update_prompt_template,
    update_slot,
)

# Compute Lock (optional — graceful if not available)
try:
    from hub.compute_lock import (
        DEFAULT_CHECK_SCRIPT, DEFAULT_LOCK_PATH,
        check_compute_active, pause_compute_jobs, resume_compute_jobs,
        start_resume_monitor, recover_paused_jobs, format_status_message,
        write_session_flag, update_session_flag, delete_session_flag,
        set_inferenz_active, get_effective_keep_alive_seconds,
        get_fackel_preference, set_fackel_preference,
    )
    HAS_COMPUTE_LOCK = True
except ImportError:
    HAS_COMPUTE_LOCK = False
    DEFAULT_LOCK_PATH = "~/.memwatchdog/compute_active.lock"
    DEFAULT_CHECK_SCRIPT = ""
    def get_fackel_preference():
        return "compute"
    def set_fackel_preference(pref):
        return pref

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
log = logging.getLogger("bach.telegram_chat")


# --- Konfiguration ---

def load_config() -> dict:
    config_path = os.path.expanduser("~/.config/bach/telegram_chat.json")
    config = {}

    if os.path.exists(config_path):
        with open(config_path) as f:
            config = json.load(f)

    config.setdefault("bot_token", "")
    config.setdefault("owner_id", "")
    config.setdefault("backend", {
        "type": "ollama",
        "base_url": "http://localhost:11434",
        "default_model": "qwen3.8:27b-mlx",
    })

    if not config["bot_token"]:
        config["bot_token"] = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not config["bot_token"]:
        tf = os.path.expanduser("~/.credentials/telegram_bot_token")
        if os.path.exists(tf):
            config["bot_token"] = open(tf, encoding="utf-8").read().strip()

    if not config["owner_id"]:
        config["owner_id"] = os.environ.get("TELEGRAM_OWNER_ID", "")
    if not config["owner_id"]:
        of = os.path.expanduser("~/.credentials/telegram_owner_id")
        if os.path.exists(of):
            config["owner_id"] = open(of, encoding="utf-8").read().strip()

    env_model = os.environ.get("OLLAMA_MODEL")
    if env_model:
        config["backend"]["default_model"] = env_model
    env_url = os.environ.get("OLLAMA_URL")
    if env_url:
        config["backend"]["base_url"] = env_url

    # Compute Lock config (default: disabled for users without memwatchdog)
    config.setdefault("compute_lock", {
        "enabled": False,
        "lock_path": DEFAULT_LOCK_PATH,
        "check_script": DEFAULT_CHECK_SCRIPT,
        "pause_method": "sigstop",
    })

    return config


CONFIG = load_config()
BOT_TOKEN = CONFIG["bot_token"]
OWNER_ID = CONFIG["owner_id"]

# Backend + Runtime initialisieren
backend = create_backend(CONFIG["backend"])

try:
    from hub.bach_paths import DATA_DIR
    system_file = str(DATA_DIR / "system_prompt_buddha.txt")
except Exception:
    system_file = os.path.join(os.environ.get("PYTHONPATH", "."), "data", "system_prompt_buddha.txt")
if os.path.exists(system_file):
    system_prompt = open(system_file, encoding="utf-8").read().strip()
else:
    system_prompt = "Du bist ein lokaler BACH Chat-Assistent. Antworte auf Deutsch, präzise und klar."

from hub._services.chat.session_store import SQLiteChatSessionStore

session_store = None
try:
    from hub.bach_paths import BACH_DB
    if BACH_DB.exists():
        session_store = SQLiteChatSessionStore(BACH_DB)
        log.info("Chat-SessionStore an %s gebunden", BACH_DB)
except Exception as e:
    log.warning("Chat-SessionStore konnte nicht initialisiert werden: %s", e)

runtime = ChatRuntime(
    backend=backend,
    system_prompt=system_prompt,
    bach_app=_bach_app if HAS_BACH else None,
    memory_fn=_memory if HAS_BACH else None,
    injector=_injector if HAS_BACH else None,
    session_store=session_store,
)

_global_defaults = {
    "mode": "safe",
    "think": True,
    "model": "",
    "max_tool_rounds": 12,
}
_runtime_state_lock = threading.RLock()

# Pending actions for compute lock confirmations (keyed by chat_id)
# Format: {chat_id: {"kind": "compute_pause_for_ollama", "status": dict,
#                     "text": str, "timestamp": float}}
_pending_actions: dict = {}
_PENDING_TTL = 120  # seconds before a pending action expires

_orig_get_session = runtime.get_session

def _patched_get_session(chat_id: str):
    with _runtime_state_lock:
        session = _orig_get_session(chat_id)
        if len(session.messages) == 0:
            if _global_defaults.get("mode"):
                session.mode = _global_defaults["mode"]
            if _global_defaults.get("model"):
                session.model = _global_defaults["model"]
            session.think = _global_defaults.get("think", True)
            try:
                _apply_slot_to_session(chat_id, session)
            except Exception as e:
                log.debug("Konnte Slot nicht auf Session anwenden: %s", e)
        return session

runtime.get_session = _patched_get_session


# --- Telegram-Handler ---

WELCOME = (
    "Hallo! Ich bin dein BACH Chat-Assistent.\n"
    f"Backend: {CONFIG['backend'].get('type', 'ollama')} | "
    f"Modell: {backend.get_default_model()}\n\n"
    "Modi & Modelle:\n"
    "  /mode [safe|full] — Sicherheitsmodus\n"
    "  /think — Denkmodus an (gründlich)\n"
    "  /nothink — Denkmodus aus (schnell)\n"
    "  /model <name> — Modell wechseln\n"
    "  /backend [ollama|claude|openai] — Backend wechseln\n"
    "  /maxrounds [0|5|10|20] — Max Tool-Runden (0=unbegrenzt)\n"
    "  /settings — Alle Einstellungen\n\n"
    "Chat:\n"
    "  /clear — Konversation zurücksetzen\n\n"
    + ("BACH Memory:\n"
       "  /remember <text> — Merken\n"
       "  /recall <suche> — Suchen\n"
       "  /facts — Gespeicherte Fakten\n\n"
       "BACH System:\n"
       "  /bach <befehl> — BACH-Befehl\n"
       "  /task <text> — Aufgabe anlegen\n"
       "  /tasks — Offene Aufgaben\n"
       "  /status — System-Status\n\n"
       if HAS_BACH else "")
    + "Sicherheit: Safe-Modus (Standard) = nur lesen\n"
    "  /mode full bestätigt = auch schreiben/ausführen"
)


def _owner_check(update: Update) -> bool:
    if not OWNER_ID:
        return True
    return str(update.effective_chat.id) == OWNER_ID


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(WELCOME)


async def cmd_clear(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    archived_id = runtime.clear_session(chat_id, archive_reason="Telegram /clear")
    if archived_id:
        await update.message.reply_text("Konversation archiviert und neue Session gestartet.")
    else:
        await update.message.reply_text("Konversation zurückgesetzt.")


async def cmd_think(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    runtime.get_session(str(update.effective_chat.id)).think = True
    await update.message.reply_text("Denkmodus AN")


async def cmd_nothink(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    runtime.get_session(str(update.effective_chat.id)).think = False
    await update.message.reply_text("Denkmodus AUS")


async def cmd_mode(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    session = runtime.get_session(str(update.effective_chat.id))
    args = ctx.args or []
    if not args:
        await update.message.reply_text(
            f"Modus: {session.mode}\n\n"
            "/mode safe — Nur lesen\n"
            "/mode full bestätigt — Alles"
        )
        return
    m = args[0].lower()
    if m == "full":
        if len(args) < 2 or args[1].lower() != "bestätigt":
            await update.message.reply_text(
                "Full-Modus erlaubt Shell-Befehle und Dateischreiben.\n"
                "Aktivieren: /mode full bestätigt"
            )
            return
        session.mode = "full"
        await update.message.reply_text("Full-Modus aktiviert.")
    elif m == "safe":
        session.mode = "safe"
        await update.message.reply_text("Safe-Modus aktiviert.")
    else:
        await update.message.reply_text("Nutze: safe oder full")


async def cmd_model(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    session = runtime.get_session(str(update.effective_chat.id))
    args = ctx.args or []
    if not args:
        try:
            models = backend.list_models()
            backend_type = type(runtime.backend).__name__
            await update.message.reply_text(
                f"Aktiv: {session.model}\n"
                f"Backend: {backend_type}\n\n"
                f"Verfügbar:\n"
                + "\n".join(f"  {m}" for m in models)
                + "\n\nWechseln: /model <name>"
            )
        except Exception as e:
            await update.message.reply_text(f"Fehler: {e}")
        return
    session.model = args[0]
    await update.message.reply_text(f"Modell: {args[0]}")


BACKEND_PRESETS = {
    "ollama": {
        "type": "ollama",
        "base_url": os.environ.get("OLLAMA_URL", "http://localhost:11434"),
        "default_model": os.environ.get("OLLAMA_MODEL", "qwen3.8:27b-mlx"),
        "method": "api",
        "description": "Lokales Ollama (Qwen, Llama, etc.)",
    },
    "ollama-cloud": {
        "type": "ollama",
        "base_url": os.environ.get("OLLAMA_URL", "http://localhost:11434"),
        "default_model": os.environ.get("OLLAMA_CLOUD_MODEL", "kimi-k3:cloud"),
        "method": "api",
        "description": "Ollama Cloud Proxies (:cloud Modelle wie Kimi, GLM)",
    },
    "lmstudio": {
        "type": "lmstudio",
        "base_url": os.environ.get("LM_STUDIO_URL", "http://localhost:1234/v1"),
        "default_model": os.environ.get("LM_STUDIO_MODEL", "auto"),
        "method": "api",
        "description": "LM Studio (lokal, Port 1234)",
    },
    "hermes": {
        "type": "hermes",
        "base_url": os.environ.get("HERMES_URL", "https://openrouter.ai/api/v1"),
        "default_model": os.environ.get("HERMES_MODEL", "nousresearch/hermes-3-llama-3.1-8b"),
        "method": "api",
        "description": "Nous Hermes Agent (OpenRouter / Lokal)",
    },
    "claude": {
        "type": "claude-cli",
        "default_model": "sonnet",
        "method": "cli",
        "description": "Claude Code CLI (--continue Session)",
    },
    "claude-api": {
        "type": "claude-api",
        "default_model": "claude-sonnet-4-6",
        "method": "api",
        "description": "Anthropic API (braucht Key)",
    },
    "codex": {
        "type": "codex-cli",
        "default_model": "o4-mini",
        "method": "cli",
        "description": "Codex CLI (GPT-Modelle)",
    },
    "openai": {
        "type": "openai",
        "default_model": "gpt-4o",
        "method": "api",
        "description": "OpenAI API (braucht Key)",
    },
}


def _check_cli_available(name: str) -> str:
    import shutil
    if name == "claude":
        return "vorhanden" if shutil.which("claude") else "nicht gefunden"
    elif name == "codex":
        return "vorhanden" if shutil.which("codex") else "nicht gefunden"
    return ""


_API_KEY_SOURCES = {
    "claude-api": ("ANTHROPIC_API_KEY", "anthropic_api_key"),
    "openai": ("OPENAI_API_KEY", "openai_api_key"),
}


def _load_api_key(name: str) -> str:
    source = _API_KEY_SOURCES.get(name)
    if source is None:
        return ""

    env_var, file_name = source
    configured = str(os.environ.get(env_var) or "").strip()
    if configured:
        return configured

    key_file = Path(os.path.expanduser(f"~/.credentials/{file_name}"))
    try:
        return key_file.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return ""


def _check_api_key(name: str) -> str:
    if name not in _API_KEY_SOURCES:
        return ""
    return "Key vorhanden" if _load_api_key(name) else "Key fehlt"


_backends_pool: dict[str, Any] = {"ollama": backend}
_backends_pool_lock = threading.Lock()


def _get_or_create_backend(backend_type: str, model: str = "") -> Any:
    backend_key = (backend_type or "ollama").lower().strip()
    cache_key = f"{backend_key}:{model}" if model else backend_key

    with _backends_pool_lock:
        if cache_key in _backends_pool:
            return _backends_pool[cache_key]
        if backend_key in _backends_pool and not model:
            return _backends_pool[backend_key]

        if backend_key in BACKEND_PRESETS:
            preset = BACKEND_PRESETS[backend_key].copy()
            if model:
                preset["default_model"] = model
            if preset["method"] == "api" and backend_key in ("claude-api", "openai"):
                api_key = _load_api_key(backend_key)
                if api_key:
                    preset["api_key"] = api_key
            config = {k: v for k, v in preset.items() if k not in ("method", "description")}
        else:
            config = {"type": backend_key}
            if model:
                config["default_model"] = model

        try:
            b = create_backend(config)
            _backends_pool[cache_key] = b
            return b
        except Exception as e:
            log.warning("Konnte Backend %s nicht erstellen (%s); Fallback auf runtime.backend", cache_key, e)
            return runtime.backend


def _resolve_slot_for_chat(chat_id: str) -> dict:
    try:
        cfg = load_slots_config()
    except Exception:
        cfg = {}
    slots = cfg.get("slots", {})
    str_id = str(chat_id)

    # 1. Check dynamic workers first
    for w in cfg.get("dynamic_workers", []):
        if w.get("id") == str_id or w.get("name") == str_id:
            return w
    if str_id.startswith("worker-"):
        try:
            for w in list_workers():
                if w.get("id") == str_id:
                    return w
        except Exception:
            pass
        return slots.get("buddha_always_on", DEFAULT_CORE_SLOTS["buddha_always_on"])

    # 2. Always-On / Idle Worker
    if str_id in ("idle-worker", "worker-always-on") or str_id.startswith("idle"):
        return slots.get("buddha_always_on", DEFAULT_CORE_SLOTS["buddha_always_on"])

    # 3. Messaging Connectors (Telegram, WhatsApp, Signal)
    if str_id.isdigit() or any(str_id.startswith(p) for p in ("tg:", "telegram", "wa:", "whatsapp", "signal:")):
        conn_slot = slots.get("buddha_connector", DEFAULT_CORE_SLOTS["buddha_connector"])
        if (str_id.isdigit() or str_id.startswith("tg:") or str_id == "telegram") and "providers" in conn_slot:
            tg_cfg = conn_slot.get("providers", {}).get("telegram")
            if tg_cfg:
                combined = dict(conn_slot)
                combined.update(tg_cfg)
                return combined
        return conn_slot

    # 4. Default to Buddha Chat (Interactive)
    return slots.get("buddha_chat", DEFAULT_CORE_SLOTS["buddha_chat"])


def _apply_slot_to_session(chat_id: str, session: Any) -> tuple[Any, str]:
    slot = _resolve_slot_for_chat(chat_id)
    slot_backend_type = slot.get("backend") or "ollama"
    slot_model = slot.get("model") or ""

    target_backend = _get_or_create_backend(slot_backend_type, slot_model)
    session.backend = target_backend
    if slot_model:
        session.model = slot_model
    elif not getattr(session, "model", ""):
        session.model = getattr(target_backend, "default_model", "")

    if "mode" in slot:
        session.mode = slot["mode"]
    if "think" in slot:
        session.think = bool(slot["think"])
    if "max_tool_rounds" in slot:
        session.max_tool_rounds = int(slot["max_tool_rounds"])
    if slot.get("system_prompt"):
        session.custom_system_prompt = slot["system_prompt"]

    return target_backend, session.model


async def cmd_backend(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    args = ctx.args or []
    current = type(runtime.backend).__name__
    current_cli = getattr(runtime.backend, "cli_name", "")

    if not args:
        lines = [f"Aktiv: {current}" + (f" ({current_cli})" if current_cli else "")]
        lines.append("")
        for name, preset in BACKEND_PRESETS.items():
            status = ""
            if preset["method"] == "cli":
                cli_name = preset["type"].replace("-cli", "")
                status = _check_cli_available(cli_name)
            elif preset["method"] == "api" and name in ("claude-api", "openai"):
                status = _check_api_key(name)
            status_str = f" [{status}]" if status else ""
            lines.append(f"  {name} — {preset['description']}{status_str}")
        lines.append("")
        lines.append("Wechseln: /backend <name> [model]")
        lines.append("Beispiele:")
        lines.append("  /backend claude opus")
        lines.append("  /backend codex o4-mini")
        lines.append("  /backend ollama qwen3.8:27b-mlx")
        lines.append("  /backend lmstudio")
        lines.append("  /backend hermes")
        await update.message.reply_text("\n".join(lines))
        return

    name = args[0].lower()
    if name not in BACKEND_PRESETS:
        await update.message.reply_text(
            f"Unbekannt: {name}\nVerfügbar: {', '.join(BACKEND_PRESETS.keys())}"
        )
        return

    preset = BACKEND_PRESETS[name].copy()

    if len(args) > 1:
        preset["default_model"] = args[1]

    if preset["method"] == "api" and name in ("claude-api", "openai"):
        env_var, file_name = _API_KEY_SOURCES[name]
        key_file = os.path.expanduser(f"~/.credentials/{file_name}")
        api_key = _load_api_key(name)
        if not api_key:
            await update.message.reply_text(
                f"Kein API-Key für {name}.\n"
                f"Setze {env_var} oder lege {key_file} an."
            )
            return
        preset["api_key"] = api_key

    try:
        config_for_backend = {k: v for k, v in preset.items()
                              if k not in ("method", "description")}
        new_backend = create_backend(config_for_backend)
        available, availability_status = await asyncio.to_thread(
            _checked_backend_availability,
            new_backend,
            preset["default_model"],
        )
        if not available:
            await update.message.reply_text(
                f"Backend nicht verfügbar: {availability_status}"
            )
            return

        with _runtime_state_lock:
            runtime.backend = new_backend
            session = runtime.get_session(str(update.effective_chat.id))
            session.model = preset["default_model"]
        _invalidate_backend_inventory_cache()

        method_str = "CLI-Session" if preset["method"] == "cli" else "API"
        owns_tools = getattr(new_backend, "manages_own_tools", False)
        tool_str = "CLI-eigene Tools" if owns_tools else "BACH Tool-Use"

        await update.message.reply_text(
            f"Backend: {name}\n"
            f"Modell: {preset['default_model']}\n"
            f"Methode: {method_str}\n"
            f"Tools: {tool_str}"
        )
    except Exception as e:
        await update.message.reply_text(f"Backend-Wechsel fehlgeschlagen: {e}")


async def cmd_settings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    session = runtime.get_session(str(update.effective_chat.id))
    n_msgs = len(session.messages)
    chars = sum(len(m.get("content", "")) for m in session.messages)
    mr = runtime.max_tool_rounds
    mr_label = "Unbegrenzt" if mr == 0 else str(mr)
    tool_info = ""
    if session.current_tool:
        tool_info = f"\nAktives Tool: {session.current_tool} (Runde {session.tool_round})"
    elif session.last_tools:
        tool_info = f"\nLetzte Tools: {', '.join(session.last_tools)}"
    await update.message.reply_text(
        f"Backend: {CONFIG['backend'].get('type', 'ollama')}\n"
        f"Modus: {session.mode}\n"
        f"Denken: {'AN' if session.think else 'AUS'}\n"
        f"Modell: {session.model}\n"
        f"Max Tool-Runden: {mr_label}\n"
        f"Fackel: {get_fackel_preference().capitalize()}\n"
        f"BACH: {'Ja' if HAS_BACH else 'Nein'}\n"
        f"Kontext: {n_msgs} Nachrichten, ~{chars:,} Zeichen"
        + tool_info
    )


async def cmd_maxrounds(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    args = ctx.args or []
    if not args:
        mr = runtime.max_tool_rounds
        await update.message.reply_text(
            f"Max Tool-Runden: {'Unbegrenzt' if mr == 0 else mr}\n\n"
            "/maxrounds 0 — Unbegrenzt\n"
            "/maxrounds 5 — Max 5 Runden\n"
            "/maxrounds 10 — Max 10 Runden"
        )
        return
    try:
        val = int(args[0])
        if val < 0:
            val = 0
        runtime.max_tool_rounds = val
        _global_defaults["max_tool_rounds"] = val
        label = "Unbegrenzt" if val == 0 else str(val)
        await update.message.reply_text(f"Max Tool-Runden: {label}")
    except ValueError:
        await update.message.reply_text("Nutzung: /maxrounds <zahl>")


# --- BACH Commands ---

async def cmd_remember(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not HAS_BACH:
        await update.message.reply_text("BACH nicht verfügbar.")
        return
    text = " ".join(ctx.args) if ctx.args else ""
    if not text:
        await update.message.reply_text("Nutzung: /remember <text>")
        return
    try:
        if ":" in text and len(text.split(":")[0]) < 30:
            _memory("fact", text, "--conf=0.8", "--source=telegram")
            await update.message.reply_text(f"Fakt: {text}")
        else:
            _memory("write", text)
            await update.message.reply_text(f"Notiz: {text}")
    except Exception as e:
        await update.message.reply_text(f"Fehler: {e}")


async def cmd_recall(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not HAS_BACH:
        await update.message.reply_text("BACH nicht verfügbar.")
        return
    q = " ".join(ctx.args) if ctx.args else ""
    if not q:
        await update.message.reply_text("Nutzung: /recall <suche>")
        return
    try:
        r = _memory("search", q)
        await update.message.reply_text(str(r)[:4000] if r else "Nichts gefunden.")
    except Exception as e:
        await update.message.reply_text(f"Fehler: {e}")


async def cmd_facts(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not HAS_BACH:
        await update.message.reply_text("BACH nicht verfügbar.")
        return
    try:
        r = _memory("facts")
        await update.message.reply_text(str(r)[:4000] if r else "Keine Fakten.")
    except Exception as e:
        await update.message.reply_text(f"Fehler: {e}")


async def cmd_bach(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not HAS_BACH:
        await update.message.reply_text("BACH nicht verfügbar.")
        return
    args = ctx.args or []
    if not args:
        await update.message.reply_text(
            "Nutzung: /bach <handler> [operation] [args]\n"
            "Beispiele: /bach status, /bach task list, /bach mem facts"
        )
        return
    h = args[0]
    op = args[1] if len(args) > 1 else ""
    ex = args[2:] if len(args) > 2 else []
    try:
        ok, out = _bach_app.execute(h, op, ex)
        r = str(out)[:4000] if out else "(keine Ausgabe)"
        await update.message.reply_text(r if ok else "Fehler: " + r)
    except Exception as e:
        await update.message.reply_text(f"BACH Fehler: {e}")


async def cmd_task(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not HAS_BACH:
        await update.message.reply_text("BACH nicht verfügbar.")
        return
    text = " ".join(ctx.args) if ctx.args else ""
    if not text:
        await update.message.reply_text("Nutzung: /task <beschreibung>")
        return
    try:
        ok, out = _bach_app.execute("task", "add", [text])
        await update.message.reply_text(str(out)[:2000] if out else "Task erstellt.")
    except Exception as e:
        await update.message.reply_text(f"Fehler: {e}")


async def cmd_tasks(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not HAS_BACH:
        await update.message.reply_text("BACH nicht verfügbar.")
        return
    try:
        ok, out = _bach_app.execute("task", "list", [])
        await update.message.reply_text(str(out)[:4000] if out else "Keine offenen Tasks.")
    except Exception as e:
        await update.message.reply_text(f"Fehler: {e}")


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    session = runtime.get_session(str(update.effective_chat.id))
    parts = []
    try:
        models = backend.list_models()
        parts.append(f"Modelle: {', '.join(models)}\nAktiv: {session.model}")
    except Exception as e:
        parts.append(f"Backend: {e}")
    parts.append(f"Modus: {session.mode} | Denken: {'AN' if session.think else 'AUS'}")
    parts.append(f"Fackel: {get_fackel_preference().capitalize()}")
    if HAS_BACH:
        try:
            ok, out = _bach_app.execute("status", "", [])
            parts.append(str(out)[:1500])
        except Exception:
            parts.append("BACH: Fehler")
    await update.message.reply_text("\n\n".join(parts)[:4000])


async def cmd_fackel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _owner_check(update):
        await update.message.reply_text("Zugriff nur für den Owner.")
        return
    args = ctx.args or []
    current_pref = get_fackel_preference()
    if not args:
        status_text = "Ollama (Chat & Worker bevorzugt)" if current_pref == "ollama" else "Rechenjobs bevorzugt (Compute)"
        await update.message.reply_text(
            f"Fackel-Priorität: {status_text}\n\n"
            f"Umschalten:\n"
            f"/fackel ollama — Chat & Worker bevorzugen\n"
            f"/fackel compute — Rechenjobs bevorzugen (Standard)"
        )
        return
    pref = args[0].lower().strip()
    if pref in ("ollama", "chat", "worker"):
        set_fackel_preference("ollama")
        await update.message.reply_text("Fackel umgestellt: Ollama (Chat & Worker) bevorzugt.")
    elif pref in ("compute", "rechenjobs", "jobs"):
        set_fackel_preference("compute")
        await update.message.reply_text("Fackel umgestellt: Rechenjobs bevorzugt (Compute).")
    else:
        await update.message.reply_text("Nutze: /fackel ollama oder /fackel compute")



async def cmd_voice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _owner_check(update):
        return
    session = runtime.get_session(str(update.effective_chat.id))
    session.voice_output = not session.voice_output
    status = "AN" if session.voice_output else "AUS"
    await update.message.reply_text(f"Sprachausgabe: {status}")


async def _send_voice_reply(update, text: str):
    """Text als Sprachnachricht senden (macOS say + ffmpeg)."""
    tmp_aiff = None
    tmp_ogg = None
    try:
        import shutil
        if not shutil.which("say") or not shutil.which("ffmpeg"):
            return False

        with tempfile.NamedTemporaryFile(suffix=".aiff", delete=False) as aiff_file:
            tmp_aiff = aiff_file.name
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as ogg_file:
            tmp_ogg = ogg_file.name

        clean_text = text[:3000].replace('"', "'").replace("`", "'")

        proc = await asyncio.subprocess.create_subprocess_exec(
            "say", "-v", "Anna", "-o", tmp_aiff, clean_text,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL
        )
        await asyncio.wait_for(proc.wait(), timeout=30)

        proc = await asyncio.subprocess.create_subprocess_exec(
            "ffmpeg", "-y", "-i", tmp_aiff,
            "-c:a", "libopus", "-b:a", "48k", "-ar", "48000",
            "-application", "voip", tmp_ogg,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL
        )
        await asyncio.wait_for(proc.wait(), timeout=15)

        if os.path.exists(tmp_ogg) and os.path.getsize(tmp_ogg) > 0:
            with open(tmp_ogg, "rb") as f:
                await update.message.reply_voice(voice=f)
            return True
    except Exception as e:
        log.error(f"TTS-Fehler: {e}")
    finally:
        for p in (tmp_aiff, tmp_ogg):
            if p and os.path.exists(p):
                os.unlink(p)
    return False


# --- Voice & Photo ---

async def handle_voice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _owner_check(update):
        await update.message.reply_text("Zugriff nur für den Owner.")
        return

    voice = update.message.voice or update.message.audio
    if not voice:
        return

    await update.effective_chat.send_action("typing")
    tmp_path = None

    try:
        tfile = await voice.get_file()
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            tmp_path = tmp.name
        await tfile.download_to_drive(tmp_path)

        text = None
        try:
            from hub._services.voice.voice_stt import VoiceSTT
            if not hasattr(handle_voice, "_stt"):
                handle_voice._stt = VoiceSTT()
            available, engine = handle_voice._stt.is_available()
            if available:
                text = handle_voice._stt.transcribe_file(tmp_path, language="de")
                if text and text.startswith("[Fehler"):
                    text = None
        except ImportError:
            pass

        if not text:
            try:
                import whisper
                if not hasattr(handle_voice, "_whisper"):
                    await update.message.reply_text("Lade Whisper-Modell (einmalig)...")
                    handle_voice._whisper = whisper.load_model("base")
                result = handle_voice._whisper.transcribe(tmp_path, language="de")
                text = result.get("text", "").strip()
            except ImportError:
                await update.message.reply_text(
                    "Weder BACH VoiceSTT noch Whisper verfügbar.\n"
                    "pip install openai-whisper"
                )
                return

        if not text:
            await update.message.reply_text("Konnte keine Sprache erkennen.")
            return

        await update.message.reply_text(f"Erkannt: {text}")
        update.message.text = text
        await handle_message(update, ctx)

    except Exception as e:
        log.error(f"Voice-Fehler: {e}")
        await update.message.reply_text(f"Transkription fehlgeschlagen: {e}")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


async def handle_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _owner_check(update):
        await update.message.reply_text("Zugriff nur für den Owner.")
        return

    photos = update.message.photo
    if not photos:
        return

    await update.effective_chat.send_action("typing")
    tmp_path = None

    try:
        photo = photos[-1]
        tfile = await photo.get_file()
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            tmp_path = tmp.name
        await tfile.download_to_drive(tmp_path)

        ocr_text = None

        try:
            from hub._services.document.ocr_service import OCREngineService
            ocr = OCREngineService()
            ocr_text = ocr.ocr_file(tmp_path, lang="deu")
            if ocr_text:
                ocr_text = ocr_text.strip()
        except (ImportError, Exception):
            pass

        if not ocr_text:
            try:
                import pytesseract
                from PIL import Image
                img = Image.open(tmp_path)
                ocr_text = pytesseract.image_to_string(img, lang="deu").strip()
            except ImportError:
                pass

        caption = update.message.caption or ""

        if ocr_text and len(ocr_text) > 2:
            await update.message.reply_text(f"OCR:\n{ocr_text[:2000]}")
            query = caption if caption else f"Der User hat ein Bild mit folgendem Text geschickt:\n{ocr_text}"
        elif caption:
            query = caption
        else:
            await update.message.reply_text(
                "Kein Text im Bild erkannt. Sende eine Bildunterschrift für Kontext."
            )
            return

        update.message.text = query
        await handle_message(update, ctx)

    except Exception as e:
        log.error(f"Photo-Fehler: {e}")
        await update.message.reply_text(f"Bildverarbeitung fehlgeschlagen: {e}")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


# --- Compute Lock Helpers ---

def _compute_lock_enabled() -> bool:
    """Check if compute lock feature is enabled and available."""
    return (HAS_COMPUTE_LOCK
            and CONFIG.get("compute_lock", {}).get("enabled", False)
            and isinstance(runtime.backend, OllamaBackend))


def _compute_lock_blocks() -> bool:
    """Laeuft gerade ein Rechenjob, der einen Modell-Load verbieten wuerde?

    Haengt in ``ChatRuntime.process``, damit JEDER Aufrufer davor haltmacht --
    der Idle-Worker ueber /api/chat lud das 18-GB-Modell bisher trotz aktivem
    Lock und draengte einen Sage-Job in den Swap (T-20260907-440775748).

    Den vom Nutzer per JA freigegebenen Telegram-Load blockiert das nicht:
    dort sind die Jobs vorher per SIGSTOP pausiert, und check_compute_active
    filtert gestoppte PIDs heraus -- der Lock meldet dann "inaktiv".
    """
    if not _compute_lock_enabled():
        return False
    if get_fackel_preference() == "ollama":
        return False
    cl_cfg = CONFIG.get("compute_lock", {})
    is_active, _status = check_compute_active(
        lock_path=cl_cfg.get("lock_path", DEFAULT_LOCK_PATH),
        check_script=cl_cfg.get("check_script", DEFAULT_CHECK_SCRIPT),
    )
    return is_active


runtime.compute_gate = _compute_lock_blocks


async def _handle_pending_action(chat_id: str, text: str, update: Update) -> bool:
    """Handle JA/NEIN reply to a pending compute lock question.

    Returns True if the message was consumed (caller should return).
    """
    pending = _pending_actions.get(chat_id)
    if not pending:
        return False

    # Check TTL
    if time.time() - pending["timestamp"] > _PENDING_TTL:
        del _pending_actions[chat_id]
        return False

    reply = text.strip().upper()

    if reply in ("JA", "J", "YES", "Y"):
        del _pending_actions[chat_id]
        status = pending["status"]
        original_text = pending["text"]

        await update.message.reply_text("Pausiere Compute-Jobs...")

        cl_cfg = CONFIG.get("compute_lock", {})
        paused = pause_compute_jobs(status)

        if not paused:
            await update.message.reply_text(
                "Keine Jobs pausiert (evtl. bereits beendet). Fahre fort..."
            )
        else:
            pid_str = ", ".join(str(p) for p in paused)
            await update.message.reply_text(
                f"Pausiert: {pid_str}\n"
                "Starte Ollama-Anfrage..."
            )

        # Session flag VOR dem LLM-Call schreiben (Watchdog braucht es für Inferenz-Schutz)
        model = runtime.get_session(chat_id).model or runtime.backend.get_default_model()
        if _compute_lock_enabled():
            write_session_flag(chat_id, model,
                               effective_keep_alive_seconds=get_effective_keep_alive_seconds())

        # Run the original message through the LLM
        typing = asyncio.create_task(_keep_typing(update))
        success = False
        try:
            if _compute_lock_enabled():
                set_inferenz_active(True)
            answer = await runtime.process(original_text, chat_id, skip_compute_gate=True)
            for i in range(0, len(answer), 4000):
                await update.message.reply_text(answer[i:i + 4000])
            session = runtime.get_session(chat_id)
            if session.voice_output:
                await _send_voice_reply(update, answer)
            success = True
        except Exception as e:
            log.error(f"Chat-Fehler nach Compute-Pause: {e}")
            await update.message.reply_text(f"Fehler: {e}")
        finally:
            if _compute_lock_enabled():
                set_inferenz_active(False)
            typing.cancel()

        # Start resume monitor if jobs were paused
        if paused:
            if not success:
                log.info("Chat inference failed after pause, resuming compute jobs immediately: %s", paused)
                delete_session_flag()
                resume_compute_jobs(paused)
                await update.message.reply_text(
                    "Anfrage fehlgeschlagen. Pausierte Compute-Jobs wurden wieder fortgesetzt."
                )
            else:
                ollama_url = getattr(runtime.backend, "base_url", "http://localhost:11434")

                def _on_resume(pids):
                    log.info("Compute jobs resumed: %s", pids)

                start_resume_monitor(
                    model_name=model,
                    paused_pids=paused,
                    callback=_on_resume,
                    ollama_url=ollama_url,
                    idle_wait=90.0,
                )
                await update.message.reply_text(
                    f"Resume-Monitor gestartet. Jobs werden automatisch "
                    f"fortgesetzt wenn {model} entladen wird."
                )

        return True

    elif reply in ("NEIN", "N", "NO"):
        del _pending_actions[chat_id]
        await update.message.reply_text("OK, kein Ollama-Load. Nachricht verworfen.")
        return True

    # Not a JA/NEIN reply — treat as new message, expire the pending action
    del _pending_actions[chat_id]
    return False


# --- Hauptnachrichten-Handler ---

async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _owner_check(update):
        await update.message.reply_text("Zugriff nur für den Owner.")
        return

    text = update.message.text
    if not text:
        return

    chat_id = str(update.effective_chat.id)

    # Handle pending compute lock confirmation (JA/NEIN)
    if chat_id in _pending_actions:
        consumed = await _handle_pending_action(chat_id, text, update)
        if consumed:
            return

    # Compute lock check: before Ollama call, check if compute jobs are running
    if _compute_lock_enabled():
        cl_cfg = CONFIG.get("compute_lock", {})
        is_active, status = check_compute_active(
            lock_path=cl_cfg.get("lock_path", DEFAULT_LOCK_PATH),
            check_script=cl_cfg.get("check_script", DEFAULT_CHECK_SCRIPT),
        )
        if is_active:
            pref = get_fackel_preference()
            if pref == "ollama":
                cl_cfg = CONFIG.get("compute_lock", {})
                paused = pause_compute_jobs(status)
                if paused:
                    pid_str = ", ".join(str(p) for p in paused)
                    await update.message.reply_text(
                        f"Fackel steht auf Ollama: Pausiere Compute-Jobs automatisch ({pid_str})...\n"
                        f"Starte Ollama-Anfrage..."
                    )
                model = runtime.get_session(chat_id).model or runtime.backend.get_default_model()
                write_session_flag(chat_id, model,
                                   effective_keep_alive_seconds=get_effective_keep_alive_seconds())
                typing = asyncio.create_task(_keep_typing(update))
                success = False
                try:
                    set_inferenz_active(True)
                    answer = await runtime.process(text, chat_id, skip_compute_gate=True)
                    for i in range(0, len(answer), 4000):
                        await update.message.reply_text(answer[i:i + 4000])
                    session = runtime.get_session(chat_id)
                    if session.voice_output:
                        await _send_voice_reply(update, answer)
                    success = True
                except Exception as e:
                    log.error(f"Chat-Fehler mit Ollama-Fackel: {e}")
                    await update.message.reply_text(f"Fehler: {e}")
                finally:
                    set_inferenz_active(False)
                    typing.cancel()

                if paused:
                    if not success:
                        log.info("Chat inference failed after auto-pause, resuming compute jobs: %s", paused)
                        delete_session_flag()
                        resume_compute_jobs(paused)
                        await update.message.reply_text(
                            "Anfrage fehlgeschlagen. Pausierte Compute-Jobs wurden wieder fortgesetzt."
                        )
                    else:
                        ollama_url = getattr(runtime.backend, "base_url", "http://localhost:11434")

                        def _on_resume(pids):
                            log.info("Compute jobs resumed: %s", pids)

                        start_resume_monitor(
                            model_name=model,
                            paused_pids=paused,
                            callback=_on_resume,
                            ollama_url=ollama_url,
                            idle_wait=90.0,
                        )
                        await update.message.reply_text(
                            f"Resume-Monitor gestartet. Jobs werden automatisch "
                            f"fortgesetzt wenn {model} entladen wird."
                        )
                return
            else:
                msg = format_status_message(status)
                _pending_actions[chat_id] = {
                    "kind": "compute_pause_for_ollama",
                    "status": status,
                    "text": text,
                    "timestamp": time.time(),
                }
                await update.message.reply_text(msg)
                return
        model = runtime.get_session(chat_id).model or runtime.backend.get_default_model()
        write_session_flag(chat_id, model,
                           effective_keep_alive_seconds=get_effective_keep_alive_seconds())

    typing = asyncio.create_task(_keep_typing(update))

    try:
        if _compute_lock_enabled():
            set_inferenz_active(True)
        answer = await runtime.process(text, chat_id)
        for i in range(0, len(answer), 4000):
            await update.message.reply_text(answer[i:i + 4000])
        session = runtime.get_session(chat_id)
        if session.voice_output:
            await _send_voice_reply(update, answer)
    except Exception as e:
        log.error(f"Chat-Fehler: {e}")
        await update.message.reply_text(f"Fehler: {e}")
    finally:
        if _compute_lock_enabled():
            set_inferenz_active(False)
        typing.cancel()


async def _keep_typing(update):
    try:
        while True:
            await update.effective_chat.send_action("typing")
            await asyncio.sleep(5)
    except asyncio.CancelledError:
        pass


# --- Control API (Port 8081) ---

CONTROL_PORT = int(os.environ.get("BACH_CONTROL_PORT", "8081"))
TELEGRAM_VERIFIED = False

WEB_DASHBOARD = """<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>BACH Chat Control</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,sans-serif;background:#1a1a2e;color:#e0e0e0;padding:20px}
h1{color:#00d4ff;margin-bottom:20px;font-size:1.4em}
.card{background:#16213e;border-radius:12px;padding:16px;margin-bottom:16px;border:1px solid #0f3460}
.card h2{color:#00d4ff;font-size:1em;margin-bottom:12px}
.status-row{display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid #0f3460}
.status-row:last-child{border:none}
.label{color:#888}
.value{color:#00d4ff;font-weight:600}
.btn-group{display:flex;flex-wrap:wrap;gap:8px;margin-top:8px}
.btn{background:#0f3460;color:#e0e0e0;border:1px solid #00d4ff;border-radius:8px;padding:8px 16px;cursor:pointer;font-size:.9em;transition:all .2s}
.btn:hover{background:#00d4ff;color:#1a1a2e}
.btn.active{background:#00d4ff;color:#1a1a2e;font-weight:700}
.dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px}
.dot.green{background:#00ff88}
.dot.red{background:#ff4444}
.dot.yellow{background:#ffcc00}
#toast{position:fixed;bottom:20px;right:20px;background:#00d4ff;color:#1a1a2e;padding:12px 20px;border-radius:8px;display:none;font-weight:600;z-index:99}
</style>
</head>
<body>
<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;flex-wrap:wrap;gap:10px">
  <h1>BACH Chat Control</h1>
  <a href="/activity" style="display:inline-block;padding:8px 14px;background:#0f3460;color:#00d4ff;border:1px solid #00d4ff;border-radius:8px;text-decoration:none;font-size:0.85em;font-weight:600">📊 Zur Aktivitätsanzeige &amp; Worker Dashboard &rarr;</a>
</div>

<div class="card" id="status-card">
<h2><span class="dot green" id="conn-dot"></span>Status</h2>
<div class="status-row"><span class="label">Backend</span><span class="value" id="s-backend">-</span></div>
<div class="status-row"><span class="label">Modell</span><span class="value" id="s-model">-</span></div>
<div class="status-row"><span class="label">Modus</span><span class="value" id="s-mode">-</span></div>
<div class="status-row"><span class="label">Denken</span><span class="value" id="s-think">-</span></div>
<div class="status-row"><span class="label">BACH</span><span class="value" id="s-bach">-</span></div>
<div class="status-row"><span class="label">Sessions</span><span class="value" id="s-sessions">-</span></div>
<div class="status-row"><span class="label">Max Tool-Runden</span><span class="value" id="s-maxrounds">-</span></div>
<div class="status-row"><span class="label">Fackel</span><span class="value" id="s-fackel">-</span></div>
<div class="status-row" id="tool-activity" style="display:none"><span class="label">Aktives Tool</span><span class="value" id="s-tool"><span class="dot yellow"></span>-</span></div>
</div>

<div class="card">
<h2>Backend</h2>
<div class="btn-group" id="backend-btns"></div>
</div>

<div class="card">
<h2>Fackel (Ressourcen-Priorität)</h2>
<div class="btn-group">
<button class="btn" id="fackel-btn-compute" onclick="setFackel('compute')">Rechenjobs (Compute)</button>
<button class="btn" id="fackel-btn-ollama" onclick="setFackel('ollama')">Ollama (Chat &amp; Worker)</button>
</div>
</div>

<div class="card">
<h2>Modus</h2>
<div class="btn-group">
<button class="btn" onclick="setMode('safe')">Safe</button>
<button class="btn" onclick="setMode('full')">Full</button>
</div>
</div>

<div class="card">
<h2>Denkmodus</h2>
<div class="btn-group">
<button class="btn" onclick="setThink(true)">AN</button>
<button class="btn" onclick="setThink(false)">AUS</button>
</div>
</div>

<div class="card">
<h2>Max Tool-Runden</h2>
<div class="btn-group">
<button class="btn" onclick="setMaxRounds(5)">5</button>
<button class="btn" onclick="setMaxRounds(10)">10</button>
<button class="btn" onclick="setMaxRounds(20)">20</button>
<button class="btn" onclick="setMaxRounds(0)">Unbegrenzt</button>
</div>
</div>

<div class="card">
<h2>Modelle</h2>
<div class="btn-group" id="model-btns"></div>
</div>

<div id="toast"></div>

<script>
const API = location.origin + '/api';
function toast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg; t.style.display = 'block';
  setTimeout(() => t.style.display = 'none', 2000);
}
async function api(method, path, body) {
  try {
    const opts = {method, headers: {'Content-Type': 'application/json'}};
    if (body) opts.body = JSON.stringify(body);
    const r = await fetch(API + path, opts);
    return await r.json();
  } catch(e) {
    document.getElementById('conn-dot').className = 'dot red';
    return {error: e.message};
  }
}
async function refresh() {
  const s = await api('GET', '/status');
  if (s.error) return;
  document.getElementById('conn-dot').className = 'dot green';
  document.getElementById('s-backend').textContent = s.backend + (s.backend_cli ? ' (' + s.backend_cli + ')' : '');
  document.getElementById('s-model').textContent = s.model;
  document.getElementById('s-mode').textContent = s.mode;
  document.getElementById('s-think').textContent = s.think ? 'AN' : 'AUS';
  document.getElementById('s-bach').textContent = s.bach ? 'Ja' : 'Nein';
  document.getElementById('s-sessions').textContent = s.sessions;
  document.getElementById('s-maxrounds').textContent = s.max_tool_rounds === 0 ? 'Unbegrenzt' : s.max_tool_rounds;
  const fackelVal = s.fackel_preference === 'ollama' ? 'Ollama (Inferenz)' : 'Rechenjobs (Compute)';
  const fackelEl = document.getElementById('s-fackel');
  if (fackelEl) fackelEl.textContent = fackelVal;
  const fComputeBtn = document.getElementById('fackel-btn-compute');
  const fOllamaBtn = document.getElementById('fackel-btn-ollama');
  if (fComputeBtn) fComputeBtn.className = 'btn' + (s.fackel_preference === 'compute' ? ' active' : '');
  if (fOllamaBtn) fOllamaBtn.className = 'btn' + (s.fackel_preference === 'ollama' ? ' active' : '');
  const toolEl = document.getElementById('tool-activity');
  if (s.current_tool) {
    toolEl.style.display = '';
    document.getElementById('s-tool').innerHTML = '<span class="dot yellow"></span>' + s.current_tool + ' (Runde ' + s.tool_round + ')';
  } else if (s.last_tools && s.last_tools.length) {
    toolEl.style.display = '';
    document.getElementById('s-tool').innerHTML = s.last_tools.join(', ');
  } else {
    toolEl.style.display = 'none';
  }

  const bs = await api('GET', '/backends');
  if (!bs.error) {
    const c = document.getElementById('backend-btns');
    c.innerHTML = '';
    for (const [name, info] of Object.entries(bs)) {
      const b = document.createElement('button');
      b.className = 'btn';
      b.textContent = name + (info.status ? ' [' + info.status + ']' : '');
      b.disabled = info.available !== true;
      b.title = info.status || 'Backend nicht verfügbar';
      b.onclick = () => setBackend(name);
      c.appendChild(b);
    }
  }

  const ms = await api('GET', '/models');
  if (!ms.error && ms.models) {
    const c = document.getElementById('model-btns');
    c.innerHTML = '';
    ms.models.forEach(m => {
      const b = document.createElement('button');
      b.className = 'btn' + (m === s.model ? ' active' : '');
      b.textContent = m;
      b.onclick = () => setModel(m);
      c.appendChild(b);
    });
  }
}
async function setBackend(name) {
  const r = await api('POST', '/backend', {name});
  toast(r.error || 'Backend: ' + name);
  refresh();
}
async function setMode(mode) {
  const r = await api('POST', '/mode', {mode});
  toast(r.error || 'Modus: ' + mode);
  refresh();
}
async function setThink(think) {
  const r = await api('POST', '/think', {think});
  toast(r.error || 'Denken: ' + (think ? 'AN' : 'AUS'));
  refresh();
}
async function setModel(model) {
  const r = await api('POST', '/model', {model});
  toast(r.error || 'Modell: ' + model);
  refresh();
}
async function setMaxRounds(rounds) {
  const r = await api('POST', '/max_tool_rounds', {rounds});
  toast(r.error || 'Max Runden: ' + (rounds === 0 ? 'Unbegrenzt' : rounds));
  refresh();
}
async function setFackel(pref) {
  const r = await api('POST', '/fackel', {preference: pref});
  toast(r.error || 'Fackel: ' + (pref === 'ollama' ? 'Ollama' : 'Rechenjobs'));
  refresh();
}
refresh();
let _refreshTimer = setInterval(refresh, 30000);
document.addEventListener('visibilitychange', () => {
  clearInterval(_refreshTimer);
  if (!document.hidden) { refresh(); _refreshTimer = setInterval(refresh, 30000); }
});
</script>
</body>
</html>"""


WEB_ACTIVITY_DASHBOARD = """<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>BACH Aktivitätsanzeige & Worker Dashboard</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:#101726;color:#e2e8f0;padding:20px;line-height:1.5}
a{color:#38bdf8;text-decoration:none}
a:hover{text-decoration:underline}
header{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px;margin-bottom:24px;padding-bottom:16px;border-bottom:1px solid #1e293b}
h1{color:#38bdf8;font-size:1.5rem;font-weight:700;display:flex;align-items:center;gap:10px}
.subtitle{color:#94a3b8;font-size:0.85rem;margin-top:2px}
.header-actions{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.fackel-btn{background:#1e293b;color:#f1f5f9;border:1px solid #38bdf8;padding:6px 14px;border-radius:20px;cursor:pointer;font-size:0.85rem;font-weight:600;display:flex;align-items:center;gap:6px;transition:all .2s}
.fackel-btn:hover{background:#38bdf8;color:#0f172a}
.fackel-btn.ollama{border-color:#10b981;color:#10b981}
.fackel-btn.ollama:hover{background:#10b981;color:#0f172a}
.fackel-btn.compute{border-color:#f59e0b;color:#f59e0b}
.fackel-btn.compute:hover{background:#f59e0b;color:#0f172a}
.live-pill{display:inline-flex;align-items:center;gap:6px;font-size:0.75rem;padding:4px 10px;background:#1e293b;border-radius:12px;color:#94a3b8;border:1px solid #334155}
.pulse-dot{width:8px;height:8px;border-radius:50%;background:#10b981;box-shadow:0 0 8px #10b981;animation:pulse 2s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.4}}
.section-title{color:#f8fafc;font-size:1.15rem;font-weight:600;margin:24px 0 12px;display:flex;align-items:center;justify-content:space-between}
.grid-3{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:16px}
.card{background:#1e293b;border-radius:12px;padding:18px;border:1px solid #334155;display:flex;flex-direction:column;gap:12px;position:relative}
.card-header{display:flex;justify-content:space-between;align-items:flex-start}
.card-title{font-size:1.05rem;font-weight:700;color:#38bdf8;display:flex;align-items:center;gap:8px}
.card-desc{font-size:0.8rem;color:#94a3b8;margin-top:2px}
.badge{display:inline-block;padding:2px 8px;border-radius:10px;font-size:0.75rem;font-weight:600;text-transform:uppercase}
.badge-ready{background:#065f46;color:#34d399}
.badge-idle{background:#1e3a8a;color:#93c5fd}
.badge-running{background:#854d0e;color:#fde047;animation:pulse 1.5s infinite}
.badge-paused{background:#475569;color:#cbd5e1}
.badge-error{background:#991b1b;color:#fca5a5}
.badge-expired{background:#374151;color:#9ca3af}
.form-group{display:flex;flex-direction:column;gap:4px}
.form-group label{font-size:0.75rem;color:#94a3b8;font-weight:600;text-transform:uppercase}
.form-row{display:grid;grid-template-columns:1fr 1fr;gap:10px}
input,select,textarea{background:#0f172a;color:#f8fafc;border:1px solid #475569;border-radius:6px;padding:8px 10px;font-size:0.88rem;outline:none;transition:border-color .2s}
input:focus,select:focus,textarea:focus{border-color:#38bdf8}
.activity-box{background:#0f172a;border-radius:8px;padding:8px 10px;font-size:0.8rem;color:#cbd5e1;border:1px solid #334155;min-height:36px;display:flex;align-items:center}
.btn{background:#0284c7;color:#fff;border:none;border-radius:6px;padding:8px 14px;cursor:pointer;font-size:0.85rem;font-weight:600;transition:all .2s;display:inline-flex;align-items:center;justify-content:center;gap:6px}
.btn:hover{background:#38bdf8;color:#0f172a}
.btn-sm{padding:4px 8px;font-size:0.75rem;border-radius:4px}
.btn-secondary{background:#334155;color:#e2e8f0}
.btn-secondary:hover{background:#475569;color:#fff}
.btn-danger{background:#dc2626;color:#fff}
.btn-danger:hover{background:#ef4444}
.btn-success{background:#16a34a;color:#fff}
.btn-success:hover{background:#22c55e}
.btn-outline{background:transparent;border:1px solid #475569;color:#94a3b8}
.btn-outline:hover{background:#334155;color:#fff;border-color:#64748b}
.workers-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px}
.worker-card{background:#1e293b;border:1px solid #334155;border-radius:10px;padding:14px;display:flex;flex-direction:column;gap:10px}
.worker-top{display:flex;justify-content:space-between;align-items:center}
.worker-name{font-weight:700;color:#f1f5f9;font-size:0.95rem}
.worker-meta{font-size:0.78rem;color:#94a3b8;display:flex;flex-direction:column;gap:2px}
.worker-actions{display:flex;gap:6px;margin-top:auto}
.table-wrap{background:#1e293b;border-radius:12px;border:1px solid #334155;overflow:hidden}
table{width:100%;border-collapse:collapse;font-size:0.85rem;text-align:left}
th{background:#0f172a;color:#94a3b8;font-weight:600;padding:10px 14px;border-bottom:1px solid #334155}
td{padding:10px 14px;border-bottom:1px solid #1e293b;color:#cbd5e1}
tr:last-child td{border-bottom:none}
tr:hover td{background:#24334d}
.modal-bg{position:fixed;top:0;left:0;width:100vw;height:100vh;background:rgba(0,0,0,0.7);display:none;align-items:center;justify-content:center;z-index:100}
.modal{background:#1e293b;border:1px solid #38bdf8;border-radius:12px;padding:24px;width:95%;max-width:520px;max-height:90vh;overflow-y:auto;display:flex;flex-direction:column;gap:14px}
.modal-header{display:flex;justify-content:space-between;align-items:center}
.modal-title{font-size:1.2rem;font-weight:700;color:#38bdf8}
#toast{position:fixed;bottom:20px;right:20px;background:#38bdf8;color:#0f172a;padding:10px 18px;border-radius:8px;font-weight:600;box-shadow:0 4px 12px rgba(0,0,0,0.3);display:none;z-index:110}
</style>
</head>
<body>

<header>
  <div>
    <h1><span>🤖</span> BACH Aktivitätsanzeige &amp; Worker Dashboard</h1>
    <div class="subtitle">Modell-Zuweisung je Slot · Hintergrundworker · Parallele Ausführung · Live-Aktivitäten</div>
  </div>
  <div class="header-actions">
    <button id="btn-fackel" class="fackel-btn compute" onclick="toggleFackel()">Fackel: Lädt...</button>
    <div class="live-pill"><span class="pulse-dot"></span> Live (3s)</div>
    <a href="/" class="btn btn-outline btn-sm">Chat-Control</a>
    <a href="http://127.0.0.1:8000/" target="_blank" class="btn btn-outline btn-sm">GUI :8000</a>
  </div>
</header>

<div style="display:flex;gap:10px;margin-bottom:20px;border-bottom:1px solid #334155;padding-bottom:12px">
  <button id="nav-btn-dash" class="btn btn-sm" style="background:#38bdf8;color:#0f172a;font-weight:700" onclick="showTab('dash')">📊 Aktivitäten &amp; Worker</button>
  <button id="nav-btn-prompts" class="btn btn-sm btn-outline" onclick="showTab('prompts')">📜 System- &amp; Rollenprompts</button>
</div>

<div id="tab-dash">

<div class="section-title">
  <span>1. Modell-Slots &amp; Konfiguration</span>
</div>

<div class="grid-3">
  <!-- Slot 1: Buddha Chat -->
  <div class="card" id="card-buddha_chat">
    <div class="card-header">
      <div>
        <div class="card-title"><span>💬</span> Buddha Chat</div>
        <div class="card-desc">Interaktiver Chat (WebChat, GUI &amp; Tray)</div>
      </div>
      <span class="badge badge-ready" id="badge-buddha_chat">Ready</span>
    </div>
    <div class="form-row">
      <div class="form-group">
        <label>Backend</label>
        <select id="chat-backend" onchange="onBackendChange('chat')">
          <option value="ollama">💻 Ollama (lokal)</option>
          <option value="ollama-cloud">☁️ Ollama (Cloud :cloud)</option>
          <option value="hermes">Hermes (API)</option>
          <option value="claude">Claude CLI</option>
          <option value="claude-api">Claude API</option>
          <option value="codex">Codex CLI</option>
          <option value="openai">OpenAI API</option>
          <option value="lmstudio">LM Studio</option>
        </select>
      </div>
      <div class="form-group">
        <label>Modell-Vorauswahl</label>
        <select id="chat-model-preset" onchange="applyModelPreset('chat', this.value)">
          <option value="">-- Schnell-Auswahl --</option>
          <optgroup label="☁️ Ollama Cloud (:cloud)">
            <option value="kimi-k3:cloud">kimi-k3:cloud (131k)</option>
            <option value="kimi-k2.7-code:cloud">kimi-k2.7-code:cloud</option>
            <option value="glm-5.3:cloud">glm-5.3:cloud</option>
          </optgroup>
          <optgroup label="💻 Ollama Lokal (MLX)">
            <option value="qwen3.8:27b-mlx">qwen3.8:27b-mlx</option>
            <option value="gemma4:26b-mlx">gemma4:26b-mlx</option>
            <option value="qwen3.5:4b">qwen3.5:4b</option>
          </optgroup>
          <optgroup label="🌐 CLI / API">
            <option value="claude-3-7-sonnet">Claude 3.7 Sonnet</option>
            <option value="sonnet">Claude CLI (sonnet)</option>
            <option value="gpt-4o">GPT-4o</option>
            <option value="o4-mini">o4-mini</option>
          </optgroup>
        </select>
      </div>
    </div>
    <div class="form-group">
      <label>Modell</label>
      <input type="text" id="chat-model" list="model-presets-list" placeholder="qwen3.8:27b-mlx">
    </div>
    <div class="form-row">
      <div class="form-group">
        <label>Max Turns</label>
        <select id="chat-turns">
          <option value="5">5 Runden</option>
          <option value="10">10 Runden</option>
          <option value="12">12 Runden</option>
          <option value="15">15 Runden</option>
          <option value="20">20 Runden</option>
          <option value="0">Unbegrenzt</option>
        </select>
      </div>
      <div class="form-group">
        <label>Modus &amp; Denken</label>
        <div style="display:flex;gap:8px;align-items:center;margin-top:4px">
          <select id="chat-mode" style="flex:1">
            <option value="safe">Safe (Lesen)</option>
            <option value="full">Full (Schreiben)</option>
          </select>
          <label style="display:flex;align-items:center;gap:4px;font-size:0.8rem;cursor:pointer">
            <input type="checkbox" id="chat-think"> Think
          </label>
        </div>
      </div>
    </div>
    <div class="form-group">
      <label>Aktuelle Aktivität</label>
      <div class="activity-box" id="chat-activity">Bereit für Interaktionen</div>
    </div>
    <div style="display:flex;gap:8px">
      <button class="btn" style="flex:1" onclick="saveCoreSlot('buddha_chat')">💾 Speichern</button>
      <button class="btn btn-secondary btn-sm" onclick="openHistoryModal('gui-web')">📜 Verlauf</button>
    </div>
  </div>

  <!-- Slot 2: Buddha Always-On -->
  <div class="card" id="card-buddha_always_on">
    <div class="card-header">
      <div>
        <div class="card-title"><span>⚡</span> Buddha Always-On</div>
        <div class="card-desc">Hintergrundworker für offene Tasks</div>
      </div>
      <div style="display:flex;gap:6px;align-items:center">
        <span class="badge badge-ready" id="badge-buddha_always_on">Aktiv</span>
        <button class="btn btn-sm btn-secondary" id="btn-toggle-always-on" onclick="toggleAlwaysOn()">Toggle</button>
      </div>
    </div>
    <div class="form-row">
      <div class="form-group">
        <label>Backend</label>
        <select id="always-backend" onchange="onBackendChange('always')">
          <option value="ollama">💻 Ollama (lokal)</option>
          <option value="ollama-cloud">☁️ Ollama (Cloud :cloud)</option>
          <option value="hermes">Hermes (API)</option>
          <option value="claude">Claude CLI</option>
          <option value="claude-api">Claude API</option>
          <option value="codex">Codex CLI</option>
          <option value="openai">OpenAI API</option>
        </select>
      </div>
      <div class="form-group">
        <label>Modell-Vorauswahl</label>
        <select id="always-model-preset" onchange="applyModelPreset('always', this.value)">
          <option value="">-- Schnell-Auswahl --</option>
          <optgroup label="☁️ Ollama Cloud (:cloud)">
            <option value="kimi-k3:cloud">kimi-k3:cloud (131k)</option>
            <option value="kimi-k2.7-code:cloud">kimi-k2.7-code:cloud</option>
            <option value="glm-5.3:cloud">glm-5.3:cloud</option>
          </optgroup>
          <optgroup label="💻 Ollama Lokal (MLX)">
            <option value="qwen3.8:27b-mlx">qwen3.8:27b-mlx</option>
            <option value="gemma4:26b-mlx">gemma4:26b-mlx</option>
            <option value="qwen3.5:4b">qwen3.5:4b</option>
          </optgroup>
          <optgroup label="🌐 CLI / API">
            <option value="claude-3-7-sonnet">Claude 3.7 Sonnet</option>
            <option value="sonnet">Claude CLI (sonnet)</option>
            <option value="gpt-4o">GPT-4o</option>
            <option value="o4-mini">o4-mini</option>
          </optgroup>
        </select>
      </div>
    </div>
    <div class="form-group">
      <label>Modell</label>
      <input type="text" id="always-model" list="model-presets-list" placeholder="qwen3.8:27b-mlx">
    </div>
    <div class="form-row">
      <div class="form-group">
        <label>Max Turns</label>
        <select id="always-turns">
          <option value="10">10 Runden</option>
          <option value="20">20 Runden</option>
          <option value="25">25 Runden</option>
          <option value="30">30 Runden</option>
          <option value="50">50 Runden</option>
          <option value="0">Unbegrenzt</option>
        </select>
      </div>
      <div class="form-group">
        <label>Modus</label>
        <select id="always-mode">
          <option value="full">Full (Schreibrechte / Auto-Commit)</option>
          <option value="safe">Safe (Nur Analyse)</option>
        </select>
      </div>
    </div>
    <div class="form-group">
      <label>Aktuelle Aktivität</label>
      <div class="activity-box" id="always-activity">Wartet auf Idle-Schwelle</div>
    </div>
    <div style="display:flex;gap:8px">
      <button class="btn" style="flex:1" onclick="saveCoreSlot('buddha_always_on')">💾 Speichern</button>
      <button class="btn btn-secondary btn-sm" onclick="openHistoryModal('idle-worker')">📜 Verlauf</button>
    </div>
  </div>

  <!-- Slot 3: Buddha Connector -->
  <div class="card" id="card-buddha_connector">
    <div class="card-header">
      <div>
        <div class="card-title"><span>📱</span> Buddha Connector</div>
        <div class="card-desc">Messaging (Telegram, WhatsApp, Signal)</div>
      </div>
      <span class="badge badge-ready" id="badge-buddha_connector">Ready</span>
    </div>
    <div class="form-row">
      <div class="form-group">
        <label>Backend</label>
        <select id="conn-backend" onchange="onBackendChange('conn')">
          <option value="ollama">💻 Ollama (lokal)</option>
          <option value="ollama-cloud">☁️ Ollama (Cloud :cloud)</option>
          <option value="hermes">Hermes (API)</option>
          <option value="claude">Claude CLI</option>
          <option value="claude-api">Claude API</option>
          <option value="codex">Codex CLI</option>
          <option value="openai">OpenAI API</option>
        </select>
      </div>
      <div class="form-group">
        <label>Modell-Vorauswahl</label>
        <select id="conn-model-preset" onchange="applyModelPreset('conn', this.value)">
          <option value="">-- Schnell-Auswahl --</option>
          <optgroup label="☁️ Ollama Cloud (:cloud)">
            <option value="kimi-k3:cloud">kimi-k3:cloud (131k)</option>
            <option value="kimi-k2.7-code:cloud">kimi-k2.7-code:cloud</option>
            <option value="glm-5.3:cloud">glm-5.3:cloud</option>
          </optgroup>
          <optgroup label="💻 Ollama Lokal (MLX)">
            <option value="qwen3.8:27b-mlx">qwen3.8:27b-mlx</option>
            <option value="gemma4:26b-mlx">gemma4:26b-mlx</option>
            <option value="qwen3.5:4b">qwen3.5:4b</option>
          </optgroup>
          <optgroup label="🌐 CLI / API">
            <option value="claude-3-7-sonnet">Claude 3.7 Sonnet</option>
            <option value="sonnet">Claude CLI (sonnet)</option>
            <option value="gpt-4o">GPT-4o</option>
            <option value="o4-mini">o4-mini</option>
          </optgroup>
        </select>
      </div>
    </div>
    <div class="form-group">
      <label>Modell</label>
      <input type="text" id="conn-model" list="model-presets-list" placeholder="qwen3.8:27b-mlx">
    </div>
    <div class="form-row">
      <div class="form-group">
        <label>Max Turns</label>
        <select id="conn-turns">
          <option value="5">5 Runden</option>
          <option value="10">10 Runden</option>
          <option value="15">15 Runden</option>
          <option value="20">20 Runden</option>
        </select>
      </div>
      <div class="form-group">
        <label>Provider</label>
        <div style="font-size:0.75rem;color:#94a3b8;margin-top:6px;line-height:1.4">
          <span id="p-tg-status">Telegram: Verifiziert</span> · WhatsApp: Bereit
        </div>
      </div>
    </div>
    <div class="form-group">
      <label>Aktuelle Aktivität</label>
      <div class="activity-box" id="conn-activity">Bereit</div>
    </div>
    <div style="display:flex;gap:8px">
      <button class="btn" style="flex:1" onclick="saveCoreSlot('buddha_connector')">💾 Speichern</button>
      <button class="btn btn-secondary btn-sm" onclick="openHistoryModal('telegram')">📜 Verlauf</button>
    </div>
  </div>
</div>

<div class="section-title">
  <span>2. Dynamische &amp; Temporäre Hintergrundworker</span>
  <button class="btn btn-success btn-sm" onclick="openNewWorkerModal()">+ Neuer Worker anlegen</button>
</div>

<div class="workers-grid" id="workers-container">
  <!-- Dynamic workers injected here -->
</div>

<div class="section-title">
  <span>3. Echtzeit-Aktivitätsanzeige &amp; Verlauf (Timeline)</span>
  <button class="btn btn-secondary btn-sm" onclick="refreshActivity()">Neu laden</button>
</div>

<div class="table-wrap">
  <table>
    <thead>
      <tr>
        <th style="width:110px">Zeit</th>
        <th style="width:160px">Akteur / Slot</th>
        <th>Aktivität (Tool, Runde, Aufgabe)</th>
        <th style="width:100px">Status</th>
      </tr>
    </thead>
    <tbody id="activity-tbody">
      <tr><td colspan="4" style="text-align:center;color:#64748b">Lade Aktivitäten...</td></tr>
    </tbody>
  </table>
</div>
</div> <!-- end of tab-dash -->

<!-- Tab 2: System- & Rollenprompts -->
<div id="tab-prompts" style="display:none">
  <div class="section-title">
    <span>📜 System-Default-Prompt &amp; Rollen-Vorlagen anpassen</span>
    <button class="btn btn-secondary btn-sm" onclick="loadPromptTemplates()">↺ Neu laden</button>
  </div>
  <p style="color:#94a3b8;font-size:0.88rem;margin-bottom:16px">
    Hier können der allgemeine Buddha-Systemprompt sowie alle Rollenprompts eingesehen und angepasst werden.
    Der unveränderliche Werkstandard bleibt im System gesichert und kann jederzeit für jeden Prompt wiederhergestellt werden.
  </p>

  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(380px,1fr));gap:20px;margin-bottom:24px">
    <!-- Card A: System-Default-Prompt -->
    <div class="card">
      <div class="card-header">
        <div>
          <div class="card-title"><span>🛡️</span> System-Default-Prompt</div>
          <div class="card-desc">Basis-Instruktion für Buddha (Werkzeuge, Regeln, Deutsch-Gebot)</div>
        </div>
        <span class="badge badge-ready" id="badge-prompt-sys">Werkstandard</span>
      </div>
      <div class="form-group" style="margin-top:10px">
        <textarea id="prompt-sys-text" rows="12" style="width:100%;font-family:monospace;font-size:0.82rem"></textarea>
      </div>
      <div style="display:flex;gap:8px;justify-content:flex-end">
        <button class="btn btn-secondary btn-sm" onclick="resetPrompt('system_default')">↺ Auf Werkstandard zurücksetzen</button>
        <button class="btn btn-success btn-sm" onclick="savePrompt('system_default')">💾 Systemprompt speichern</button>
      </div>
    </div>

    <!-- Card B: Rollen-Prompts -->
    <div class="card">
      <div class="card-header">
        <div>
          <div class="card-title"><span>🎭</span> Rollen- &amp; Experten-Prompts</div>
          <div class="card-desc">Spezifische Verhaltensregeln je Rolle / Experte</div>
        </div>
        <span class="badge badge-ready" id="badge-prompt-role">Werkstandard</span>
      </div>
      <div class="form-group" style="margin-top:10px">
        <label>Rolle / Experte auswählen</label>
        <select id="role-select" onchange="onRolePromptSelect(this.value)">
          <option value="hintergrund_worker">Hintergrundworker (Task-Abarbeitung &amp; FERTIG-Signal)</option>
          <option value="task_worker">Task-Worker (Gezielte Auftragserledigung)</option>
          <option value="boss_routing">Bossagent &amp; Koordinator (Dekomposition &amp; Delegation)</option>
          <option value="entwickler">Entwickler (Python, Architektur, TDD, Git)</option>
          <option value="bueroassistent">Büroassistent (Organisation &amp; Dokumente)</option>
          <option value="gesundheitsassistent">Gesundheitsassistent (Medizin &amp; Berichte)</option>
          <option value="steuer">Steuer-Experte (Belege, Rechnungen, Werbungskosten)</option>
          <option value="foerderplaner">Förderplaner (ICF, Pädagogik &amp; Berichte)</option>
          <option value="recherche">Recherche-Experte (Wissenschaftliche Synthese)</option>
          <option value="psycho-berater">Psycho-Berater (Therapeutische Reflexion)</option>
        </select>
      </div>
      <div class="form-group">
        <textarea id="prompt-role-text" rows="9" style="width:100%;font-family:monospace;font-size:0.82rem"></textarea>
      </div>
      <div style="display:flex;gap:8px;justify-content:flex-end">
        <button class="btn btn-secondary btn-sm" onclick="resetCurrentRolePrompt()">↺ Auf Werkstandard zurücksetzen</button>
        <button class="btn btn-success btn-sm" onclick="saveCurrentRolePrompt()">💾 Rollenprompt speichern</button>
      </div>
    </div>
  </div>
</div>

<!-- Modal: Neuer Worker anlegen -->
<div class="modal-bg" id="new-worker-modal">
  <div class="modal" style="max-width:560px">
    <div class="modal-header">
      <div class="modal-title">+ Neuen Hintergrundworker starten</div>
      <button class="btn btn-outline btn-sm" onclick="closeNewWorkerModal()">✕</button>
    </div>
    <div class="form-group">
      <label>Worker-Name</label>
      <input type="text" id="nw-name" placeholder="z.B. Recherche-Worker, Atlas-Refactoring">
    </div>
    <div class="form-group">
      <label>Modus / Untermodus</label>
      <select id="nw-sub-mode" onchange="onSubModeChange(this.value)">
        <option value="task_worker">3.2 Taskworker (Gezielter Einzelauftrag)</option>
        <option value="hintergrund_worker">3.1 Weiterer Hintergrundworker (wie Always-On)</option>
        <option value="boss_routing">3.3 Bossrouting (Koordination &amp; Unteragenten)</option>
        <option value="expert_role">3.4 Spezifische Expertenrolle</option>
      </select>
    </div>
    <div class="form-group">
      <label>Ausführungstyp</label>
      <select id="nw-type">
        <option value="persistent">Dauerhaft (bis manuell gelöscht)</option>
        <option value="once">Einmalig (beendet nach Task)</option>
      </select>
    </div>

    <!-- Dynamic Fields for Bossrouting -->
    <div id="nw-boss-fields" style="display:none;background:#0f172a;padding:10px 12px;border-radius:8px;border:1px dashed #38bdf8;margin-bottom:6px">
      <div class="form-row">
        <div class="form-group">
          <label>Max. beteiligte Experten</label>
          <input type="number" id="nw-max-experts" value="3" min="1" max="10">
        </div>
        <div class="form-group">
          <label>Modellallokation je Experte (optional)</label>
          <input type="text" id="nw-expert-models" placeholder='{"entwickler":"kimi-k3:cloud"}'>
        </div>
      </div>
    </div>

    <!-- Dynamic Fields for Expert Role -->
    <div id="nw-expert-fields" style="display:none;background:#0f172a;padding:10px 12px;border-radius:8px;border:1px dashed #38bdf8;margin-bottom:6px">
      <div class="form-row">
        <div class="form-group">
          <label>Fachrolle / Experte</label>
          <select id="nw-role-id">
            <option value="entwickler">Entwickler (Senior Python / TDD)</option>
            <option value="bueroassistent">Büroassistent (Organisation &amp; Dokumente)</option>
            <option value="gesundheitsassistent">Gesundheitsassistent (Medizin &amp; Berichte)</option>
            <option value="steuer">Steuer-Agent (Belege &amp; Werbungskosten)</option>
            <option value="foerderplaner">Förderplaner (Pädagogik &amp; Berichte)</option>
            <option value="recherche">Recherche-Experte (Wissenschaft)</option>
            <option value="psycho-berater">Psycho-Berater (Reflexion)</option>
          </select>
        </div>
        <div class="form-group" style="display:flex;align-items:center;margin-top:22px">
          <label style="display:flex;align-items:center;gap:6px;font-size:0.84rem;cursor:pointer;color:#38bdf8">
            <input type="checkbox" id="nw-multi-role"> Alle Rollen spielen (Multi-Role Pool)
          </label>
        </div>
      </div>
    </div>

    <!-- System Prompt Checkbox -->
    <div style="background:#0f172a;padding:10px 12px;border-radius:8px;border:1px solid #334155;margin-bottom:6px">
      <label style="display:flex;align-items:center;gap:8px;font-weight:600;color:#38bdf8;cursor:pointer">
        <input type="checkbox" id="nw-include-system-prompt" checked> System-Default-Prompt einbinden (Standard aktiv)
      </label>
      <div style="font-size:0.78rem;color:#94a3b8;margin-top:3px;margin-left:24px">
        Vererbt automatische BACH-Grundregeln, Werkzeuge, Pfade und das Deutsch-Gebot.
      </div>
    </div>

    <div class="form-row">
      <div class="form-group">
        <label>Backend</label>
        <select id="nw-backend" onchange="onBackendChange('nw')">
          <option value="ollama">💻 Ollama (lokal)</option>
          <option value="ollama-cloud">☁️ Ollama (Cloud :cloud)</option>
          <option value="hermes">Hermes (API)</option>
          <option value="claude">Claude CLI</option>
          <option value="claude-api">Claude API</option>
          <option value="codex">Codex CLI</option>
          <option value="openai">OpenAI API</option>
        </select>
      </div>
      <div class="form-group">
        <label>Modell-Vorauswahl</label>
        <select id="nw-model-preset" onchange="applyModelPreset('nw', this.value)">
          <option value="">-- Schnell-Auswahl --</option>
          <optgroup label="☁️ Ollama Cloud (:cloud)">
            <option value="kimi-k3:cloud">kimi-k3:cloud (131k)</option>
            <option value="kimi-k2.7-code:cloud">kimi-k2.7-code:cloud</option>
            <option value="glm-5.3:cloud">glm-5.3:cloud</option>
          </optgroup>
          <optgroup label="💻 Ollama Lokal (MLX)">
            <option value="qwen3.8:27b-mlx">qwen3.8:27b-mlx</option>
            <option value="gemma4:26b-mlx">gemma4:26b-mlx</option>
            <option value="qwen3.5:4b">qwen3.5:4b</option>
            <option value="gemma4:e2b">gemma4:e2b</option>
            <option value="deepseek-ocr:latest">deepseek-ocr:latest</option>
          </optgroup>
          <optgroup label="🌐 CLI / API">
            <option value="claude-3-7-sonnet">Claude 3.7 Sonnet</option>
            <option value="sonnet">Claude CLI (sonnet)</option>
            <option value="gpt-4o">GPT-4o</option>
            <option value="o4-mini">o4-mini</option>
          </optgroup>
        </select>
      </div>
    </div>
    <div class="form-group">
      <label>Modellbezeichnung (exakt)</label>
      <input type="text" id="nw-model" list="model-presets-list" placeholder="z. B. kimi-k3:cloud oder qwen3.8:27b-mlx">
      <div style="font-size:0.75rem;color:#94a3b8;margin-top:3px">
        💡 <strong>Ollama Cloud:</strong> Modellname muss wie im CLI mit <code>:cloud</code> enden (z. B. <code>kimi-k3:cloud</code>). Lokale Modelle laufen direkt auf deiner Hardware.
      </div>
    </div>
    <div class="form-row">
      <div class="form-group">
        <label>Max Turns</label>
        <input type="number" id="nw-turns" value="25" min="1" max="100">
      </div>
      <div class="form-group">
        <label>Modus</label>
        <select id="nw-mode">
          <option value="full">Full (Schreibrechte)</option>
          <option value="safe">Safe (Nur Lesen)</option>
        </select>
      </div>
    </div>
    <div class="form-row">
      <div class="form-group">
        <label>Task-ID (optional)</label>
        <input type="number" id="nw-task-id" placeholder="z.B. 104">
      </div>
      <div class="form-group">
        <label>Ablaufzeit / TTL</label>
        <select id="nw-ttl">
          <option value="">Kein Ablaufdatum</option>
          <option value="3600">1 Stunde</option>
          <option value="14400">4 Stunden</option>
          <option value="86400">24 Stunden</option>
          <option value="604800">7 Tage</option>
        </select>
      </div>
    </div>
    <div class="form-group">
      <label>Aufgaben- / Nutzereingabe-Prompt (optional / zielspezifisch)</label>
      <textarea id="nw-task-prompt" rows="3" placeholder="Konkrete Aufgabenstellung oder Verhaltensanweisung für diesen Worker..."></textarea>
    </div>
    <div style="display:flex;justify-content:flex-end;gap:8px;margin-top:8px">
      <button class="btn btn-secondary" onclick="closeNewWorkerModal()">Abbrechen</button>
      <button class="btn btn-success" onclick="createWorker()">Worker erstellen</button>
    </div>
  </div>
</div>

<!-- Modal: Chat- & Tool-Verlauf einsehen -->
<div class="modal-bg" id="history-modal">
  <div class="modal" style="max-width:760px;width:95%">
    <div class="modal-header">
      <div class="modal-title" id="history-modal-title">📜 Session-Verlauf</div>
      <button class="btn btn-outline btn-sm" onclick="closeHistoryModal()">✕</button>
    </div>
    <div id="history-modal-body" style="max-height:65vh;overflow-y:auto;display:flex;flex-direction:column;gap:10px;padding:4px">
      <!-- Chat bubbles injected here -->
    </div>
    <div style="display:flex;justify-content:flex-end;margin-top:10px">
      <button class="btn btn-secondary" onclick="closeHistoryModal()">Schließen</button>
    </div>
  </div>
</div>

<datalist id="model-presets-list">
  <option value="kimi-k3:cloud">☁️ Ollama Cloud (Moonshot Kimi K3, 131k)</option>
  <option value="kimi-k2.7-code:cloud">☁️ Ollama Cloud (Kimi Code Spezialist)</option>
  <option value="glm-5.3:cloud">☁️ Ollama Cloud (Zhipu GLM 5.3, 131k)</option>
  <option value="qwen3.8:27b-mlx">💻 Ollama Lokal (Qwen 27B MLX)</option>
  <option value="gemma4:26b-mlx">💻 Ollama Lokal (Google Gemma 26B)</option>
  <option value="qwen3.5:4b">💻 Ollama Lokal (Qwen 4B)</option>
  <option value="gemma4:e2b">💻 Ollama Lokal (Google Gemma 2B)</option>
  <option value="deepseek-ocr:latest">💻 Ollama Lokal (OCR)</option>
  <option value="claude-3-7-sonnet">🌐 Claude 3.7 Sonnet (Anthropic)</option>
  <option value="sonnet">🌐 Claude CLI (sonnet)</option>
  <option value="gpt-4o">🌐 OpenAI API (gpt-4o)</option>
  <option value="o4-mini">🌐 Codex CLI (o4-mini)</option>
  <option value="nousresearch/hermes-3-llama-3.1-8b">🌐 Hermes 3</option>
</datalist>

<div id="toast"></div>

<script>
const API = location.origin + '/api';
let _isEditing = false;

function toast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.style.display = 'block';
  setTimeout(() => { t.style.display = 'none'; }, 2800);
}

async function api(method, path, body = null) {
  try {
    const opts = { method, headers: {} };
    if (body) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }
    const res = await fetch(API + path, opts);
    return await res.json();
  } catch (err) {
    return { error: String(err) };
  }
}

async function refreshAll() {
  await Promise.all([refreshSlots(), refreshActivity()]);
}

async function refreshSlots() {
  const data = await api('GET', '/slots');
  if (!data || !data.ok) return;

  // Fackel Button
  const pref = (data.fackel_preference || 'compute').toLowerCase();
  const fackelBtn = document.getElementById('btn-fackel');
  if (pref === 'ollama') {
    fackelBtn.className = 'fackel-btn ollama';
    fackelBtn.textContent = '🔥 Fackel: Ollama (Priorität)';
  } else {
    fackelBtn.className = 'fackel-btn compute';
    fackelBtn.textContent = '⚙️ Fackel: Rechenjobs (Compute)';
  }

  const slots = data.slots || {};
  // Chat Slot
  if (slots.buddha_chat && !_isEditing) {
    const s = slots.buddha_chat;
    let b = s.backend || 'ollama';
    if (b === 'ollama' && s.model && s.model.includes(':cloud')) b = 'ollama-cloud';
    document.getElementById('chat-backend').value = b;
    document.getElementById('chat-model').value = s.model || '';
    document.getElementById('chat-turns').value = s.max_tool_rounds != null ? s.max_tool_rounds : 12;
    document.getElementById('chat-mode').value = s.mode || 'safe';
    document.getElementById('chat-think').checked = !!s.think;
    document.getElementById('chat-activity').textContent = s.current_activity || 'Bereit';
    document.getElementById('badge-buddha_chat').textContent = (s.status || 'ready').toUpperCase();
  }

  // Always-On Slot
  if (slots.buddha_always_on && !_isEditing) {
    const s = slots.buddha_always_on;
    let b = s.backend || 'ollama';
    if (b === 'ollama' && s.model && s.model.includes(':cloud')) b = 'ollama-cloud';
    document.getElementById('always-backend').value = b;
    document.getElementById('always-model').value = s.model || '';
    document.getElementById('always-turns').value = s.max_tool_rounds != null ? s.max_tool_rounds : 25;
    document.getElementById('always-mode').value = s.mode || 'full';
    document.getElementById('always-activity').textContent = s.current_activity || (s.enabled ? 'Wartet auf Idle-Schwelle' : 'Pausiert');
    const enabled = s.enabled !== false;
    const badge = document.getElementById('badge-buddha_always_on');
    badge.textContent = enabled ? 'AKTIV' : 'PAUSIERT';
    badge.className = 'badge ' + (enabled ? 'badge-ready' : 'badge-paused');
    document.getElementById('btn-toggle-always-on').textContent = enabled ? 'Pausieren' : 'Aktivieren';
  }

  // Connector Slot
  if (slots.buddha_connector && !_isEditing) {
    const s = slots.buddha_connector;
    let b = s.backend || 'ollama';
    if (b === 'ollama' && s.model && s.model.includes(':cloud')) b = 'ollama-cloud';
    document.getElementById('conn-backend').value = b;
    document.getElementById('conn-model').value = s.model || '';
    document.getElementById('conn-turns').value = s.max_tool_rounds != null ? s.max_tool_rounds : 10;
    document.getElementById('conn-activity').textContent = s.current_activity || 'Bereit';
  }

  // Dynamic Workers
  renderWorkers(data.dynamic_workers || []);
}

function renderWorkers(workers) {
  const container = document.getElementById('workers-container');
  if (!workers || workers.length === 0) {
    container.innerHTML = '<div style="color:#64748b;font-size:0.88rem;grid-column:1/-1;padding:12px;background:#1e293b;border-radius:8px;border:1px dashed #334155">Keine dynamischen Hintergrundworker aktiv. Klicke auf "+ Neuer Worker anlegen", um Aufgaben oder Rollen autonom ausführen zu lassen.</div>';
    return;
  }

  let html = '';
  for (const w of workers) {
    const st = w.status || 'idle';
    let badgeClass = 'badge-idle';
    if (st === 'running') badgeClass = 'badge-running';
    else if (st === 'paused') badgeClass = 'badge-paused';
    else if (st === 'error') badgeClass = 'badge-error';
    else if (st === 'expired' || st === 'completed') badgeClass = 'badge-expired';

    const expires = w.expires_at ? new Date(w.expires_at).toLocaleString() : 'Kein Ablauf';
    const taskBadge = w.task_id ? `<span style="color:#38bdf8">Task #${w.task_id}</span>` : `<span style="color:#94a3b8">${escapeHtml(w.category || 'General')}</span>`;
    
    // Sub-mode formatting
    let subModeLabel = '3.2 Taskworker';
    if (w.sub_mode === 'hintergrund_worker') subModeLabel = '3.1 Hintergrundworker';
    else if (w.sub_mode === 'boss_routing') subModeLabel = `3.3 Bossrouting (${w.max_experts || 3} Exp.)`;
    else if (w.sub_mode === 'expert_role') subModeLabel = w.multi_role ? '3.4 Multi-Role Pool' : `3.4 Experte: ${escapeHtml(w.role_id || w.role)}`;

    const sysPromptBadge = w.include_system_prompt !== false 
      ? '<span style="color:#10b981;font-size:0.75rem;font-weight:600">✓ SysPrompt</span>' 
      : '<span style="color:#f59e0b;font-size:0.75rem;font-weight:600">✗ Kein SysPrompt</span>';

    const isRunning = (st === 'running');
    const cardBorder = isRunning ? 'border:1px solid #38bdf8;box-shadow:0 0 12px rgba(56,189,248,0.25);' : '';
    const runBtn = isRunning 
      ? `<button class="btn btn-sm" style="background:#854d0e;color:#fef08a;cursor:not-allowed;font-weight:600" disabled>⏳ Läuft...</button>`
      : `<button class="btn btn-sm btn-success" id="btn-run-${w.id}" onclick="runWorker('${w.id}')">▶ Start</button>`;

    html += `
      <div class="worker-card" id="wcard-${w.id}" style="${cardBorder}">
        <div class="worker-top">
          <div class="worker-name">${escapeHtml(w.name || w.id)}</div>
          <span class="badge ${badgeClass}">${escapeHtml(st)}</span>
        </div>
        <div class="worker-meta">
          <div><strong>Modus:</strong> <span style="color:#38bdf8">${subModeLabel}</span> · ${taskBadge} · ${sysPromptBadge}</div>
          <div><strong>Modell:</strong> ${escapeHtml(w.model || '?')} (${escapeHtml(w.backend || 'ollama')})</div>
          <div><strong>Turns:</strong> ${w.max_tool_rounds || 20} · <strong>Modus:</strong> ${w.mode || 'full'}</div>
          <div><strong>Ablauf:</strong> ${expires}</div>
        </div>
        <div class="activity-box" style="min-height:30px">${escapeHtml(w.current_activity || 'Bereit')}</div>
        <div class="worker-actions">
          ${runBtn}
          <button class="btn btn-sm btn-secondary" onclick="openHistoryModal('${w.id}')">📜 Verlauf</button>
          <button class="btn btn-sm btn-secondary" onclick="toggleWorker('${w.id}', '${st}')">${st === 'paused' ? '▶ Aktiv' : '⏸ Pause'}</button>
          <button class="btn btn-sm btn-danger" onclick="deleteWorker('${w.id}')">🗑 Löschen</button>
        </div>
      </div>
    `;
  }
  container.innerHTML = html;
}

async function refreshActivity() {
  const data = await api('GET', '/activity?limit=30');
  const tbody = document.getElementById('activity-tbody');
  const history = (data && data.history) ? data.history : [];
  if (history.length === 0) {
    tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:#64748b">Noch keine Aktivitäten protokolliert</td></tr>';
    return;
  }

  let rows = '';
  for (const item of history) {
    const timeStr = item.timestamp ? new Date(item.timestamp).toLocaleTimeString() : '-';
    const st = item.status || 'ok';

    rows += `
      <tr>
        <td style="color:#94a3b8;font-size:0.8rem">${timeStr}</td>
        <td><strong>${escapeHtml(item.source || '-')}</strong></td>
        <td>${escapeHtml(item.activity || '-')}</td>
        <td><span class="badge badge-${st === 'running' ? 'running' : (st === 'error' ? 'error' : 'ready')}">${escapeHtml(st)}</span></td>
      </tr>
    `;
  }
  tbody.innerHTML = rows;
}

async function saveCoreSlot(slotId) {
  let updates = {};
  if (slotId === 'buddha_chat') {
    updates = {
      backend: document.getElementById('chat-backend').value,
      model: document.getElementById('chat-model').value.trim(),
      max_tool_rounds: parseInt(document.getElementById('chat-turns').value) || 0,
      mode: document.getElementById('chat-mode').value,
      think: document.getElementById('chat-think').checked,
    };
  } else if (slotId === 'buddha_always_on') {
    updates = {
      backend: document.getElementById('always-backend').value,
      model: document.getElementById('always-model').value.trim(),
      max_tool_rounds: parseInt(document.getElementById('always-turns').value) || 0,
      mode: document.getElementById('always-mode').value,
    };
  } else if (slotId === 'buddha_connector') {
    updates = {
      backend: document.getElementById('conn-backend').value,
      model: document.getElementById('conn-model').value.trim(),
      max_tool_rounds: parseInt(document.getElementById('conn-turns').value) || 0,
    };
  }
  const res = await api('POST', '/slots', { slot_id: slotId, updates });
  if (res && res.ok) {
    toast(`Slot ${slotId} gespeichert!`);
    refreshSlots();
  } else {
    toast(`Fehler beim Speichern: ${res.error || 'Unbekannt'}`);
  }
}

async function toggleAlwaysOn() {
  const currentBadge = document.getElementById('badge-buddha_always_on').textContent;
  const newEnabled = currentBadge !== 'AKTIV';
  const res = await api('POST', '/slots', {
    slot_id: 'buddha_always_on',
    updates: { enabled: newEnabled }
  });
  if (res && res.ok) {
    toast(newEnabled ? 'Buddha Always-On aktiviert' : 'Buddha Always-On pausiert');
    refreshSlots();
  }
}

async function toggleFackel() {
  const btn = document.getElementById('btn-fackel');
  const isOllama = btn.classList.contains('ollama');
  const newPref = isOllama ? 'compute' : 'ollama';
  const res = await api('POST', '/fackel', { preference: newPref });
  if (res && res.ok) {
    toast(newPref === 'ollama' ? 'Fackel an Ollama (Chat & Worker bevorzugt)' : 'Fackel an Rechenjobs (Compute bevorzugt)');
    refreshSlots();
  }
}

function showTab(tab) {
  const dash = document.getElementById('tab-dash');
  const prompts = document.getElementById('tab-prompts');
  const btnDash = document.getElementById('nav-btn-dash');
  const btnPrompts = document.getElementById('nav-btn-prompts');
  if (tab === 'prompts') {
    dash.style.display = 'none';
    prompts.style.display = 'block';
    btnPrompts.style.background = '#38bdf8';
    btnPrompts.style.color = '#0f172a';
    btnPrompts.style.fontWeight = '700';
    btnDash.style.background = 'transparent';
    btnDash.style.color = '#38bdf8';
    btnDash.style.fontWeight = 'normal';
    loadPromptTemplates();
  } else {
    prompts.style.display = 'none';
    dash.style.display = 'block';
    btnDash.style.background = '#38bdf8';
    btnDash.style.color = '#0f172a';
    btnDash.style.fontWeight = '700';
    btnPrompts.style.background = 'transparent';
    btnPrompts.style.color = '#38bdf8';
    btnPrompts.style.fontWeight = 'normal';
    refreshAll();
  }
}

let _promptTemplates = null;

async function loadPromptTemplates() {
  const res = await api('GET', '/prompts');
  if (!res || !res.ok || !res.templates) return;
  _promptTemplates = res.templates;

  const sys = _promptTemplates.system_default || {};
  document.getElementById('prompt-sys-text').value = sys.text || '';
  const badgeSys = document.getElementById('badge-prompt-sys');
  badgeSys.textContent = sys.is_custom ? 'Angepasst' : 'Werkstandard';
  badgeSys.className = 'badge ' + (sys.is_custom ? 'badge-running' : 'badge-ready');

  const roleSelect = document.getElementById('role-select').value;
  onRolePromptSelect(roleSelect);
}

function onRolePromptSelect(roleId) {
  if (!_promptTemplates || !_promptTemplates.roles) return;
  const role = _promptTemplates.roles[roleId] || {};
  document.getElementById('prompt-role-text').value = role.text || '';
  const badgeRole = document.getElementById('badge-prompt-role');
  badgeRole.textContent = role.is_custom ? 'Angepasst' : 'Werkstandard';
  badgeRole.className = 'badge ' + (role.is_custom ? 'badge-running' : 'badge-ready');
}

async function savePrompt(key) {
  let text = '';
  if (key === 'system_default') {
    text = document.getElementById('prompt-sys-text').value;
  } else if (key.startsWith('role_')) {
    text = document.getElementById('prompt-role-text').value;
  }
  const res = await api('POST', '/prompts', { key, text });
  if (res && res.ok) {
    toast(`Prompt '${key}' erfolgreich gespeichert!`);
    loadPromptTemplates();
  } else {
    toast(`Fehler beim Speichern: ${res.error || 'Unbekannt'}`);
  }
}

async function resetPrompt(key) {
  if (!confirm(`Prompt '${key}' wirklich auf den unveränderlichen Werkstandard zurücksetzen?`)) return;
  const res = await api('POST', '/prompts/reset', { key });
  if (res && res.ok) {
    toast(`Prompt '${key}' auf Werkstandard zurückgesetzt.`);
    loadPromptTemplates();
  } else {
    toast(`Fehler beim Zurücksetzen: ${res.error || 'Unbekannt'}`);
  }
}

function saveCurrentRolePrompt() {
  const roleId = document.getElementById('role-select').value;
  savePrompt('role_' + roleId);
}

function resetCurrentRolePrompt() {
  const roleId = document.getElementById('role-select').value;
  resetPrompt('role_' + roleId);
}

function openNewWorkerModal() {
  document.getElementById('new-worker-modal').style.display = 'flex';
  onSubModeChange(document.getElementById('nw-sub-mode').value);
}

function closeNewWorkerModal() {
  document.getElementById('new-worker-modal').style.display = 'none';
}

function onSubModeChange(subMode) {
  const bossFields = document.getElementById('nw-boss-fields');
  const expertFields = document.getElementById('nw-expert-fields');
  bossFields.style.display = subMode === 'boss_routing' ? 'block' : 'none';
  expertFields.style.display = subMode === 'expert_role' ? 'block' : 'none';
}

async function createWorker() {
  const name = document.getElementById('nw-name').value.trim();
  const subMode = document.getElementById('nw-sub-mode').value;
  const workerType = document.getElementById('nw-type').value;
  const backend = document.getElementById('nw-backend').value;
  const model = document.getElementById('nw-model').value.trim() || 'qwen3.8:27b-mlx';
  const turns = parseInt(document.getElementById('nw-turns').value) || 25;
  const mode = document.getElementById('nw-mode').value;
  const taskId = document.getElementById('nw-task-id').value.trim() ? parseInt(document.getElementById('nw-task-id').value) : null;
  const ttl = document.getElementById('nw-ttl').value ? parseInt(document.getElementById('nw-ttl').value) : null;
  const taskPrompt = document.getElementById('nw-task-prompt').value.trim();
  const includeSys = document.getElementById('nw-include-system-prompt').checked;

  let roleId = '';
  let multiRole = false;
  if (subMode === 'expert_role') {
    roleId = document.getElementById('nw-role-id').value;
    multiRole = document.getElementById('nw-multi-role').checked;
  }

  let maxExperts = 3;
  let expertModels = {};
  if (subMode === 'boss_routing') {
    maxExperts = parseInt(document.getElementById('nw-max-experts').value) || 3;
    const emStr = document.getElementById('nw-expert-models').value.trim();
    if (emStr) {
      try { expertModels = JSON.parse(emStr); } catch (e) { expertModels = { default: emStr }; }
    }
  }

  const payload = {
    name: name || `Worker-${subMode}`,
    sub_mode: subMode,
    role_id: roleId,
    multi_role: multiRole,
    max_experts: maxExperts,
    expert_models: expertModels,
    include_system_prompt: includeSys,
    task_prompt: taskPrompt,
    type: workerType,
    backend,
    model,
    max_tool_rounds: turns,
    mode,
    task_id: taskId,
    ttl_seconds: ttl,
  };

  const res = await api('POST', '/workers', payload);
  if (res && res.ok) {
    toast(`Worker '${res.worker.name}' gestartet!`);
    closeNewWorkerModal();
    document.getElementById('nw-name').value = '';
    document.getElementById('nw-task-id').value = '';
    document.getElementById('nw-task-prompt').value = '';
    refreshSlots();
  } else {
    toast(`Fehler: ${res.error || 'Worker konnte nicht erstellt werden'}`);
  }
}

async function openHistoryModal(chatId) {
  document.getElementById('history-modal-title').textContent = `📜 Session-Verlauf: ${chatId}`;
  const body = document.getElementById('history-modal-body');
  body.innerHTML = '<div style="color:#94a3b8;padding:20px;text-align:center">Lade Chat- und Werkzeugverlauf...</div>';
  document.getElementById('history-modal').style.display = 'flex';

  const res = await api('GET', `/chat/history?chat_id=${encodeURIComponent(chatId)}`);
  if (!res || !res.ok || !res.messages || res.messages.length === 0) {
    body.innerHTML = '<div style="color:#64748b;padding:24px;text-align:center">Noch keine Nachrichten oder Werkzeugläufe für diese Session vorhanden.</div>';
    return;
  }

  let html = '';
  for (const msg of res.messages) {
    const role = msg.role || 'unknown';
    const content = msg.content || '';
    const toolCalls = msg.tool_calls || [];
    let roleBadge = 'badge-idle';
    let roleLabel = role.toUpperCase();
    let bubbleStyle = 'background:#1e293b;border:1px solid #334155;';

    if (role === 'user') {
      roleBadge = 'badge-ready';
      roleLabel = 'USER / AUFTRAG';
      bubbleStyle = 'background:#0f172a;border:1px solid #38bdf8;';
    } else if (role === 'assistant') {
      roleBadge = 'badge-running';
      roleLabel = 'ASSISTANT';
      bubbleStyle = 'background:#1e293b;border:1px solid #10b981;';
    } else if (role === 'system') {
      roleBadge = 'badge-paused';
      roleLabel = 'SYSTEM';
      bubbleStyle = 'background:#1e1e2e;border:1px dashed #64748b;';
    } else if (role === 'tool') {
      roleBadge = 'badge-paused';
      roleLabel = 'TOOL RESULT';
      bubbleStyle = 'background:#182234;border:1px solid #f59e0b;';
    }

    html += `
      <div style="padding:10px 14px;border-radius:8px;${bubbleStyle}">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
          <span class="badge ${roleBadge}">${roleLabel}</span>
        </div>
        <div style="white-space:pre-wrap;word-break:break-word;font-size:0.86rem;color:#e2e8f0">${escapeHtml(content)}</div>
    `;
    if (toolCalls && toolCalls.length > 0) {
      html += `<div style="margin-top:8px;padding:6px 10px;background:#0f172a;border-radius:4px;font-size:0.8rem;color:#f59e0b">`;
      for (const tc of toolCalls) {
        const fn = tc.function || {};
        html += `<div>⚙️ <strong>${escapeHtml(fn.name || 'Tool')}</strong>(${escapeHtml(JSON.stringify(fn.arguments || {}))})</div>`;
      }
      html += `</div>`;
    }
    html += `</div>`;
  }
  body.innerHTML = html;
  body.scrollTop = body.scrollHeight;
}

function closeHistoryModal() {
  document.getElementById('history-modal').style.display = 'none';
}

async function runWorker(workerId) {
  const btn = document.getElementById(`btn-run-${workerId}`);
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = '⏳ Starte...';
    btn.style.background = '#854d0e';
    btn.style.color = '#fef08a';
  }
  const card = document.getElementById(`wcard-${workerId}`);
  if (card) {
    const actBox = card.querySelector('.activity-box');
    if (actBox) actBox.textContent = 'Starte Worker...';
    const badge = card.querySelector('.badge');
    if (badge) {
      badge.className = 'badge badge-running';
      badge.textContent = 'running';
    }
  }
  toast(`Starte Worker ${workerId}...`);
  const res = await api('POST', '/workers/run', { id: workerId });
  if (res && res.ok) {
    toast(`Worker ${workerId} läuft!`);
    refreshAll();
  } else {
    toast(`Fehler: ${res.error || 'Konnte nicht starten'}`);
    refreshAll();
  }
}

async function toggleWorker(workerId, currentStatus) {
  const newStatus = currentStatus === 'paused' ? 'idle' : 'paused';
  const res = await api('POST', '/workers/toggle', { id: workerId, status: newStatus });
  if (res && res.ok) {
    toast(`Worker ${workerId}: ${newStatus}`);
    refreshSlots();
  }
}

async function deleteWorker(workerId) {
  if (!confirm(`Worker ${workerId} wirklich löschen?`)) return;
  const res = await api('POST', '/workers/delete', { id: workerId });
  if (res && res.ok) {
    toast(`Worker ${workerId} gelöscht.`);
    refreshSlots();
  } else {
    toast(`Fehler: ${res.error || 'Löschen fehlgeschlagen'}`);
  }
}

function applyModelPreset(prefix, modelValue) {
  if (!modelValue) return;
  const mInput = document.getElementById(`${prefix}-model`);
  const bSelect = document.getElementById(`${prefix}-backend`);
  if (mInput) mInput.value = modelValue;
  if (!bSelect) return;

  const m = modelValue.toLowerCase();
  if (m.includes(':cloud')) {
    bSelect.value = 'ollama-cloud';
  } else if (m.includes('mlx') || m.includes('qwen') || m.includes('gemma') || m.includes('ocr') || m.includes('llama-guard')) {
    bSelect.value = 'ollama';
  } else if (m.includes('claude') || m.includes('sonnet') || m.includes('opus')) {
    bSelect.value = (bSelect.querySelector('option[value="claude-api"]') ? 'claude-api' : 'claude');
  } else if (m.includes('gpt') || m.includes('o3') || m.includes('o4')) {
    bSelect.value = (m.includes('o4-mini') && bSelect.querySelector('option[value="codex"]') ? 'codex' : 'openai');
  } else if (m.includes('hermes')) {
    bSelect.value = 'hermes';
  }
}

function onBackendChange(prefix) {
  const bSelect = document.getElementById(`${prefix}-backend`);
  const mInput = document.getElementById(`${prefix}-model`);
  if (!bSelect || !mInput) return;
  const val = bSelect.value;
  if (val === 'ollama-cloud') {
    if (!mInput.value || !mInput.value.includes(':cloud')) mInput.value = 'kimi-k3:cloud';
  } else if (val === 'ollama') {
    if (!mInput.value || mInput.value.includes(':cloud') || mInput.value.includes('sonnet') || mInput.value.includes('gpt')) {
      mInput.value = 'qwen3.8:27b-mlx';
    }
  } else if (val === 'claude' || val === 'claude-api') {
    if (!mInput.value || mInput.value.includes('qwen') || mInput.value.includes(':cloud')) {
      mInput.value = val === 'claude-api' ? 'claude-3-7-sonnet' : 'sonnet';
    }
  } else if (val === 'codex') {
    if (!mInput.value || mInput.value.includes('qwen') || mInput.value.includes(':cloud')) mInput.value = 'o4-mini';
  } else if (val === 'openai') {
    if (!mInput.value || mInput.value.includes('qwen') || mInput.value.includes(':cloud')) mInput.value = 'gpt-4o';
  } else if (val === 'hermes') {
    if (!mInput.value || mInput.value.includes('qwen') || mInput.value.includes(':cloud')) {
      mInput.value = 'nousresearch/hermes-3-llama-3.1-8b';
    }
  }
}

async function loadModelsIntoPresets() {
  const data = await api('GET', '/models');
  if (!data || !data.models || !Array.isArray(data.models)) return;
  const dl = document.getElementById('model-presets-list');
  if (!dl) return;
  let opts = '';
  for (const m of data.models) {
    const isCloud = m.includes(':cloud');
    const label = isCloud ? '☁️ Ollama Cloud' : '💻 Ollama Lokal';
    opts += `<option value="${escapeHtml(m)}">${label} (${escapeHtml(m)})</option>`;
  }
  opts += '<option value="claude-3-7-sonnet">🌐 Claude 3.7 Sonnet (Anthropic)</option>';
  opts += '<option value="sonnet">🌐 Claude CLI (sonnet)</option>';
  opts += '<option value="gpt-4o">🌐 OpenAI API (gpt-4o)</option>';
  opts += '<option value="o4-mini">🌐 Codex CLI (o4-mini)</option>';
  opts += '<option value="nousresearch/hermes-3-llama-3.1-8b">🌐 Hermes 3</option>';
  dl.innerHTML = opts;
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

document.addEventListener('focusin', (e) => {
  if (['INPUT', 'SELECT', 'TEXTAREA'].includes(e.target.tagName)) _isEditing = true;
});
document.addEventListener('focusout', () => { _isEditing = false; });

refreshAll();
loadModelsIntoPresets();
setInterval(refreshAll, 3000);
</script>
</body>
</html>"""


def _get_active_session_state():
    try:
        sessions_copy = list(runtime.sessions.values())
        if sessions_copy:
            s = sessions_copy[0]
            return s.model, s.mode, s.think
    except Exception:
        pass
    backend_model = ""
    try:
        backend_model = runtime.backend.get_default_model()
    except Exception:
        pass
    return (
        _global_defaults.get("model") or backend_model or "?",
        _global_defaults.get("mode", "safe"),
        _global_defaults.get("think", True),
    )


def _get_session_model(chat_id: str) -> str:
    with _runtime_state_lock:
        session = runtime.sessions.get(chat_id)
        session_model = str(getattr(session, "model", "") or "").strip()
        if session_model:
            return session_model

        configured_default = str(_global_defaults.get("model") or "").strip()
        return configured_default or runtime.backend.get_default_model()


def _snapshot_chat_backend(chat_id: str):
    with _runtime_state_lock:
        session = runtime.get_session(chat_id)
        try:
            target_backend, model = _apply_slot_to_session(chat_id, session)
            return target_backend, model
        except Exception:
            return runtime.backend, _get_session_model(chat_id)


def _checked_backend_availability(selected_backend, model: str) -> tuple[bool, str]:
    timeout = 8.0 if isinstance(selected_backend, CLIBackend) else 1.5
    try:
        available, status = selected_backend.availability(model=model, timeout=timeout)
    except Exception:
        return False, "Prüfung fehlgeschlagen"
    return available is True, str(status or "nicht verfügbar")


_BACKEND_INVENTORY_TTL_SECONDS = 30.0
_backend_inventory_lock = threading.Lock()
_backend_inventory_cache = {
    "expires_at": 0.0,
    "signature": None,
    "value": None,
}


def _invalidate_backend_inventory_cache() -> None:
    with _backend_inventory_lock:
        _backend_inventory_cache.update(
            expires_at=0.0,
            signature=None,
            value=None,
        )


def _copy_backend_inventory(value: dict[str, dict]) -> dict[str, dict]:
    return {name: dict(entry) for name, entry in value.items()}


def _probe_backend_inventory_entry(
    name: str,
    preset: dict,
    selected_id: str,
    selected_model: str,
) -> tuple[bool, str]:
    if name == selected_id:
        return _checked_backend_availability(runtime.backend, selected_model)

    try:
        candidate_config = {
            key: value
            for key, value in preset.items()
            if key not in ("method", "description")
        }
        if preset["method"] == "cli":
            cli_name = preset["type"].replace("-cli", "")
            if _check_cli_available(cli_name) != "vorhanden":
                raise FileNotFoundError(cli_name)
        elif name in ("claude-api", "openai"):
            api_key = _load_api_key(name)
            if not api_key:
                return False, "Key fehlt"
            candidate_config["api_key"] = api_key

        candidate = create_backend(candidate_config)
        return _checked_backend_availability(
            candidate,
            preset["default_model"],
        )
    except FileNotFoundError:
        return False, "nicht gefunden"
    except Exception:
        return False, "Prüfung fehlgeschlagen"


def _backend_inventory() -> dict[str, dict]:
    from concurrent.futures import ThreadPoolExecutor

    selected_id = backend_identifier(runtime.backend)
    selected_model, _, _ = _get_active_session_state()
    signature = (id(runtime.backend), selected_id, selected_model)
    now = time.monotonic()

    with _backend_inventory_lock:
        cached_value = _backend_inventory_cache["value"]
        if (
            cached_value is not None
            and _backend_inventory_cache["signature"] == signature
            and now < _backend_inventory_cache["expires_at"]
        ):
            return _copy_backend_inventory(cached_value)

        with ThreadPoolExecutor(max_workers=max(1, len(BACKEND_PRESETS))) as pool:
            futures = {
                name: pool.submit(
                    _probe_backend_inventory_entry,
                    name,
                    preset,
                    selected_id,
                    selected_model,
                )
                for name, preset in BACKEND_PRESETS.items()
            }
            backends = {}
            for name, preset in BACKEND_PRESETS.items():
                try:
                    available, status = futures[name].result()
                except Exception:
                    available, status = False, "Prüfung fehlgeschlagen"
                backends[name] = {
                    "description": preset["description"],
                    "method": preset["method"],
                    "default_model": preset["default_model"],
                    "status": status,
                    "available": available,
                    "selected": name == selected_id,
                }

        _backend_inventory_cache.update(
            expires_at=time.monotonic() + _BACKEND_INVENTORY_TTL_SECONDS,
            signature=signature,
            value=_copy_backend_inventory(backends),
        )
        return _copy_backend_inventory(backends)


def _control_chat_response(answer) -> tuple[dict, int]:
    text = str(answer or "").strip()
    if not text:
        return {"ok": False, "error": "Chat-Backend lieferte keine Antwort"}, 502
    if text.startswith(("Backend-Fehler:", "Fehler:")):
        return {"ok": False, "error": text}, 502
    return {"ok": True, "answer": text}, 200


def _is_trusted_host(host: str) -> bool:
    normalized = str(host or "").strip().strip("[]").lower()
    if normalized in ("localhost", "127.0.0.1", "::1", "macstudvonlukas", "workstation-lg", "asus-gei"):
        return True
    if normalized.endswith(".local") or normalized.endswith(".internal"):
        return True
    try:
        ip = ipaddress.ip_address(normalized)
        if ip.is_loopback or ip.is_private:
            return True
        # Tailscale Carrier Grade NAT range 100.64.0.0/10
        if ip in ipaddress.ip_network("100.64.0.0/10"):
            return True
    except ValueError:
        pass
    return False


def _is_loopback_host(host: str) -> bool:
    normalized = str(host or "").strip().strip("[]")
    if normalized.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _is_allowed_origin(origin: str, req_host: str = "") -> bool:
    if not origin:
        return True
    parsed = urlparse(str(origin or "").strip())
    if parsed.scheme not in {"http", "https"}:
        return False
    if parsed.username or parsed.password:
        return False
    # Same-Origin match against request Host header
    if req_host:
        norm_req_host = req_host.split(":")[0].strip().lower()
        if parsed.hostname and parsed.hostname.lower() == norm_req_host:
            return True
    return _is_trusted_host(parsed.hostname or "")


def _is_loopback_origin(origin: str) -> bool:
    """Kompatibilitäts-Wrapper."""
    return _is_allowed_origin(origin)


def _control_bind_host() -> str:
    bind_host = os.environ.get("BACH_CONTROL_HOST", "127.0.0.1").strip()
    allow_remote = os.environ.get("BACH_CONTROL_ALLOW_REMOTE", "").strip().lower() in ("1", "true", "yes", "on")
    if not allow_remote and not _is_loopback_host(bind_host):
        raise ValueError(
            "Control API darf ohne authentifizierten Ingress nur an Loopback binden"
        )
    return bind_host


class QuietHTTPServer(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        if isinstance(exc, (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)):
            return
        super().handle_error(request, client_address)


class ControlHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        log.debug("ControlAPI: " + fmt % args)

    def handle_one_request(self):
        try:
            super().handle_one_request()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def _cors(self):
        origin = str(self.headers.get("Origin") or "").strip()
        host = str(self.headers.get("Host") or "").strip()
        if not _is_allowed_origin(origin, host):
            return
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode()
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self._cors()
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def _html(self, html):
        body = html.encode()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self._cors()
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length:
            try:
                return json.loads(self.rfile.read(length))
            except (json.JSONDecodeError, UnicodeDecodeError):
                return {}
        return {}

    def _allow_json_post(self) -> bool:
        origin = str(self.headers.get("Origin") or "").strip()
        host = str(self.headers.get("Host") or "").strip()
        if origin and not _is_allowed_origin(origin, host):
            self._json({"error": "Fremd-Origin nicht erlaubt"}, 403)
            return False

        content_type = str(self.headers.get("Content-Type") or "")
        media_type = content_type.partition(";")[0].strip().lower()
        if media_type != "application/json":
            self._json({"error": "Content-Type application/json erforderlich"}, 415)
            return False
        return True

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_GET(self):
        parsed_url = urlparse(self.path)
        path = parsed_url.path

        if path == "/":
            self._html(WEB_DASHBOARD)

        elif path == "/api/status":
            try:
                model, mode, think = _get_active_session_state()
                backend_name = type(runtime.backend).__name__
                cli_name = getattr(runtime.backend, "cli_name", "")
                owns_tools = getattr(runtime.backend, "manages_own_tools", False)
                active_tools = []
                current_tool = ""
                tool_round = 0
                sessions_snapshot = list(runtime.sessions.values())
                for s in sessions_snapshot:
                    if s.current_tool:
                        current_tool = s.current_tool
                        tool_round = s.tool_round
                    if s.last_tools:
                        active_tools = s.last_tools
                        break
                _SYS_IDS = {"idle-worker", "tray-prompt", "api-delegate", "claude-delegate"}
                now = time.time()
                items_snapshot = list(runtime.sessions.items())
                active_user = sum(
                    1 for cid, s in items_snapshot
                    if cid not in _SYS_IDS and (s.current_tool or now - s.last_active < 120)
                )
                self._json({
                    "service": "bach-chat-control",
                    "telegram_verified": TELEGRAM_VERIFIED,
                    "backend": backend_name,
                    "backend_id": backend_identifier(runtime.backend),
                    "backend_cli": cli_name,
                    "model": model,
                    "mode": mode,
                    "think": think,
                    "manages_own_tools": owns_tools,
                    "bach": HAS_BACH,
                    "sessions": len(sessions_snapshot),
                    "active_sessions": active_user,
                    "max_tool_rounds": runtime.max_tool_rounds,
                    "fackel_preference": get_fackel_preference(),
                    "current_tool": current_tool,
                    "tool_round": tool_round,
                    "last_tools": active_tools,
                })
            except Exception as e:
                logger.warning(f"/api/status Snapshot-Fehler abgefangen: {e}")
                self._json({
                    "service": "bach-chat-control",
                    "telegram_verified": TELEGRAM_VERIFIED,
                    "backend": type(runtime.backend).__name__,
                    "backend_id": backend_identifier(runtime.backend),
                    "backend_cli": getattr(runtime.backend, "cli_name", ""),
                    "model": _global_defaults.get("model") or getattr(runtime.backend, "get_default_model", lambda: "?")(),
                    "mode": _global_defaults.get("mode", "safe"),
                    "think": _global_defaults.get("think", True),
                    "manages_own_tools": getattr(runtime.backend, "manages_own_tools", False),
                    "bach": HAS_BACH,
                    "sessions": len(list(runtime.sessions.keys())),
                    "active_sessions": 0,
                    "max_tool_rounds": runtime.max_tool_rounds,
                    "fackel_preference": get_fackel_preference(),
                    "current_tool": "",
                    "tool_round": 0,
                    "last_tools": [],
                })

        elif path == "/api/backends":
            self._json(_backend_inventory())

        elif path == "/api/readiness":
            chat_id = parse_qs(parsed_url.query).get("chat_id", ["api-delegate"])[0]
            selected_backend, model = _snapshot_chat_backend(chat_id)
            available, availability_status = _checked_backend_availability(
                selected_backend,
                model,
            )
            self._json({
                "available": available,
                "status": availability_status,
                "backend_id": backend_identifier(selected_backend),
                "model": model,
            })

        elif path == "/api/models":
            try:
                with _runtime_state_lock:
                    selected_backend = runtime.backend
                models = selected_backend.list_models()
                self._json({"models": models})
            except Exception as e:
                self._json({"error": str(e)}, 500)

        elif path == "/api/history":
            chat_id = parse_qs(parsed_url.query).get("chat_id", ["gui-web"])[0]
            self._json({"ok": True, "chat_id": chat_id, "messages": runtime.history(chat_id)})

        elif path == "/api/sessions":
            limit = int(parse_qs(parsed_url.query).get("limit", [50])[0])
            if runtime.session_store:
                try:
                    snapshots = runtime.session_store.list_snapshots(limit=limit)
                    self._json({"ok": True, "sessions": snapshots})
                except Exception as e:
                    self._json({"error": str(e)}, 500)
            else:
                self._json({"ok": False, "error": "Kein SessionStore konfiguriert"}, 500)

        elif path == "/api/session":
            try:
                sid = int(parse_qs(parsed_url.query).get("id", [0])[0])
            except ValueError:
                sid = 0
            if runtime.session_store and sid > 0:
                try:
                    snap = runtime.session_store.get_snapshot_by_id(sid)
                    if snap:
                        self._json({"ok": True, "session": snap})
                    else:
                        self._json({"error": "Snapshot nicht gefunden"}, 404)
                except Exception as e:
                    self._json({"error": str(e)}, 500)
            else:
                self._json({"error": "Ungültige oder fehlende Snapshot-ID"}, 400)

        elif path == "/activity":
            self._html(WEB_ACTIVITY_DASHBOARD)

        elif path == "/api/slots":
            try:
                cfg = load_slots_config()
                self._json({
                    "ok": True,
                    "slots": cfg.get("slots", {}),
                    "dynamic_workers": list_workers(include_expired=True),
                    "fackel_preference": get_fackel_preference(),
                })
            except Exception as e:
                self._json({"error": str(e)}, 500)

        elif path == "/api/workers":
            try:
                self._json({
                    "ok": True,
                    "workers": list_workers(include_expired=True),
                })
            except Exception as e:
                self._json({"error": str(e)}, 500)

        elif path == "/api/activity":
            try:
                limit = int(parse_qs(parsed_url.query).get("limit", [50])[0])
                self._json({
                    "ok": True,
                    "history": get_activity_history(limit=limit),
                })
            except Exception as e:
                self._json({"error": str(e)}, 500)

        elif path == "/api/prompts":
            try:
                self._json({
                    "ok": True,
                    "templates": get_prompt_templates(),
                })
            except Exception as e:
                self._json({"error": str(e)}, 500)

        elif path == "/api/chat/history":
            chat_id = parse_qs(parsed_url.query).get("chat_id", [""])[0]
            if not chat_id:
                self._json({"error": "chat_id erforderlich"}, 400)
            else:
                try:
                    msgs = []
                    session = runtime.sessions.get(chat_id)
                    if session and session.messages:
                        msgs = session.messages
                    elif runtime.session_store:
                        msgs = runtime._load_messages(chat_id)
                    self._json({
                        "ok": True,
                        "chat_id": chat_id,
                        "messages": msgs,
                    })
                except Exception as e:
                    self._json({"error": str(e)}, 500)

        else:
            self._json({"error": "Not found"}, 404)

    def do_POST(self):
        if not self._allow_json_post():
            return
        path = urlparse(self.path).path
        body = self._read_body()
        if not isinstance(body, dict):
            self._json({"error": "JSON-Objekt erforderlich"}, 400)
            return

        if path == "/api/backend":
            name = body.get("name", "")
            model = body.get("model", "")
            if name not in BACKEND_PRESETS:
                self._json({"error": f"Unbekannt: {name}"}, 400)
                return
            preset = BACKEND_PRESETS[name].copy()
            if model:
                preset["default_model"] = model
            elif name == "ollama":
                current_m = _global_defaults.get("model") or getattr(runtime.backend, "default_model", None)
                if current_m:
                    preset["default_model"] = current_m
            if preset["method"] == "api" and name in ("claude-api", "openai"):
                api_key = _load_api_key(name)
                if not api_key:
                    self._json({"error": f"Kein API-Key für {name}"}, 400)
                    return
                preset["api_key"] = api_key
            try:
                config = {k: v for k, v in preset.items()
                          if k not in ("method", "description")}
                new_backend = create_backend(config)
                selected_model = preset["default_model"]
                available, availability_status = _checked_backend_availability(
                    new_backend,
                    selected_model,
                )
                if not available:
                    self._json({
                        "ok": False,
                        "error": f"Backend nicht verfügbar: {availability_status}",
                    }, 503)
                    return
                with _runtime_state_lock:
                    runtime.backend = new_backend
                    _global_defaults["model"] = selected_model
                    for s in list(runtime.sessions.values()):
                        s.model = selected_model
                _invalidate_backend_inventory_cache()
                self._json({"ok": True, "backend": name, "model": preset["default_model"]})
            except Exception as e:
                self._json({"error": str(e)}, 500)

        elif path == "/api/mode":
            mode = body.get("mode", "")
            if mode not in ("safe", "full"):
                self._json({"error": "safe oder full"}, 400)
                return
            _global_defaults["mode"] = mode
            for s in list(runtime.sessions.values()):
                s.mode = mode
            self._json({"ok": True, "mode": mode})

        elif path == "/api/model":
            model = body.get("model", "")
            if not model:
                self._json({"error": "model erforderlich"}, 400)
                return
            _global_defaults["model"] = model
            for s in list(runtime.sessions.values()):
                s.model = model
            self._json({"ok": True, "model": model})

        elif path == "/api/think":
            think = body.get("think", True)
            _global_defaults["think"] = bool(think)
            for s in list(runtime.sessions.values()):
                s.think = bool(think)
            self._json({"ok": True, "think": bool(think)})

        elif path == "/api/max_tool_rounds":
            rounds = int(body.get("rounds", 0))
            if rounds < 0:
                rounds = 0
            runtime.max_tool_rounds = rounds
            _global_defaults["max_tool_rounds"] = rounds
            self._json({"ok": True, "max_tool_rounds": rounds})

        elif path == "/api/fackel":
            pref = str(body.get("preference", "")).lower().strip()
            if pref not in ("compute", "ollama"):
                self._json({"error": "preference muss 'compute' oder 'ollama' sein"}, 400)
                return
            try:
                set_fackel_preference(pref)
            except Exception as e:
                self._json({"error": f"Konnte Fackel nicht setzen: {e}"}, 500)
                return
            self._json({"ok": True, "fackel_preference": pref})

        elif path == "/api/chat":
            prompt = body.get("prompt", "")
            chat_id = body.get("chat_id", "api-delegate")
            depth = int(self.headers.get("X-Delegation-Depth", "0"))
            if not prompt:
                self._json({"error": "prompt erforderlich"}, 400)
                return
            if depth >= 2:
                self._json({"error": "Maximale Delegationstiefe erreicht"}, 429)
                return
            selected_backend, model = _snapshot_chat_backend(chat_id)
            available, availability_status = _checked_backend_availability(
                selected_backend,
                model,
            )
            if not available:
                self._json({
                    "ok": False,
                    "error": f"Backend nicht verfügbar: {availability_status}",
                }, 503)
                return
            os.environ["BACH_DELEGATION_DEPTH"] = str(depth + 1)
            try:
                loop = asyncio.new_event_loop()
                try:
                    answer = loop.run_until_complete(
                        runtime.process(
                            prompt,
                            chat_id,
                            backend=selected_backend,
                            model=model,
                        )
                    )
                finally:
                    loop.close()
                if not isinstance(answer, FailedAnswer):
                    response, status = _control_chat_response(answer)
                    self._json(response, status)
                else:
                    self._json({"ok": False, "error": str(answer)}, 502)
            except ComputeLocked as e:
                self._json({"ok": False, "compute_locked": True, "answer": str(e)})
            except Exception as e:
                self._json({"error": str(e)}, 500)
            finally:
                os.environ.pop("BACH_DELEGATION_DEPTH", None)

        elif path == "/api/clear":
            chat_id = body.get("chat_id", "gui-web")
            archived_id = runtime.clear_session(chat_id, archive_reason="Control-API")
            self._json({"ok": True, "chat_id": chat_id, "archived_id": archived_id})

        elif path == "/api/fork":
            chat_id = body.get("chat_id", "gui-web")
            try:
                snapshot_id = int(body.get("snapshot_id", 0))
            except (TypeError, ValueError):
                snapshot_id = 0
            if snapshot_id <= 0:
                self._json({"error": "snapshot_id erforderlich"}, 400)
                return
            try:
                count = runtime.fork_session(chat_id, snapshot_id)
                self._json({"ok": True, "chat_id": chat_id, "snapshot_id": snapshot_id, "messages_count": count})
            except Exception as e:
                self._json({"error": str(e)}, 500)

        elif path == "/api/slots":
            slot_id = body.get("slot_id") or body.get("id")
            updates = body.get("updates") or {}
            if not slot_id or not isinstance(updates, dict):
                self._json({"error": "slot_id und updates dict erforderlich"}, 400)
                return
            try:
                updated = update_slot(slot_id, updates)
                record_activity(slot_id, f"Slot {slot_id} aktualisiert", "ok")
                self._json({"ok": True, "slot": updated})
            except KeyError as e:
                self._json({"error": str(e)}, 404)
            except Exception as e:
                self._json({"error": str(e)}, 500)

        elif path == "/api/workers":
            try:
                worker = add_worker(body)
                record_activity("system", f"Neuer Worker erstellt: {worker.get('name', worker.get('id'))}", "ok")
                self._json({"ok": True, "worker": worker})
            except Exception as e:
                self._json({"error": str(e)}, 500)

        elif path in ("/api/workers/delete", "/api/worker/delete"):
            worker_id = body.get("id") or body.get("worker_id")
            if not worker_id:
                self._json({"error": "id erforderlich"}, 400)
                return
            ok = remove_worker(worker_id)
            if ok:
                record_activity("system", f"Worker gelöscht: {worker_id}", "ok")
                self._json({"ok": True, "id": worker_id})
            else:
                self._json({"error": f"Worker {worker_id} nicht gefunden"}, 404)

        elif path == "/api/workers/toggle":
            worker_id = body.get("id") or body.get("worker_id")
            new_status = body.get("status")
            if not worker_id:
                self._json({"error": "id erforderlich"}, 400)
                return
            try:
                w = get_slot(worker_id)
                if not w:
                    self._json({"error": "Worker nicht gefunden"}, 404)
                    return
                if not new_status:
                    new_status = "paused" if w.get("status") != "paused" else "idle"
                updated = update_slot(worker_id, {"status": new_status})
                record_activity(worker_id, f"Worker Status: {new_status}", "ok")
                self._json({"ok": True, "worker": updated})
            except Exception as e:
                self._json({"error": str(e)}, 500)

        elif path == "/api/workers/run":
            worker_id = body.get("id") or body.get("worker_id")
            custom_prompt = body.get("prompt")
            w = get_slot(worker_id)
            if not w:
                self._json({"error": f"Worker {worker_id} nicht gefunden"}, 404)
                return
            def _run_worker_job():
                try:
                    update_slot(worker_id, {"status": "running", "current_activity": "Starte Routine..."})
                    record_activity(worker_id, f"Worker gestartet: {w.get('name')}", "running")
                    target_backend, model = _snapshot_chat_backend(worker_id)
                    
                    if custom_prompt:
                        task_prompt = custom_prompt
                    elif w.get("task_id"):
                        task_prompt = f"Führe Task #{w.get('task_id')} aus und schließe ihn ab."
                    elif w.get("sub_mode") == "hintergrund_worker":
                        task_prompt = "Prüfe offene Tasks in BACH und bearbeite die wichtigste offene Aufgabe autonom."
                    elif w.get("sub_mode") == "boss_routing":
                        task_prompt = "Analysiere die anstehenden Aufgaben in BACH, koordiniere die Experten und weise Teilaufgaben zu."
                    elif w.get("sub_mode") == "expert_role":
                        role = w.get("role_id") or "Experte"
                        task_prompt = f"Arbeite als {role} die offenen Aufgaben deines Fachgebiets in BACH ab."
                    else:
                        task_prompt = w.get("task_prompt") or "Prüfe offene Aufgaben und beginne mit der Bearbeitung."

                    loop = asyncio.new_event_loop()
                    try:
                        ans = loop.run_until_complete(
                            runtime.process(task_prompt, worker_id, backend=target_backend, model=model)
                        )
                        next_status = "completed" if w.get("type") == "once" else "idle"
                        update_slot(worker_id, {"status": next_status, "current_activity": "Abgeschlossen"})
                        record_activity(worker_id, f"Fertig: {str(ans)[:60]}", "ok")
                    finally:
                        loop.close()
                except Exception as exc:
                    log.error(f"Worker {worker_id} Fehler: {exc}")
                    update_slot(worker_id, {"status": "error", "current_activity": f"Fehler: {exc}"})
                    record_activity(worker_id, f"Fehler: {exc}", "error")
            threading.Thread(target=_run_worker_job, daemon=True).start()
            self._json({"ok": True, "message": f"Worker {worker_id} gestartet"})

        elif path == "/api/activity":
            source = body.get("source", "system")
            act = body.get("activity", "")
            st = body.get("status", "ok")
            dt = body.get("details", {})
            record_activity(source, act, st, dt)
            self._json({"ok": True})

        elif path == "/api/prompts":
            key = str(body.get("key", "")).strip()
            text = body.get("text", "")
            if not key or text is None:
                self._json({"error": "key und text erforderlich"}, 400)
                return
            try:
                update_prompt_template(key, text)
                record_activity("system", f"Prompt-Vorlage {key} aktualisiert", "ok")
                self._json({"ok": True, "key": key})
            except Exception as e:
                self._json({"error": str(e)}, 500)

        elif path == "/api/prompts/reset":
            key = body.get("key")
            try:
                reset_prompt_template(key)
                record_activity("system", f"Prompt-Vorlage(n) zurückgesetzt: {key or 'alle'}", "ok")
                self._json({"ok": True, "key": key})
            except Exception as e:
                self._json({"error": str(e)}, 500)

        else:
            self._json({"error": "Not found"}, 404)

    def do_DELETE(self):
        parsed_url = urlparse(self.path)
        path = parsed_url.path
        if path == "/api/workers":
            params = parse_qs(parsed_url.query)
            worker_id = params.get("id", [""])[0]
            if not worker_id:
                self._json({"error": "id erforderlich"}, 400)
                return
            ok = remove_worker(worker_id)
            if ok:
                record_activity("system", f"Worker gelöscht: {worker_id}", "ok")
                self._json({"ok": True, "id": worker_id})
            else:
                self._json({"error": f"Worker {worker_id} nicht gefunden"}, 404)
        else:
            self._json({"error": "Method not allowed"}, 405)


def start_control_api():
    try:
        bind_host = _control_bind_host()
        server = QuietHTTPServer((bind_host, CONTROL_PORT), ControlHandler)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        actual_port = int(server.server_port)
        log.info("Control API auf %s:%s", bind_host, actual_port)
        print(f"Web-Dashboard: http://localhost:{actual_port}/")
        return server
    except (OSError, ValueError) as e:
        log.warning(f"Control API konnte nicht starten: {e}")
        return None


def verify_telegram_token() -> bool:
    """Verifiziert den Bot ohne Token oder Request-URL in Fehlerlogs offenzulegen."""
    try:
        response = httpx.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/getMe",
            timeout=8.0,
        )
    except httpx.HTTPError:
        log.error("Telegram-Verifikation nicht erreichbar")
        return False
    if response.status_code != 200:
        log.error("Telegram-Verifikation abgelehnt (HTTP %s)", response.status_code)
        return False
    try:
        payload = response.json()
    except ValueError:
        log.error("Telegram-Verifikation lieferte kein gültiges JSON")
        return False
    return bool(payload.get("ok") and payload.get("result", {}).get("id"))


def serve_control_only(server, reason: str) -> None:
    """Keep local Chat/Control available when the Telegram connector is offline."""
    message = f"{reason}; lokaler Chat/Control läuft im Offlinebetrieb weiter."
    log.warning(message)
    print(message)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()


# --- Main ---

def main():
    global TELEGRAM_VERIFIED
    control_server = start_control_api()
    if control_server is None:
        print("Chat/Control konnte nicht gestartet werden.")
        return 1

    # Crash recovery: resume any compute jobs stopped by a previous bot session
    if HAS_COMPUTE_LOCK and CONFIG.get("compute_lock", {}).get("enabled", False):
        try:
            resumed = recover_paused_jobs()
            if resumed:
                log.info("Crash recovery: resumed PIDs %s", resumed)
                print(f"Compute Lock: {len(resumed)} Jobs nach Crash resumed: {resumed}")
            else:
                print("Compute Lock: kein Crash-Recovery noetig")
        except Exception as e:
            log.warning("Crash recovery failed: %s", e)

    if not BOT_TOKEN:
        serve_control_only(control_server, "Kein Telegram-Bot-Token")
        return 0
    if not verify_telegram_token():
        serve_control_only(control_server, "Telegram-Bot konnte nicht verifiziert werden")
        return 0
    TELEGRAM_VERIFIED = True
    print("Telegram Bot verifiziert")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("clear", cmd_clear))
    app.add_handler(CommandHandler("think", cmd_think))
    app.add_handler(CommandHandler("nothink", cmd_nothink))
    app.add_handler(CommandHandler("mode", cmd_mode))
    app.add_handler(CommandHandler("model", cmd_model))
    app.add_handler(CommandHandler("backend", cmd_backend))
    app.add_handler(CommandHandler("maxrounds", cmd_maxrounds))
    app.add_handler(CommandHandler("settings", cmd_settings))
    app.add_handler(CommandHandler("fackel", cmd_fackel))

    if HAS_BACH:
        app.add_handler(CommandHandler("remember", cmd_remember))
        app.add_handler(CommandHandler("recall", cmd_recall))
        app.add_handler(CommandHandler("facts", cmd_facts))
        app.add_handler(CommandHandler("bach", cmd_bach))
        app.add_handler(CommandHandler("task", cmd_task))
        app.add_handler(CommandHandler("tasks", cmd_tasks))
        app.add_handler(CommandHandler("status", cmd_status))

    app.add_handler(CommandHandler("voice", cmd_voice))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voice))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    backend_type = CONFIG["backend"].get("type", "ollama")
    model = backend.get_default_model()
    cl_status = "AN" if _compute_lock_enabled() else "AUS"
    print(
        f"BACH Telegram Chat gestartet "
        f"(BACH: {'JA' if HAS_BACH else 'NEIN'}, "
        f"Backend: {backend_type}, Modell: {model}, Think: AN, "
        f"Compute-Lock: {cl_status})"
    )
    try:
        app.run_polling(allowed_updates=Update.ALL_TYPES)
    finally:
        control_server.shutdown()
        control_server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
