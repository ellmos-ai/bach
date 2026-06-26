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
BACH Mail Service Setup v1.0
=============================
Richtet Gmail OAuth2-Zugang ein (read + send).

Aufruf:
    python mail_setup.py check    - Status pruefen
    python mail_setup.py refresh  - Token erneuern (nur wenn refresh_token vorhanden)
    python mail_setup.py auth     - Neuen OAuth-Flow starten (Browser-Fenster)
    python mail_setup.py test     - Test-Mail-Abfrage

Autor: BACH System
Datum: 2026-02-18
"""

import json
import os
import sys
from pathlib import Path
from datetime import datetime, timezone

SERVICE_DIR = Path(__file__).parent.resolve()
CREDENTIALS_FILE = SERVICE_DIR / "credentials" / "gmail_credentials.json"
TOKEN_FILE = SERVICE_DIR / "credentials" / "gmail_token.json"

REQUIRED_SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/gmail.compose',
]


def write_private_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def check_dependencies():
    """Prueft ob Google-API-Bibliotheken installiert sind."""
    missing = []
    try:
        from googleapiclient.discovery import build
    except ImportError:
        missing.append("google-api-python-client")
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
    except ImportError:
        missing.append("google-auth")
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        missing.append("google-auth-oauthlib")

    if missing:
        print(f"[FEHLER] Fehlende Pakete: {', '.join(missing)}")
        print(f"Installieren mit: pip install {' '.join(missing)}")
        return False
    return True


def check_status():
    """Zeigt Status des Mail-Service."""
    print("\n=== BACH Mail Service Status ===\n")

    # Credentials pruefen
    if CREDENTIALS_FILE.exists():
        try:
            creds = json.loads(CREDENTIALS_FILE.read_text(encoding="utf-8"))
            client = creds.get("installed") or creds.get("web", {})
            print(f"[OK] Credentials: {CREDENTIALS_FILE.name}")
            print(f"     Client-ID: {client.get('client_id', '?')[:30]}...")
        except Exception as e:
            print(f"[FEHLER] Credentials lesen: {e}")
    else:
        print(f"[FEHLER] Keine credentials.json unter {CREDENTIALS_FILE}")
        print("         Lade sie von Google Cloud Console herunter.")

    # Token pruefen
    if TOKEN_FILE.exists():
        try:
            token = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
            expiry_str = token.get("expiry", "")
            scopes = token.get("scopes", [])
            has_send = any("send" in s for s in scopes)
            has_read = any("readonly" in s for s in scopes)
            has_refresh = bool(token.get("refresh_token"))

            print(f"\n[OK] Token: {TOKEN_FILE.name}")
            print(f"     Scopes: {', '.join(s.split('/')[-1] for s in scopes)}")
            print(f"     Lesen: {'ja' if has_read else 'NEIN'}")
            print(f"     Senden: {'ja' if has_send else 'NEIN - neu authorizieren!'}")
            print(f"     Refresh-Token: {'vorhanden' if has_refresh else 'FEHLT'}")
            print(f"     Ablauf: {expiry_str}")

            # Ablauf pruefen
            if expiry_str:
                try:
                    from datetime import datetime, timezone
                    expiry = datetime.fromisoformat(expiry_str.replace('Z', '+00:00'))
                    now = datetime.now(timezone.utc)
                    if expiry < now:
                        if has_refresh:
                            print(f"     [WARN] Token abgelaufen - kann erneuert werden (refresh)")
                        else:
                            print(f"     [FEHLER] Token abgelaufen und kein Refresh-Token!")
                    else:
                        remaining = (expiry - now).seconds // 60
                        print(f"     Gueltig noch: ~{remaining} Min")
                except Exception as e:
                    print(f"     [WARN] Ablauf konnte nicht geprueft werden: {e}")

            if not has_send:
                print("\n[ACTION REQUIRED] 'send'-Scope fehlt!")
                print("  Loesung: python mail_setup.py auth")
                print("  Dies startet einen Browser-OAuth-Flow mit vollstaendigen Rechten.")
        except Exception as e:
            print(f"[FEHLER] Token lesen: {e}")
    else:
        print(f"\n[FEHLER] Kein Token unter {TOKEN_FILE}")
        print("  Loesung: python mail_setup.py auth")

    # Bibliotheken
    print(f"\nBibliotheken:")
    deps_ok = check_dependencies()
    if deps_ok:
        print("[OK] Alle Google-API-Pakete verfuegbar")
    print()


def refresh_token():
    """Erneuert den Access-Token via Refresh-Token."""
    if not check_dependencies():
        return False

    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    if not TOKEN_FILE.exists():
        print("[FEHLER] Kein Token vorhanden. Bitte zuerst: python mail_setup.py auth")
        return False

    try:
        token_data = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
        creds = Credentials(
            token=token_data.get("token"),
            refresh_token=token_data.get("refresh_token"),
            token_uri=token_data.get("token_uri", "https://oauth2.googleapis.com/token"),
            client_id=token_data.get("client_id"),
            client_secret=token_data.get("client_secret"),
            scopes=token_data.get("scopes", REQUIRED_SCOPES),
        )

        if not creds.refresh_token:
            print("[FEHLER] Kein Refresh-Token im Token vorhanden.")
            print("  Loesung: python mail_setup.py auth (neuer OAuth-Flow)")
            return False

        print("Erneuere Token...")
        creds.refresh(Request())
        print(f"[OK] Token erneuert. Ablauf: {creds.expiry}")

        # Token speichern
        token_out = {
            "token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "scopes": list(creds.scopes) if creds.scopes else REQUIRED_SCOPES,
            "universe_domain": "googleapis.com",
            "account": "",
            "expiry": creds.expiry.isoformat() if creds.expiry else "",
        }
        write_private_json(TOKEN_FILE, token_out)
        print(f"[OK] Token gespeichert: {TOKEN_FILE}")
        return True

    except Exception as e:
        print(f"[FEHLER] Token-Refresh fehlgeschlagen: {e}")
        print("  Moeglicherweise muessen die Scopes neu autorisiert werden.")
        print("  Loesung: python mail_setup.py auth")
        return False


def start_oauth_flow():
    """Startet neuen OAuth-Flow (oeffnet Browser)."""
    if not check_dependencies():
        return False

    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request

    if not CREDENTIALS_FILE.exists():
        print(f"[FEHLER] Keine credentials.json unter {CREDENTIALS_FILE}")
        print("  Lade sie von Google Cloud Console (APIs & Services → Credentials)")
        print("  als 'OAuth 2.0 Client IDs' → 'Desktop App' herunter.")
        print()
        print("  Hinweis fuer neue BACH-Nutzer:")
        print("  1. Neues Google Cloud Projekt anlegen")
        print("  2. Gmail API aktivieren (APIs & Services → Library)")
        print("  3. OAuth Consent Screen: App-Name 'BachMailService' setzen")
        print("  4. Credentials → 'OAuth 2.0-Client-ID' → 'Desktop-App' erstellen")
        print("  5. JSON herunterladen und als gmail_credentials.json speichern")
        return False

    # Localhost-OAuth erlauben (kein echtes HTTPS noetig fuer loopback)
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

    print("\n=== Gmail OAuth2 Autorisierung ===\n")
    print(f"Scopes: {', '.join(s.split('/')[-1] for s in REQUIRED_SCOPES)}")
    print("\nOeffne Browser fuer Google-Login...")
    print("(Falls kein Browser oeffnet, URL manuell kopieren)\n")

    try:
        flow = InstalledAppFlow.from_client_secrets_file(
            str(CREDENTIALS_FILE),
            REQUIRED_SCOPES
        )
        creds = flow.run_local_server(port=0, open_browser=True)

        # Token SOFORT speichern im authorized_user Format
        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        token_data = {
            "type": "authorized_user",
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "refresh_token": creds.refresh_token,
            "token": creds.token,
            "token_uri": creds.token_uri or "https://oauth2.googleapis.com/token",
            "scopes": list(creds.scopes) if creds.scopes else REQUIRED_SCOPES,
        }
        write_private_json(TOKEN_FILE, token_data)
        print(f"[OK] Token gespeichert: {TOKEN_FILE}")
        print("     OAuth-Daten wurden privat gespeichert.")

        # E-Mail-Adresse ermitteln (nach Token-Speicherung)
        email = "unbekannt"
        try:
            from googleapiclient.discovery import build
            service = build('gmail', 'v1', credentials=creds)
            profile = service.users().getProfile(userId='me').execute()
            email = profile.get('emailAddress', 'unbekannt')
        except Exception as e2:
            print(f"[WARN] E-Mail-Adresse konnte nicht abgerufen werden: {e2}")

        print(f"[OK] Autorisiert als: {email}")

        # email_sender.py DEFAULT_SENDER aktualisieren
        if email != "unbekannt":
            sender_file = SERVICE_DIR / "email_sender.py"
            if sender_file.exists():
                content = sender_file.read_text(encoding='utf-8')
                import re as _re
                updated = _re.sub(
                    r'DEFAULT_SENDER\s*=\s*"[^"]*"',
                    f'DEFAULT_SENDER = "{email}"',
                    content
                )
                if updated != content:
                    sender_file.write_text(updated, encoding='utf-8')
                    print(f"[OK] email_sender.py: DEFAULT_SENDER = {email}")

        print(f"\n=== Setup abgeschlossen! ===")
        print(f"E-Mail-Adresse: {email}")
        print(f"Scopes: read + send + compose")
        print(f"\nMail-Service testen: python mail_setup.py test")
        return True

    except Exception as e:
        print(f"[FEHLER] OAuth-Flow fehlgeschlagen: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_service():
    """Testet den Mail-Service (Verbindung + Ungelesene zaehlen)."""
    if not check_dependencies():
        return

    from googleapiclient.discovery import build
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    if not TOKEN_FILE.exists():
        print("[FEHLER] Kein Token. Bitte: python mail_setup.py auth")
        return

    try:
        token_data = json.loads(TOKEN_FILE.read_text(encoding='utf-8'))

        # Felder pruefen
        missing = [f for f in ("client_id", "client_secret", "refresh_token")
                   if not token_data.get(f)]
        if missing:
            print(f"[FEHLER] Token-Datei unvollstaendig, fehlende Felder: {missing}")
            print("  Bitte nochmal: python mail_setup.py auth")
            return

        creds = Credentials(
            token=token_data.get("token"),
            refresh_token=token_data["refresh_token"],
            token_uri=token_data.get("token_uri", "https://oauth2.googleapis.com/token"),
            client_id=token_data["client_id"],
            client_secret=token_data["client_secret"],
            scopes=token_data.get("scopes", REQUIRED_SCOPES),
        )

        # Token erneuern falls abgelaufen
        if not creds.valid:
            if creds.expired and creds.refresh_token:
                print("Token abgelaufen, erneuere...")
                creds.refresh(Request())
                print("[OK] Token erneuert")
            else:
                print("[FEHLER] Token ungueltig. Bitte: python mail_setup.py auth")
                return

        service = build('gmail', 'v1', credentials=creds)

        # Profil abfragen
        profile = service.users().getProfile(userId='me').execute()
        email = profile.get('emailAddress', '?')
        total = profile.get('messagesTotal', 0)
        unread = profile.get('threadsTotal', 0)

        print(f"\n=== Gmail Verbindungstest ===")
        print(f"[OK] Verbunden als: {email}")
        print(f"     Gesamt-Nachrichten: {total}")
        print(f"     Threads gesamt: {unread}")

        # Letzte 3 Mails abfragen
        result = service.users().messages().list(
            userId='me', maxResults=3, q='in:inbox'
        ).execute()
        msgs = result.get('messages', [])
        print(f"\nLetzte Posteingang-Nachrichten:")
        for msg in msgs:
            detail = service.users().messages().get(
                userId='me', id=msg['id'], format='metadata',
                metadataHeaders=['From', 'Subject']
            ).execute()
            headers = {h['name']: h['value']
                       for h in detail.get('payload', {}).get('headers', [])}
            print(f"  Von: {headers.get('From', '?')[:50]}")
            print(f"  Betreff: {headers.get('Subject', '?')[:60]}")
            print()

        print("[OK] Mail-Service funktioniert!")

    except Exception as e:
        print(f"[FEHLER] Test fehlgeschlagen: {e}")
        import traceback
        traceback.print_exc()


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"

    if cmd == "check":
        check_status()
    elif cmd == "refresh":
        refresh_token()
    elif cmd == "auth":
        start_oauth_flow()
    elif cmd == "test":
        test_service()
    else:
        print(f"Unbekannter Befehl: {cmd}")
        print("Gueltig: check | refresh | auth | test")
        sys.exit(1)


if __name__ == "__main__":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    main()
