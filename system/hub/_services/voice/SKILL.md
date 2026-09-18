---
name: voice-service
version: 1.1.0
type: service
author: BACH Team
created: 2026-02-08
updated: 2026-09-18
anthropic_compatible: true
status: production

dependencies:
  tools: [voice_stt.py]
  services: []
  workflows: []

metadata:
  inputs: "audio-file, microphone-stream, keyboard-trigger, text-input"
  outputs: "transcript-text, tts-audio, audio-files (mp3/ogg/wav), wake-event"

description: >
  Voice Service fuer BACH - STT, TTS und Wake-Word-Erkennung.
  Portiert und erweitert aus BachForelle voice.py + ears.py.
  Version 1.1: Erweitert um File-Export und Piper-TTS.
---

# Voice Service

## Status: PRODUCTION

Vollstaendige Implementation mit STT, TTS (inkl. File-Export), Wake-Word.
Alle Komponenten haben graceful Fallbacks bei fehlenden Dependencies.

## Features

1. **STT (Speech-to-Text)**: Whisper (online) oder Vosk (offline)
2. **TTS (Text-to-Speech)**:
   - pyttsx3 mit Voice-Selection (Zira bevorzugt) und Non-Blocking-Modus
   - **NEU**: Piper-TTS für hochwertige deutsche neuronale Stimmen
   - **NEU**: `speak_to_file()` - Text als MP3/OGG/WAV exportieren
3. **Wake-Word**: openwakeword + pyaudio, Keyboard-Fallback bei fehlender Hardware
4. **VoiceService**: Kombinierte Klasse mit Status-Reporting

## Abhaengigkeiten (alle optional)

```bash
# STT Engines
pip install openai-whisper   # STT Option 1 (online, hohe Qualitaet)
pip install vosk             # STT Option 2 (offline)

# TTS Engines
pip install pyttsx3          # TTS Option 1 (Basic, Windows SAPI5)
pip install piper-tts        # TTS Option 2 (Neural, EMPFOHLEN fuer DE)

# Wake-Word
pip install openwakeword     # Wake-Word Detection
pip install pyaudio numpy    # Mikrofon fuer Wake-Word

# Optional: Audio-Konvertierung
# ffmpeg (fuer MP3/OGG Export)
```

## Verwendung

### Basis-Nutzung

```python
from hub._services.voice.voice_stt import VoiceService

svc = VoiceService()

# Status aller Komponenten
status = svc.status()

# Text-to-Speech (Live)
svc.tts.speak("Hallo von BACH")
svc.tts.speak("Nicht blockierend", block=False)

# Speech-to-Text
text = svc.stt.transcribe_file("aufnahme.wav", language="de")

# Wake-Word (threaded)
thread, stop = svc.wakeword.listen_threaded(on_wake=lambda: print("Wach!"))
# ... spaeter: stop.set()
```

### NEU: Text-to-File (für Telegram/Discord Voice-Nachrichten)

```python
from hub._services.voice.voice_stt import VoiceTTS

# Mit pyttsx3 (Standard Windows-Stimmen)
tts = VoiceTTS(engine="pyttsx3")
tts.speak_to_file("Hallo von BACH!", "output.mp3", format="mp3")

# Mit Piper-TTS (hochwertige deutsche neuronale Stimmen)
# Voraussetzung: PIPER_MODEL Environment-Variable gesetzt
# z.B. export PIPER_MODEL=/path/to/de_DE-thorsten-medium.onnx
tts = VoiceTTS(engine="piper")
tts.speak_to_file("Hallo von BACH!", "output.ogg", format="ogg")

# Auto-Select (beste verfügbare Engine)
tts = VoiceTTS(engine="auto")
tts.speak_to_file("Test", "voice.mp3")
```

### Integration mit Telegram

```python
from hub._services.voice.voice_stt import VoiceTTS
from connectors.telegram_connector import TelegramConnector

tts = VoiceTTS()
telegram = TelegramConnector(config)

# Text als Voice-Nachricht senden
tts.speak_to_file("Hallo! Dies ist eine Test-Nachricht.", "temp_voice.ogg")
telegram.send_voice("CHAT_ID", "temp_voice.ogg")
```

## Piper-TTS Setup (Empfohlen für Deutsch)

1. Piper installieren:
   ```bash
   pip install piper-tts
   ```

2. Deutsches Modell herunterladen:
   ```bash
   # Thorsten Voice (hochwertig, mittel)
   wget https://github.com/rhasspy/piper/releases/download/v1.2.0/voice-de-de-thorsten-medium.tar.gz
   tar -xzf voice-de-de-thorsten-medium.tar.gz
   ```

3. Modell-Pfad setzen:
   ```bash
   # Windows
   set PIPER_MODEL=C:\path\to\de_DE-thorsten-medium.onnx

   # Linux/Mac
   export PIPER_MODEL=/path/to/de_DE-thorsten-medium.onnx
   ```

## Verfügbare deutsche Piper-Modelle

- **thorsten-medium**: Männliche Stimme, hohe Qualität, moderate Größe
- **thorsten-high**: Männliche Stimme, höchste Qualität, größere Dateigröße
- **eva_k-x_low**: Weibliche Stimme, schnell, kleine Dateigröße

Alle Modelle: https://github.com/rhasspy/piper/releases
