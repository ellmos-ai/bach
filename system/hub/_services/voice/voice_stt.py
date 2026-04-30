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
Tool: voice_service
Version: 1.1.0
Author: BACH Team
Created: 2026-02-08
Updated: 2026-02-15
Anthropic-Compatible: True

Description:
    Voice Service fuer BACH - STT, TTS und Wake-Word-Erkennung.
    Portiert und erweitert aus BachForelle voice.py + ears.py.

    STT-Engines: Whisper (online), Vosk (offline)
    TTS-Engines: pyttsx3 (Windows SAPI5 / espeak), Piper-TTS (neural, DE-optimiert)
    Wake-Word:   openwakeword (optional), Keyboard-Fallback

    NEU in 1.1.0:
    - speak_to_file(): Text als MP3/OGG/WAV exportieren
    - Piper-TTS Support fuer hochwertige deutsche Stimmen
    - Multi-Engine-Support (auto-select bestes verfuegbares TTS)

Dependencies (alle optional):
    pip install openai-whisper   # STT Option 1
    pip install vosk             # STT Option 2 (offline)
    pip install pyttsx3          # TTS Option 1 (Basic)
    pip install piper-tts        # TTS Option 2 (Neural, empfohlen fuer DE)
    pip install openwakeword     # Wake-Word
    pip install pyaudio numpy    # Mikrofon fuer Wake-Word
    ffmpeg                       # Optional: MP3/OGG Export
"""

__version__ = "1.1.0"

import os
import json
import threading
import time
from pathlib import Path
from typing import Optional, Tuple, Callable

# ---- Optional Imports mit Verfuegbarkeits-Flags ----

try:
    import pyttsx3
    TTS_AVAILABLE = True
except ImportError:
    TTS_AVAILABLE = False

try:
    from piper import PiperVoice
    PIPER_AVAILABLE = True
except ImportError:
    PIPER_AVAILABLE = False

try:
    import openwakeword
    import pyaudio
    import numpy as np
    from openwakeword.model import Model as OWWModel
    WAKEWORD_AVAILABLE = True
except ImportError:
    WAKEWORD_AVAILABLE = False


class VoiceSTT:
    """Speech-to-Text Service. Whisper (online) oder Vosk (offline)."""

    def __init__(self, engine: str = "auto", model_size: str = "base"):
        """
        engine: 'whisper', 'vosk', oder 'auto' (erster verfuegbarer)
        model_size: Whisper-Modellgroesse ('tiny', 'base', 'small', 'medium')
        """
        self.engine = engine
        self.model_size = model_size
        self._whisper_model = None
        self._vosk_model = None

    def is_available(self) -> Tuple[bool, str]:
        """Prueft ob STT verfuegbar ist."""
        if self.engine in ("whisper", "auto"):
            try:
                import whisper
                return True, "whisper"
            except ImportError:
                pass

        if self.engine in ("vosk", "auto"):
            try:
                import vosk
                return True, "vosk"
            except ImportError:
                pass

        return False, "Kein STT-Engine verfuegbar. pip install openai-whisper oder pip install vosk"

    def transcribe_file(self, audio_path: str, language: str = "de") -> Optional[str]:
        """Audio-Datei transkribieren."""
        available, engine = self.is_available()
        if not available:
            return None

        if engine == "whisper":
            return self._transcribe_whisper(audio_path, language)
        elif engine == "vosk":
            return self._transcribe_vosk(audio_path)
        return None

    def _transcribe_whisper(self, path: str, language: str) -> Optional[str]:
        try:
            import whisper
            if not self._whisper_model:
                self._whisper_model = whisper.load_model(self.model_size)
            result = self._whisper_model.transcribe(path, language=language)
            return result.get("text", "")
        except Exception as e:
            return f"[Fehler: {e}]"

    def _transcribe_vosk(self, path: str) -> Optional[str]:
        try:
            import vosk
            import wave
            model_path = os.environ.get("VOSK_MODEL", "")
            if not model_path or not os.path.exists(model_path):
                return "[Fehler: VOSK_MODEL Pfad nicht gesetzt oder ungueltig]"

            if not self._vosk_model:
                vosk.SetLogLevel(-1)
                self._vosk_model = vosk.Model(model_path)

            wf = wave.open(path, "rb")
            rec = vosk.KaldiRecognizer(self._vosk_model, wf.getframerate())

            text_parts = []
            while True:
                data = wf.readframes(4000)
                if len(data) == 0:
                    break
                if rec.AcceptWaveform(data):
                    result = json.loads(rec.Result())
                    text_parts.append(result.get("text", ""))

            final = json.loads(rec.FinalResult())
            text_parts.append(final.get("text", ""))
            wf.close()
            return " ".join(text_parts).strip()
        except Exception as e:
            return f"[Fehler: {e}]"


class VoiceTTS:
    """Text-to-Speech Service mit Voice-Selection und Non-Blocking-Modus.

    Portiert aus BachForelle voice.py - nutzt pyttsx3 (Windows SAPI5).
    Erweitert um Piper-TTS für bessere deutsche Stimmen und File-Export.
    """

    def __init__(self, rate: int = 170, voice_name: str = "auto", engine: str = "auto"):
        """
        rate: Sprechgeschwindigkeit (Standard: 170, schneller als pyttsx3-Default 200)
        voice_name: 'auto' (Zira bevorzugt), oder Name-Fragment der Stimme
        engine: 'pyttsx3', 'piper', oder 'auto' (erster verfuegbarer)
        """
        self.rate = rate
        self.voice_name = voice_name
        self.engine = engine
        self._engine = None
        self._piper_voice = None
        self._piper_model_path = None
        self._setup_done = False

    def is_available(self) -> Tuple[bool, str]:
        """Prueft ob TTS verfuegbar ist."""
        if self.engine in ("pyttsx3", "auto") and TTS_AVAILABLE:
            return True, "pyttsx3"
        if self.engine in ("piper", "auto") and PIPER_AVAILABLE:
            return True, "piper"
        return False, "Kein TTS-Engine verfuegbar. pip install pyttsx3 oder pip install piper-tts"

    def _detect_language(self, text: str) -> str:
        """Heuristische Sprach-Erkennung: 'de' oder 'en'.

        Kriterien: deutsche Umlaute/ß zaehlen stark, deutsche Stoppwoerter
        und englische Stoppwoerter werden gegeneinander abgewogen.
        """
        if not text:
            return "de"
        lower = text.lower()
        de_score = 0
        en_score = 0
        for ch in "äöüß":
            if ch in lower:
                de_score += 3
        de_words = (" der ", " die ", " das ", " und ", " ist ", " nicht ", " mit ", " ein ",
                    " eine ", " ich ", " du ", " wir ", " auch ", " auf ", " für ", " fuer ",
                    " sind ", " wurde ", " werden ", " kann ", " soll ", " hat ", " haben ")
        en_words = (" the ", " and ", " is ", " not ", " with ", " a ", " an ", " of ", " to ",
                    " in ", " on ", " for ", " are ", " was ", " were ", " be ", " have ",
                    " has ", " this ", " that ", " you ", " we ", " they ", " it ")
        padded = f" {lower} "
        for w in de_words:
            if w in padded:
                de_score += 1
        for w in en_words:
            if w in padded:
                en_score += 1
        return "en" if en_score > de_score else "de"

    def _select_voice_id(self, lang: str) -> Optional[str]:
        """Liefert die voice.id zur passenden Sprache (de=Hedda, en=Zira) oder None."""
        if not self._engine:
            return None
        try:
            voices = self._engine.getProperty("voices")
        except Exception:
            return None
        prefs_de = ("hedda", "katja", "stefan", "german")
        prefs_en = ("zira", "david", "mark", "english")
        prefs = prefs_en if lang == "en" else prefs_de
        for pref in prefs:
            for v in voices:
                if pref in v.name.lower():
                    return v.id
        return None

    def _ensure_engine(self):
        """Engine lazy initialisieren (vermeidet Import-Fehler bei fehlender Abhaengigkeit)."""
        if self._setup_done:
            return
        self._setup_done = True

        if not TTS_AVAILABLE:
            return

        try:
            self._engine = pyttsx3.init()
            self._engine.setProperty("rate", self.rate)
            self._engine.setProperty("volume", 1.0)

            # Voice-Selection: bei voice_name='auto' uebernimmt _apply_voice_for_text()
            # die sprachsensitive Auswahl. Bei explizitem Namen: festen Match setzen.
            if self.voice_name not in ("none", "auto"):
                voices = self._engine.getProperty("voices")
                for v in voices:
                    if self.voice_name.lower() in v.name.lower():
                        self._engine.setProperty("voice", v.id)
                        break
            elif self.voice_name == "auto":
                # Default vor Sprach-Erkennung: deutsche Stimme
                vid = self._select_voice_id("de")
                if vid:
                    self._engine.setProperty("voice", vid)
        except Exception:
            self._engine = None

    def _apply_voice_for_text(self, text: str):
        """Wenn auto-Modus: passende Stimme zur erkannten Textsprache setzen."""
        if self.voice_name != "auto" or not self._engine:
            return
        lang = self._detect_language(text)
        vid = self._select_voice_id(lang)
        if vid:
            try:
                self._engine.setProperty("voice", vid)
            except Exception:
                pass

    def speak(self, text: str, block: bool = True) -> bool:
        """Text sprechen. block=False fuer non-blocking."""
        self._ensure_engine()
        if not self._engine:
            # Silent-Fallback
            print(f"[Silent Mode] >> {text}")
            return False

        self._apply_voice_for_text(text)

        try:
            self._engine.say(text)
            if block:
                self._engine.runAndWait()
            else:
                self._engine.startLoop(False)
                self._engine.iterate()
                self._engine.endLoop()
            return True
        except Exception:
            print(f"[Silent Mode] >> {text}")
            return False

    def speak_to_file(self, text: str, output_path: str, format: str = "mp3") -> bool:
        """Text als Audio-Datei speichern (MP3 oder OGG).

        Args:
            text: Zu sprechender Text
            output_path: Ausgabepfad (mit oder ohne Extension)
            format: 'mp3' oder 'ogg'

        Returns:
            True wenn erfolgreich, False bei Fehler
        """
        import tempfile
        import wave

        # Extension sicherstellen
        output_path = Path(output_path)
        if not output_path.suffix:
            output_path = output_path.with_suffix(f".{format}")

        # Piper bevorzugen wenn verfuegbar (bessere Qualitaet)
        if PIPER_AVAILABLE and self.engine in ("piper", "auto"):
            return self._speak_to_file_piper(text, str(output_path))

        # Fallback auf pyttsx3
        if TTS_AVAILABLE and self.engine in ("pyttsx3", "auto"):
            return self._speak_to_file_pyttsx3(text, str(output_path), format)

        print("[TTS Error] Kein TTS-Engine verfuegbar")
        return False

    def _speak_to_file_pyttsx3(self, text: str, output_path: str, format: str) -> bool:
        """Text-to-File via pyttsx3 (WAV → MP3/OGG Konvertierung)."""
        self._ensure_engine()
        if not self._engine:
            return False

        self._apply_voice_for_text(text)

        try:
            import tempfile
            import subprocess

            # pyttsx3 kann nur WAV direkt speichern
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_wav = tmp.name

            self._engine.save_to_file(text, tmp_wav)
            self._engine.runAndWait()

            # WAV zu MP3/OGG konvertieren mit ffmpeg
            if format.lower() in ("mp3", "ogg"):
                try:
                    subprocess.run([
                        "ffmpeg", "-i", tmp_wav, "-y",
                        "-codec:a", "libmp3lame" if format == "mp3" else "libopus",
                        "-b:a", "64k",
                        output_path
                    ], check=True, capture_output=True)
                    Path(tmp_wav).unlink(missing_ok=True)
                    return True
                except (subprocess.CalledProcessError, FileNotFoundError):
                    # Fallback: WAV direkt kopieren wenn ffmpeg fehlt
                    import shutil
                    output_wav = str(Path(output_path).with_suffix(".wav"))
                    shutil.copy(tmp_wav, output_wav)
                    Path(tmp_wav).unlink(missing_ok=True)
                    print(f"[TTS Warning] ffmpeg nicht gefunden, WAV gespeichert: {output_wav}")
                    return True
            else:
                # Direkt als WAV speichern
                import shutil
                shutil.copy(tmp_wav, output_path)
                Path(tmp_wav).unlink(missing_ok=True)
                return True

        except Exception as e:
            print(f"[TTS Error] speak_to_file failed: {e}")
            return False

    def _speak_to_file_piper(self, text: str, output_path: str) -> bool:
        """Text-to-File via Piper TTS (direkt WAV-Export, optional MP3/OGG)."""
        try:
            if not self._piper_voice:
                # Default deutsches Modell laden
                model_path = os.environ.get("PIPER_MODEL", "de_DE-thorsten-medium.onnx")
                if not Path(model_path).exists():
                    print(f"[Piper] Modell nicht gefunden: {model_path}")
                    print("[Piper] Setze PIPER_MODEL Environment-Variable oder installiere Modell")
                    return False

                self._piper_voice = PiperVoice.load(model_path)

            # Piper generiert WAV direkt
            import wave
            import tempfile

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_wav = tmp.name

            with wave.open(tmp_wav, "wb") as wav_file:
                self._piper_voice.synthesize(text, wav_file)

            # Optional: Konvertierung zu MP3/OGG
            output_ext = Path(output_path).suffix.lower()
            if output_ext in (".mp3", ".ogg"):
                import subprocess
                try:
                    subprocess.run([
                        "ffmpeg", "-i", tmp_wav, "-y",
                        "-codec:a", "libmp3lame" if output_ext == ".mp3" else "libopus",
                        "-b:a", "64k",
                        output_path
                    ], check=True, capture_output=True)
                    Path(tmp_wav).unlink(missing_ok=True)
                    return True
                except (subprocess.CalledProcessError, FileNotFoundError):
                    # Fallback: WAV kopieren
                    import shutil
                    output_wav = str(Path(output_path).with_suffix(".wav"))
                    shutil.copy(tmp_wav, output_wav)
                    Path(tmp_wav).unlink(missing_ok=True)
                    print(f"[Piper Warning] ffmpeg nicht gefunden, WAV gespeichert: {output_wav}")
                    return True
            else:
                # Direkt als WAV
                import shutil
                shutil.copy(tmp_wav, output_path)
                Path(tmp_wav).unlink(missing_ok=True)
                return True

        except Exception as e:
            print(f"[Piper Error] speak_to_file failed: {e}")
            return False

    def list_voices(self) -> list:
        """Alle verfuegbaren Stimmen auflisten."""
        self._ensure_engine()
        if not self._engine:
            return []
        return [{"id": v.id, "name": v.name, "lang": getattr(v, "languages", [])}
                for v in self._engine.getProperty("voices")]


class WakeWordListener:
    """Wake-Word-Erkennung mit openwakeword + Keyboard-Fallback.

    Portiert aus BachForelle ears.py.
    """

    def __init__(self, threshold: float = 0.5):
        self.threshold = threshold
        self.is_listening = False
        self._oww_model = None
        self._pyaudio = None

    def is_available(self) -> Tuple[bool, str]:
        if WAKEWORD_AVAILABLE:
            return True, "openwakeword + pyaudio"
        return False, "Keyboard-Fallback (openwakeword/pyaudio nicht installiert)"

    def listen(self, on_wake: Callable, stop_event: threading.Event = None):
        """Blockierende Listening-Schleife. Ruft on_wake() bei Erkennung auf.

        Nutzt openwakeword wenn verfuegbar, sonst Keyboard-Fallback (Enter).
        """
        if WAKEWORD_AVAILABLE:
            self._listen_audio(on_wake, stop_event)
        else:
            self._listen_keyboard(on_wake, stop_event)

    def listen_threaded(self, on_wake: Callable) -> Tuple[threading.Thread, threading.Event]:
        """Startet Listen-Loop in eigenem Thread. Gibt (Thread, StopEvent) zurueck."""
        stop_event = threading.Event()
        thread = threading.Thread(
            target=self.listen, args=(on_wake, stop_event),
            daemon=True, name="bach-wakeword")
        thread.start()
        return thread, stop_event

    def _listen_keyboard(self, on_wake: Callable, stop_event: threading.Event = None):
        """Fallback: Enter druecken als Wake-Word."""
        print("[WakeWord] Mikrofon nicht verfuegbar.")
        print("[WakeWord] Keyboard-Modus: ENTER druecken zum Aktivieren.")
        self.is_listening = True

        while not (stop_event and stop_event.is_set()):
            try:
                input()
                print("[WakeWord] Aktiviert (Keyboard)!")
                on_wake()
            except EOFError:
                break

        self.is_listening = False

    def _listen_audio(self, on_wake: Callable, stop_event: threading.Event = None):
        """Echtzeit Wake-Word-Erkennung via openwakeword."""
        try:
            self._oww_model = OWWModel()

            CHUNK = 1280
            FORMAT = pyaudio.paInt16
            CHANNELS = 1
            RATE = 16000

            self._pyaudio = pyaudio.PyAudio()
            stream = self._pyaudio.open(
                format=FORMAT, channels=CHANNELS, rate=RATE,
                input=True, frames_per_buffer=CHUNK)

            print("[WakeWord] Lausche auf Wake-Word...")
            self.is_listening = True

            while not (stop_event and stop_event.is_set()):
                audio = np.frombuffer(stream.read(CHUNK), dtype=np.int16)
                self._oww_model.predict(audio)

                for mdl in self._oww_model.prediction_buffer.keys():
                    score = self._oww_model.prediction_buffer[mdl][-1]
                    if score > self.threshold:
                        print(f"[WakeWord] Erkannt! ({mdl}, Score: {score:.2f})")
                        on_wake()
                        self._oww_model.reset()
                        time.sleep(1)
                        break

        except Exception as e:
            print(f"[WakeWord] Audio-Fehler: {e}")
            print("[WakeWord] Wechsle zu Keyboard-Fallback.")
            self._listen_keyboard(on_wake, stop_event)
        finally:
            self.is_listening = False
            if self._pyaudio:
                self._pyaudio.terminate()


class VoiceService:
    """Kombinierter Voice Service - verbindet STT, TTS und Wake-Word."""

    def __init__(self):
        self.stt = VoiceSTT()
        self.tts = VoiceTTS()
        self.wakeword = WakeWordListener()

    def status(self) -> dict:
        """Gesamtstatus aller Voice-Komponenten."""
        stt_ok, stt_engine = self.stt.is_available()
        tts_ok, tts_engine = self.tts.is_available()
        ww_ok, ww_engine = self.wakeword.is_available()

        return {
            "stt": {"available": stt_ok, "engine": stt_engine},
            "tts": {"available": tts_ok, "engine": tts_engine,
                    "voices": len(self.tts.list_voices())},
            "wakeword": {"available": ww_ok, "engine": ww_engine,
                         "listening": self.wakeword.is_listening},
        }


def main():
    """CLI-Einstiegspunkt."""
    svc = VoiceService()
    status = svc.status()

    print("Voice Service Status (v1.0)")
    print("=" * 40)
    for component, info in status.items():
        ok = "OK" if info["available"] else "FEHLT"
        print(f"  {component:>10}: [{ok}] {info['engine']}")
        for k, v in info.items():
            if k not in ("available", "engine"):
                print(f"{'':>14}{k}: {v}")

    # TTS-Test wenn verfuegbar
    if status["tts"]["available"]:
        print("\nTTS-Test:")
        voices = svc.tts.list_voices()
        for v in voices[:5]:
            print(f"  - {v['name']}")


if __name__ == "__main__":
    main()
