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
import json
import logging
import os
import sys
import tempfile
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, os.path.expanduser("~/services/bach/system"))

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
from hub._services.llm.model_backend import create_backend, OllamaBackend
from hub._services.chat.chat_runtime import ChatRuntime

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
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
        "default_model": "qwen3.5:35b-a3b",
    })

    if not config["bot_token"]:
        config["bot_token"] = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not config["bot_token"]:
        tf = os.path.expanduser("~/.credentials/telegram_bot_token")
        if os.path.exists(tf):
            config["bot_token"] = open(tf).read().strip()

    if not config["owner_id"]:
        config["owner_id"] = os.environ.get("TELEGRAM_OWNER_ID", "")
    if not config["owner_id"]:
        of = os.path.expanduser("~/.credentials/telegram_owner_id")
        if os.path.exists(of):
            config["owner_id"] = open(of).read().strip()

    env_model = os.environ.get("OLLAMA_MODEL")
    if env_model:
        config["backend"]["default_model"] = env_model
    env_url = os.environ.get("OLLAMA_URL")
    if env_url:
        config["backend"]["base_url"] = env_url

    return config


CONFIG = load_config()
BOT_TOKEN = CONFIG["bot_token"]
OWNER_ID = CONFIG["owner_id"]

# Backend + Runtime initialisieren
backend = create_backend(CONFIG["backend"])

system_file = os.path.expanduser("~/services/bach/system/data/system_prompt_buddha.txt")
if os.path.exists(system_file):
    system_prompt = open(system_file).read().strip()
else:
    system_prompt = "Du bist ein persönlicher KI-Assistent auf dem Mac Studio. Antworte auf Deutsch, präzise und klar."

runtime = ChatRuntime(
    backend=backend,
    system_prompt=system_prompt,
    bach_app=_bach_app if HAS_BACH else None,
    memory_fn=_memory if HAS_BACH else None,
    injector=_injector if HAS_BACH else None,
)

_global_defaults = {
    "mode": "safe",
    "think": True,
    "model": "",
}

_orig_get_session = runtime.get_session

def _patched_get_session(chat_id: str):
    session = _orig_get_session(chat_id)
    if len(session.messages) == 0:
        if _global_defaults.get("mode"):
            session.mode = _global_defaults["mode"]
        if _global_defaults.get("model"):
            session.model = _global_defaults["model"]
        session.think = _global_defaults.get("think", True)
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
    runtime.clear_session(str(update.effective_chat.id))
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
        "default_model": os.environ.get("OLLAMA_MODEL", "qwen3.5:35b-a3b"),
        "method": "api",
        "description": "Lokales Ollama (Qwen, Llama, etc.)",
    },
    "claude": {
        "type": "claude-cli",
        "default_model": "sonnet",
        "method": "cli",
        "description": "Claude Code CLI (--continue Session)",
    },
    "claude-api": {
        "type": "claude-api",
        "default_model": "claude-sonnet-4-20250514",
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


def _check_api_key(name: str) -> str:
    key_map = {
        "claude-api": ("ANTHROPIC_API_KEY", "anthropic_api_key"),
        "openai": ("OPENAI_API_KEY", "openai_api_key"),
    }
    if name not in key_map:
        return ""
    env_var, file_name = key_map[name]
    key_file = os.path.expanduser(f"~/.credentials/{file_name}")
    has_key = bool(os.environ.get(env_var)) or os.path.exists(key_file)
    return "Key vorhanden" if has_key else "Key fehlt"


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
        lines.append("  /backend ollama qwen3.5:35b-a3b")
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
        env_var = "ANTHROPIC_API_KEY" if "claude" in name else "OPENAI_API_KEY"
        file_name = "anthropic_api_key" if "claude" in name else "openai_api_key"
        key_file = os.path.expanduser(f"~/.credentials/{file_name}")
        api_key = os.environ.get(env_var, "")
        if not api_key and os.path.exists(key_file):
            api_key = open(key_file).read().strip()
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
        runtime.backend = new_backend
        session = runtime.get_session(str(update.effective_chat.id))
        session.model = preset["default_model"]

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
    await update.message.reply_text(
        f"Backend: {CONFIG['backend'].get('type', 'ollama')}\n"
        f"Modus: {session.mode}\n"
        f"Denken: {'AN' if session.think else 'AUS'}\n"
        f"Modell: {session.model}\n"
        f"BACH: {'Ja' if HAS_BACH else 'Nein'}\n"
        f"Kontext: {n_msgs} Nachrichten, ~{chars:,} Zeichen"
    )


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
    if HAS_BACH:
        try:
            ok, out = _bach_app.execute("status", "", [])
            parts.append(str(out)[:1500])
        except Exception:
            parts.append("BACH: Fehler")
    await update.message.reply_text("\n\n".join(parts)[:4000])


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


# --- Hauptnachrichten-Handler ---

async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _owner_check(update):
        await update.message.reply_text("Zugriff nur für den Owner.")
        return

    text = update.message.text
    if not text:
        return

    chat_id = str(update.effective_chat.id)
    typing = asyncio.create_task(_keep_typing(update))

    try:
        answer = await runtime.process(text, chat_id)
        for i in range(0, len(answer), 4000):
            await update.message.reply_text(answer[i:i + 4000])
    except Exception as e:
        log.error(f"Chat-Fehler: {e}")
        await update.message.reply_text(f"Fehler: {e}")
    finally:
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
<h1>BACH Chat Control</h1>

<div class="card" id="status-card">
<h2><span class="dot green" id="conn-dot"></span>Status</h2>
<div class="status-row"><span class="label">Backend</span><span class="value" id="s-backend">-</span></div>
<div class="status-row"><span class="label">Modell</span><span class="value" id="s-model">-</span></div>
<div class="status-row"><span class="label">Modus</span><span class="value" id="s-mode">-</span></div>
<div class="status-row"><span class="label">Denken</span><span class="value" id="s-think">-</span></div>
<div class="status-row"><span class="label">BACH</span><span class="value" id="s-bach">-</span></div>
<div class="status-row"><span class="label">Sessions</span><span class="value" id="s-sessions">-</span></div>
</div>

<div class="card">
<h2>Backend</h2>
<div class="btn-group" id="backend-btns"></div>
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

  const bs = await api('GET', '/backends');
  if (!bs.error) {
    const c = document.getElementById('backend-btns');
    c.innerHTML = '';
    for (const [name, info] of Object.entries(bs)) {
      const b = document.createElement('button');
      b.className = 'btn';
      b.textContent = name + (info.status ? ' [' + info.status + ']' : '');
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
refresh();
setInterval(refresh, 5000);
</script>
</body>
</html>"""


def _get_active_session_state():
    if runtime.sessions:
        sid = next(iter(runtime.sessions))
        s = runtime.sessions[sid]
        return s.model, s.mode, s.think
    return (
        _global_defaults["model"] or runtime.backend.get_default_model(),
        _global_defaults["mode"],
        _global_defaults["think"],
    )


class ControlHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        log.debug("ControlAPI: " + fmt % args)

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _html(self, html):
        body = html.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length:
            return json.loads(self.rfile.read(length))
        return {}

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/":
            self._html(WEB_DASHBOARD)

        elif path == "/api/status":
            model, mode, think = _get_active_session_state()
            backend_name = type(runtime.backend).__name__
            cli_name = getattr(runtime.backend, "cli_name", "")
            owns_tools = getattr(runtime.backend, "manages_own_tools", False)
            self._json({
                "backend": backend_name,
                "backend_cli": cli_name,
                "model": model,
                "mode": mode,
                "think": think,
                "manages_own_tools": owns_tools,
                "bach": HAS_BACH,
                "sessions": len(runtime.sessions),
            })

        elif path == "/api/backends":
            backends = {}
            for name, preset in BACKEND_PRESETS.items():
                status = ""
                if preset["method"] == "cli":
                    cli_name = preset["type"].replace("-cli", "")
                    status = _check_cli_available(cli_name)
                elif name in ("claude-api", "openai"):
                    status = _check_api_key(name)
                backends[name] = {
                    "description": preset["description"],
                    "method": preset["method"],
                    "default_model": preset["default_model"],
                    "status": status,
                }
            self._json(backends)

        elif path == "/api/models":
            try:
                models = runtime.backend.list_models()
                self._json({"models": models})
            except Exception as e:
                self._json({"error": str(e)}, 500)

        else:
            self._json({"error": "Not found"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path
        body = self._read_body()

        if path == "/api/backend":
            name = body.get("name", "")
            model = body.get("model", "")
            if name not in BACKEND_PRESETS:
                self._json({"error": f"Unbekannt: {name}"}, 400)
                return
            preset = BACKEND_PRESETS[name].copy()
            if model:
                preset["default_model"] = model
            if preset["method"] == "api" and name in ("claude-api", "openai"):
                env_var = "ANTHROPIC_API_KEY" if "claude" in name else "OPENAI_API_KEY"
                file_name = "anthropic_api_key" if "claude" in name else "openai_api_key"
                key_file = os.path.expanduser(f"~/.credentials/{file_name}")
                api_key = os.environ.get(env_var, "")
                if not api_key and os.path.exists(key_file):
                    api_key = open(key_file).read().strip()
                if not api_key:
                    self._json({"error": f"Kein API-Key für {name}"}, 400)
                    return
                preset["api_key"] = api_key
            try:
                config = {k: v for k, v in preset.items()
                          if k not in ("method", "description")}
                new_backend = create_backend(config)
                runtime.backend = new_backend
                _global_defaults["model"] = preset["default_model"]
                for s in runtime.sessions.values():
                    s.model = preset["default_model"]
                self._json({"ok": True, "backend": name, "model": preset["default_model"]})
            except Exception as e:
                self._json({"error": str(e)}, 500)

        elif path == "/api/mode":
            mode = body.get("mode", "")
            if mode not in ("safe", "full"):
                self._json({"error": "safe oder full"}, 400)
                return
            _global_defaults["mode"] = mode
            for s in runtime.sessions.values():
                s.mode = mode
            self._json({"ok": True, "mode": mode})

        elif path == "/api/model":
            model = body.get("model", "")
            if not model:
                self._json({"error": "model erforderlich"}, 400)
                return
            _global_defaults["model"] = model
            for s in runtime.sessions.values():
                s.model = model
            self._json({"ok": True, "model": model})

        elif path == "/api/think":
            think = body.get("think", True)
            _global_defaults["think"] = bool(think)
            for s in runtime.sessions.values():
                s.think = bool(think)
            self._json({"ok": True, "think": bool(think)})

        else:
            self._json({"error": "Not found"}, 404)


def start_control_api():
    try:
        server = HTTPServer(("127.0.0.1", CONTROL_PORT), ControlHandler)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        log.info(f"Control API auf 127.0.0.1:{CONTROL_PORT}")
        print(f"Web-Dashboard: http://localhost:{CONTROL_PORT}/")
        return server
    except OSError as e:
        log.warning(f"Control API konnte nicht starten: {e}")
        return None


# --- Main ---

def main():
    if not BOT_TOKEN:
        print("Kein Bot-Token! Setze TELEGRAM_BOT_TOKEN oder ~/.credentials/telegram_bot_token")
        sys.exit(1)

    start_control_api()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("clear", cmd_clear))
    app.add_handler(CommandHandler("think", cmd_think))
    app.add_handler(CommandHandler("nothink", cmd_nothink))
    app.add_handler(CommandHandler("mode", cmd_mode))
    app.add_handler(CommandHandler("model", cmd_model))
    app.add_handler(CommandHandler("backend", cmd_backend))
    app.add_handler(CommandHandler("settings", cmd_settings))

    if HAS_BACH:
        app.add_handler(CommandHandler("remember", cmd_remember))
        app.add_handler(CommandHandler("recall", cmd_recall))
        app.add_handler(CommandHandler("facts", cmd_facts))
        app.add_handler(CommandHandler("bach", cmd_bach))
        app.add_handler(CommandHandler("task", cmd_task))
        app.add_handler(CommandHandler("tasks", cmd_tasks))
        app.add_handler(CommandHandler("status", cmd_status))

    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voice))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    backend_type = CONFIG["backend"].get("type", "ollama")
    model = backend.get_default_model()
    print(
        f"BACH Telegram Chat gestartet "
        f"(BACH: {'JA' if HAS_BACH else 'NEIN'}, "
        f"Backend: {backend_type}, Modell: {model}, Think: AN)"
    )
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
