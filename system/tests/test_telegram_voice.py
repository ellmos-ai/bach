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
Test: Telegram Voice Message Integration
=========================================

Testet das Senden von TTS-generierten Voice-Nachrichten über Telegram.

Datum: 2026-02-15
"""

import os
import sys
import tempfile
from pathlib import Path

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
from connectors.telegram_connector import TelegramConnector
from connectors.base import ConnectorConfig


def test_telegram_voice_integration():
    """Testet TTS → Telegram Voice Integration."""

    print("=" * 60)
    print("Telegram Voice Message Integration Test")
    print("=" * 60)

    # 1. VoiceTTS initialisieren
    print("\n[1] VoiceTTS initialisieren")
    print("-" * 60)

    tts = VoiceTTS(engine="auto")
    available, engine = tts.is_available()

    if not available:
        import pytest
        pytest.skip(f"TTS nicht verfügbar: {engine}")

    print(f"✓ TTS verfügbar: {engine}")

    # 2. Telegram-Connector aus DB laden
    print("\n[2] Telegram-Connector laden")
    print("-" * 60)

    import sqlite3
    db_path = SYSTEM_DIR / "data" / "bach.db"

    if not db_path.exists():
        print(f"✗ Datenbank nicht gefunden: {db_path}")
        import pytest
        pytest.skip("Voraussetzung fehlt")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    row = conn.execute("""
        SELECT name, type, endpoint, auth_type, auth_config
        FROM connections
        WHERE name = 'telegram_main' AND category = 'connector'
    """).fetchone()

    conn.close()

    if not row:
        print("✗ telegram_main Connector nicht in DB gefunden")
        import pytest
        pytest.skip("Voraussetzung fehlt")

    print(f"✓ Connector gefunden: {row['name']}")

    # Auth-Config parsen
    import json
    auth_config = json.loads(row['auth_config']) if row['auth_config'] else {}

    # owner_chat_id ist in auth_config, nicht in options
    options = {"owner_chat_id": auth_config.get("owner_chat_id", "")}

    # 3. TelegramConnector initialisieren
    print("\n[3] TelegramConnector initialisieren")
    print("-" * 60)

    config = ConnectorConfig(
        name=row['name'],
        connector_type=row['type'],
        auth_type=row['auth_type'],
        auth_config=auth_config,
        options=options
    )

    telegram = TelegramConnector(config)

    if not telegram.connect():
        print("✗ Telegram-Verbindung fehlgeschlagen")
        import pytest
        pytest.skip("Voraussetzung fehlt")

    print(f"✓ Verbunden als: {telegram._bot_info.get('username', 'unknown')}")

    # 4. Voice-Nachricht generieren
    print("\n[4] Voice-Nachricht generieren")
    print("-" * 60)

    test_text = "Hallo! Dies ist eine automatisch generierte Test-Nachricht von BACH."

    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
        tmp_path = tmp.name

    print(f"  Text: {test_text}")
    print(f"  Datei: {tmp_path}")

    success = tts.speak_to_file(test_text, tmp_path, format="ogg")

    if not success or not Path(tmp_path).exists():
        print("✗ Voice-Generierung fehlgeschlagen")
        import pytest
        pytest.skip("Voraussetzung fehlt")

    size_kb = Path(tmp_path).stat().st_size / 1024
    print(f"✓ Voice-Datei erstellt ({size_kb:.1f} KB)")

    # 5. Voice-Nachricht an Telegram senden
    print("\n[5] Voice-Nachricht senden")
    print("-" * 60)

    recipient = options.get("owner_chat_id", "")
    if not recipient:
        print("✗ owner_chat_id nicht konfiguriert")
        Path(tmp_path).unlink(missing_ok=True)
        import pytest
        pytest.skip("Voraussetzung fehlt")

    print(f"  Empfänger: {recipient}")

    success = telegram.send_voice(recipient, tmp_path)

    # Temp-Datei aufräumen
    Path(tmp_path).unlink(missing_ok=True)

    if success:
        print("✓ Voice-Nachricht erfolgreich gesendet!")
    else:
        print("✗ Senden fehlgeschlagen")

    # 6. Disconnect
    telegram.disconnect()

    print("\n" + "=" * 60)
    print("Test abgeschlossen")
    print("=" * 60)

    assert success, "Voice-Nachricht senden fehlgeschlagen"


if __name__ == "__main__":
    try:
        success = test_telegram_voice_integration()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\nTest abgebrochen.")
        sys.exit(1)
    except Exception as e:
        print(f"\n\nFEHLER: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
