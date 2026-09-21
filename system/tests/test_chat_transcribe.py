#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test: Audio-Transkription im Buddha-Chat (Task #1338)
======================================================

Deckt ab:
1. transcribe_b64_payload() — Domaenenlogik: Validierung, Base64-Dekodierung,
   Groessen-/Typ-Limits, STT-Dispatch, Temp-Datei-Aufraeumen (fail-closed).
2. ControlHandler-Dispatch: POST /api/transcribe gegen einen echten
   Control-API-Server (Port 0) mit injiziertem Fake-STT.
3. GUI-Proxy-Freigabe: "transcribe" in CHAT_CONTROL_PATHS.

Die STT-Engines selbst (Whisper/Vosk) werden NICHT geladen — der Fake
injiziert sich in voice_stt._STT_SINGLETON, damit Tests kein Modell laden
und ohne Netz laufen. Die 600s-Timeout-Sonderbehandlung fuer "transcribe"
im GUI-Proxy ist inline in chat_control_proxy verdrahtet und wird per
Code-Review (grep) verifiziert, nicht per Unit-Test.
"""

import base64
import json
import os
import threading
import urllib.error
import urllib.request

import pytest

from hub._services.voice import voice_stt
from hub._services.voice.voice_stt import (
    MAX_TRANSCRIBE_BYTES,
    TRANSCRIBE_SUFFIXES,
    transcribe_b64_payload,
)


TEST_CONTROL_TOKEN = "test-control-token"


class FakeSTT:
    """Drop-in fuer VoiceSTT — ohne Modell, ohne Netz."""

    def __init__(self, text="  Hallo Buddha, hier spricht Task 1338. ",
                 available=True, engine="whisper"):
        self.text = text
        self.available = available
        self.engine = engine
        self.calls = []

    def is_available(self):
        if self.available:
            return True, self.engine
        return False, "Kein STT-Engine verfügbar (Fake)"

    def transcribe_file(self, path, language="de"):
        self.calls.append((path, language))
        with open(path, "rb") as fh:
            self.seen_bytes = fh.read()
        return self.text


@pytest.fixture
def fake_stt(monkeypatch):
    """Ersetzt den Prozess-Singleton durch einen Fake (monkeypatch restauration)."""
    stt = FakeSTT()
    monkeypatch.setattr(voice_stt, "_STT_SINGLETON", stt)
    return stt


def _payload(data=b"fake-audio-bytes", filename="sprachmemo.m4a", **extra):
    body = {"audio_b64": base64.b64encode(data).decode(), "filename": filename}
    body.update(extra)
    return body


# ===================================================================
# transcribe_b64_payload — Validierung & Dispatch
# ===================================================================


class TestTranscribePayload:
    """Fail-closed-Validierung vor jedem STT-Aufruf."""

    def test_happy_path_returns_text_and_engine(self, fake_stt):
        payload, status = transcribe_b64_payload(_payload())
        assert status == 200
        assert payload["ok"] is True
        assert payload["text"] == "Hallo Buddha, hier spricht Task 1338."
        assert payload["engine"] == "whisper"
        # Rohe Audio-Bytes unveraendert in der Temp-Datei angekommen:
        assert fake_stt.seen_bytes == b"fake-audio-bytes"
        assert fake_stt.calls[0][1] == "de"  # Standardsprache

    def test_language_passthrough(self, fake_stt):
        transcribe_b64_payload(_payload(language="en"))
        assert fake_stt.calls[0][1] == "en"

    def test_missing_audio_b64_rejected(self, fake_stt):
        payload, status = transcribe_b64_payload({"filename": "a.mp3"})
        assert status == 400
        assert payload["ok"] is False
        assert fake_stt.calls == []

    def test_non_dict_body_rejected(self):
        payload, status = transcribe_b64_payload("kein dict")
        assert status == 400

    def test_forbidden_suffix_rejected(self, fake_stt):
        payload, status = transcribe_b64_payload(_payload(filename="skript.exe"))
        assert status == 415
        assert "Nicht erlaubter Dateityp" in payload["error"]
        assert fake_stt.calls == []

    @pytest.mark.parametrize("suffix", sorted(TRANSCRIBE_SUFFIXES))
    def test_each_allowlisted_suffix_is_accepted(self, fake_stt, suffix):
        payload, status = transcribe_b64_payload(
            _payload(filename="sprachmemo" + suffix.upper())
        )
        assert status == 200
        assert payload["ok"] is True

    @pytest.mark.parametrize(
        "filename",
        [
            "../../tmp/sprachmemo.mp3/../../payload.exe",
            r"..\..\Windows\Temp\sprachmemo.wav\..\payload.ps1",
            "sprachmemo.mp3::$DATA",
        ],
    )
    def test_pathlike_filename_with_forbidden_ending_is_rejected(
        self, fake_stt, filename
    ):
        payload, status = transcribe_b64_payload(_payload(filename=filename))
        assert status == 415
        assert payload["ok"] is False
        assert fake_stt.calls == []

    @pytest.mark.parametrize(
        ("filename", "expected_suffix"),
        [
            ("../../tmp/attacker-controlled.MP3", ".mp3"),
            (r"..\..\Windows\Temp\attacker-controlled.WAV", ".wav"),
        ],
    )
    def test_pathlike_filename_uses_internal_suffix_and_cleans_up(
        self, fake_stt, monkeypatch, filename, expected_suffix
    ):
        suffixes = []
        original = voice_stt.tempfile.NamedTemporaryFile

        def tracked_tempfile(*args, **kwargs):
            suffixes.append(kwargs.get("suffix"))
            return original(*args, **kwargs)

        monkeypatch.setattr(
            voice_stt.tempfile, "NamedTemporaryFile", tracked_tempfile
        )
        payload, status = transcribe_b64_payload(_payload(filename=filename))

        assert status == 200
        assert payload["ok"] is True
        assert suffixes == [expected_suffix]
        assert fake_stt.calls
        assert not os.path.exists(fake_stt.calls[0][0])

    def test_invalid_base64_rejected(self, fake_stt):
        # Laenge % 4 == 1 ist auch mit validate=False garantiert ungueltig.
        payload, status = transcribe_b64_payload(
            {"audio_b64": "abcde", "filename": "a.mp3"}
        )
        assert status == 400
        assert "Ungültige Base64-Daten" in payload["error"]
        assert fake_stt.calls == []

    def test_empty_audio_rejected(self, fake_stt):
        payload, status = transcribe_b64_payload(_payload(data=b""))
        assert status == 400

    def test_oversized_audio_rejected(self, fake_stt):
        big = b"x" * (MAX_TRANSCRIBE_BYTES + 1)
        payload, status = transcribe_b64_payload(_payload(data=big))
        assert status == 413
        assert "zu groß" in payload["error"]
        assert fake_stt.calls == []

    def test_stt_unavailable_returns_503(self, monkeypatch):
        monkeypatch.setattr(voice_stt, "_STT_SINGLETON", FakeSTT(available=False))
        payload, status = transcribe_b64_payload(_payload())
        assert status == 503
        assert payload["ok"] is False
        assert "verfügbar" in payload["error"]

    def test_engine_error_string_maps_to_500(self, fake_stt):
        fake_stt.text = "[Fehler: Modell kaputt]"
        payload, status = transcribe_b64_payload(_payload())
        assert status == 500
        assert "Modell kaputt" in payload["error"]

    def test_empty_transcript_maps_to_500(self, fake_stt):
        fake_stt.text = "   "
        payload, status = transcribe_b64_payload(_payload())
        assert status == 500
        assert payload["error"] == "Keine Sprache erkannt"

    def test_temp_file_cleaned_up(self, fake_stt):
        seen_paths = []
        original = fake_stt.transcribe_file

        def remember(path, language="de"):
            seen_paths.append(path)
            return original(path, language)

        fake_stt.transcribe_file = remember
        payload, status = transcribe_b64_payload(_payload())
        assert status == 200
        assert seen_paths, "STT wurde nicht aufgerufen"
        assert not os.path.exists(seen_paths[0]), "Temp-Datei nicht aufgeraeumt"

    def test_temp_file_cleaned_up_when_transcription_raises(self, fake_stt):
        seen_paths = []

        def fail(path, language="de"):
            seen_paths.append(path)
            raise RuntimeError("kaputt")

        fake_stt.transcribe_file = fail
        payload, status = transcribe_b64_payload(_payload())

        assert status == 500
        assert payload["ok"] is False
        assert seen_paths, "STT wurde nicht aufgerufen"
        assert not os.path.exists(seen_paths[0]), "Temp-Datei nicht aufgeräumt"


# ===================================================================
# ControlHandler-Dispatch — POST /api/transcribe (echter Server)
# ===================================================================


class TestControlHandlerDispatch:
    """Der Chat-Control-Server beantwortet /api/transcribe fail-closed."""

    @pytest.fixture
    def control_url(self, fake_stt, monkeypatch):
        from hub._services.chat.telegram_chat import ControlHandler, QuietHTTPServer
        monkeypatch.setenv("BACH_CONTROL_API_TOKEN", TEST_CONTROL_TOKEN)
        server = QuietHTTPServer(("127.0.0.1", 0), ControlHandler)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        yield f"http://127.0.0.1:{server.server_port}"
        server.shutdown()
        server.server_close()

    @staticmethod
    def _post_json(url, payload):
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            url + "/api/transcribe",
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {TEST_CONTROL_TOKEN}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def test_dispatch_transcribes(self, control_url, fake_stt):
        status, payload = self._post_json(control_url, _payload(filename="memo.ogg"))
        assert status == 200
        assert payload["ok"] is True
        assert payload["text"] == "Hallo Buddha, hier spricht Task 1338."

    def test_dispatch_validation_error_passes_through(self, control_url, fake_stt):
        status, payload = self._post_json(
            control_url, {"audio_b64": "abcde", "filename": "memo.exe"}
        )
        # Suffix-Check kommt vor dem Base64-Decode -> 415
        assert status == 415
        assert payload["ok"] is False

    def test_dispatch_rejects_non_json_content_type(self, control_url, fake_stt):
        req = urllib.request.Request(
            control_url + "/api/transcribe",
            data=b"raw-bytes",
            headers={
                "Content-Type": "application/octet-stream",
                "Authorization": f"Bearer {TEST_CONTROL_TOKEN}",
            },
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            urllib.request.urlopen(req, timeout=10)
        assert excinfo.value.code == 415
        assert fake_stt.calls == []


# ===================================================================
# GUI-Proxy-Freigabe
# ===================================================================


class TestGuiProxyRelease:
    """Der GUI-Proxy gibt "transcribe" an den Chat-Control-Dienst frei."""

    def test_transcribe_whitelisted(self):
        from gui import server as gui_server
        assert "transcribe" in gui_server.CHAT_CONTROL_PATHS
