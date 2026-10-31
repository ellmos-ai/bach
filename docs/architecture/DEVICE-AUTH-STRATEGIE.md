# BACH Geräte- und Token-Strategie (Task #1456 / #1497–#1502)

Dokumentation der Implementierung für individuelle, permanente Geräte-Tokens im BACH-Ecosystem.

## 1. Übersicht & Prinzipien

- **Ein eigener Token pro Gerät**: Jeder Client (Laptop, Workstation, Handy, Browser, Tray) erhält einen individuellen Token.
- **Kein Ablaufdatum**: Der Token verfällt nicht automatisch nach einer Zeitspanne, sondern bleibt gültig, bis er aktiv widerrufen wird.
- **Individuell sperrbar**: Geht ein Gerät verloren oder wird kompromittiert, wird nur dessen Token gesperrt (`revoke_device(name)`). Alle anderen Geräte arbeiten unterbrechungsfrei weiter.
- **Sichere Serverablage**: Der Server speichert niemals Plaintext-Tokens, sondern ausschließlich kryptographische SHA-256-Hex-Hashes in der Tabelle `devices`.
- **Sichere Clientablage**:
  - Native Clients (macOS/Windows): Ablage im OS-Schlüsselbund (macOS Keychain bzw. Windows Credential Manager) über `hub.secrets_handler`.
  - Tray: Liest den Token automatisch aus dem Schlüsselbund (`bach_device_token_tray`) und authentifiziert API-Calls ohne Benutzereingabe.
  - Browser: Eine ausdrückliche Tokenprüfung über `POST /api/devices/verify` setzt ein
    `HttpOnly`-/`SameSite=Strict`-Cookie für die aktuelle Browsersitzung. Der Token
    bleibt im Eingabefeld nur bis zur Prüfung und wird weder in `localStorage` noch
    in einem JavaScript-Bundle abgelegt. `POST /api/devices/session/logout` löscht
    das Cookie.

  Browser können das OS-Schlüsselbund eines anderen Hosts nicht sicher selbst lesen.
  Eine automatische Keyring→Browser-Brücke ist deshalb kein impliziter Fallback:
  Hosttokens werden über einen ausdrücklich privaten Übergabekanal eingegeben und
  anschließend nur als HttpOnly-Cookie verwendet. Ein Hostempfänger gilt erst nach
  individueller CredentialStore-Provisionierung und unabhängigem API-Readback als
  verifiziert; ein `.SYNC`- oder Direct-Beam-Eintrag ist kein Empfangsbeleg.

## 2. Datenbank-Schema

In `bach.db`:

```sql
CREATE TABLE IF NOT EXISTS devices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    token_hash TEXT NOT NULL UNIQUE,
    status TEXT DEFAULT 'active' CHECK (status IN ('active', 'revoked')),
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    revoked_at TEXT,
    last_seen_at TEXT
);
```

## 3. Kernkomponenten & Dateien

1. **`system/gui/device_auth.py` (Tasks #1497, #1498)**:
   - `create_device(name)`: Erzeugt URL-safe Plaintext-Token (nur einmalige Rückgabe), speichert SHA-256-Hash.
   - `revoke_device(name)`: Sperrt das Gerät und setzt `status = 'revoked'` sowie `revoked_at`.
   - `list_devices()`: Listet alle registrierten Geräte ohne Hash-Exposition.
   - `validate_token(token)`: Validiert Plaintext-Token gegen aktiven Hash und aktualisiert `last_seen_at`.
   - `store_device_token(device_name, token, keyring_backend)`: Speichert Token im OS-Keyring (`bach_device_token_<gerät>`).
   - `get_device_token(device_name, keyring_backend)`: Liest Token aus dem OS-Keyring.
   - `delete_device_token(device_name, keyring_backend)`: Entfernt Token aus dem OS-Keyring.

2. **`system/gui/server.py` (Task #1499)**:
   - `DeviceAuthMiddleware`: Prüft `Authorization: Bearer <token>` gegen die `devices`-Tabelle.
   - **Fail-Closed auf geschützten Pfaden:** Ohne gültigen Geräte-Token verweigert die Middleware den Zugriff. Das gilt auch für unkonfigurierte Systeme ohne aktive Geräte und für Loopback-Clients; fehlende Tokens führen zu HTTP 401. Explizit öffentliche Pfade bleiben davon ausgenommen.
   - **Erstanlage:** Das erste Gerät wird durch eine ausdrückliche lokale Administrationsaktion angelegt (`gui.device_auth.create_device`); der öffentliche Hinweis steht in `system/gui/templates/token-dashboard.html`. HTTP-Anfragen ohne Token erhalten dadurch keinen Bootstrap-Schreibzugriff.
   - Endpunkte:
     - `GET /api/devices`: Liste registrierter Geräte.
     - `POST /api/devices`: Registrierung eines neuen Geräts.
     - `POST /api/devices/{name}/revoke`: Widerruf eines Geräts.
     - `POST /api/devices/verify`: Validierung eines Tokens und Setzen der
       Browser-Session als HttpOnly-Cookie; bei ungültigem Token wird ein altes
       Browser-Cookie gelöscht.
     - `POST /api/devices/session/logout`: Löschen der Browser-Session.
     - `GET /token-dashboard`: HTML-Oberfläche für Geräteverwaltung.

3. **`system/hub/_services/chat/chat_tray.py` (Task #1500)**:
   - Liest `bach_device_token_tray` beim Start über `hub.secrets_handler.get_secret_value`.
   - Sendet `Authorization: Bearer <token>` automatisch bei Anfragen an `gui_url`.

4. **`system/gui/templates/token-dashboard.html` (Task #1501)**:
   - Statusanzeige für aktuellen Browser ("Angemeldet" / "Nicht angemeldet").
   - "Gerät abmelden"-Funktion (löscht die serverseitige Browser-Session).
   - Einmalige Anzeige neu generierter Tokens mit Zwischenablage-Kopierfunktion.
   - Übersicht aller aktiven/gesperrten Geräte mit Sperren-Button.
   - Die Browseroberfläche liest keinen Gerätetoken aus `localStorage`; same-origin
     API-Aufrufe senden das HttpOnly-Cookie automatisch.

5. **`system/tests/test_device_auth.py` (Task #1502)**:
   - Vollständige Suite von 8 Unit- und Integrationstests (Isolation mit `MemoryKeyring` und temporärer SQLite-DB, FastAPI TestClient).
