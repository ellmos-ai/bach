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
BACH Mail Account Manager v1.0
==============================
Verwaltung von E-Mail-Konten fuer den Financial Mail Service.

Features:
- IMAP-Konten mit Keyring-Passwortspeicherung
- Gmail API mit OAuth2 (credentials.json/token.json)
- Automatische Suche nach vorhandenen Gmail-Credentials
- Interaktive Konto-Einrichtung

Autor: BACH System
Datum: 2026-01-20
"""

import json
import sqlite3
import os
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass, asdict
import logging

# Den DB-Pfad zentral erfragen, nicht selbst bauen: ein repo-relativer Pfad zeigt auf die
# veraltete Kopie im OneDrive-Ordner (bzw. auf ein Verzeichnis, das es gar nicht gibt —
# dort legt sqlite3.connect() still eine leere 0-KB-Datenbank an).
_SYSTEM_ROOT = next(
    p for p in Path(__file__).resolve().parents if (p / "hub" / "bach_paths.py").exists()
)
if str(_SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(_SYSTEM_ROOT))
from hub.bach_paths import BACH_DB

# ============ PFADE ============

SERVICE_DIR = Path(__file__).parent.resolve()
SKILLS_DIR = SERVICE_DIR.parent.parent
BACH_DIR = SKILLS_DIR.parent

DATA_DIR = BACH_DIR / "data"
USER_DB = BACH_DB
CREDENTIALS_DIR = SERVICE_DIR / "credentials"
CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)

# Gmail-spezifische Dateien
GMAIL_CREDENTIALS_FILE = CREDENTIALS_DIR / "gmail_credentials.json"
GMAIL_TOKEN_FILE = CREDENTIALS_DIR / "gmail_token.json"
GMAIL_SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.send',
]

# Logging
LOG_FILE = BACH_DIR / "data" / "logs" / "mail_accounts.log"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ============ OPTIONALE IMPORTS ============

# Keyring
try:
    import keyring
    KEYRING_AVAILABLE = True
except ImportError:
    KEYRING_AVAILABLE = False
    logger.warning("keyring nicht installiert - Passwoerter werden nicht sicher gespeichert")

# Gmail API
try:
    from googleapiclient.discovery import build
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google.auth.exceptions import RefreshError
    GMAIL_API_AVAILABLE = True
except ImportError:
    GMAIL_API_AVAILABLE = False
    logger.info("Gmail API nicht verfuegbar - nur IMAP-Zugang moeglich")

# ============ IMAP PRESETS ============

IMAP_PRESETS = {
    "gmail.com": {
        "name": "Gmail",
        "host": "imap.gmail.com",
        "port": 993,
        "note": "App-Passwort erforderlich (2FA aktiviert)"
    },
    "googlemail.com": {
        "name": "Gmail",
        "host": "imap.gmail.com",
        "port": 993,
        "note": "App-Passwort erforderlich"
    },
    "outlook.com": {
        "name": "Outlook",
        "host": "outlook.office365.com",
        "port": 993,
        "note": ""
    },
    "hotmail.com": {
        "name": "Hotmail",
        "host": "outlook.office365.com",
        "port": 993,
        "note": ""
    },
    "live.com": {
        "name": "Live",
        "host": "outlook.office365.com",
        "port": 993,
        "note": ""
    },
    "gmx.de": {
        "name": "GMX",
        "host": "imap.gmx.net",
        "port": 993,
        "note": "IMAP muss in Einstellungen aktiviert werden"
    },
    "gmx.net": {
        "name": "GMX",
        "host": "imap.gmx.net",
        "port": 993,
        "note": ""
    },
    "web.de": {
        "name": "Web.de",
        "host": "imap.web.de",
        "port": 993,
        "note": "IMAP muss in Einstellungen aktiviert werden"
    },
    "t-online.de": {
        "name": "T-Online",
        "host": "secureimap.t-online.de",
        "port": 993,
        "note": "E-Mail-Passwort in Kundencenter erstellen"
    },
    "yahoo.com": {
        "name": "Yahoo",
        "host": "imap.mail.yahoo.com",
        "port": 993,
        "note": "App-Passwort erforderlich"
    },
    "yahoo.de": {
        "name": "Yahoo",
        "host": "imap.mail.yahoo.com",
        "port": 993,
        "note": ""
    },
    "icloud.com": {
        "name": "iCloud",
        "host": "imap.mail.me.com",
        "port": 993,
        "note": "App-spezifisches Passwort erforderlich"
    },
    "me.com": {
        "name": "iCloud",
        "host": "imap.mail.me.com",
        "port": 993,
        "note": ""
    },
    "posteo.de": {
        "name": "Posteo",
        "host": "posteo.de",
        "port": 993,
        "note": ""
    },
    "mailbox.org": {
        "name": "Mailbox.org",
        "host": "imap.mailbox.org",
        "port": 993,
        "note": ""
    },
    "protonmail.com": {
        "name": "ProtonMail",
        "host": "127.0.0.1",
        "port": 1143,
        "note": "ProtonMail Bridge erforderlich"
    },
    "proton.me": {
        "name": "ProtonMail",
        "host": "127.0.0.1",
        "port": 1143,
        "note": "ProtonMail Bridge erforderlich"
    },
    "1und1.de": {
        "name": "1&1",
        "host": "imap.1und1.de",
        "port": 993,
        "note": ""
    },
    "ionos.de": {
        "name": "IONOS",
        "host": "imap.ionos.de",
        "port": 993,
        "note": ""
    },
}

# ============ DATENMODELL ============

@dataclass
class MailAccount:
    """E-Mail Konto"""
    id: Optional[int] = None
    name: str = ""
    email: str = ""
    provider: str = "imap"  # imap, gmail_api
    imap_host: str = ""
    imap_port: int = 993
    use_oauth: bool = False
    is_active: bool = True
    last_sync: Optional[str] = None
    created_at: Optional[str] = None


# ============ ACCOUNT MANAGER ============

class AccountManager:
    """Verwaltet E-Mail-Konten"""

    def __init__(self):
        self._init_database()

    def _init_database(self):
        """Stellt sicher, dass die Tabelle existiert"""
        conn = sqlite3.connect(USER_DB)
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS mail_accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                provider TEXT NOT NULL DEFAULT 'imap',
                imap_host TEXT,
                imap_port INTEGER DEFAULT 993,
                use_oauth INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                last_sync TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.commit()
        conn.close()

    # ========== CRUD OPERATIONEN ==========

    def list_accounts(self, active_only: bool = False) -> List[MailAccount]:
        """Listet alle Konten"""
        conn = sqlite3.connect(USER_DB)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        query = "SELECT * FROM mail_accounts"
        if active_only:
            query += " WHERE is_active = 1"
        query += " ORDER BY name"

        cursor.execute(query)
        rows = cursor.fetchall()
        conn.close()

        return [
            MailAccount(
                id=row['id'],
                name=row['name'],
                email=row['email'],
                provider=row['provider'],
                imap_host=row['imap_host'] or '',
                imap_port=row['imap_port'] or 993,
                use_oauth=bool(row['use_oauth']),
                is_active=bool(row['is_active']),
                last_sync=row['last_sync'],
                created_at=row['created_at']
            )
            for row in rows
        ]

    def get_account(self, account_id: int) -> Optional[MailAccount]:
        """Holt einzelnes Konto"""
        conn = sqlite3.connect(USER_DB)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM mail_accounts WHERE id = ?", (account_id,))
        row = cursor.fetchone()
        conn.close()

        if not row:
            return None

        return MailAccount(
            id=row['id'],
            name=row['name'],
            email=row['email'],
            provider=row['provider'],
            imap_host=row['imap_host'] or '',
            imap_port=row['imap_port'] or 993,
            use_oauth=bool(row['use_oauth']),
            is_active=bool(row['is_active']),
            last_sync=row['last_sync'],
            created_at=row['created_at']
        )

    def get_account_by_email(self, email: str) -> Optional[MailAccount]:
        """Holt Konto nach E-Mail-Adresse"""
        conn = sqlite3.connect(USER_DB)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM mail_accounts WHERE email = ?", (email,))
        row = cursor.fetchone()
        conn.close()

        if not row:
            return None

        return MailAccount(
            id=row['id'],
            name=row['name'],
            email=row['email'],
            provider=row['provider'],
            imap_host=row['imap_host'] or '',
            imap_port=row['imap_port'] or 993,
            use_oauth=bool(row['use_oauth']),
            is_active=bool(row['is_active']),
            last_sync=row['last_sync'],
            created_at=row['created_at']
        )

    def add_account(self, account: MailAccount) -> int:
        """Fuegt Konto hinzu"""
        conn = sqlite3.connect(USER_DB)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO mail_accounts (name, email, provider, imap_host, imap_port, use_oauth, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            account.name,
            account.email,
            account.provider,
            account.imap_host,
            account.imap_port,
            1 if account.use_oauth else 0,
            1 if account.is_active else 0
        ))

        account_id = cursor.lastrowid
        conn.commit()
        conn.close()

        logger.info(f"Konto hinzugefuegt: {account.email} (ID: {account_id})")
        return account_id

    def update_account(self, account: MailAccount) -> bool:
        """Aktualisiert Konto"""
        if not account.id:
            return False

        conn = sqlite3.connect(USER_DB)
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE mail_accounts
            SET name = ?, email = ?, provider = ?, imap_host = ?, imap_port = ?,
                use_oauth = ?, is_active = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (
            account.name,
            account.email,
            account.provider,
            account.imap_host,
            account.imap_port,
            1 if account.use_oauth else 0,
            1 if account.is_active else 0,
            account.id
        ))

        conn.commit()
        conn.close()

        logger.info(f"Konto aktualisiert: {account.email}")
        return True

    def delete_account(self, account_id: int, delete_password: bool = True) -> bool:
        """Loescht Konto"""
        account = self.get_account(account_id)
        if not account:
            return False

        # Passwort loeschen
        if delete_password:
            self.delete_password(account.email)

        conn = sqlite3.connect(USER_DB)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM mail_accounts WHERE id = ?", (account_id,))
        conn.commit()
        conn.close()

        logger.info(f"Konto geloescht: {account.email}")
        return True

    def toggle_account(self, account_id: int) -> bool:
        """Aktiviert/Deaktiviert Konto"""
        conn = sqlite3.connect(USER_DB)
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE mail_accounts
            SET is_active = CASE WHEN is_active = 1 THEN 0 ELSE 1 END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (account_id,))

        conn.commit()
        conn.close()
        return True

    # ========== PASSWORT-VERWALTUNG ==========

    def set_password(self, email: str, password: str) -> bool:
        """Speichert Passwort sicher im Keyring"""
        if not KEYRING_AVAILABLE:
            logger.warning("Keyring nicht verfuegbar - Passwort wird nicht gespeichert")
            return False

        try:
            keyring.set_password("bach_financial_mail", email, password)
            logger.info(f"Passwort gespeichert fuer: {email}")
            return True
        except Exception as e:
            logger.error(f"Keyring-Fehler: {e}")
            return False

    def get_password(self, email: str) -> Optional[str]:
        """Holt Passwort aus Keyring"""
        if not KEYRING_AVAILABLE:
            return None

        try:
            return keyring.get_password("bach_financial_mail", email)
        except Exception as e:
            logger.error(f"Keyring-Fehler: {e}")
            return None

    def delete_password(self, email: str) -> bool:
        """Loescht Passwort aus Keyring"""
        if not KEYRING_AVAILABLE:
            return False

        try:
            keyring.delete_password("bach_financial_mail", email)
            return True
        except Exception:
            return False

    def has_password(self, email: str) -> bool:
        """Prueft ob Passwort vorhanden"""
        return self.get_password(email) is not None

    # ========== GMAIL API ==========

    def find_gmail_credentials(self) -> List[Path]:
        """
        Sucht nach vorhandenen Gmail credentials.json Dateien.

        Durchsucht:
        1. BACH-spezifische Pfade
        2. Bekannte Tool-Verzeichnisse (UniversalInvoiceMail, etc.)
        3. Standard-Verzeichnisse (Downloads, Documents, etc.)
        4. Rekursive Suche in User-Ordnern (max 4 Ebenen)
        5. Breite Suche im gesamten User-Verzeichnis
        """
        found = []
        user_home = Path.home()

        # === 1. Direkte Pfade (schnelle Suche) ===
        direct_paths = [
            # BACH-spezifisch
            GMAIL_CREDENTIALS_FILE,
            CREDENTIALS_DIR / "credentials.json",

            # UniversalInvoiceMail
            user_home / ".universal_invoice_mail" / "credentials.json",

            # Andere bekannte Tools
            user_home / ".invoicemaster" / "credentials.json",
            user_home / ".gmail_credentials" / "credentials.json",

            # Typische Orte
            user_home / ".credentials" / "gmail_credentials.json",
            user_home / ".config" / "gmail" / "credentials.json",
            user_home / "credentials.json",

            # Downloads - direkter Check
            user_home / "Downloads" / "credentials.json",

            # Projekt-Ordner
            Path.cwd() / "credentials.json",

            # AppData
            user_home / "AppData" / "Local" / "Google" / "credentials.json",
            user_home / "AppData" / "Roaming" / "gmail" / "credentials.json",
        ]

        for path in direct_paths:
            try:
                if path.exists() and path.stat().st_size > 100:
                    found.append(path)
            except (PermissionError, OSError):
                continue

        # === 2. Glob-Pattern fuer Downloads ===
        downloads_dir = user_home / "Downloads"
        if downloads_dir.exists():
            # client_secret_*.json (Google Cloud Console Format)
            for pattern in ["client_secret*.json", "credentials*.json"]:
                try:
                    for match in downloads_dir.glob(pattern):
                        if match.stat().st_size > 100:
                            found.append(match)
                except (PermissionError, OSError):
                    continue

        # === 3. Rekursive Suche in wichtigen Verzeichnissen ===
        recursive_search_dirs = [
            # OneDrive-Ordner
            user_home / "OneDrive" / ".SOFTWARE" / "TOOLS",
            user_home / "OneDrive" / ".SOFTWARE",
            user_home / "OneDrive" / ".AI",
            user_home / "OneDrive",

            # Standard Windows-Ordner
            user_home / "Documents",
            user_home / "Dokumente",  # Deutsches Windows

            # Versteckte Ordner
            user_home / ".config",

            # Desktop
            user_home / "Desktop",

            # Projekte
            user_home / "Projects",
            user_home / "Projekte",
            user_home / "dev",
            user_home / "Development",
        ]

        for base_dir in recursive_search_dirs:
            if not base_dir.exists():
                continue

            # Direkt im Ordner
            try:
                cred_file = base_dir / "credentials.json"
                if cred_file.exists() and cred_file.stat().st_size > 100:
                    found.append(cred_file)
            except (PermissionError, OSError):
                continue

            # Rekursiv suchen (max 4 Ebenen Tiefe)
            try:
                for depth in range(1, 5):
                    pattern = "/".join(["*"] * depth) + "/credentials.json"
                    for match in base_dir.glob(pattern):
                        try:
                            if match.exists() and match.stat().st_size > 100:
                                found.append(match)
                        except (PermissionError, OSError):
                            continue
            except (PermissionError, OSError):
                continue

        # === 4. Breite Suche im User-Home (client_secret_*.json) ===
        # Google Cloud Console liefert oft Dateien mit diesem Muster
        try:
            for pattern in ["client_secret_*.json", "*credentials*.json"]:
                for base in [user_home, user_home / "Downloads", user_home / "Desktop"]:
                    if base.exists():
                        for match in base.glob(pattern):
                            try:
                                if match.stat().st_size > 100 and match not in found:
                                    # Pruefe ob es eine Google OAuth Datei ist
                                    content = match.read_text(encoding='utf-8', errors='ignore')[:500]
                                    if '"installed"' in content or '"web"' in content or '"client_id"' in content:
                                        found.append(match)
                            except (PermissionError, OSError):
                                continue
        except (PermissionError, OSError):
            pass

        # === 5. Deduplizieren und sortieren ===
        unique_paths = list(set(found))

        # BACH-eigene Credentials zuerst, dann nach Modifikationszeit
        def sort_key(p: Path) -> tuple:
            is_bach = 1 if CREDENTIALS_DIR in p.parents or p == GMAIL_CREDENTIALS_FILE else 0
            try:
                mtime = p.stat().st_mtime
            except OSError:
                mtime = 0
            return (-is_bach, -mtime)

        unique_paths.sort(key=sort_key)

        if unique_paths:
            logger.info(f"Gefundene Gmail credentials: {len(unique_paths)} Datei(en)")
            for p in unique_paths[:5]:  # Erste 5 loggen
                logger.info(f"  - {p}")

        return unique_paths

    def setup_gmail_api(self, credentials_path: Optional[Path] = None) -> Tuple[bool, str]:
        """
        Richtet Gmail API Zugang ein.

        Sucht automatisch nach vorhandenen credentials.json Dateien und
        kopiert diese bei Bedarf in das BACH-Verzeichnis.

        Args:
            credentials_path: Optionaler expliziter Pfad zu credentials.json

        Returns:
            Tuple[bool, str]: (Erfolg, E-Mail-Adresse oder Fehlermeldung)
        """
        if not GMAIL_API_AVAILABLE:
            return False, "Gmail API Bibliotheken nicht installiert (google-api-python-client)"

        # Credentials-Datei finden
        if credentials_path and credentials_path.exists():
            creds_file = credentials_path
            logger.info(f"Verwende angegebene credentials.json: {creds_file}")
        else:
            # Automatische Suche
            logger.info("Suche nach vorhandenen Gmail credentials.json...")
            found = self.find_gmail_credentials()

            if not found:
                # Detaillierte Hilfe ausgeben
                search_hint = (
                    "Durchsuchte Orte:\n"
                    f"  - {CREDENTIALS_DIR}\n"
                    f"  - {Path.home() / '.universal_invoice_mail'}\n"
                    f"  - {Path.home() / 'Downloads'}\n"
                    f"  - {Path.home() / 'OneDrive' / 'Software Entwicklung'}\n"
                )
                return False, (
                    "Keine credentials.json gefunden.\n\n"
                    f"{search_hint}\n"
                    "Bitte erstellen Sie OAuth-Credentials in der Google Cloud Console:\n"
                    "1. https:/console.cloud.google.com/apis/credentials\n"
                    "2. 'Create Credentials' -> 'OAuth client ID'\n"
                    "3. Application type: 'Desktop app'\n"
                    "4. Download als JSON und speichern unter:\n"
                    f"   {GMAIL_CREDENTIALS_FILE}"
                )

            creds_file = found[0]
            logger.info(f"Gefundene credentials.json: {creds_file}")

            if len(found) > 1:
                logger.info(f"Weitere {len(found)-1} Datei(en) gefunden, verwende neueste")

        # Kopiere nach BACH falls noetig
        if creds_file != GMAIL_CREDENTIALS_FILE:
            import shutil
            shutil.copy(creds_file, GMAIL_CREDENTIALS_FILE)
            logger.info(f"Credentials kopiert nach: {GMAIL_CREDENTIALS_FILE}")

        # Token erstellen/laden
        creds = None

        if GMAIL_TOKEN_FILE.exists():
            try:
                creds = Credentials.from_authorized_user_file(str(GMAIL_TOKEN_FILE), GMAIL_SCOPES)
            except Exception as e:
                logger.warning(f"Token ungueltig: {e}")

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except RefreshError:
                    creds = None

            if not creds:
                try:
                    flow = InstalledAppFlow.from_client_secrets_file(
                        str(GMAIL_CREDENTIALS_FILE), GMAIL_SCOPES
                    )
                    # Browser automatisch oeffnen fuer OAuth
                    import webbrowser
                    creds = flow.run_local_server(
                        port=8089,
                        open_browser=True,
                        authorization_prompt_message='Bitte im Browser autorisieren...',
                        success_message='Gmail API erfolgreich autorisiert! Sie koennen dieses Fenster schliessen.',
                        timeout_seconds=120
                    )
                except Exception as e:
                    logger.error(f"OAuth-Fehler: {e}")
                    return False, f"OAuth-Fehler: {e}"

            # Token speichern
            with open(GMAIL_TOKEN_FILE, 'w') as token:
                token.write(creds.to_json())
            logger.info("Gmail Token gespeichert")

        # Verbindung testen
        try:
            service = build('gmail', 'v1', credentials=creds)
            profile = service.users().getProfile(userId='me').execute()
            email = profile.get('emailAddress', '')
            logger.info(f"Gmail API verbunden: {email}")
            return True, email
        except Exception as e:
            return False, f"Gmail API Fehler: {e}"

    def upgrade_gmail_scopes(self) -> Tuple[bool, str]:
        """
        Erweitert Gmail API Scopes (loescht alten Token bei Bedarf).

        Prueft ob bestehender Token die benoetigten Scopes hat.
        Falls nicht: Token loeschen + neuen OAuth-Flow starten.

        Returns:
            Tuple[bool, str]: (Erfolg, Beschreibung)
        """
        if not GMAIL_API_AVAILABLE:
            return False, "Gmail API Bibliotheken nicht installiert"

        if GMAIL_TOKEN_FILE.exists():
            try:
                creds = Credentials.from_authorized_user_file(
                    str(GMAIL_TOKEN_FILE), GMAIL_SCOPES
                )
                if creds and creds.valid:
                    # Pruefen ob alle Scopes vorhanden
                    if creds.scopes and set(GMAIL_SCOPES).issubset(creds.scopes):
                        return True, "Gmail Scopes bereits aktuell (readonly + send)"
                    # Scopes unvollstaendig - Token loeschen
                    logger.info("Token hat unvollstaendige Scopes - loesche fuer Re-Auth")
            except Exception:
                pass

            # Token loeschen - erzwingt neuen OAuth-Flow
            GMAIL_TOKEN_FILE.unlink(missing_ok=True)
            logger.info("Alter Token geloescht - starte neuen OAuth-Flow mit erweiterten Scopes")

        return self.setup_gmail_api()

    def get_gmail_service(self):
        """Holt Gmail API Service-Objekt"""
        if not GMAIL_API_AVAILABLE:
            return None

        if not GMAIL_TOKEN_FILE.exists():
            return None

        try:
            creds = Credentials.from_authorized_user_file(str(GMAIL_TOKEN_FILE), GMAIL_SCOPES)

            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                with open(GMAIL_TOKEN_FILE, 'w') as token:
                    token.write(creds.to_json())

            return build('gmail', 'v1', credentials=creds)
        except Exception as e:
            logger.error(f"Gmail Service Fehler: {e}")
            return None

    def has_gmail_api_setup(self) -> bool:
        """Prueft ob Gmail API eingerichtet ist"""
        return GMAIL_TOKEN_FILE.exists() and GMAIL_CREDENTIALS_FILE.exists()

    # ========== IMAP HELPER ==========

    def get_imap_preset(self, email: str) -> Optional[Dict]:
        """Holt IMAP-Einstellungen fuer E-Mail-Domain"""
        domain = email.split('@')[-1].lower()
        return IMAP_PRESETS.get(domain)

    def test_imap_connection(self, email: str, password: str,
                              host: str, port: int = 993) -> Tuple[bool, str]:
        """Testet IMAP-Verbindung"""
        import imaplib

        try:
            mail = imaplib.IMAP4_SSL(host, port)
            mail.login(email, password)
            mail.logout()
            return True, "Verbindung erfolgreich"
        except imaplib.IMAP4.error as e:
            return False, f"Login fehlgeschlagen: {e}"
        except Exception as e:
            return False, f"Verbindungsfehler: {e}"

    # ========== INTERAKTIVE EINRICHTUNG ==========

    def interactive_add_account(self) -> Optional[int]:
        """Interaktive Konto-Einrichtung via CLI"""
        print("\n" + "=" * 50)
        print("BACH Financial Mail - Konto hinzufuegen")
        print("=" * 50)

        # E-Mail-Adresse
        email = input("\nE-Mail-Adresse: ").strip()
        if not email or '@' not in email:
            print("Ungueltige E-Mail-Adresse")
            return None

        # Pruefen ob bereits vorhanden
        existing = self.get_account_by_email(email)
        if existing:
            print(f"Konto existiert bereits (ID: {existing.id})")
            return existing.id

        # Domain erkennen
        domain = email.split('@')[-1].lower()
        is_gmail = domain in ['gmail.com', 'googlemail.com']

        # Name
        preset = self.get_imap_preset(email)
        default_name = preset['name'] if preset else domain.split('.')[0].title()
        name = input(f"Konto-Name [{default_name}]: ").strip() or default_name

        # Provider-Auswahl
        if is_gmail and GMAIL_API_AVAILABLE:
            print("\nGmail-Zugang:")
            print("  1. Gmail API (empfohlen, OAuth2)")
            print("  2. IMAP (App-Passwort erforderlich)")
            choice = input("Auswahl [1]: ").strip() or "1"
            use_gmail_api = choice == "1"
        else:
            use_gmail_api = False

        if use_gmail_api:
            # Gmail API Setup
            print("\nGmail API Einrichtung...")
            success, result = self.setup_gmail_api()

            if not success:
                print(f"Fehler: {result}")
                print("\nFallback auf IMAP...")
                use_gmail_api = False

            if success:
                # Konto speichern
                account = MailAccount(
                    name=name,
                    email=result,  # E-Mail aus API
                    provider="gmail_api",
                    use_oauth=True
                )
                account_id = self.add_account(account)
                print(f"\nGmail API Konto eingerichtet (ID: {account_id})")
                return account_id

        # IMAP Setup
        if preset:
            host = preset['host']
            port = preset['port']
            if preset.get('note'):
                print(f"\nHinweis: {preset['note']}")
        else:
            host = input("IMAP Server: ").strip()
            port = int(input("IMAP Port [993]: ").strip() or "993")

        # Passwort
        import getpass
        password = getpass.getpass("Passwort: ")

        # Verbindung testen
        print("\nTeste Verbindung...")
        success, msg = self.test_imap_connection(email, password, host, port)

        if not success:
            print(f"Fehler: {msg}")
            retry = input("Trotzdem speichern? [j/N]: ").strip().lower()
            if retry != 'j':
                return None

        # Konto speichern
        account = MailAccount(
            name=name,
            email=email,
            provider="imap",
            imap_host=host,
            imap_port=port,
            use_oauth=False
        )
        account_id = self.add_account(account)

        # Passwort speichern
        if self.set_password(email, password):
            print("Passwort sicher gespeichert")
        else:
            print("WARNUNG: Passwort konnte nicht gespeichert werden")

        print(f"\nKonto eingerichtet (ID: {account_id})")
        return account_id


# ============ CLI ============

def main():
    """CLI-Einstiegspunkt"""
    import argparse

    parser = argparse.ArgumentParser(description="BACH Mail Account Manager")
    subparsers = parser.add_subparsers(dest='command', help='Befehle')

    # list
    subparsers.add_parser('list', help='Konten auflisten')

    # add
    add_parser = subparsers.add_parser('add', help='Konto hinzufuegen')
    add_parser.add_argument('--email', help='E-Mail-Adresse')
    add_parser.add_argument('--password', help='Passwort')
    add_parser.add_argument('--host', help='IMAP Host')
    add_parser.add_argument('--port', type=int, default=993, help='IMAP Port')
    add_parser.add_argument('--name', help='Konto-Name')
    add_parser.add_argument('--gmail-api', action='store_true', help='Gmail API verwenden')

    # delete
    del_parser = subparsers.add_parser('delete', help='Konto loeschen')
    del_parser.add_argument('id', type=int, help='Konto-ID')

    # toggle
    toggle_parser = subparsers.add_parser('toggle', help='Konto aktivieren/deaktivieren')
    toggle_parser.add_argument('id', type=int, help='Konto-ID')

    # test
    test_parser = subparsers.add_parser('test', help='Verbindung testen')
    test_parser.add_argument('id', type=int, help='Konto-ID')

    # setup-gmail
    gmail_parser = subparsers.add_parser('setup-gmail', help='Gmail API einrichten')
    gmail_parser.add_argument('--credentials', help='Pfad zu credentials.json')

    # find-credentials
    subparsers.add_parser('find-credentials', help='Nach Gmail credentials.json suchen')

    # interactive
    subparsers.add_parser('interactive', help='Interaktive Konto-Einrichtung')

    args = parser.parse_args()

    manager = AccountManager()

    if args.command == 'list' or args.command is None:
        accounts = manager.list_accounts()
        if not accounts:
            print("Keine Konten konfiguriert")
            print("\nKonto hinzufuegen:")
            print("  python account_manager.py interactive")
            return

        print("\n=== E-Mail Konten ===\n")
        for acc in accounts:
            status = "aktiv" if acc.is_active else "inaktiv"
            has_pw = "Passwort" if manager.has_password(acc.email) else "kein PW"
            print(f"[{acc.id}] {acc.name}")
            print(f"    E-Mail:   {acc.email}")
            print(f"    Provider: {acc.provider}")
            if acc.provider == 'imap':
                print(f"    IMAP:     {acc.imap_host}:{acc.imap_port}")
            print(f"    Status:   {status}, {has_pw}")
            if acc.last_sync:
                print(f"    Letzer Sync: {acc.last_sync}")
            print()

    elif args.command == 'add':
        if not args.email:
            # Interaktiv
            manager.interactive_add_account()
        else:
            preset = manager.get_imap_preset(args.email)
            host = args.host or (preset['host'] if preset else '')
            port = args.port or (preset['port'] if preset else 993)
            name = args.name or args.email.split('@')[0]

            if args.gmail_api:
                success, result = manager.setup_gmail_api()
                if success:
                    account = MailAccount(
                        name=name,
                        email=result,
                        provider="gmail_api",
                        use_oauth=True
                    )
                    aid = manager.add_account(account)
                    print(f"Gmail API Konto erstellt: ID {aid}")
                else:
                    print(f"Fehler: {result}")
            else:
                if not host:
                    print("IMAP Host erforderlich (--host)")
                    return

                account = MailAccount(
                    name=name,
                    email=args.email,
                    provider="imap",
                    imap_host=host,
                    imap_port=port
                )
                aid = manager.add_account(account)

                if args.password:
                    manager.set_password(args.email, args.password)

                print(f"Konto erstellt: ID {aid}")

    elif args.command == 'delete':
        if manager.delete_account(args.id):
            print(f"Konto {args.id} geloescht")
        else:
            print("Konto nicht gefunden")

    elif args.command == 'toggle':
        if manager.toggle_account(args.id):
            acc = manager.get_account(args.id)
            status = "aktiviert" if acc.is_active else "deaktiviert"
            print(f"Konto {args.id} {status}")
        else:
            print("Konto nicht gefunden")

    elif args.command == 'test':
        acc = manager.get_account(args.id)
        if not acc:
            print("Konto nicht gefunden")
            return

        print(f"Teste Verbindung: {acc.email}")

        if acc.provider == 'gmail_api':
            service = manager.get_gmail_service()
            if service:
                try:
                    profile = service.users().getProfile(userId='me').execute()
                    print(f"Gmail API OK: {profile.get('emailAddress')}")
                except Exception as e:
                    print(f"Fehler: {e}")
            else:
                print("Gmail API nicht eingerichtet")
        else:
            password = manager.get_password(acc.email)
            if not password:
                print("Kein Passwort gespeichert")
                return

            success, msg = manager.test_imap_connection(
                acc.email, password, acc.imap_host, acc.imap_port
            )
            print(msg)

    elif args.command == 'setup-gmail':
        creds_path = Path(args.credentials) if args.credentials else None
        success, result = manager.setup_gmail_api(creds_path)
        if success:
            print(f"Gmail API eingerichtet: {result}")
        else:
            print(f"Fehler: {result}")

    elif args.command == 'find-credentials':
        found = manager.find_gmail_credentials()
        if found:
            print("Gefundene credentials.json Dateien:\n")
            for p in found:
                print(f"  {p}")
        else:
            print("Keine credentials.json gefunden")
            print("\nBitte erstellen Sie OAuth-Credentials:")
            print("  https:/console.cloud.google.com/apis/credentials")

    elif args.command == 'interactive':
        manager.interactive_add_account()


if __name__ == "__main__":
    main()
