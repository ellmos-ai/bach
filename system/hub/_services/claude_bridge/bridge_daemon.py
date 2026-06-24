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
BACH Claude Bridge Daemon v2.3
===============================
Verbindet Telegram direkt mit Claude Code CLI.

Fixes in v2.0:
- Robuster Singleton via File-Lock (statt fragiler PID-Check)
- Restart-Loop-Schutz (min 30s Cooldown)
- Nachrichten-Alters-Limit (nur letzte 5 Min verarbeiten)
- Eigenes bridge_memory.md fuer Chat-Kontext-Persistenz
- Persistentes Budget (state.json statt In-Memory)
- Worker-Sandboxing (kein Zugriff auf bridge_daemon.py)
- Worker stdout=None Bug gefixt

Fixes in v2.1:
- Persistente Claude-Session via --continue (Kontext bleibt erhalten)
- Erster Aufruf: Voller System-Prompt, Session wird gespeichert
- Folge-Aufrufe: Nur User-Text mit --continue (Claude hat Kontext)
- Automatischer Fallback bei Session-Verlust (neue Session)
- End-of-Day Summary in BACH Memory (Tages-Reset)
- 'reset' Codeword fuer manuellen Neustart der Session

Fixes in v2.2:
- ASYNC CHAT: Main-Loop blockiert nicht mehr waehrend Claude antwortet
- Nachrichten-Queue: Neue Nachrichten werden gequeued statt verworfen
- Encoding-Fixes: Raw-Bytes Subprocess, zentrale Sanitierung (encoding_fix.py)
- Permission-Fixes: P1 (Hint nach Toggle), P2 (State-Logging), P3 (Worker-Rechte)
- Capability-Parity: Teams, Tasks, Skills via Telegram verfuegbar

New in v2.3:
- SERVER MODE: FastAPI REST layer fuer Server-Deployment (config: mode=server)
- Endpoints: POST /api/message, GET /api/status, POST /api/control
- Bearer-Token Auth, konfigurierbare CORS-Origins
- Deployment via SSH-Tunnel + systemd auf Hetzner

Architektur: Persistent Chat + Sandboxed Workers + Async Main Loop
- Chat-Claude: EINE Session pro Tag, --continue fuer Kontext-Erhalt
- Worker-Claude: Laeuft autonom, DARF bridge_daemon.py NICHT editieren
- Async: Chat laeuft im Thread, Main-Loop pollt weiter, Messages queued

Usage:
  python bridge_daemon.py                # Starten (local mode)
  python bridge_daemon.py --server       # Starten (server mode, FastAPI)
  python bridge_daemon.py --stop         # Stoppen
  python bridge_daemon.py --status       # Status anzeigen
  python bridge_daemon.py --test "msg"   # Test-Nachricht simulieren

Deployment (Hetzner):
  ssh -L 8080:localhost:8080 user@example-host
  systemctl start bach-bridge
  # Siehe DEPLOYMENT.md fuer Details

Version: 2.3.0
Erstellt: 2026-02-11
Updated: 2026-03-02
"""

import json
import os
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import datetime, date, timedelta
from pathlib import Path
from threading import Event, Thread, Lock

try:
    from .fackel import acquire_fackel, heartbeat, release_fackel, get_fackel_holder, check_fackel_mine
except ImportError:
    from fackel import acquire_fackel, heartbeat, release_fackel, get_fackel_holder, check_fackel_mine

FACKEL_LOST_EXIT_CODE = 2  # Exit-Code wenn Fackel durch anderen PC uebernommen wurde

# ============ PFADE ============

BRIDGE_DIR = Path(__file__).parent.resolve()
SERVICES_DIR = BRIDGE_DIR.parent
HUB_DIR = SERVICES_DIR.parent
BACH_DIR = HUB_DIR.parent

CONFIG_FILE = BRIDGE_DIR / "config.json"
PID_FILE = BRIDGE_DIR / "bridge.pid"
LOCK_FILE = Path(tempfile.gettempdir()) / "bach_bridge.lock"
TRAY_LOCK_FILE = Path(tempfile.gettempdir()) / "bach_bridge_tray.lock"  # Tray-Kopplung
STATE_FILE = BRIDGE_DIR / "state.json"
MEMORY_FILE = BRIDGE_DIR / "bridge_memory.md"
LOG_FILE = BACH_DIR / "data" / "logs" / "claude_bridge.log"

# Restart-Loop-Schutz: Zeitstempel des letzten Starts
LAST_START_FILE = BRIDGE_DIR / "last_start.txt"
MIN_RESTART_INTERVAL = 30  # Sekunden zwischen Starts

DB_PATH = BACH_DIR / "data" / "bach.db"

# Maximales Alter von Nachrichten die verarbeitet werden (Sekunden)
MAX_MESSAGE_AGE = 300  # 5 Minuten

# Queue-Processor fuer Dispatch importieren
sys.path.insert(0, str(BACH_DIR))
_dispatch_fn = None


def _get_dispatch():
    """Lazy-Import von dispatch_outgoing aus queue_processor."""
    global _dispatch_fn
    if _dispatch_fn is None:
        try:
            from hub._services.connector.queue_processor import dispatch_outgoing
            _dispatch_fn = dispatch_outgoing
        except Exception as e:
            err_msg = str(e)
            log(f"dispatch_outgoing Import fehlgeschlagen: {err_msg}", "WARN")
            return lambda: {"sent": 0, "errors": [err_msg]}
    return _dispatch_fn


def _fetch_weather(lat: float, lng: float) -> str:
    """Ruft aktuelles Wetter via weather_service ab (wttr.in, kein API-Key)."""
    try:
        from hub._services.weather.weather_service import get_weather_text
        return get_weather_text(lat, lng)
    except Exception as e:
        log(f"WEATHER fetch fehlgeschlagen: {e}", "WARN")
        return ""


def _get_route(start_lat: float, start_lon: float, end_lat: float, end_lon: float, mode: str = "car") -> str:
    """Berechnet Route via routing_service (OSRM, kein API-Key)."""
    try:
        from hub._services.routing.routing_service import get_route_text
        return get_route_text(
            start=(start_lat, start_lon),
            end=(end_lat, end_lon),
            mode=mode,
        )
    except Exception as e:
        log(f"ROUTING fetch fehlgeschlagen: {e}", "WARN")
        return ""


# ============ LOGGING ============

def log(msg: str, level: str = "INFO"):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] [{level}] {msg}"
    print(line)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ============ CONFIG ============

def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"enabled": True, "poll_interval_seconds": 5}


def _resolve_claude_cli_path(config: dict) -> dict:
    """Prueft Claude CLI Pfad aus config und sucht automatisch neu falls ungueltig.
    Aktualisiert config.json wenn ein neuer Pfad gefunden wird."""
    import shutil
    cli_config = config.setdefault("claude_cli", {})
    current_path = cli_config.get("path", "")

    # Pfad gueltig? (existiert als Datei oder im PATH)
    path_ok = False
    if current_path:
        p = Path(current_path)
        path_ok = p.exists() or (shutil.which(current_path) is not None)

    if path_ok:
        return config

    # Automatisch suchen
    log(f"Claude CLI Pfad ungueltig ({current_path!r}) - suche automatisch...", "WARN")
    candidates = [
        shutil.which("claude"),
        str(Path(os.environ.get("APPDATA", "")) / "npm" / "claude"),
        str(Path(os.environ.get("APPDATA", "")) / "npm" / "claude.cmd"),
        "/usr/local/bin/claude",
        str(Path.home() / ".local" / "bin" / "claude"),
    ]
    localappdata = os.environ.get("LOCALAPPDATA", "")
    if localappdata:
        for _p in Path(localappdata).glob("Microsoft/WinGet/Packages/Anthropic.ClaudeCode*/**/claude.exe"):
            candidates.append(str(_p))

    found = next((c for c in candidates if c and (Path(c).exists() or shutil.which(c))), None)

    if found:
        log(f"Claude CLI gefunden: {found}", "INFO")
        cli_config["path"] = found.replace("\\", "/")
        # In config.json persistieren
        try:
            CONFIG_FILE.write_text(
                json.dumps(config, indent=4, ensure_ascii=False), encoding="utf-8"
            )
            log(f"config.json aktualisiert: claude.path = {found}", "INFO")
        except Exception as e:
            log(f"config.json Update fehlgeschlagen: {e}", "WARN")
    else:
        log("Claude CLI nicht gefunden - Bridge laeuft ohne Chat-Funktion!", "ERROR")

    return config


# ============ PERSISTENT STATE ============

def load_state() -> dict:
    """Laedt persistenten State (Budget, Permission-Mode etc.)."""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            log(f"state.json korrupt, verwende Defaults: {e}", "WARN")
    else:
        log("state.json nicht vorhanden - Daemon startet mit Defaults (restricted, kein Budget-Tracking)", "WARN")
    return {}


def save_state(state: dict):
    """Speichert persistenten State."""
    try:
        STATE_FILE.write_text(
            json.dumps(state, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
    except Exception as e:
        log(f"State speichern fehlgeschlagen: {e}", "WARN")


# ============ BRIDGE MEMORY ============

def load_bridge_memory() -> str:
    """Laedt das persistente Chat-Memory."""
    if MEMORY_FILE.exists():
        try:
            return MEMORY_FILE.read_text(encoding="utf-8")
        except Exception:
            pass
    return ""


def save_bridge_memory(content: str):
    """Speichert das Chat-Memory."""
    try:
        MEMORY_FILE.write_text(content, encoding="utf-8")
    except Exception as e:
        log(f"Memory speichern fehlgeschlagen: {e}", "WARN")


def update_bridge_memory(updates: str):
    """Fuegt Updates zum Memory hinzu (append mit Zeitstempel)."""
    current = load_bridge_memory()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    new_entry = f"\n## [{timestamp}]\n{updates}\n"

    # Memory auf max 3000 Zeichen halten (aeltestes entfernen)
    combined = current + new_entry
    if len(combined) > 3000:
        # Behalte Header + letzte Eintraege
        lines = combined.split("\n## [")
        header = lines[0] if lines else ""
        entries = lines[1:] if len(lines) > 1 else []
        # Behalte die letzten Eintraege die in 3000 Zeichen passen
        kept = []
        total = len(header)
        for entry in reversed(entries):
            entry_text = "\n## [" + entry
            if total + len(entry_text) < 2800:
                kept.insert(0, entry_text)
                total += len(entry_text)
            else:
                break
        combined = header + "".join(kept)

    save_bridge_memory(combined)


# ============ FILE-LOCK SINGLETON ============

_lock_handle = None


def acquire_lock() -> bool:
    """Erwirbt exklusiven File-Lock. Gibt False zurueck wenn bereits gelockt.

    Verwendet 'a+' statt 'w' um die PID-Datei nicht zu truncaten
    bevor der Lock geprueft wird (verhindert PID-0-Bug).
    """
    global _lock_handle
    try:
        LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
        _lock_handle = open(LOCK_FILE, "a+")
        if sys.platform == "win32":
            import msvcrt
            _lock_handle.seek(0)
            msvcrt.locking(_lock_handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(_lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        # Lock erworben → jetzt PID reinschreiben
        _lock_handle.seek(0)
        _lock_handle.truncate()
        _lock_handle.write(str(os.getpid()))
        _lock_handle.flush()
        return True
    except (OSError, IOError):
        if _lock_handle:
            _lock_handle.close()
            _lock_handle = None
        return False


def release_lock():
    """Gibt den File-Lock frei."""
    global _lock_handle
    if _lock_handle:
        try:
            if sys.platform == "win32":
                import msvcrt
                try:
                    _lock_handle.seek(0)
                    msvcrt.locking(_lock_handle.fileno(), msvcrt.LK_UNLCK, 1)
                except Exception:
                    pass
            else:
                import fcntl
                fcntl.flock(_lock_handle.fileno(), fcntl.LOCK_UN)
            _lock_handle.close()
        except Exception:
            pass
        _lock_handle = None
    try:
        LOCK_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def get_running_pid() -> int:
    """Liest PID aus Lock-File (fuer Status-Anzeige)."""
    if not LOCK_FILE.exists():
        return 0
    try:
        content = LOCK_FILE.read_text(encoding="utf-8").strip()
        if content:
            pid = int(content)
            if _is_process_running(pid):
                return pid
        return 0
    except Exception:
        return 0


def _is_process_running(pid: int) -> bool:
    if sys.platform == "win32":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x1000, False, pid)
            if handle:
                kernel32.CloseHandle(handle)
                return True
            return False
        except Exception:
            return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False


# ============ RESTART-LOOP SCHUTZ ============

def check_restart_cooldown() -> bool:
    """Prueft ob genug Zeit seit dem letzten Start vergangen ist.
    Gibt True zurueck wenn Start erlaubt ist."""
    try:
        if LAST_START_FILE.exists():
            last_start = float(LAST_START_FILE.read_text(encoding="utf-8").strip())
            elapsed = time.time() - last_start
            if elapsed < MIN_RESTART_INTERVAL:
                remaining = int(MIN_RESTART_INTERVAL - elapsed)
                print(f"Restart-Cooldown: Bitte {remaining}s warten (Schutz gegen Restart-Loop).")
                log(f"RESTART BLOCKED: Cooldown noch {remaining}s", "WARN")
                return False
    except Exception:
        pass
    return True


def record_start_time():
    """Speichert den aktuellen Zeitpunkt als letzten Start."""
    try:
        LAST_START_FILE.write_text(str(time.time()))
    except Exception:
        pass


# ============ STOP ============

def stop_daemon() -> bool:
    """Stoppt laufenden Daemon via PID."""
    pid = get_running_pid()
    if pid == 0:
        print("Kein Claude Bridge Daemon laeuft.")
        # Lock-File aufraeumen falls vorhanden
        try:
            LOCK_FILE.unlink(missing_ok=True)
        except Exception:
            pass
        return True
    if pid == os.getpid():
        return True
    log(f"Stoppe Claude Bridge Daemon (PID {pid})...")
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                           capture_output=True, timeout=10)
        else:
            os.kill(pid, signal.SIGTERM)
            time.sleep(2)
            if _is_process_running(pid):
                os.kill(pid, signal.SIGKILL)
        time.sleep(1)  # Warten bis Lock freigegeben
        try:
            LOCK_FILE.unlink(missing_ok=True)
        except Exception:
            pass
        log("Claude Bridge Daemon gestoppt")
        return True
    except Exception as e:
        log(f"Fehler beim Stoppen: {e}", "ERROR")
        return False


# ============ DATABASE HELPERS ============

def db_connect():
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def db_execute(query, params=(), fetch=False, fetchone=False):
    """Sichere DB-Operation mit Retry bei BUSY."""
    for attempt in range(3):
        try:
            conn = db_connect()
            cursor = conn.execute(query, params)
            if fetchone:
                result = cursor.fetchone()
            elif fetch:
                result = cursor.fetchall()
            else:
                conn.commit()
                result = cursor.lastrowid
            conn.close()
            return result
        except sqlite3.OperationalError as e:
            if "locked" in str(e) and attempt < 2:
                time.sleep(0.5 * (attempt + 1))
                continue
            raise


# ============ MULTI-CONNECTOR POLLING ============

def run_connector_poll():
    """Pollt alle aktiven Connectors (Telegram, WhatsApp, Signal, Discord)."""
    total_new = 0

    # Telegram
    total_new += run_telegram_poll()

    # WhatsApp (wenn konfiguriert)
    # total_new += run_whatsapp_poll()

    # Signal (wenn konfiguriert)
    # total_new += run_signal_poll()

    # Discord (wenn konfiguriert)
    # total_new += run_discord_poll()

    return total_new


def _load_secret_from_db(key: str) -> str:
    """Laedt Secret aus der secrets-Tabelle in bach.db (ENT-44 Primaerquelle)."""
    try:
        conn = db_connect()
        row = conn.execute("SELECT value FROM secrets WHERE key = ?", (key,)).fetchone()
        conn.close()
        return row[0] if row and row[0] else ""
    except Exception:
        return ""


def _resolve_secret_ref(auth: dict, field: str) -> str:
    """Loest _secret_refs fuer ein Feld auf (ENT-44).
    Reihenfolge: 1) Direktwert in auth_config, 2) _secret_refs -> secrets-Tabelle,
    3) bach_secrets.json Fallback (Legacy)."""
    # 1. Direktwert (Legacy / alte Configs)
    value = auth.get(field, "")
    if value:
        return value
    # 2. _secret_refs -> secrets-Tabelle (ENT-44)
    secret_key = auth.get("_secret_refs", {}).get(field, "")
    if secret_key:
        value = _load_secret_from_db(secret_key)
        if value:
            return value
    return ""


def _load_bot_token_from_file() -> str:
    """Laedt Bot-Token: Primaer secrets-Tabelle (ENT-44), Fallback bach_secrets.json.
    Wird genutzt wenn kein auth_config vorhanden (z.B. direkte Aufrufe ohne auth)."""
    # Primaer: secrets-Tabelle in bach.db
    token = _load_secret_from_db("telegram_main_bot_token")
    if token:
        return token
    # Fallback: ~/.bach/bach_secrets.json
    try:
        secrets_file = Path.home() / ".bach" / "bach_secrets.json"
        if secrets_file.exists():
            data = json.loads(secrets_file.read_text(encoding="utf-8"))
            token = data.get("secrets", {}).get("telegram_main_bot_token", {}).get("value", "")
            if token:
                return token
    except Exception:
        pass
    # Legacy: %LOCALAPPDATA%/BACH/keys/telegram_bot_token.txt
    try:
        key_file = Path(os.environ.get("LOCALAPPDATA", "")) / "BACH" / "keys" / "telegram_bot_token.txt"
        if key_file.exists():
            token = key_file.read_text(encoding="utf-8").strip()
            if token:
                return token
    except Exception:
        pass
    return ""


def run_telegram_poll():
    """Pollt neue Nachrichten direkt von Telegram API in die DB."""
    try:
        conn = db_connect()
        row = conn.execute(
            "SELECT name, auth_config FROM connections WHERE name = 'telegram_main' AND is_active = 1"
        ).fetchone()
        conn.close()
        if not row:
            return 0

        connector_name = row["name"]
        auth = json.loads(row["auth_config"]) if row["auth_config"] else {}
        token = _resolve_secret_ref(auth, "bot_token") or _load_bot_token_from_file()
        last_update_id = auth.get("last_update_id", 0)
        if not token:
            return 0

        import urllib.request
        url = f"https://api.telegram.org/bot{token}/getUpdates?offset={last_update_id + 1}&timeout=1&limit=10"
        resp = urllib.request.urlopen(url, timeout=5)
        data = json.loads(resp.read())

        if not data.get("ok") or not data.get("result"):
            return 0

        stored = 0
        max_update_id = last_update_id
        now = datetime.now().isoformat()

        for update in data["result"]:
            uid = update.get("update_id", 0)
            if uid > max_update_id:
                max_update_id = uid

            msg = update.get("message", {})
            text = msg.get("text", "")
            chat_id = str(msg.get("chat", {}).get("id", ""))
            sender = msg.get("from", {}).get("first_name", "User")

            # Voice-Message?
            if not text:
                voice = msg.get("voice") or msg.get("audio")
                if voice and voice.get("file_id"):
                    # TelegramConnector nutzen fuer Transkription
                    try:
                        sys.path.insert(0, str(BACH_DIR / "connectors"))
                        from telegram_connector import TelegramConnector
                        from connectors.base import ConnectorConfig

                        cfg = ConnectorConfig(
                            name="telegram_transcribe",
                            connector_type="telegram",
                            auth_type="api_key",
                            auth_config={"bot_token": token},
                            options={}
                        )
                        tg = TelegramConnector(cfg)
                        transcription = tg._transcribe_voice(voice["file_id"], voice.get("duration", 0))
                        if transcription:
                            text = transcription
                            log(f"VOICE TRANSCRIBED: {len(text)} Zeichen")
                        else:
                            text = f"[Sprachnachricht ({voice.get('duration', 0)}s) - Transkription fehlgeschlagen]"
                            log(f"VOICE TRANSCRIPTION FAILED", "WARN")
                    except Exception as e:
                        text = f"[Sprachnachricht - Fehler: {e}]"
                        log(f"VOICE ERROR: {e}", "ERROR")

            # Location-Message? (Telegram GPS-Pin)
            if not text:
                location = msg.get("location")
                if location:
                    lat = location.get("latitude", 0)
                    lng = location.get("longitude", 0)
                    log(f"LOCATION: lat={lat}, lng={lng}")

                    # Wetter automatisch abrufen
                    weather_text = _fetch_weather(lat, lng)
                    weather_section = f"\n{weather_text}" if weather_text else ""

                    routing_hint = (
                        f"python \"{BACH_DIR}/hub/_services/routing/routing_service.py\" "
                        f"{lat:.5f} {lng:.5f} <ziel_lat> <ziel_lon> [car|bike|foot]"
                    )
                    text = (
                        f"[Standort gesendet] Koordinaten: {lat:.5f}°N, {lng:.5f}°E"
                        f"{weather_section}\n\n"
                        f"OpenStreetMap: https://www.openstreetmap.org/?mlat={lat}&mlon={lng}&zoom=14\n\n"
                        f"Verfuegbare Aktionen mit diesen Koordinaten:\n"
                        f"- Wetter: Bereits oben abgerufen (wttr.in, kein Key noetig)\n"
                        f"- Route (OSRM, kein Key): {routing_hint}\n"
                        f"  Tipp: Ziel-Koordinaten via geocode_place() oder WebSearch ermitteln\n"
                        f"- Naechste Orte/Services: WebSearch mit lat/lon\n"
                        f"- Adresse: WebFetch nominatim.openstreetmap.org/reverse?lat={lat:.4f}&lon={lng:.4f}&format=json"
                    )

            if not text or not chat_id:
                continue

            # Duplikat-Check (60 Sekunden Fenster)
            conn2 = db_connect()
            existing = conn2.execute(
                "SELECT id FROM connector_messages WHERE connector_name='telegram_main' "
                "AND sender=? AND content=? AND direction='in' "
                "AND created_at >= datetime(?, '-60 seconds') LIMIT 1",
                (sender, text, now)
            ).fetchone()

            if not existing:
                conn2.execute(
                    "INSERT INTO connector_messages "
                    "(connector_name, direction, sender, recipient, content, status, created_at, bridge_processed) "
                    "VALUES (?, 'in', ?, ?, ?, 'pending', ?, 0)",
                    (connector_name, sender, chat_id, text, now)
                )
                conn2.commit()
                stored += 1

            conn2.close()

        # Update last_update_id persistent
        if max_update_id > last_update_id:
            auth["last_update_id"] = max_update_id
            conn3 = db_connect()
            conn3.execute(
                "UPDATE connections SET auth_config = ?, last_used = ? WHERE name = ?",
                (json.dumps(auth, ensure_ascii=True), now, connector_name)
            )
            conn3.commit()
            conn3.close()

        if stored > 0:
            log(f"POLL [{connector_name}]: {stored} neue Nachricht(en)")
        return stored

    except Exception as e:
        log(f"POLL FEHLER: {e}", "ERROR")
        return 0


def run_dispatch():
    """Dispatcht ausgehende Nachrichten an Telegram."""
    try:
        fn = _get_dispatch()
        result = fn()
        sent = result.get("sent", 0)
        if sent > 0:
            log(f"DISPATCH: {sent} Nachricht(en) an Telegram gesendet")
        if result.get("errors"):
            log(f"DISPATCH ERRORS: {result['errors']}", "WARN")
        return result
    except Exception as e:
        log(f"DISPATCH FEHLER: {e}", "ERROR")
        return {"sent": 0, "errors": [str(e)]}


def _split_telegram_message(text: str, max_len: int = 3800) -> list:
    """Teilt eine lange Nachricht an Absatz-Grenzen auf."""
    if len(text) <= max_len:
        return [text]

    parts = []
    # Trenne an Leerzeilen (Absaetze)
    paragraphs = text.split('\n\n')
    current = ""
    for para in paragraphs:
        if not current:
            current = para
        elif len(current) + len(para) + 2 <= max_len:
            current += '\n\n' + para
        else:
            parts.append(current)
            current = para
    if current:
        parts.append(current)

    # Falls einzelne Absaetze noch zu lang: hart trennen
    result = []
    for part in parts:
        if len(part) <= max_len:
            result.append(part)
        else:
            # Hart aufteilen an Zeilenenden
            lines = part.split('\n')
            chunk = ""
            for line in lines:
                if len(chunk) + len(line) + 1 <= max_len:
                    chunk = (chunk + '\n' + line).lstrip('\n')
                else:
                    if chunk:
                        result.append(chunk)
                    chunk = line[:max_len]
            if chunk:
                result.append(chunk)

    return result if result else [text[:max_len]]


def send_telegram(text: str, config: dict):
    """Schreibt Nachricht in die Outbound-Queue und dispatcht sofort.
    Lange Nachrichten werden automatisch aufgeteilt."""
    connector_name = config.get("connector_name", "telegram_main")
    chat_id = config.get("chat_id", "YOUR_CHAT_ID")

    # Encoding-Sanitierung (behebt Mojibake aus Claude CLI Output)
    try:
        from tools.encoding_fix import sanitize_outbound
        text = sanitize_outbound(text)
    except ImportError:
        pass

    # Nachrichten aufteilen wenn noetig
    parts = _split_telegram_message(text)
    now = datetime.now().isoformat()

    for i, part in enumerate(parts):
        suffix = f" [{i+1}/{len(parts)}]" if len(parts) > 1 else ""
        msg_text = part + suffix if suffix else part
        db_execute(
            "INSERT INTO connector_messages "
            "(connector_name, direction, sender, recipient, content, processed, status, created_at) "
            "VALUES (?, 'out', 'bach-claude', ?, ?, 0, 'pending', ?)",
            (connector_name, chat_id, msg_text, now)
        )
        log(f"TELEGRAM OUT: {msg_text[:80]}...")

    # Sofort dispatchen
    run_dispatch()


def send_telegram_voice(text: str, config: dict):
    """Konvertiert Text zu Sprache und sendet als Voice-Nachricht via Telegram.
    Fallback auf Text wenn TTS nicht verfuegbar."""
    import tempfile
    from pathlib import Path

    try:
        from hub._services.voice.voice_stt import VoiceTTS
        from connectors.telegram_connector import TelegramConnector

        tts = VoiceTTS(engine="auto")
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            tmp_path = tmp.name

        success = tts.speak_to_file(text, tmp_path, format="ogg")

        if success and Path(tmp_path).exists() and Path(tmp_path).stat().st_size > 0:
            chat_id = config.get("chat_id", "YOUR_CHAT_ID")
            bot_token = config.get("bot_token", "")
            if not bot_token:
                # Token aus DB laden via _secret_refs (ENT-44)
                try:
                    row = db_execute(
                        "SELECT auth_config FROM connections WHERE name='telegram_main' LIMIT 1",
                        fetch=True
                    )
                    if row:
                        conn_cfg = json.loads(row[0]["auth_config"] or "{}")
                        bot_token = _resolve_secret_ref(conn_cfg, "bot_token")
                except Exception:
                    pass
            if not bot_token:
                bot_token = _load_bot_token_from_file()

            if bot_token:
                from connectors.base import ConnectorConfig
                cfg = ConnectorConfig(name="telegram_main", connector_type="telegram",
                                      auth_type="api_key",
                                      auth_config={"bot_token": bot_token},
                                      options={"owner_chat_id": chat_id})
                tg = TelegramConnector(cfg)
                tg.send_voice(chat_id, tmp_path)
                Path(tmp_path).unlink(missing_ok=True)
                log(f"VOICE OUT: {len(text)} Zeichen als Sprache gesendet")
                return
            else:
                log("VOICE OUT: kein bot_token - Fallback auf Text", "WARN")

        Path(tmp_path).unlink(missing_ok=True)

    except Exception as e:
        log(f"VOICE OUT FEHLER: {e} - Fallback auf Text", "WARN")

    # Fallback: als Text senden
    send_telegram(text, config)


def get_recent_history(config: dict, limit: int = 15) -> str:
    """Liest die letzten N bidirektionalen Nachrichten.
    Sanitiert Encoding um Mojibake-Feedback-Loop zu verhindern."""
    connector_name = config.get("connector_name", "telegram_main")
    rows = db_execute(
        "SELECT direction, sender, content, created_at "
        "FROM connector_messages "
        "WHERE connector_name = ? AND (direction = 'in' OR direction = 'out') "
        "ORDER BY created_at DESC LIMIT ?",
        (connector_name, limit), fetch=True
    )
    if not rows:
        return "(keine bisherigen Nachrichten)"

    # Encoding-Sanitizer laden (verhindert dass Mojibake an Claude geht)
    try:
        from tools.encoding_fix import sanitize_outbound
        _sanitize = sanitize_outbound
    except ImportError:
        _sanitize = lambda x: x

    lines = []
    for row in reversed(rows):  # Chronologisch
        direction = row["direction"]
        content = _sanitize(row["content"] or "")
        ts = row["created_at"][:16] if row["created_at"] else ""
        if direction == "in":
            lines.append(f"[{ts}] User: {content}")
        else:
            sender = row["sender"] or "bach"
            lines.append(f"[{ts}] {sender}: {content}")
    return "\n".join(lines)


# ============ BACH CONTEXT ============

def get_bach_context() -> str:
    """Liest offene Tasks und letztes Memory."""
    parts = []

    # Offene Tasks
    try:
        rows = db_execute(
            "SELECT id, title, priority FROM tasks "
            "WHERE status = 'open' ORDER BY "
            "CASE priority WHEN 'P1' THEN 1 WHEN 'P2' THEN 2 WHEN 'P3' THEN 3 ELSE 4 END "
            "LIMIT 5",
            fetch=True
        )
        if rows:
            parts.append("Offene Tasks:")
            for r in rows:
                parts.append(f"  [{r['id']}] {r['priority'] or ''} {r['title']}")
    except Exception:
        pass

    # Letztes Memory
    try:
        rows = db_execute(
            "SELECT content FROM memory_working ORDER BY created_at DESC LIMIT 3",
            fetch=True
        )
        if rows:
            parts.append("Letztes Memory:")
            for r in rows:
                parts.append(f"  - {r['content'][:100]}")
    except Exception:
        pass

    return "\n".join(parts) if parts else "(kein Kontext)"


def get_worker_status() -> str:
    """Status aller Worker (laufende + letzte erledigte)."""
    parts = []

    try:
        running = db_execute(
            "SELECT id, task_description, started_at FROM claude_bridge_workers "
            "WHERE status = 'running' ORDER BY started_at DESC",
            fetch=True
        )
        if running:
            parts.append("Laufende Worker:")
            for r in running:
                parts.append(f"  [W{r['id']}] {r['task_description'][:80]} (seit {r['started_at'][:16]})")
    except Exception:
        pass

    try:
        done = db_execute(
            "SELECT id, task_description, status, result_summary, ended_at "
            "FROM claude_bridge_workers "
            "WHERE status IN ('completed', 'error') "
            "ORDER BY ended_at DESC LIMIT 3",
            fetch=True
        )
        if done:
            parts.append("Letzte Worker-Ergebnisse:")
            for r in done:
                emoji = "OK" if r["status"] == "completed" else "FEHLER"
                summary = (r["result_summary"] or "")[:150]
                parts.append(f"  [W{r['id']}] {emoji}: {summary}")
    except Exception:
        pass

    return "\n".join(parts) if parts else "(keine Worker)"


# ============ PROMPT BUILDER ============

def _load_startup_skills() -> str:
    """Lädt SKILL.md + persoenlicher-assistent beim Start."""
    skills = []

    # 1. SKILL.md (root)
    root_skill = BACH_DIR.parent / "SKILL.md"
    if root_skill.exists():
        try:
            content = root_skill.read_text(encoding='utf-8')
            skills.append(f"### SKILL.md (Root-Skill)\n{content}")
            log("SKILL.md geladen", "INFO")
        except Exception as e:
            log(f"SKILL.md lesen fehlgeschlagen: {e}", "WARN")
    else:
        log("SKILL.md nicht gefunden", "WARN")

    # 2. Persönlicher Assistent
    assistant_skill = BACH_DIR / "agents" / "persoenlicher-assistent" / "SKILL.md"
    if assistant_skill.exists():
        try:
            content = assistant_skill.read_text(encoding='utf-8')
            skills.append(f"### Persönlicher Assistent\n{content}")
            log("persoenlicher-assistent SKILL.md geladen", "INFO")
        except Exception as e:
            log(f"persoenlicher-assistent SKILL.md lesen fehlgeschlagen: {e}", "WARN")
    else:
        # Fallback: skills/persoenlicher-assistent.txt (alte Struktur)
        assistant_skill_alt = BACH_DIR / "skills" / "persoenlicher-assistent.txt"
        if assistant_skill_alt.exists():
            try:
                content = assistant_skill_alt.read_text(encoding='utf-8')
                skills.append(f"### Persönlicher Assistent\n{content}")
                log("skills/persoenlicher-assistent.txt geladen", "INFO")
            except Exception as e:
                log(f"skills/persoenlicher-assistent.txt lesen fehlgeschlagen: {e}", "WARN")
        else:
            # Fallback 2: agents/persoenlicher-assistent.txt
            assistant_skill_alt2 = BACH_DIR / "agents" / "persoenlicher-assistent.txt"
            if assistant_skill_alt2.exists():
                try:
                    content = assistant_skill_alt2.read_text(encoding='utf-8')
                    skills.append(f"### Persönlicher Assistent\n{content}")
                    log("agents/persoenlicher-assistent.txt geladen", "INFO")
                except Exception as e:
                    log(f"agents/persoenlicher-assistent.txt lesen fehlgeschlagen: {e}", "WARN")

    if not skills:
        return "# Keine Skills geladen (SKILL.md fehlt)"

    return "\n\n".join(skills)


def _get_bach_cli_reference() -> str:
    """Statische Kurzreferenz der wichtigsten BACH CLI-Befehle und API."""
    return """### BACH CLI (python bach.py <befehl> [op] [args])

Kern-Handler:
  task add "Beschreibung" [--priority P1/P2/P3]  - Aufgabe anlegen
  task list [--open] [--all]                       - Aufgaben anzeigen
  task done <id>                                   - Aufgabe abschliessen
  task update <id> --status <status>               - Status aendern
  memory write "Notiz"                             - Notiz ins Working-Memory
  memory status                                    - Memory-Uebersicht
  status                                           - System-Status-Uebersicht

Email-Handler:
  email send <to> --subject "..." --body "..."    - Mail als Entwurf anlegen
  email drafts                                     - Offene Entwuerfe anzeigen
  email show <id>                                  - Entwurf anzeigen
  email confirm <id>                               - Mail senden (IMMER User fragen!)
  email cancel <id>                                - Entwurf verwerfen

Weitere Handler:
  partner list                                     - Partner anzeigen
  partner delegate "Aufgabe" --to=<partner>        - Aufgabe delegieren
  tools list / tools search "Begriff"              - BACH-Tools
  help <handler>                                   - Hilfe zu Handler

### BACH Library API (programmatisch)
  from bach_api import task, memory, partner, tools, session, app
  task.add("Aufgabe")          memory.write("Notiz")
  task.list()                  partner.delegate("Aufgabe", "--to=gemini")
  session.startup(partner="claude", mode="silent")
  app().execute("handler", "operation", ["arg1"])  # Raw-Zugriff"""


def _load_claude_md() -> str:
    """Laedt CLAUDE.md (globale Regeln) aus User-Home oder BACH-Root."""
    # 1. User-Home (~)
    home_claude_md = Path.home() / "CLAUDE.md"
    if home_claude_md.exists():
        try:
            content = home_claude_md.read_text(encoding='utf-8')
            if content.strip():
                return content[:2000]  # Max 2000 Zeichen
        except Exception:
            pass
    # 2. BACH-Root (Elternordner von system/)
    root_claude_md = BACH_DIR.parent / "CLAUDE.md"
    if root_claude_md.exists():
        try:
            content = root_claude_md.read_text(encoding='utf-8')
            if content.strip():
                return content[:2000]
        except Exception:
            pass
    return ""


def _load_home_memory() -> str:
    """Laedt MEMORY.md aus Home-Memory-Verzeichnis."""
    home_memory = Path.home() / ".claude" / "projects" / "C--Users-User" / "memory" / "MEMORY.md"
    if home_memory.exists():
        try:
            content = home_memory.read_text(encoding='utf-8')
            if content.strip():
                # Erste 150 Zeilen (MEMORY.md ist kompakt)
                lines = content.split('\n')[:150]
                return '\n'.join(lines)
        except Exception:
            pass
    return ""


def build_chat_prompt(new_messages: list, config: dict) -> str:
    """Baut den kompletten Prompt fuer Chat-Claude inkl. Memory + BACH System-Kontext."""
    history = get_recent_history(config, config.get("chat", {}).get("history_count", 15))
    workers = get_worker_status()
    bach_context = get_bach_context()
    bridge_memory = load_bridge_memory()
    cwd = config.get("claude_cli", {}).get("cwd", str(BACH_DIR))

    user_lines = []
    for msg in new_messages:
        user_lines.append(msg["content"])
    user_text = "\n".join(user_lines)

    memory_section = ""
    if bridge_memory:
        memory_section = f"""
## Dein Gedaechtnis (persistent zwischen Neustarts)
{bridge_memory}
"""

    # === Globale Regeln (CLAUDE.md) ===
    claude_md = _load_claude_md()
    claude_md_section = f"""
## Globale Systemregeln (CLAUDE.md)
{claude_md}
""" if claude_md else ""

    # === Home-Memory (MEMORY.md) ===
    home_memory = _load_home_memory()
    home_memory_section = f"""
## Nutzer-Kontext (MEMORY.md)
{home_memory}
""" if home_memory else ""

    # === NEU: Skills laden (SKILL.md + persoenlicher-assistent) ===
    startup_skills = _load_startup_skills()

    bach_skill_section = f"""
## BACH-System Skills (Auto-geladen beim Start)
{startup_skills}
"""

    # === BACH CLI/API Kurzreferenz ===
    bach_cli_ref = _get_bach_cli_reference()

    return f"""Du bist BACH, ein persönlicher KI-Assistent. Du kommunizierst via Telegram.
Antworte knapp und auf Deutsch. KEIN Markdown - kein **, ##, --, keine Sternchen.
WICHTIG: Nutze IMMER echte deutsche Umlaute (ä, ö, ü, Ä, Ö, Ü, ß). NIEMALS ae, oe, ue, ss schreiben.
Stelle dich NICHT vor - der User kennt dich bereits.
Deine Session bleibt den ganzen Tag bestehen (via --continue).
{claude_md_section}
{home_memory_section}
{memory_section}
{bach_skill_section}
## Telegram-Verlauf (letzte Nachrichten)
{history}

## Worker-Status (Hintergrund-Aufgaben)
{workers}

## BACH-System
Working Directory: {cwd}
{bach_context}

## Regeln
- Antworte kurz und prägnant (max 2000 Zeichen)
- Nutze IMMER echte Umlaute (ä, ö, ü, ß) - NIEMALS ae/oe/ue/ss
- Stelle dich NICHT vor, begrüße nicht bei jeder Nachricht
- Beziehe dich auf den Verlauf - du kennst die bisherige Unterhaltung

## BACH CLI & API Referenz
{bach_cli_ref}

## Aufgaben-Ausführung
- Du hast die GLEICHEN Tools wie in der Konsole: Read, Write, Edit, Glob, Grep, Bash, WebSearch, WebFetch
- Du hast Zugriff auf BACH CLI: python bach.py <command>
- Für einfache Aufgaben (< 1 Min): Führe sie DIREKT aus mit deinen Tools
- Für längere Aufgaben: Nutze WORKER: Tag (siehe unten)

## Teams & Multi-Agent (NEU)
- Du kannst Teams mit mehreren Agenten spawnen via TeamCreate + Task Tool
- Nutze Teams für komplexe Aufgaben die Parallelarbeit erfordern
- Beispiel: "Recherchiere X und schreibe gleichzeitig Y" → Team mit 2 Agenten
- Für einfache Hintergrund-Aufgaben reicht ein einzelner WORKER:
- Teams koordinieren sich selbst via SendMessage und TaskCreate/TaskUpdate

## Standort (GPS)
- Der User kann einen GPS-Pin aus Telegram senden
- Du bekommst: "[Standort gesendet] Koordinaten: XX.XXXXX°N, XX.XXXXX°E ..."
- Das Wetter wird AUTOMATISCH vorab abgerufen (wttr.in) und steht im Nachrichten-Text
- Wetter-Daten nutzen: Einfach die vorgefüllten Infos aus der Nachricht wiedergeben
- Route berechnen: Sag dem User "Nenn mir dein Ziel" und nutze dann:
    python <BACH_DIR>/hub/_services/routing/routing_service.py <start_lat> <start_lon> <end_lat> <end_lon> [car|bike|foot]
  oder rufe get_route_text() via Bash/Python aus
- Routing-Modi: car (Auto, Standard), bike (Fahrrad), foot (zu Fuß)
- Nächste Orte/Restaurants: WebSearch mit Koordinaten z.B. "Restaurant 47.761 8.079"
- Adresse ermitteln: WebSearch oder WebFetch nominatim.openstreetmap.org

## E-Mail-Versand
- Du kannst E-Mails senden via: python bach.py email send <to> --subject "..." --body "..."
- Jede Mail wird IMMER als Entwurf erstellt - NICHT direkt gesendet
- NIEMALS einen Entwurf selbst bestätigen (bach email confirm) - IMMER den User fragen!
- Zeige dem User eine Vorschau und sage: "Zum Senden antworte mit: senden <id>"
- Account: user@example.com (Gmail)
- Weitere Befehle: bach email drafts, bach email show <id>, bach email cancel <id>

## Worker (Hintergrund-Aufgaben)
- Wenn der User eine Aufgabe beschreibt die länger als 1 Minute dauert,
  antworte normal UND füge am ENDE eine separate Zeile hinzu:
  WORKER:Kurze Beschreibung der Aufgabe
- Du kannst max. 1 WORKER pro Nachricht starten
- Worker laufen autonom und senden Status-Updates via Telegram

## Memory
- WICHTIG: Wenn du etwas Neues über den User erfährst oder er etwas
  Wichtiges sagt das du dir merken sollst, füge am ENDE hinzu:
  MEMORY:Was du dir merken willst (1-2 Sätze)

## Aktuelle Nachricht(en) vom User
{user_text}"""


def build_followup_prompt(new_messages: list, config: dict,
                          permission_hint: str = "") -> str:
    """Baut minimalen Follow-up-Prompt fuer --continue Session.

    Claude hat den vollen Kontext bereits in seiner Session.
    Wir senden nur die neue Nachricht + ggf. Worker-Status-Updates.
    """
    user_lines = [msg["content"] for msg in new_messages]
    user_text = "\n".join(user_lines)

    parts = []

    # P1-Fix: Claude ueber Rechteaenderung informieren
    if permission_hint:
        parts.append(permission_hint)

    # Worker-Status nur einfuegen wenn relevante Updates vorhanden
    workers = get_worker_status()
    if workers != "(keine Worker)":
        parts.append(f"[Worker-Update: {workers}]")

    parts.append(user_text)
    return "\n\n".join(parts)


def build_worker_prompt(task: str, config: dict) -> str:
    """Baut den Prompt fuer einen Worker mit Sandboxing-Regeln."""
    cwd = config.get("claude_cli", {}).get("cwd", str(BACH_DIR))
    chat_id = config.get("chat_id", "YOUR_CHAT_ID")
    connector = config.get("connector_name", "telegram_main")

    return f"""Du bist ein BACH Worker-Agent. Du arbeitest autonom an einer Aufgabe.
Working Directory: {cwd}

## Deine Tools
Du hast die gleichen Tools wie Claude Code in der Konsole:
Read, Write, Edit, Glob, Grep, Bash, WebSearch, WebFetch, Task
Du kannst BACH CLI nutzen: PYTHONIOENCODING=utf-8 python bach.py <command>

## Teams (fuer komplexe Aufgaben)
Fuer Aufgaben die Parallelarbeit erfordern, kannst du Teams spawnen:
- TeamCreate fuer ein neues Team
- Task Tool um spezialisierte Sub-Agenten zu starten
- TaskCreate/TaskUpdate fuer Koordination
Nutze Teams nur wenn die Aufgabe wirklich davon profitiert.

## VERBOTEN (Sandboxing)
- Du darfst bridge_daemon.py NICHT editieren oder lesen
- Du darfst KEINE Dateien in hub/_services/claude_bridge/ aendern
- Du darfst den Bridge-Daemon NICHT neu starten

## Status-Updates senden
Nutze diesen Befehl um den User ueber Fortschritte zu informieren:
  PYTHONIOENCODING=utf-8 python bach.py connector send {connector} {chat_id} "dein Status-Text"

Sende Updates bei: Beginn, wichtigen Fortschritten, Problemen, Abschluss.

## Aufgabe
{task}

## Wenn fertig
- Sende abschliessenden Status via Telegram
- Schreibe Zusammenfassung als letzte Ausgabe (wird in DB gespeichert)"""


# ============ SESSION CONTEXT / 24h-AGENT (SQ048) ============

class SessionContextManager:
    """Verwaltet tagesbasierte Session-Kontexte und Arbeitsmodi."""

    VALID_MODES = ("focused", "assistant", "autonomous")

    def __init__(self, config: dict):
        self._config = config
        wm = config.get("work_modes", {})
        self._default_mode = wm.get("default", "assistant")

    def get_today_context(self) -> dict:
        """Laedt oder erstellt den Session-Kontext fuer heute."""
        today = date.today().isoformat()
        row = db_execute(
            "SELECT * FROM session_context WHERE date = ?",
            (today,), fetchone=True
        )
        if row:
            ctx = dict(row)
            try:
                ctx["context_json"] = json.loads(ctx.get("context_json", "{}"))
            except (json.JSONDecodeError, TypeError):
                ctx["context_json"] = {}
            return ctx

        # Neuen Eintrag erstellen
        db_execute(
            "INSERT INTO session_context (date, work_mode) VALUES (?, ?)",
            (today, self._default_mode)
        )
        return {
            "date": today, "context_json": {},
            "summary": None, "handover_notes": None,
            "work_mode": self._default_mode
        }

    def save_context(self, context_json: dict, summary: str = None):
        """Aktualisiert den heutigen Session-Kontext."""
        today = date.today().isoformat()
        self.get_today_context()  # Sicherstellen, dass Eintrag existiert
        if summary:
            db_execute(
                "UPDATE session_context SET context_json = ?, summary = ?, "
                "updated_at = datetime('now') WHERE date = ?",
                (json.dumps(context_json, ensure_ascii=False), summary, today)
            )
        else:
            db_execute(
                "UPDATE session_context SET context_json = ?, "
                "updated_at = datetime('now') WHERE date = ?",
                (json.dumps(context_json, ensure_ascii=False), today)
            )

    def day_transition(self, old_summary: str = None):
        """Tageswechsel: Alten Kontext zusammenfassen, neuen Tag mit Handover starten."""
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        today = date.today().isoformat()

        # Gestern: Summary setzen falls vorhanden
        if old_summary:
            db_execute(
                "UPDATE session_context SET summary = ?, updated_at = datetime('now') "
                "WHERE date = ?",
                (old_summary, yesterday)
            )

        # Handover-Notes vom Vortag holen
        prev_row = db_execute(
            "SELECT summary FROM session_context WHERE date = ? ",
            (yesterday,), fetchone=True
        )
        handover = prev_row["summary"] if prev_row and prev_row["summary"] else None

        # Heute erstellen (falls noch nicht vorhanden)
        existing = db_execute(
            "SELECT id FROM session_context WHERE date = ?",
            (today,), fetchone=True
        )
        if not existing:
            db_execute(
                "INSERT INTO session_context (date, work_mode, handover_notes) VALUES (?, ?, ?)",
                (today, self._default_mode, handover)
            )
            log(f"DAY TRANSITION: Neuer Tag {today}, Handover: {'ja' if handover else 'nein'}")
        return handover

    def get_work_mode(self) -> str:
        """Gibt den aktuellen Arbeitsmodus zurueck."""
        ctx = self.get_today_context()
        return ctx.get("work_mode", self._default_mode)

    def set_work_mode(self, mode: str) -> bool:
        """Setzt den Arbeitsmodus fuer heute. Gibt False zurueck bei ungueltigem Modus."""
        if mode not in self.VALID_MODES:
            return False
        today = date.today().isoformat()
        self.get_today_context()  # Sicherstellen, dass Eintrag existiert
        db_execute(
            "UPDATE session_context SET work_mode = ?, updated_at = datetime('now') "
            "WHERE date = ?",
            (mode, today)
        )
        log(f"WORK MODE: {mode}")
        return True


# ============ BRIDGE DAEMON ============

class BridgeDaemon:
    """Hauptdaemon: Verbindet Telegram mit Claude Code CLI."""

    def __init__(self):
        self.config = _resolve_claude_cli_path(load_config())
        self.stop_event = Event()
        self.worker_threads = []
        self.worker_lock = Lock()

        # Persistenten State laden
        state = load_state()
        self.permission_mode = state.get("permission_mode",
                                         self.config.get("permissions", {}).get("default_mode", "restricted"))
        self.full_mode_since = state.get("full_mode_since", 0.0)

        # Budget aus State laden (persistent!)
        self.budget_enabled = state.get("budget_enabled", True)
        today_str = date.today().isoformat()
        if state.get("budget_date") == today_str:
            self.daily_spent = state.get("daily_spent", 0.0)
        else:
            self.daily_spent = 0.0
        self.daily_date = date.today()

        # Session-Tracking: Claude bleibt via --continue persistent
        self.has_active_session = state.get("has_active_session", False)
        self.session_start_time = state.get("session_start_time", None)
        self._last_chat_failed = False
        self._permission_changed = False  # P1-Fix: Wird True nach toggle, Reset nach Claude-Aufruf
        self._fackel_lost = False  # True wenn Fackel durch Force-Takeover verloren

        # Async-Chat: Nachrichten werden in Thread verarbeitet, Main-Loop bleibt frei
        self._chat_thread = None
        self._chat_lock = Lock()
        self._pending_messages = []  # Liste von (messages, perm_hint) Tupeln
        self._chat_busy = False

        # Voice-Modus: Antworten als Sprachnachricht senden
        self.voice_mode = state.get("voice_mode", False)

        # Max-Turns: 0 = kein Limit (--max-turns wird weggelassen), >0 = explizites Limit
        self.max_turns = state.get("max_turns",
                                   self.config.get("chat", {}).get("max_turns", 0))

        # Chat-Timeout: 0 = kein Timeout (Default), >0 = Inaktivitaets-Timeout in Sekunden
        self.chat_timeout = state.get("chat_timeout",
                                      self.config.get("chat", {}).get("timeout_seconds", 0))

        # Aktuelles Claude-Modell (persistent, via Telegram/Tray aenderbar)
        self.current_model = state.get("current_model",
                                       self.config.get("claude_cli", {}).get("model", "sonnet"))

        # SQ048: Session Context Manager & Arbeitsmodus
        self.session_ctx = SessionContextManager(self.config)
        self.work_mode = state.get("work_mode",
                                   self.config.get("work_modes", {}).get("default", "assistant"))

    def _save_state(self):
        """Speichert aktuellen State persistent."""
        save_state({
            "permission_mode": self.permission_mode,
            "full_mode_since": self.full_mode_since,
            "daily_spent": self.daily_spent,
            "budget_date": self.daily_date.isoformat(),
            "budget_enabled": self.budget_enabled,
            "has_active_session": self.has_active_session,
            "session_start_time": self.session_start_time,
            "voice_mode": self.voice_mode,
            "max_turns": self.max_turns,
            "chat_timeout": self.chat_timeout,
            "current_model": self.current_model,
            "work_mode": self.work_mode,
        })

    # ---------- POLLING ----------

    def poll_new_messages(self) -> list:
        """Pollt neue Nachrichten mit Alters-Limit und Batch-Fenster."""
        connector = self.config.get("connector_name", "telegram_main")
        batch_wait = self.config.get("chat", {}).get("message_batch_wait_seconds", 3)
        max_age = MAX_MESSAGE_AGE

        # Berechne Cutoff-Zeitpunkt
        cutoff = (datetime.now() - timedelta(seconds=max_age)).isoformat()

        rows = db_execute(
            "SELECT id, sender, content, created_at FROM connector_messages "
            "WHERE direction = 'in' AND connector_name = ? "
            "AND bridge_processed = 0 AND created_at >= ? "
            "ORDER BY created_at ASC",
            (connector, cutoff), fetch=True
        )

        # Alte unverarbeitete Nachrichten als verarbeitet markieren (aufraemen)
        old_rows = db_execute(
            "SELECT id FROM connector_messages "
            "WHERE direction = 'in' AND connector_name = ? "
            "AND bridge_processed = 0 AND created_at < ?",
            (connector, cutoff), fetch=True
        )
        if old_rows:
            old_count = len(old_rows)
            for r in old_rows:
                db_execute(
                    "UPDATE connector_messages SET bridge_processed = 1 WHERE id = ?",
                    (r["id"],)
                )
            log(f"CLEANUP: {old_count} alte Nachricht(en) uebersprungen (aelter als {max_age}s)")

        if not rows:
            return []

        # Kurz warten fuer Batching
        time.sleep(batch_wait)

        # Nochmal lesen (vielleicht kamen mehr)
        rows = db_execute(
            "SELECT id, sender, content, created_at FROM connector_messages "
            "WHERE direction = 'in' AND connector_name = ? "
            "AND bridge_processed = 0 AND created_at >= ? "
            "ORDER BY created_at ASC",
            (connector, cutoff), fetch=True
        )

        return [dict(r) for r in rows] if rows else []

    def mark_processed(self, msg_ids: list):
        """Markiert Nachrichten als verarbeitet."""
        for mid in msg_ids:
            db_execute(
                "UPDATE connector_messages SET bridge_processed = 1 WHERE id = ?",
                (mid,)
            )

    # ---------- CODEWORT ----------

    def handle_codeword(self, msg: dict) -> bool:
        """Prueft und verarbeitet Codewort-Befehle."""
        content = msg["content"].strip()
        content_lower = content.lower()
        first_word = content_lower.split()[0] if content_lower else ""

        if first_word == "toggle":
            if self.permission_mode == "restricted":
                self.permission_mode = "full"
                self.full_mode_since = time.time()
                self._permission_changed = True  # P1-Fix: Claude beim naechsten Aufruf informieren
                timeout_min = self.config.get("permissions", {}).get("full_access_timeout_seconds", 3600) // 60
                send_telegram(
                    f"Vollzugriff AKTIVIERT\n"
                    f"Auto-Lock in {timeout_min} Min.\n"
                    f"Naechster Claude startet mit vollen Rechten.",
                    self.config
                )
                log("MODUS: full (toggle)")
            else:
                self.permission_mode = "restricted"
                self._permission_changed = True  # P1-Fix: Claude beim naechsten Aufruf informieren
                send_telegram(
                    f"Eingeschraenkter Modus AKTIVIERT\n"
                    f"Claude kann lesen, schreiben, suchen, Bash.\n"
                    f"Destruktive Ops (rm, force-push) geblockt.",
                    self.config
                )
                log("MODUS: restricted (toggle)")
            self._save_state()
            return True

        if first_word == "mode":
            parts = content_lower.split()
            new_mode = parts[1] if len(parts) > 1 else ""
            if new_mode in SessionContextManager.VALID_MODES:
                # SQ048: Arbeitsmodus setzen
                self.work_mode = new_mode
                self.session_ctx.set_work_mode(new_mode)
                self._save_state()
                labels = {
                    "focused": "Fokussiert (minimale Unterbrechungen)",
                    "assistant": "Assistent (Standard, reagiert auf alles)",
                    "autonomous": "Autonom (proaktive Aktionen)"
                }
                send_telegram(f"Arbeitsmodus: {labels.get(new_mode, new_mode)}", self.config)
            else:
                # Status beider Modi anzeigen
                info = f"Rechte: {self.permission_mode}"
                if self.permission_mode == "full" and self.full_mode_since:
                    timeout = self.config.get("permissions", {}).get("full_access_timeout_seconds", 3600)
                    remaining = int(timeout - (time.time() - self.full_mode_since))
                    if remaining > 0:
                        info += f" (Auto-Lock in {remaining // 60} Min)"
                info += f"\nArbeitsmodus: {self.work_mode}"
                info += "\nVerfuegbar: mode focused / assistant / autonomous"
                send_telegram(info, self.config)
            return True

        if first_word == "budget":
            parts = content_lower.split()
            sub = parts[1] if len(parts) > 1 else ""

            if sub == "off":
                self.budget_enabled = False
                self._save_state()
                send_telegram(
                    "Budget-Limit DEAKTIVIERT\n"
                    "Keine Kostenbegrenzung aktiv.\n"
                    "Reaktivieren mit: budget on",
                    self.config
                )
                log("BUDGET: deaktiviert (manuell)")
                return True

            if sub == "on":
                self.budget_enabled = True
                self._save_state()
                limit = self.config.get("budget", {}).get("daily_limit_usd", 5.0)
                send_telegram(
                    f"Budget-Limit AKTIVIERT\n"
                    f"Limit: ${limit:.2f}/Tag\n"
                    f"Aktuell: ${self.daily_spent:.2f} verbraucht",
                    self.config
                )
                log("BUDGET: aktiviert (manuell)")
                return True

            if sub == "reset":
                self.daily_spent = 0.0
                self.daily_date = date.today()
                self._save_state()
                limit = self.config.get("budget", {}).get("daily_limit_usd", 5.0)
                send_telegram(
                    f"Budget zurueckgesetzt\n"
                    f"Verbrauch: $0.00 / ${limit:.2f}\n"
                    f"Status: {'aktiv' if self.budget_enabled else 'deaktiviert'}",
                    self.config
                )
                log("BUDGET: reset (manuell)")
                return True

            if sub == "set" and len(parts) >= 3:
                try:
                    new_limit = float(parts[2].replace(",", "."))
                    if new_limit <= 0:
                        send_telegram("Budget-Limit muss groesser als 0 sein.", self.config)
                        return True
                    # Config-Datei aktualisieren
                    cfg = load_config()
                    if "budget" not in cfg:
                        cfg["budget"] = {}
                    cfg["budget"]["daily_limit_usd"] = new_limit
                    CONFIG_FILE.write_text(
                        json.dumps(cfg, indent=4, ensure_ascii=False),
                        encoding="utf-8"
                    )
                    self.config = cfg
                    send_telegram(
                        f"Budget-Limit geaendert: ${new_limit:.2f}/Tag\n"
                        f"Aktuell verbraucht: ${self.daily_spent:.2f}",
                        self.config
                    )
                    log(f"BUDGET: Limit geaendert auf ${new_limit:.2f}")
                    return True
                except ValueError:
                    send_telegram(
                        f"Ungueltiger Betrag: {parts[2]}\n"
                        f"Beispiel: budget set 10",
                        self.config
                    )
                    return True

            # Kein Sub-Command: Status anzeigen
            send_telegram(self.get_budget_status(), self.config)
            return True

        if first_word == "workers":
            status = get_worker_status()
            send_telegram(status if status != "(keine Worker)" else "Keine aktiven oder kuerzlichen Worker.", self.config)
            return True

        if first_word == "stop":
            self._stop_workers()
            return True

        if first_word == "memory":
            mem = load_bridge_memory()
            send_telegram(mem if mem else "Noch kein Chat-Memory gespeichert.", self.config)
            return True

        if first_word == "reset":
            # Session-Summary speichern bevor Reset
            if self.has_active_session:
                self._save_session_summary()
            self.has_active_session = False
            self.session_start_time = None
            self._save_state()
            send_telegram(
                "Session zurueckgesetzt.\n"
                "Naechste Nachricht startet neuen Claude mit vollem System-Prompt.",
                self.config
            )
            log("SESSION RESET (manuell via Codeword)")
            return True

        if first_word == "voice":
            parts = content_lower.split()
            sub = parts[1] if len(parts) > 1 else ""
            if sub == "on":
                self.voice_mode = True
                self._save_state()
                send_telegram("Voice-Modus AKTIVIERT\nAntworten werden als Sprachnachricht gesendet.\nDeaktivieren mit: voice off", self.config)
                log("VOICE MODE: aktiviert")
            elif sub == "off":
                self.voice_mode = False
                self._save_state()
                send_telegram("Voice-Modus DEAKTIVIERT\nAntworten wieder als Text.", self.config)
                log("VOICE MODE: deaktiviert")
            else:
                status = "aktiv" if self.voice_mode else "inaktiv"
                send_telegram(f"Voice-Modus: {status}\nBefehle: voice on / voice off", self.config)
            return True

        if content_lower == "telegram-test" or content_lower == "tg-test":
            # Direkttest: Bot-Info + gesendete Testnachricht
            try:
                import urllib.request as _ur
                row = db_execute(
                    "SELECT auth_config FROM connections WHERE name='telegram_main' LIMIT 1",
                    fetch=True
                )
                if row:
                    auth = json.loads(row[0]["auth_config"] or "{}")
                    token = auth.get("bot_token", "") or _load_bot_token_from_file()
                    if token:
                        url = f"https://api.telegram.org/bot{token}/getMe"
                        resp = _ur.urlopen(url, timeout=10)
                        data = json.loads(resp.read())
                        if data.get("ok"):
                            bot = data["result"]
                            send_telegram(
                                f"Telegram-Test OK!\n"
                                f"Bot: {bot.get('first_name')} (@{bot.get('username')})\n"
                                f"ID: {bot.get('id')}\n"
                                f"Verbindung: aktiv",
                                self.config
                            )
                        else:
                            send_telegram(f"Telegram-Test FEHLER: {data.get('description')}", self.config)
                    else:
                        send_telegram("Telegram-Test: Kein Bot-Token in DB!", self.config)
                else:
                    send_telegram("Telegram-Test: Kein telegram_main Connector in DB!", self.config)
            except Exception as e:
                send_telegram(f"Telegram-Test FEHLER: {e}", self.config)
            return True

        if first_word == "turns":
            parts = content_lower.split()
            sub = parts[1] if len(parts) > 1 else ""
            if sub == "unlimited" or sub == "max" or sub == "0":
                self.max_turns = 0
                self._save_state()
                send_telegram("Max-Turns: kein Limit (--max-turns wird nicht gesetzt).", self.config)
                log("MAX_TURNS: 0 (kein Limit)")
            elif sub.isdigit():
                n = int(sub)
                if 1 <= n <= 500:
                    self.max_turns = n
                    self._save_state()
                    send_telegram(f"Max-Turns: {n}", self.config)
                    log(f"MAX_TURNS: {n}")
                else:
                    send_telegram("Gueltig: 1-500 oder 'unlimited'", self.config)
            else:
                cfg_default = self.config.get("chat", {}).get("max_turns", 0)
                cur_str = "kein Limit" if self.max_turns == 0 else str(self.max_turns)
                def_str = "kein Limit" if cfg_default == 0 else str(cfg_default)
                send_telegram(
                    f"Max-Turns aktuell: {cur_str} (Config-Default: {def_str})\n"
                    f"Aendern: turns <n> oder turns unlimited",
                    self.config
                )
            return True

        if first_word == "timeout":
            parts = content_lower.split()
            sub = parts[1] if len(parts) > 1 else ""
            if sub == "off" or sub == "unlimited" or sub == "0":
                self.chat_timeout = 0
                self._save_state()
                send_telegram("Chat-Timeout: AUS (kein Inaktivitaets-Limit).", self.config)
                log("CHAT_TIMEOUT: 0 (deaktiviert)")
            elif sub.isdigit():
                n = int(sub)
                if n >= 10:
                    self.chat_timeout = n
                    self._save_state()
                    send_telegram(f"Chat-Timeout: {n} Sekunden Inaktivitaet.", self.config)
                    log(f"CHAT_TIMEOUT: {n}s")
                else:
                    send_telegram("Timeout muss mindestens 10 Sekunden sein oder 0/off.", self.config)
            else:
                cur_str = "AUS (kein Limit)" if self.chat_timeout == 0 else f"{self.chat_timeout}s"
                cfg_default = self.config.get("chat", {}).get("timeout_seconds", 0)
                def_str = "AUS" if cfg_default == 0 else f"{cfg_default}s"
                send_telegram(
                    f"Chat-Timeout aktuell: {cur_str} (Config-Default: {def_str})\n"
                    f"Aendern: timeout <sekunden> oder timeout off",
                    self.config
                )
            return True

        if first_word == "queue":
            with self._chat_lock:
                busy = self._chat_busy
                pending_count = len(self._pending_messages)
            status = "beschaeftigt" if busy else "frei"
            send_telegram(
                f"Chat-Status: {status}\n"
                f"Wartende Nachrichten: {pending_count}",
                self.config
            )
            return True

        if content_lower == "help":
            help_text = (
                "BACH Bridge Befehle:\n"
                "  toggle - Vollzugriff ein/aus\n"
                "  mode - Arbeitsmodus (focused/assistant/autonomous)\n"
                "  turns <n> - Max-Turns setzen (z.B. turns 50)\n"
                "  turns unlimited - Kein Turn-Limit (Default)\n"
                "  turns - Aktuellen Wert anzeigen\n"
                "  timeout <sek> - Inaktivitaets-Timeout setzen\n"
                "  timeout off - Kein Timeout (Default)\n"
                "  budget - Budget-Status anzeigen\n"
                "  budget set <$> - Limit setzen\n"
                "  budget on/off - Limit ein/ausschalten\n"
                "  budget reset - Verbrauch zuruecksetzen\n"
                "  workers - Worker-Uebersicht\n"
                "  stop - Laufende Worker stoppen\n"
                "  queue - Chat-Queue Status\n"
                "  memory - Chat-Memory anzeigen\n"
                "  reset - Neue Claude-Session starten\n"
                "  voice on/off - Antworten als Sprachnachricht\n"
                "  model - Aktuelles Modell anzeigen\n"
                "  model up/down - Opus/Haiku wechseln\n"
                "  change model <name> - Beliebiges Modell\n"
                "  telegram-test - Telegram-Verbindung pruefen\n"
                "  senden <id> - E-Mail-Entwurf senden\n"
                "  verwerfen <id> - E-Mail-Entwurf verwerfen\n"
                "  entwuerfe - Offene Entwuerfe anzeigen\n"
                "  help - Diese Hilfe\n\n"
                "Standort senden: GPS-Pin in Telegram -> Claude fragt Wetter/Route.\n"
                "Claude bleibt den ganzen Tag derselbe (--continue).\n"
                "Chat ist async - neue Nachrichten werden gequeued.\n"
                "Alles andere wird an Claude weitergeleitet."
            )
            send_telegram(help_text, self.config)
            return True

        # Email-Codewords: senden/verwerfen/entwuerfe
        if first_word == "senden" and len(content.split()) >= 2:
            draft_id_str = content.split()[1]
            try:
                draft_id = int(draft_id_str)
            except ValueError:
                send_telegram(f"Ungueltige Draft-ID: {draft_id_str}", self.config)
                return True
            result = self._execute_bach_command(f"email confirm {draft_id} --by telegram")
            send_telegram(result, self.config)
            return True

        if first_word == "verwerfen" and len(content.split()) >= 2:
            draft_id_str = content.split()[1]
            try:
                draft_id = int(draft_id_str)
            except ValueError:
                send_telegram(f"Ungueltige Draft-ID: {draft_id_str}", self.config)
                return True
            result = self._execute_bach_command(f"email cancel {draft_id}")
            send_telegram(result, self.config)
            return True

        if first_word == "entwuerfe":
            result = self._execute_bach_command("email drafts")
            send_telegram(result, self.config)
            return True

        if first_word == "model":
            parts = content_lower.split()
            sub = parts[1] if len(parts) > 1 else ""

            if sub == "up":
                old = self.current_model
                self.current_model = "opus"
                self.has_active_session = False
                self.session_start_time = None
                self._save_state()
                send_telegram(
                    f"Modell: {old} -> OPUS\n"
                    f"Session zurueckgesetzt (neues Modell).",
                    self.config
                )
                log(f"MODEL: {old} -> opus")
                return True

            if sub == "down":
                old = self.current_model
                self.current_model = "haiku"
                self.has_active_session = False
                self.session_start_time = None
                self._save_state()
                send_telegram(
                    f"Modell: {old} -> HAIKU\n"
                    f"Session zurueckgesetzt (neues Modell).",
                    self.config
                )
                log(f"MODEL: {old} -> haiku")
                return True

            # Kein Sub: Status anzeigen
            send_telegram(
                f"Aktuelles Modell: {self.current_model}\n"
                f"Aendern:\n"
                f"  model up - Opus (teurer, besser)\n"
                f"  model down - Haiku (guenstiger, schneller)\n"
                f"  change model <name> - Beliebiges Modell",
                self.config
            )
            return True

        if content_lower.startswith("change model"):
            parts = content.split()
            if len(parts) >= 3:
                new_model = parts[2].lower()
                old = self.current_model
                self.current_model = new_model
                self.has_active_session = False
                self.session_start_time = None
                self._save_state()
                send_telegram(
                    f"Modell: {old} -> {new_model.upper()}\n"
                    f"Session zurueckgesetzt (neues Modell).",
                    self.config
                )
                log(f"MODEL: {old} -> {new_model}")
            else:
                send_telegram(
                    f"Verwendung: change model <name>\n"
                    f"Beispiel: change model opus\n"
                    f"Aktuell: {self.current_model}",
                    self.config
                )
            return True

        return False

    def _execute_bach_command(self, command: str) -> str:
        """Fuehrt einen BACH CLI Befehl aus und gibt Output zurueck."""
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        try:
            result = subprocess.run(
                [sys.executable, "bach.py"] + command.split(),
                capture_output=True, timeout=30,
                env=env, cwd=str(BACH_DIR)
            )
            # Smart-Decode
            try:
                from tools.encoding_fix import sanitize_subprocess_output
                stdout = sanitize_subprocess_output(result.stdout or b"")
                stderr = sanitize_subprocess_output(result.stderr or b"")
            except ImportError:
                stdout = (result.stdout or b"").decode('utf-8', errors='replace')
                stderr = (result.stderr or b"").decode('utf-8', errors='replace')
            return stdout.strip() or stderr.strip() or "Kein Output"
        except subprocess.TimeoutExpired:
            return "Timeout bei Ausfuehrung"
        except Exception as e:
            return f"Fehler: {e}"

    # ---------- BUDGET (PERSISTENT) ----------

    def check_budget(self) -> bool:
        """Prueft ob Budget noch reicht. Bei neuem Tag: Session-Summary + Reset."""
        today = date.today()
        if today > self.daily_date:
            # Neuer Tag: Session-Summary speichern und Session zuruecksetzen
            old_summary = None
            if self.has_active_session:
                log("NEUER TAG: Speichere Session-Summary...")
                self._save_session_summary()
                old_summary = f"Session vom {self.daily_date.isoformat()}"
                self.has_active_session = False
                self.session_start_time = None
                log("NEUER TAG: Session zurueckgesetzt, Budget zurueckgesetzt")
            self.daily_spent = 0.0
            self.daily_date = today
            # SQ048: Day-Transition mit Handover
            try:
                handover = self.session_ctx.day_transition(old_summary)
                self.work_mode = self.session_ctx.get_work_mode()
                if handover:
                    log(f"HANDOVER: {handover[:100]}")
            except Exception as e:
                log(f"DAY TRANSITION Fehler: {e}", "WARN")
            self._save_state()

        # Budget deaktiviert = immer erlaubt
        if not self.budget_enabled:
            return True

        limit = self.config.get("budget", {}).get("daily_limit_usd", 5.0)
        return self.daily_spent < limit

    def record_cost(self, amount: float):
        self.daily_spent += amount
        self._save_state()

    def get_budget_status(self) -> str:
        limit = self.config.get("budget", {}).get("daily_limit_usd", 5.0)
        pct = (self.daily_spent / limit * 100) if limit > 0 else 0
        status = "aktiv" if self.budget_enabled else "DEAKTIVIERT"
        return f"Budget: ${self.daily_spent:.2f} / ${limit:.2f} ({pct:.0f}%) [{status}]"

    # ---------- FULL-ACCESS TIMEOUT ----------

    def check_full_mode_timeout(self):
        """Setzt Modus zurueck wenn Vollzugriff-Timeout abgelaufen."""
        if self.permission_mode != "full":
            return
        timeout = self.config.get("permissions", {}).get("full_access_timeout_seconds", 3600)
        if time.time() - self.full_mode_since > timeout:
            self.permission_mode = "restricted"
            self._permission_changed = True  # P1-Fix: Claude informieren
            self._save_state()
            send_telegram("Vollzugriff automatisch deaktiviert (Timeout).", self.config)
            log("MODUS: restricted (timeout)")

    # ---------- CHAT ----------

    def run_claude_chat(self, prompt: str, use_continue: bool = False) -> str:
        """Startet claude -p und gibt Antwort zurueck.

        Args:
            prompt: Der Prompt-Text
            use_continue: True = --continue (bestehende Session fortsetzen),
                          False = neue Session (voller System-Prompt)
        """
        self._last_chat_failed = False

        cli_config = self.config.get("claude_cli", {})
        cli_path = cli_config.get("path", "claude")
        cwd = cli_config.get("cwd", str(BACH_DIR))
        model = self.current_model
        timeout = self.chat_timeout  # 0 = kein Timeout

        # Prompt via stdin statt CLI-Argument (Windows 32K Commandline-Limit)
        # max_turns aus State (via "turns" Codeword aenderbar), Fallback auf Config
        # max_turns == 0 bedeutet kein Limit (--max-turns wird weggelassen)
        max_turns = self.max_turns
        cmd = [cli_path, "-p", "--output-format", "text"]
        if max_turns > 0:
            cmd += ["--max-turns", str(max_turns)]

        if use_continue:
            cmd += ["--continue"]
            # Kein --no-session-persistence: Session wird automatisch gespeichert

        if self.permission_mode == "full":
            cmd += ["--dangerously-skip-permissions"]
        else:
            tools = self.config.get("permissions", {}).get("restricted_allowed_tools", "Read,Grep,Glob,Bash")
            cmd += ["--allowedTools", tools]

        cmd += ["--model", model]

        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"

        creation_flags = 0x08000000 if sys.platform == "win32" else 0

        mode_str = "CONTINUE" if use_continue else "NEW"
        log(f"CHAT START [{mode_str}]: claude -p ... --model {model} --permission={self.permission_mode}")
        start_time = time.time()

        try:
            # Popen + Streaming: Inaktivitaets-Timeout statt absolutem Timeout
            # Solange Claude Ausgabe produziert (Tool-Calls etc.), wird Timer zurueckgesetzt
            import threading
            proc = subprocess.Popen(
                cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                env=env, cwd=cwd, creationflags=creation_flags
            )
            # Pruefen ob Prozess noch lebt bevor stdin beschrieben wird
            if proc.poll() is not None:
                stderr_out = ""
                try:
                    stderr_out = proc.stderr.read().decode("utf-8", errors="replace")[:500] if proc.stderr else ""
                except Exception:
                    pass
                log(f"CHAT: Prozess bereits beendet (exit={proc.returncode}), stderr: {stderr_out}", "ERROR")
                self._last_chat_failed = True
                return f"Fehler: Claude beendet (exit={proc.returncode}). {stderr_out}"

            try:
                proc.stdin.write(prompt.encode("utf-8"))
                proc.stdin.close()
            except BrokenPipeError:
                stderr_out = ""
                try:
                    stderr_out = proc.stderr.read().decode("utf-8", errors="replace")[:500] if proc.stderr else ""
                except Exception:
                    pass
                log(f"CHAT: Broken pipe, stderr: {stderr_out}", "WARN")
                proc.wait()
                self._last_chat_failed = True
                return f"Fehler: Claude Broken pipe. {stderr_out}"

            stdout_chunks = []
            stderr_chunks = []
            last_activity = [time.time()]

            def read_stdout():
                for chunk in iter(lambda: proc.stdout.read(256), b""):
                    stdout_chunks.append(chunk)
                    last_activity[0] = time.time()
                proc.stdout.close()

            def read_stderr():
                for chunk in iter(lambda: proc.stderr.read(256), b""):
                    stderr_chunks.append(chunk)
                proc.stderr.close()

            t_out = threading.Thread(target=read_stdout, daemon=True)
            t_err = threading.Thread(target=read_stderr, daemon=True)
            t_out.start()
            t_err.start()

            # Warte auf Prozessende - Timeout nur bei Inaktivitaet (0 = kein Timeout)
            timed_out = False
            while proc.poll() is None:
                time.sleep(1)
                if timeout > 0 and time.time() - last_activity[0] > timeout:
                    proc.terminate()
                    timed_out = True
                    break

            t_out.join(5)
            t_err.join(5)

            if timed_out:
                log(f"CHAT TIMEOUT [{mode_str}]: >{timeout}s Inaktivitaet", "ERROR")
                self._last_chat_failed = True
                return "Timeout - die Verarbeitung hat zu lange gedauert. Versuche es mit einer einfacheren Frage."

            duration = time.time() - start_time
            log(f"CHAT DONE [{mode_str}]: {duration:.1f}s, exit={proc.returncode}")

            # Kosten schaetzen
            cost = self.config.get("budget", {}).get("chat_cost_estimate", 0.03)
            self.record_cost(cost)

            # Smart-Decode: UTF-8 bevorzugt, cp1252 Fallback
            raw_stdout = b"".join(stdout_chunks)
            raw_stderr = b"".join(stderr_chunks)
            try:
                from tools.encoding_fix import sanitize_subprocess_output
                stdout_text = sanitize_subprocess_output(raw_stdout)
                stderr_text = sanitize_subprocess_output(raw_stderr)
            except ImportError:
                stdout_text = raw_stdout.decode('utf-8', errors='replace')
                stderr_text = raw_stderr.decode('utf-8', errors='replace')

            if proc.returncode != 0:
                stderr = stderr_text[:500] or "Unbekannter Fehler"
                log(f"CHAT ERROR [{mode_str}]: {stderr}", "ERROR")
                # Modell-Fallback: Bei Opus-Rate-Limit auf Sonnet wechseln
                if model != "sonnet" and any(kw in stderr.lower() for kw in
                                             ["rate limit", "overloaded", "529", "quota", "capacity"]):
                    log(f"MODELL FALLBACK: {model} → sonnet (Rate-Limit/Overload)", "WARN")
                    send_telegram(f"[Modell {model} überlastet - Fallback auf Sonnet]", self.config)
                    fallback_cmd = [x if x != model else "sonnet" for x in cmd]
                    try:
                        proc2 = subprocess.Popen(
                            fallback_cmd, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            env=env, cwd=cwd, creationflags=creation_flags
                        )
                        # Pruefen ob Fallback-Prozess noch lebt
                        if proc2.poll() is not None:
                            stderr_out = ""
                            try:
                                stderr_out = proc2.stderr.read().decode("utf-8", errors="replace")[:500] if proc2.stderr else ""
                            except Exception:
                                pass
                            log(f"FALLBACK: Prozess bereits beendet (exit={proc2.returncode}), stderr: {stderr_out}", "ERROR")
                            raise RuntimeError(f"Fallback-Prozess beendet (exit={proc2.returncode}). {stderr_out}")

                        try:
                            proc2.stdin.write(prompt.encode("utf-8"))
                            proc2.stdin.close()
                        except BrokenPipeError:
                            stderr_out = ""
                            try:
                                stderr_out = proc2.stderr.read().decode("utf-8", errors="replace")[:500] if proc2.stderr else ""
                            except Exception:
                                pass
                            log(f"FALLBACK: Broken pipe, stderr: {stderr_out}", "WARN")
                            proc2.wait()
                            raise
                        fb_out, fb_err = proc2.communicate(timeout=timeout)
                        try:
                            from tools.encoding_fix import sanitize_subprocess_output
                            fb_text = sanitize_subprocess_output(fb_out)
                        except ImportError:
                            fb_text = fb_out.decode('utf-8', errors='replace')
                        if proc2.returncode == 0 and fb_text.strip():
                            log(f"MODELL FALLBACK: Sonnet erfolgreich")
                            return fb_text.strip()
                    except Exception as fb_e:
                        log(f"MODELL FALLBACK fehlgeschlagen: {fb_e}", "WARN")
                self._last_chat_failed = True
                return f"Fehler bei Verarbeitung: {stderr[:200]}"

            output = stdout_text.strip()
            if not output:
                stderr = stderr_text.strip()
                if stderr:
                    log(f"CHAT WARN [{mode_str}]: stdout leer, stderr: {stderr[:200]}", "WARN")
                    self._last_chat_failed = True
                    return f"Fehler: {stderr[:200]}"
                return "Keine Antwort erhalten."
            return output

        except FileNotFoundError:
            log(f"CHAT ERROR [{mode_str}]: Claude CLI nicht gefunden: {cli_path}", "ERROR")
            self._last_chat_failed = True
            return "Claude CLI nicht gefunden. Bitte Installation pruefen."
        except Exception as e:
            log(f"CHAT ERROR [{mode_str}]: {e}", "ERROR")
            self._last_chat_failed = True
            return f"Fehler: {str(e)[:200]}"

    def extract_worker_tasks(self, response: str) -> list:
        """Extrahiert WORKER: Tags aus Claude-Antwort (max 1)."""
        tasks = []
        for line in response.split("\n"):
            line = line.strip()
            if line.startswith("WORKER:"):
                task_desc = line[7:].strip()
                if task_desc:
                    tasks.append(task_desc)
                    break  # Max 1 Worker pro Nachricht
        return tasks

    def extract_memory_updates(self, response: str) -> list:
        """Extrahiert MEMORY: Tags aus Claude-Antwort."""
        updates = []
        for line in response.split("\n"):
            line = line.strip()
            if line.startswith("MEMORY:"):
                mem = line[7:].strip()
                if mem:
                    updates.append(mem)
        return updates

    # ---------- ASYNC CHAT ----------

    def _start_chat_async(self, messages: list, perm_hint: str = ""):
        """Startet Chat in Hintergrund-Thread. Main-Loop bleibt frei."""
        with self._chat_lock:
            self._chat_busy = True

        self._chat_thread = Thread(
            target=self._chat_thread_fn,
            args=(messages, perm_hint),
            daemon=True
        )
        self._chat_thread.start()
        log(f"CHAT ASYNC: Thread gestartet mit {len(messages)} Nachricht(en)")

    def _chat_thread_fn(self, messages: list, perm_hint: str):
        """Chat-Thread: Verarbeitet Nachrichten, prueft Pending-Queue."""
        try:
            self._execute_chat_round(messages, perm_hint)

            # Pending-Nachrichten abarbeiten (FIFO)
            while True:
                with self._chat_lock:
                    if not self._pending_messages:
                        self._chat_busy = False
                        log("CHAT ASYNC: Thread fertig, keine Pending-Nachrichten")
                        return
                    pending_batch, pending_hint = self._pending_messages.pop(0)

                log(f"CHAT ASYNC: Verarbeite {len(pending_batch)} Pending-Nachricht(en)")
                self._execute_chat_round(pending_batch, pending_hint)

        except Exception as e:
            log(f"CHAT THREAD ERROR: {e}", "ERROR")
            with self._chat_lock:
                self._chat_busy = False

    def _execute_chat_round(self, messages: list, perm_hint: str = ""):
        """Fuehrt einen Chat-Durchlauf aus (Prompt bauen, Claude rufen, Antwort senden)."""
        if self.has_active_session:
            # Follow-up: Nur User-Text, Claude hat Kontext
            prompt = build_followup_prompt(messages, self.config,
                                           permission_hint=perm_hint)
            response = self.run_claude_chat(prompt, use_continue=True)

            # Fallback: Wenn --continue fehlschlaegt, neue Session
            if self._last_chat_failed:
                log("CONTINUE FAILED: Fallback zu neuer Session")
                self.has_active_session = False
                self._save_state()
                prompt = build_chat_prompt(messages, self.config)
                response = self.run_claude_chat(prompt, use_continue=False)
                if not self._last_chat_failed:
                    self.has_active_session = True
                    self.session_start_time = datetime.now().isoformat()
                    self._save_state()
                    log("SESSION NEU (nach Fallback)")
        else:
            # Erste Nachricht: Voller System-Prompt, neue Session
            prompt = build_chat_prompt(messages, self.config)
            response = self.run_claude_chat(prompt, use_continue=False)
            if not self._last_chat_failed:
                self.has_active_session = True
                self.session_start_time = datetime.now().isoformat()
                self._save_state()
                log(f"SESSION GESTARTET: {self.session_start_time}")

        # Memory-Updates extrahieren und speichern
        memory_updates = self.extract_memory_updates(response)
        if memory_updates:
            update_bridge_memory("\n".join(memory_updates))
            log(f"MEMORY UPDATE: {len(memory_updates)} Eintrag/Eintraege")

        # Antwort senden (WORKER: und MEMORY: Tags entfernen)
        clean_response = "\n".join(
            line for line in response.split("\n")
            if not line.strip().startswith("WORKER:")
            and not line.strip().startswith("MEMORY:")
        ).strip()
        if clean_response:
            if self.voice_mode:
                send_telegram_voice(clean_response, self.config)
            else:
                send_telegram(clean_response, self.config)

        # Worker-Auftraege erkennen & spawnen
        worker_tasks = self.extract_worker_tasks(response)
        for task in worker_tasks:
            self.spawn_worker(task)

    def _heartbeat_loop(self):
        """Sendet alle 60s Heartbeat. Erkennt Force-Takeover durch anderen PC."""
        while not self.stop_event.is_set():
            if heartbeat('bridge'):
                log("Heartbeat gesendet", "DEBUG")
            else:
                # Heartbeat fehlgeschlagen: pruefen ob Fackel verloren
                if not check_fackel_mine('bridge'):
                    holder = get_fackel_holder('bridge') or "unbekannt"
                    log(f"FACKEL VERLOREN: {holder} hat die Fackel uebernommen. Bridge beendet sich.", "WARN")
                    self._handle_fackel_lost(holder)
                    return
                else:
                    log("Heartbeat fehlgeschlagen (DB-Problem) - Fackel noch vorhanden", "WARN")

            time.sleep(60)  # 60s Intervall

    def _handle_fackel_lost(self, new_holder: str = "anderer PC"):
        """Reagiert auf Fackel-Verlust: Benachrichtigung + geordneter Shutdown."""
        try:
            send_telegram(
                f"BACH Bridge: Fackel an '{new_holder}' abgegeben. Bridge wird beendet.",
                self.config
            )
        except Exception:
            pass
        self._fackel_lost = True
        self.stop_event.set()

    # ---------- SESSION SUMMARY ----------

    def _save_session_summary(self):
        """Speichert End-of-Day/Session-Zusammenfassung in BACH Memory."""
        if not self.has_active_session:
            return

        try:
            summary_prompt = (
                "Fasse die heutige Chat-Session kurz zusammen (max 3 Saetze). "
                "Was waren die Hauptthemen? Was wurde erledigt? Was steht noch an? "
                "Antworte NUR mit der Zusammenfassung, kein WORKER: oder MEMORY: Tag."
            )
            summary = self.run_claude_chat(summary_prompt, use_continue=True)

            if summary and not self._last_chat_failed:
                # In BACH Memory speichern via bach.py CLI
                try:
                    env = os.environ.copy()
                    env["PYTHONIOENCODING"] = "utf-8"
                    subprocess.run(
                        [sys.executable, "bach.py", "--memory", "session",
                         f"BRIDGE-SESSION {date.today().isoformat()}: {summary}"],
                        cwd=str(BACH_DIR), env=env, timeout=30,
                        capture_output=True, encoding='utf-8', errors='replace'
                    )
                    log(f"SESSION SUMMARY gespeichert: {summary[:100]}")
                except Exception as e:
                    log(f"SESSION SUMMARY (BACH Memory) Fehler: {e}", "WARN")

                # Auch in bridge_memory.md speichern
                update_bridge_memory(f"Session-Summary {date.today().isoformat()}: {summary[:300]}")
            else:
                log("SESSION SUMMARY: Konnte keine Zusammenfassung erstellen", "WARN")

        except Exception as e:
            log(f"SESSION SUMMARY Fehler: {e}", "WARN")

    # ---------- WORKERS ----------

    def spawn_worker(self, task_description: str):
        """Startet Worker-Claude in Hintergrund-Thread (sandboxed)."""
        max_concurrent = self.config.get("worker", {}).get("max_concurrent", 2)

        with self.worker_lock:
            active = sum(1 for t in self.worker_threads if t.is_alive())
            if active >= max_concurrent:
                send_telegram(f"Max. Worker erreicht ({max_concurrent}). Aufgabe wird spaeter erledigt.", self.config)
                return

        # Worker in DB registrieren
        worker_id = db_execute(
            "INSERT INTO claude_bridge_workers (task_description, status, permission_mode, started_at) "
            "VALUES (?, 'running', ?, ?)",
            (task_description, self.permission_mode, datetime.now().isoformat())
        )

        send_telegram(f"Worker W{worker_id} gestartet: {task_description[:100]}", self.config)
        log(f"WORKER START: W{worker_id} - {task_description[:80]}")

        thread = Thread(target=self._run_worker_thread,
                        args=(worker_id, task_description), daemon=True)
        with self.worker_lock:
            self.worker_threads.append(thread)
        thread.start()

    def _run_worker_thread(self, worker_id: int, task_description: str):
        """Worker-Thread: Fuehrt Claude aus, speichert Ergebnis."""
        cli_config = self.config.get("claude_cli", {})
        cli_path = cli_config.get("path", "claude")
        cwd = cli_config.get("cwd", str(BACH_DIR))
        model = self.config.get("worker", {}).get("model", "sonnet")
        timeout = self.config.get("worker", {}).get("timeout_seconds", 1800)

        prompt = build_worker_prompt(task_description, self.config)

        # P3-Fix: Worker-Rechte an Chat-Permission koppeln
        # Prompt via stdin statt CLI-Argument (Windows 32K Commandline-Limit)
        cmd = [cli_path, "-p", "--output-format", "text"]
        if self.permission_mode == "full":
            cmd += ["--dangerously-skip-permissions"]
        else:
            tools = self.config.get("permissions", {}).get("restricted_allowed_tools",
                                                            "Read,Write,Edit,Glob,Grep,Bash,WebFetch,WebSearch")
            cmd += ["--allowedTools", tools]
        cmd += ["--model", model, "--no-session-persistence"]

        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"

        creation_flags = 0x08000000 if sys.platform == "win32" else 0
        start_time = time.time()

        try:
            # Raw bytes lesen - verhindert Encoding-Korruption auf Windows
            # Prompt via stdin um Windows Commandline-Limit zu umgehen
            result = subprocess.run(
                cmd, input=prompt.encode("utf-8"),
                capture_output=True,
                timeout=timeout, env=env, cwd=cwd,
                creationflags=creation_flags
            )
            duration = time.time() - start_time

            # Kosten schaetzen
            cost_per_min = self.config.get("budget", {}).get("worker_minute_cost", 0.05)
            cost = cost_per_min * (duration / 60.0)
            self.record_cost(cost)

            # Smart-Decode: UTF-8 bevorzugt, cp1252 Fallback
            try:
                from tools.encoding_fix import sanitize_subprocess_output
                summary = sanitize_subprocess_output(result.stdout or b"").strip()
                stderr_text = sanitize_subprocess_output(result.stderr or b"")
            except ImportError:
                summary = (result.stdout or b"").decode('utf-8', errors='replace').strip()
                stderr_text = (result.stderr or b"").decode('utf-8', errors='replace')
            if len(summary) > 1000:
                summary = summary[-1000:]  # Letzte 1000 Zeichen

            if result.returncode == 0:
                db_execute(
                    "UPDATE claude_bridge_workers SET status='completed', "
                    "result_summary=?, ended_at=?, cost_estimate_usd=? WHERE id=?",
                    (summary, datetime.now().isoformat(), cost, worker_id)
                )
                log(f"WORKER DONE: W{worker_id} in {duration:.0f}s")
                send_telegram(f"Worker W{worker_id} erledigt ({duration:.0f}s):\n{summary[:500]}", self.config)
            else:
                error = stderr_text[:500] or "Exit Code != 0"
                db_execute(
                    "UPDATE claude_bridge_workers SET status='error', "
                    "error_message=?, ended_at=? WHERE id=?",
                    (error, datetime.now().isoformat(), worker_id)
                )
                log(f"WORKER ERROR: W{worker_id} - {error[:100]}", "ERROR")
                send_telegram(f"Worker W{worker_id} Fehler: {error[:200]}", self.config)

        except subprocess.TimeoutExpired:
            db_execute(
                "UPDATE claude_bridge_workers SET status='error', "
                "error_message='Timeout', ended_at=? WHERE id=?",
                (datetime.now().isoformat(), worker_id)
            )
            log(f"WORKER TIMEOUT: W{worker_id}", "ERROR")
            send_telegram(f"Worker W{worker_id} Timeout ({timeout // 60} Min Limit erreicht).", self.config)

        except Exception as e:
            db_execute(
                "UPDATE claude_bridge_workers SET status='error', "
                "error_message=?, ended_at=? WHERE id=?",
                (str(e)[:500], datetime.now().isoformat(), worker_id)
            )
            log(f"WORKER EXCEPTION: W{worker_id} - {e}", "ERROR")
            send_telegram(f"Worker W{worker_id} Fehler: {str(e)[:200]}", self.config)

    def _stop_workers(self):
        """Stoppt alle laufenden Worker."""
        try:
            rows = db_execute(
                "SELECT id, pid FROM claude_bridge_workers WHERE status = 'running'",
                fetch=True
            )
            if not rows:
                send_telegram("Keine laufenden Worker.", self.config)
                return

            stopped = 0
            for r in rows:
                wid = r["id"]
                pid = r["pid"]
                if pid and _is_process_running(pid):
                    try:
                        if sys.platform == "win32":
                            subprocess.run(["taskkill", "/PID", str(pid), "/F", "/T"],
                                           capture_output=True, timeout=10)
                        else:
                            os.kill(pid, signal.SIGTERM)
                        stopped += 1
                    except Exception:
                        pass
                db_execute(
                    "UPDATE claude_bridge_workers SET status='error', "
                    "error_message='Manuell gestoppt', ended_at=? WHERE id=?",
                    (datetime.now().isoformat(), wid)
                )

            send_telegram(f"{stopped} Worker gestoppt.", self.config)
        except Exception as e:
            send_telegram(f"Fehler beim Stoppen: {e}", self.config)

    # ---------- TRAY-KOPPLUNG ----------

    def _check_tray_alive(self) -> bool:
        """Prueft ob der Tray noch laeuft (wenn er uns gestartet hat).

        Wenn der Tray-Lock existiert aber der Prozess tot ist → Daemon stoppt auch.
        Wenn kein Tray-Lock → CLI-Start-Modus, Daemon laeuft weiter.
        """
        if not TRAY_LOCK_FILE.exists():
            return True  # CLI-Modus ohne Tray - kein Problem
        try:
            pid_text = TRAY_LOCK_FILE.read_text(encoding="utf-8").strip()
            if not pid_text:
                return True
            pid = int(pid_text)
            if _is_process_running(pid):
                return True
            # Tray-Lock existiert, Prozess ist tot → Tray ist gecrasht
            log("Tray-Prozess nicht mehr aktiv (Kopplung: Daemon beendet sich)", "WARN")
            return False
        except Exception:
            return True  # Im Zweifel: weiterlaufen

    # ---------- ORPHAN CLEANUP ----------

    def cleanup_orphaned_workers(self):
        """Markiert haengende Worker als Fehler beim Start."""
        try:
            rows = db_execute(
                "SELECT id, pid FROM claude_bridge_workers WHERE status = 'running'",
                fetch=True
            )
            if not rows:
                return
            for r in rows:
                pid = r["pid"]
                if not pid or not _is_process_running(pid):
                    db_execute(
                        "UPDATE claude_bridge_workers SET status='error', "
                        "error_message='Orphaned (Daemon Neustart)', ended_at=? WHERE id=?",
                        (datetime.now().isoformat(), r["id"])
                    )
                    log(f"ORPHAN: W{r['id']} bereinigt")
        except Exception:
            pass

    # ---------- MAIN LOOP ----------

    def run(self):
        """Hauptschleife des Bridge-Daemons."""
        # Restart-Cooldown pruefen
        if not check_restart_cooldown():
            return

        # File-Lock: Nur EINE Instanz
        if not acquire_lock():
            pid = get_running_pid()
            print(f"Claude Bridge Daemon laeuft bereits (PID {pid}). Nur eine Instanz erlaubt.")
            log(f"START BLOCKED: Andere Instanz laeuft (PID {pid})", "WARN")
            return

        # Fackel holen (immer erfolgreich - Force-Takeover wenn anderer PC aktiv)
        success, msg = acquire_fackel(session_type='bridge')
        log(f"Fackel erworben: {msg}", "INFO")

        record_start_time()

        log("=" * 50)
        log("BACH Claude Bridge Daemon v2.2 gestartet (async)")
        log(f"PID: {os.getpid()}")
        log(f"Modus: {self.permission_mode}")
        log(f"Session: {'aktiv (seit ' + (self.session_start_time or '?')[:16] + ')' if self.has_active_session else 'keine (erster Aufruf = voller System-Prompt)'}")
        log(f"Connector: {self.config.get('connector_name')} / Chat: {self.config.get('chat_id')}")
        log(f"Claude CLI: {self.config.get('claude_cli', {}).get('path', 'claude')}")
        log(f"Budget: ${self.daily_spent:.2f} / ${self.config.get('budget', {}).get('daily_limit_usd', 5.0)}/Tag")
        log(f"Max Nachrichten-Alter: {MAX_MESSAGE_AGE}s")
        log(f"Memory: {MEMORY_FILE}")
        log(f"Arbeitsmodus: {self.work_mode}")
        log("=" * 50)

        # SQ048: Session-Kontext fuer heute laden/erstellen
        try:
            ctx = self.session_ctx.get_today_context()
            if ctx.get("handover_notes"):
                log(f"HANDOVER vom Vortag: {ctx['handover_notes'][:100]}")
        except Exception as e:
            log(f"Session-Kontext Fehler (Tabelle existiert evtl. noch nicht): {e}", "WARN")

        # Heartbeat-Thread
        heartbeat_thread = Thread(target=self._heartbeat_loop, daemon=True, name="HeartbeatThread")
        heartbeat_thread.start()
        log("Heartbeat-Thread gestartet", "INFO")

        # Signal-Handler
        def handle_signal(signum, frame):
            log("Shutdown-Signal empfangen")
            self.stop_event.set()

        signal.signal(signal.SIGTERM, handle_signal)
        signal.signal(signal.SIGINT, handle_signal)

        # Orphaned Workers aufraumen
        self.cleanup_orphaned_workers()

        poll_interval = self.config.get("poll_interval_seconds", 5)

        # Tray-Kopplung: Merke ob Tray beim Start aktiv war
        _tray_was_present = TRAY_LOCK_FILE.exists()
        if _tray_was_present:
            log("Tray-Kopplung aktiv: Daemon beendet sich wenn Tray gestoppt wird", "INFO")
        else:
            log("Kein Tray-Lock gefunden - CLI-Modus (laeuft unabhaengig)", "INFO")

        _tray_check_counter = 0

        log("Hauptschleife startet...")
        try:
            while not self.stop_event.is_set():
                try:
                    # Full-Access Timeout pruefen
                    self.check_full_mode_timeout()

                    # Tray-Kopplung: Alle 30s pruefen ob Tray noch lebt
                    _tray_check_counter += 1
                    if _tray_was_present and _tray_check_counter >= 6:
                        _tray_check_counter = 0
                        if not self._check_tray_alive():
                            send_telegram(
                                "Bridge Daemon beendet sich - Tray wurde geschlossen.",
                                self.config
                            )
                            self.stop_event.set()
                            break

                    # 0. Multi-Connector Poll (Telegram, WhatsApp, Signal, Discord)
                    run_connector_poll()

                    # 1. Neue Nachrichten aus DB (mit Alters-Limit)
                    new_messages = self.poll_new_messages()

                    if new_messages:
                        # 2. Codewort-Check (vor Claude)
                        remaining = []
                        for msg in new_messages:
                            if self.handle_codeword(msg):
                                self.mark_processed([msg["id"]])
                            else:
                                remaining.append(msg)

                        if not remaining:
                            continue

                        # 3. Budget-Check
                        if not self.check_budget():
                            send_telegram(self.get_budget_status() + " - Limit erreicht.", self.config)
                            self.mark_processed([m["id"] for m in remaining])
                            continue

                        # 4. Rechte-Hint generieren wenn toggle stattfand
                        perm_hint = ""
                        if self._permission_changed:
                            mode_label = "VOLLZUGRIFF (alle Tools erlaubt)" if self.permission_mode == "full" \
                                else "EINGESCHRAENKT (Read,Write,Edit,Glob,Grep,Bash,WebFetch,WebSearch)"
                            perm_hint = f"[SYSTEM: Deine Rechte wurden geaendert zu: {mode_label}. Passe dein Verhalten entsprechend an.]"
                            self._permission_changed = False

                        # 5. Nachrichten sofort als verarbeitet markieren (nicht erneut pollen)
                        self.mark_processed([m["id"] for m in remaining])

                        # 6. Wenn Chat laeuft: Nachrichten queuen
                        with self._chat_lock:
                            if self._chat_busy:
                                self._pending_messages.append((remaining, perm_hint))
                                log(f"CHAT BUSY: {len(remaining)} Nachricht(en) gequeued "
                                    f"(total pending: {len(self._pending_messages)})")
                                continue

                        # 7. Chat-Thread starten (non-blocking)
                        self._start_chat_async(remaining, perm_hint)

                except Exception as e:
                    log(f"Fehler im Hauptloop: {e}", "ERROR")

                self.stop_event.wait(poll_interval)
        finally:
            # Chat-Thread abwarten falls noch aktiv
            if self._chat_thread and self._chat_thread.is_alive():
                log("SHUTDOWN: Warte auf Chat-Thread (max 30s)...")
                self._chat_thread.join(timeout=30)
                if self._chat_thread.is_alive():
                    log("SHUTDOWN: Chat-Thread antwortet nicht, fahre fort", "WARN")

            # Aufraemen: Session-Summary bei Shutdown speichern
            if self.has_active_session:
                log("SHUTDOWN: Speichere Session-Summary...")
                self._save_session_summary()

            log("Claude Bridge Daemon wird beendet...")
            self._save_state()

            # Fackel freigeben (nicht wenn durch Force-Takeover verloren)
            if not self._fackel_lost:
                if release_fackel('bridge'):
                    log("Fackel freigegeben", "INFO")
            else:
                log("Fackel nicht freigegeben (wurde durch anderen PC uebernommen)", "INFO")

            release_lock()
            log("Claude Bridge Daemon beendet")


# ============ STATUS ============

def show_status():
    """Zeigt Bridge-Status."""
    pid = get_running_pid()
    config = load_config()
    state = load_state()

    print("\n" + "=" * 50)
    print("BACH CLAUDE BRIDGE STATUS v2.2")
    print("=" * 50)

    if pid:
        print(f"[OK] Daemon laeuft (PID {pid})")
    else:
        print("[--] Daemon laeuft nicht")

    print(f"\nConfig:")
    print(f"  Connector:  {config.get('connector_name', '?')}")
    print(f"  Chat-ID:    {config.get('chat_id', '?')}")
    print(f"  Claude CLI: {config.get('claude_cli', {}).get('path', '?')}")
    print(f"  Modell:     {config.get('claude_cli', {}).get('model', '?')}")
    print(f"  Budget:     ${config.get('budget', {}).get('daily_limit_usd', '?')}/Tag")

    print(f"\nState:")
    print(f"  Modus:      {state.get('permission_mode', '?')}")
    print(f"  Budget:     ${state.get('daily_spent', 0):.2f} ({state.get('budget_date', '?')})")
    mt = state.get('max_turns', config.get('chat', {}).get('max_turns', 0))
    print(f"  Max-Turns:  {mt if mt > 0 else 'kein Limit'}")
    ct = state.get('chat_timeout', config.get('chat', {}).get('timeout_seconds', 0))
    print(f"  Timeout:    {str(ct) + 's' if ct > 0 else 'AUS'}")
    session_active = state.get("has_active_session", False)
    print(f"  Session:    {'aktiv' if session_active else 'keine'}")
    if state.get("session_start_time"):
        print(f"  Seit:       {state['session_start_time'][:16]}")
    print(f"  Arbeitsmodus: {state.get('work_mode', 'assistant')}")

    # Memory
    mem = load_bridge_memory()
    print(f"\nMemory: {len(mem)} Zeichen")
    if mem:
        lines = mem.strip().split("\n")
        for line in lines[-3:]:
            print(f"  {line[:80]}")

    # Worker-Status
    try:
        conn = db_connect()
        running = conn.execute(
            "SELECT COUNT(*) FROM claude_bridge_workers WHERE status = 'running'"
        ).fetchone()[0]
        total = conn.execute(
            "SELECT COUNT(*) FROM claude_bridge_workers"
        ).fetchone()[0]
        conn.close()
        print(f"\nWorker: {running} laufend, {total} gesamt")
    except Exception:
        pass

    # Letzte Logs
    if LOG_FILE.exists():
        print(f"\nLetzte Log-Eintraege:")
        try:
            lines = LOG_FILE.read_text(encoding="utf-8").strip().split("\n")
            for line in lines[-5:]:
                print(f"  {line}")
        except Exception:
            pass

    print("=" * 50)


# ============ TEST ============

def test_message(text: str):
    """Simuliert eine Telegram-Nachricht fuer Tests."""
    config = load_config()
    connector = config.get("connector_name", "telegram_main")
    chat_id = config.get("chat_id", "YOUR_CHAT_ID")

    db_execute(
        "INSERT INTO connector_messages "
        "(connector_name, direction, sender, recipient, content, status, bridge_processed, created_at) "
        "VALUES (?, 'in', ?, '', ?, 'pending', 0, ?)",
        (connector, chat_id, text, datetime.now().isoformat())
    )
    print(f"Test-Nachricht eingefuegt: '{text}'")
    print("Der Bridge-Daemon wird sie beim naechsten Poll verarbeiten.")


# ============ SERVER MODE ============

def start_server_mode(config: dict):
    """Startet die Bridge im Server-Modus mit FastAPI/Uvicorn."""
    try:
        from server_api import create_app, HAS_FASTAPI
    except ImportError:
        from .server_api import create_app, HAS_FASTAPI

    if not HAS_FASTAPI:
        log("FastAPI nicht installiert! pip install fastapi uvicorn", "ERROR")
        print("ERROR: FastAPI nicht installiert.")
        print("Installiere mit: pip install fastapi uvicorn")
        sys.exit(1)

    try:
        import uvicorn
    except ImportError:
        log("Uvicorn nicht installiert! pip install uvicorn", "ERROR")
        print("ERROR: Uvicorn nicht installiert.")
        print("Installiere mit: pip install uvicorn")
        sys.exit(1)

    server_cfg = config.get("server", {})
    host = server_cfg.get("host", "127.0.0.1")
    port = server_cfg.get("port", 8080)

    app = create_app(config)

    # Daemon im Hintergrund starten (optional: auch den Poll-Loop laufen lassen)
    daemon = BridgeDaemon()
    app.state.daemon = daemon

    # Daemon-Loop in eigenem Thread
    from threading import Thread
    daemon_thread = Thread(target=daemon.run, daemon=True, name="BridgeDaemonThread")
    daemon_thread.start()

    log(f"Server-Modus: FastAPI auf {host}:{port}", "INFO")
    log(f"API-Docs: http://{host}:{port}/docs", "INFO")
    print(f"BACH Bridge Server startet auf http://{host}:{port}")
    print(f"API-Docs: http://{host}:{port}/docs")

    uvicorn.run(app, host=host, port=port, log_level="info")


# ============ CLI ============

def main():
    if "--stop" in sys.argv:
        stop_daemon()
        return

    if "--status" in sys.argv:
        show_status()
        return

    if "--test" in sys.argv:
        idx = sys.argv.index("--test")
        text = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else "Test-Nachricht"
        test_message(text)
        return

    config = load_config()
    mode = config.get("mode", "local")

    # --server Flag oder config mode=server
    if "--server" in sys.argv or mode == "server":
        start_server_mode(config)
        return

    # Daemon starten (local mode)
    daemon = BridgeDaemon()
    daemon.run()

    # Fackel-Verlust: Exit-Code 2 damit Tray keinen Neustart veranlasst
    if daemon._fackel_lost:
        sys.exit(FACKEL_LOST_EXIT_CODE)


if __name__ == "__main__":
    main()
