#!/usr/bin/env python3
# -*- coding: utf-8 -*-
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
TelegramConnector - Telegram Bot API Connector fuer BACH
=========================================================

Implementiert BaseConnector fuer Telegram Bot API.
Benoetigt: Bot-Token von @BotFather

Portiert und erweitert aus BachForelle telegram.py:
- Owner-Filter: Nur Nachrichten vom konfigurierten chat_id akzeptieren
- Polling-Loop: Kontinuierliches Polling mit konfigurierbarem Intervall
- Stdlib-only: Kein 'requests' noetig (urllib)

Verwendung:
    from connectors.telegram_connector import TelegramConnector
    from connectors.base import ConnectorConfig

    config = ConnectorConfig(
        name="telegram_main",
        connector_type="telegram",
        auth_type="api_key",
        auth_config={"bot_token": "123456:ABC-DEF..."},
        options={"owner_chat_id": "123456789"}  # Optional: Nur diesen Chat akzeptieren
    )
    bot = TelegramConnector(config)
    bot.connect()
    messages = bot.get_messages()
    bot.send_message("chat_id", "Hallo von BACH!")

    # Polling-Loop (blockierend oder threaded):
    thread, stop = bot.poll_threaded(on_message=callback, interval=5)
"""

import json
import os
import sys
import shutil
import socket
import tempfile
import time
import threading
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Callable, Tuple

# UTF-8 Encoding fix
os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
if sys.stdout:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr:
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

from connectors.base import BaseConnector, ConnectorConfig, ConnectorStatus, Message

# Voice-Transkription (optional)
_stt_instance = None

def _ensure_ffmpeg():
    """Stellt sicher dass ffmpeg im PATH ist (fuer Whisper)."""
    if shutil.which("ffmpeg"):
        return  # Bereits verfuegbar

    # Unix: Explizite Pfade pruefen (launchd/cron haben minimalen PATH)
    if sys.platform != "win32":
        for candidate in (
            "/opt/homebrew/bin/ffmpeg",  # macOS Apple Silicon
            "/usr/local/bin/ffmpeg",     # macOS Intel / Linux manual
            "/usr/bin/ffmpeg",           # Linux apt/dnf
        ):
            if Path(candidate).is_file():
                os.environ["PATH"] = str(Path(candidate).parent) + ":" + os.environ.get("PATH", "")
                return

    # Windows: WinGet-Installationspfad durchsuchen
    if sys.platform == "win32":
        winget_base = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
        if winget_base.exists():
            for d in winget_base.iterdir():
                if "FFmpeg" in d.name:
                    bin_dir = next(d.rglob("ffmpeg.exe"), None)
                    if bin_dir:
                        os.environ["PATH"] = str(bin_dir.parent) + ";" + os.environ.get("PATH", "")
                        return

def _get_stt():
    """Lazy-Init des STT-Service (Singleton)."""
    global _stt_instance
    if _stt_instance is None:
        try:
            _ensure_ffmpeg()
            from hub._services.voice.voice_stt import VoiceSTT
            _stt_instance = VoiceSTT()
        except ImportError:
            _stt_instance = False  # Markierung: nicht verfuegbar
    return _stt_instance if _stt_instance is not False else None


class TelegramConnector(BaseConnector):
    """Telegram Bot API Connector mit Polling-Runtime."""

    API_BASE = "https://api.telegram.org/bot{token}/{method}"

    def __init__(self, config: ConnectorConfig):
        super().__init__(config)
        self._bot_token = config.auth_config.get("bot_token", "")
        # Falls kein direkter Token, _secret_refs über den zentralen Keyring-Resolver.
        secret_refs = config.auth_config.get("_secret_refs", {})
        if not self._bot_token:
            secret_key = secret_refs.get("bot_token", "")
            if secret_key:
                self._bot_token = self._load_from_secrets_table(secret_key)
        self._owner_chat_id = str(config.options.get("owner_chat_id", ""))
        if not self._owner_chat_id:
            owner_ref = secret_refs.get("owner_chat_id", "")
            if owner_ref:
                self._owner_chat_id = self._load_from_secrets_table(owner_ref)
        self._last_update_id = int(config.auth_config.get("last_update_id", 0))
        self._bot_info = None
        self._polling = False

    def _load_from_secrets_table(self, key: str) -> str:
        """Lädt ein Secret ohne Klartextzugriff auf bach.db."""
        try:
            from hub.secrets_handler import get_secret_value

            return get_secret_value(key) or ""
        except Exception:
            return ""

    def connect(self) -> bool:
        """Verbindung pruefen via getMe."""
        if not self._bot_token:
            self._status = ConnectorStatus.ERROR
            return False

        self._status = ConnectorStatus.CONNECTING
        try:
            result = self._api_call("getMe")
            if result:
                self._bot_info = result
                self._status = ConnectorStatus.CONNECTED
                return True
        except Exception:
            pass

        self._status = ConnectorStatus.ERROR
        return False

    def disconnect(self) -> bool:
        """Telegram benoetigt keinen expliziten Disconnect."""
        self._polling = False
        self._status = ConnectorStatus.DISCONNECTED
        return True

    def send_message(self, recipient: str, content: str,
                     attachments: Optional[List[str]] = None) -> bool:
        """Nachricht an chat_id senden."""
        try:
            # Zuerst mit Markdown versuchen
            params = {
                "chat_id": recipient or self._owner_chat_id,
                "text": content,
                "parse_mode": "Markdown"
            }
            result = self._api_call("sendMessage", params, retries=1)

            if result is None:
                # Retry ohne Markdown bei Parse-Fehlern
                params = {
                    "chat_id": recipient or self._owner_chat_id,
                    "text": content
                    # Kein parse_mode - Plain Text
                }
                result = self._api_call("sendMessage", params)

            return result is not None
        except Exception as e:
            print(f"[Telegram send_message Error] {type(e).__name__}: {e}", file=sys.stderr)
            return False

    def send_voice(self, recipient: str, audio_path: str) -> bool:
        """Sprachnachricht (OGG/MP3) an chat_id senden."""
        try:
            import urllib.request
            import mimetypes
            import os

            chat_id = recipient or self._owner_chat_id
            if not os.path.exists(audio_path):
                return False

            # Multipart-Upload vorbereiten
            boundary = "----WebKitFormBoundary" + os.urandom(16).hex()
            url = self.API_BASE.format(token=self._bot_token, method="sendVoice")

            # Body mit Multipart-Encoding
            body = []
            body.append(f'--{boundary}'.encode())
            body.append(f'Content-Disposition: form-data; name="chat_id"'.encode())
            body.append(b'')
            body.append(str(chat_id).encode())

            body.append(f'--{boundary}'.encode())
            body.append(f'Content-Disposition: form-data; name="voice"; filename="{os.path.basename(audio_path)}"'.encode())
            mime = mimetypes.guess_type(audio_path)[0] or "audio/ogg"
            body.append(f'Content-Type: {mime}'.encode())
            body.append(b'')
            with open(audio_path, 'rb') as f:
                body.append(f.read())

            body.append(f'--{boundary}--'.encode())
            body.append(b'')

            data = b'\r\n'.join(body)

            # HTTP Request
            req = urllib.request.Request(url, data=data)
            req.add_header('Content-Type', f'multipart/form-data; boundary={boundary}')

            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                return result.get("ok", False)

        except Exception as e:
            print(f"[Telegram send_voice Error] {type(e).__name__}: {e}", file=sys.stderr)
            return False

    def get_messages(self, since: Optional[str] = None,
                     limit: int = 50) -> List[Message]:
        """Neue Nachrichten via getUpdates abrufen.

        Wenn owner_chat_id gesetzt: Nachrichten von anderen Chats werden ignoriert.
        """
        try:
            params = {
                "offset": self._last_update_id + 1,
                "limit": min(limit, 100),
                "timeout": 30  # Long-polling: 30 Sekunden warten auf neue Nachrichten
            }
            result = self._api_call("getUpdates", params, timeout=40)
            if not result:
                return []

            messages = []
            for update in result:
                self._last_update_id = max(self._last_update_id, update.get("update_id", 0))

                msg = update.get("message")
                if not msg:
                    continue

                chat = msg.get("chat", {})
                sender_id = str(chat.get("id", ""))

                # Owner-Filter: Nur Nachrichten vom konfigurierten Chat akzeptieren
                if self._owner_chat_id and sender_id != self._owner_chat_id:
                    continue

                from_user = msg.get("from", {})
                sender_name = from_user.get("first_name", "") + " " + from_user.get("last_name", "")

                # Text oder Voice-Transkription ermitteln
                content = msg.get("text", "")
                msg_type = "text"

                if not content:
                    # Voice-Nachricht?
                    voice = msg.get("voice") or msg.get("audio")
                    if voice and voice.get("file_id"):
                        msg_type = "voice"
                        duration = voice.get("duration", 0)
                        transcription = self._transcribe_voice(voice["file_id"], duration)
                        if transcription:
                            content = transcription
                        else:
                            content = f"[Sprachnachricht ({duration}s) - Transkription nicht verfuegbar]"

                    # Video-Nachricht (hat auch Audio)?
                    video_note = msg.get("video_note")
                    if not content and video_note and video_note.get("file_id"):
                        msg_type = "video_note"
                        content = "[Videonachricht - Transkription nicht unterstuetzt]"

                    # Caption (Bild/Video/Dokument mit Text)?
                    if not content:
                        content = msg.get("caption", "")
                        if content:
                            msg_type = "caption"

                if not content:
                    continue  # Leere Nachrichten ueberspringen

                messages.append(Message(
                    channel="telegram",
                    sender=sender_id,
                    content=content,
                    timestamp=datetime.fromtimestamp(
                        msg.get("date", 0)).isoformat(),
                    direction="in",
                    message_id=str(msg.get("message_id", "")),
                    metadata={
                        "chat_type": chat.get("type", ""),
                        "sender_name": sender_name.strip(),
                        "update_id": update.get("update_id", 0),
                        "message_type": msg_type,
                    }
                ))

            return messages
        except Exception as e:
            print(f"[Telegram get_messages Error] {type(e).__name__}: {e}", file=sys.stderr)
            return []

    # ------------------------------------------------------------------
    # Polling Runtime
    # ------------------------------------------------------------------

    def poll_loop(self, on_message: Callable[[Message], None],
                  interval: float = 5.0, stop_event: threading.Event = None):
        """Blockierender Polling-Loop. Ruft on_message() fuer jede neue Nachricht auf.

        interval: Sekunden zwischen Polls (Standard: 5)
        stop_event: threading.Event zum Stoppen
        """
        self._polling = True
        while self._polling and not (stop_event and stop_event.is_set()):
            try:
                messages = self.get_messages()
                for msg in messages:
                    try:
                        on_message(msg)
                    except Exception as e:
                        print(f"[Telegram on_message callback Error] {type(e).__name__}: {e}", file=sys.stderr)
            except Exception as e:
                print(f"[Telegram poll_loop Error] {type(e).__name__}: {e}", file=sys.stderr)
            time.sleep(interval)

    def poll_threaded(self, on_message: Callable[[Message], None],
                      interval: float = 5.0) -> Tuple[threading.Thread, threading.Event]:
        """Startet Polling in eigenem Thread. Gibt (Thread, StopEvent) zurueck."""
        stop_event = threading.Event()
        thread = threading.Thread(
            target=self.poll_loop,
            args=(on_message, interval, stop_event),
            daemon=True, name="bach-telegram-poll")
        thread.start()
        return thread, stop_event

    # ------------------------------------------------------------------
    # Voice Message Support
    # ------------------------------------------------------------------

    def _download_voice(self, file_id: str) -> Optional[str]:
        """Telegram-Audiodatei runterladen. Gibt lokalen Pfad zurueck."""
        try:
            # Schritt 1: file_path von Telegram holen
            file_info = self._api_call("getFile", {"file_id": file_id})
            if not file_info or "file_path" not in file_info:
                return None

            # Schritt 2: Datei runterladen
            file_url = f"https://api.telegram.org/file/bot{self._bot_token}/{file_info['file_path']}"
            ext = Path(file_info["file_path"]).suffix or ".ogg"
            tmp = tempfile.NamedTemporaryFile(suffix=ext, prefix="bach_voice_", delete=False)
            tmp_path = tmp.name
            tmp.close()

            urllib.request.urlretrieve(file_url, tmp_path)
            return tmp_path
        except Exception:
            return None

    def _transcribe_voice(self, file_id: str, duration: int = 0) -> Optional[str]:
        """Voice-Nachricht runterladen und transkribieren."""
        stt = _get_stt()
        if not stt:
            return None

        available, engine = stt.is_available()
        if not available:
            return None

        audio_path = self._download_voice(file_id)
        if not audio_path:
            return None

        try:
            text = stt.transcribe_file(audio_path, language="de")
            # Fehler-Strings nicht als Transkription durchlassen
            if text and not text.startswith("[Fehler"):
                return text
            return None
        except Exception:
            return None
        finally:
            # Temp-Datei aufraeumen
            try:
                Path(audio_path).unlink(missing_ok=True)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _api_call(self, method: str, params: dict = None, retries: int = 3, timeout: int = 15) -> any:
        """Telegram Bot API aufrufen (stdlib urllib, mit Retry bei Netzwerkfehlern).

        Args:
            method: Telegram API Methode (z.B. 'getUpdates', 'sendMessage')
            params: Parameter als dict
            retries: Anzahl Wiederholungsversuche bei Fehlern
            timeout: HTTP-Timeout in Sekunden (für long-polling höher setzen)
        """
        url = self.API_BASE.format(token=self._bot_token, method=method)

        for attempt in range(retries):
            if params:
                data = json.dumps(params, ensure_ascii=False).encode("utf-8")
                req = urllib.request.Request(
                    url, data=data,
                    headers={"Content-Type": "application/json; charset=utf-8"})
            else:
                req = urllib.request.Request(url)

            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    body = json.loads(resp.read().decode("utf-8"))
                    if body.get("ok"):
                        return body.get("result")
                    # Telegram API Error loggen
                    error_msg = body.get("description", "Unknown error")
                    if attempt == retries - 1:  # Letzter Versuch
                        print(f"[Telegram API Error] {method}: {error_msg}", file=sys.stderr)
                    return None
            except urllib.error.HTTPError as e:
                if e.code < 500:
                    print(f"[Telegram HTTP Error] {method}: HTTP {e.code}", file=sys.stderr)
                    return None
                if attempt == retries - 1:
                    print(f"[Telegram HTTP Error] {method}: HTTP {e.code}", file=sys.stderr)
                    return None
                time.sleep(2 * (attempt + 1))
                continue
            except urllib.error.URLError as e:
                # Netzwerk-Fehler (DNS, Connection Refused, etc.) — retriable
                if attempt == retries - 1:
                    print(f"[Telegram Network Error] {method}: {e.reason}", file=sys.stderr)
                    return None
                time.sleep(2 * (attempt + 1))
                continue
            except socket.timeout:
                # Expliziter Timeout (kann bei long-polling normal sein)
                if method == "getUpdates":
                    return []
                if attempt == retries - 1:
                    print(f"[Telegram Timeout] {method}", file=sys.stderr)
                    return None
                time.sleep(2 * (attempt + 1))
                continue
            except Exception as e:
                # Sonstige Fehler (JSON decode, etc.)
                if attempt < retries - 1:
                    time.sleep(2 * (attempt + 1))
                    continue
                print(f"[Telegram Exception] {method}: {type(e).__name__}: {e}", file=sys.stderr)
                return None
