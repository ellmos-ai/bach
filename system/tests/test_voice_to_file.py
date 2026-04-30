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
Test-Script für Voice-to-File Funktionalität
=============================================

Testet die erweiterte VoiceTTS-Klasse mit speak_to_file().

Datum: 2026-02-15
"""

import os
import sys
from pathlib import Path
import pytest

# UTF-8 Encoding fix
os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
if sys.stdout:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr:
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# Pfad zu system/ hinzufügen
SYSTEM_DIR = Path(__file__).parent
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))

from hub._services.voice.voice_stt import VoiceTTS


@pytest.mark.skipif(
    os.environ.get("BACH_RUN_VOICE_TESTS") != "1",
    reason="Voice/TTS integration test requires explicit opt-in via BACH_RUN_VOICE_TESTS=1",
)
def test_voice_to_file():
    """Testet speak_to_file mit verschiedenen Engines."""

    print("=" * 60)
    print("Voice-to-File Test")
    print("=" * 60)

    test_text = "Hallo, dies ist ein Test der Text-to-Speech Funktion von BACH. Version eins punkt eins."
    temp_dir = SYSTEM_DIR / "data" / "temp"
    temp_dir.mkdir(parents=True, exist_ok=True)

    # Test 1: Auto-Engine (beste verfügbare)
    print("\n[Test 1] Auto-Engine (beste verfügbare)")
    print("-" * 60)

    tts_auto = VoiceTTS(engine="auto")
    available, engine = tts_auto.is_available()

    if available:
        print(f"✓ TTS verfügbar: {engine}")

        # Test MP3
        output_mp3 = temp_dir / "test_voice_auto.mp3"

        print(f"  Generiere: {output_mp3}")
        success = tts_auto.speak_to_file(test_text, str(output_mp3), format="mp3")

        if success and output_mp3.exists():
            size_kb = output_mp3.stat().st_size / 1024
            print(f"  ✓ Erfolgreich erstellt ({size_kb:.1f} KB)")
        else:
            print(f"  ✗ Fehler beim Erstellen")
    else:
        print(f"✗ TTS nicht verfügbar: {engine}")

    # Test 2: pyttsx3 (falls verfügbar)
    print("\n[Test 2] pyttsx3-Engine")
    print("-" * 60)

    tts_pyttsx3 = VoiceTTS(engine="pyttsx3")
    available, engine = tts_pyttsx3.is_available()

    if available:
        print(f"✓ pyttsx3 verfügbar")

        output_wav = temp_dir / "test_voice_pyttsx3.wav"
        print(f"  Generiere: {output_wav}")
        success = tts_pyttsx3.speak_to_file(test_text, str(output_wav), format="wav")

        if success and output_wav.exists():
            size_kb = output_wav.stat().st_size / 1024
            print(f"  ✓ Erfolgreich erstellt ({size_kb:.1f} KB)")
        else:
            print(f"  ✗ Fehler beim Erstellen")
    else:
        print(f"✗ pyttsx3 nicht verfügbar")

    # Test 3: Piper (falls verfügbar)
    print("\n[Test 3] Piper-TTS-Engine")
    print("-" * 60)

    tts_piper = VoiceTTS(engine="piper")
    available, engine = tts_piper.is_available()

    if available:
        print(f"✓ Piper verfügbar")

        # Prüfen ob Modell konfiguriert ist
        piper_model = os.environ.get("PIPER_MODEL", "")
        if piper_model:
            print(f"  Modell: {piper_model}")

            output_ogg = temp_dir / "test_voice_piper.ogg"
            print(f"  Generiere: {output_ogg}")
            success = tts_piper.speak_to_file(test_text, str(output_ogg), format="ogg")

            if success and output_ogg.exists():
                size_kb = output_ogg.stat().st_size / 1024
                print(f"  ✓ Erfolgreich erstellt ({size_kb:.1f} KB)")
            else:
                print(f"  ✗ Fehler beim Erstellen")
        else:
            print(f"  ⚠ PIPER_MODEL Environment-Variable nicht gesetzt")
            print(f"  Info: Setze PIPER_MODEL=/pfad/zu/modell.onnx")
    else:
        print(f"✗ Piper nicht verfügbar (pip install piper-tts)")

    # Zusammenfassung
    print("\n" + "=" * 60)
    print("Test abgeschlossen")
    print("=" * 60)

    # Generierte Dateien auflisten
    if temp_dir.exists():
        files = list(temp_dir.glob("test_voice_*.*"))
        if files:
            print(f"\nGenerierte Dateien ({len(files)}):")
            for f in sorted(files):
                size_kb = f.stat().st_size / 1024
                print(f"  - {f.name} ({size_kb:.1f} KB)")
        else:
            print("\nKeine Dateien generiert.")


if __name__ == "__main__":
    try:
        test_voice_to_file()
    except KeyboardInterrupt:
        print("\n\nTest abgebrochen.")
    except Exception as e:
        print(f"\n\nFEHLER: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
