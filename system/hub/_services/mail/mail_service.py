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
BACH Financial Mail Service v1.1
================================
Sammelt und extrahiert Finanzdaten aus E-Mails.

Features:
- IMAP-basierter E-Mail-Abruf
- Gmail API mit OAuth2 Support
- Pattern-Matching fuer Anbieter-Erkennung
- PDF-Anhang-Extraktion
- Automatische Steuer-Kategorisierung
- N8N JSON Export
- Daemon-Integration

Autor: BACH System
Datum: 2026-01-20
"""

import json
import sqlite3
import imaplib
import email
import email.header
import base64
import hashlib
import re
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from typing import List, Optional, Dict, Tuple
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
CONFIG_FILE = SERVICE_DIR / "config.json"
PROVIDERS_FILE = SERVICE_DIR / "providers.json"
SCHEMA_FILE = SERVICE_DIR / "schema_financial.sql"

# Attachment-Speicherort
ATTACHMENTS_DIR = DATA_DIR / "mail_attachments"
ATTACHMENTS_DIR.mkdir(parents=True, exist_ok=True)

# Logging
LOG_FILE = BACH_DIR / "data" / "logs" / "mail_service.log"
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

# Keyring fuer sichere Passwoerter
try:
    import keyring
    KEYRING_AVAILABLE = True
except ImportError:
    KEYRING_AVAILABLE = False

# Gmail API
try:
    from googleapiclient.discovery import build
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    GMAIL_API_AVAILABLE = True
except ImportError:
    GMAIL_API_AVAILABLE = False

# Account Manager Import
try:
    from account_manager import AccountManager
    ACCOUNT_MANAGER_AVAILABLE = True
except ImportError:
    ACCOUNT_MANAGER_AVAILABLE = False


# ============ DATENMODELLE ============

@dataclass
class MailAccount:
    """E-Mail Konto Konfiguration"""
    id: int
    name: str
    email: str
    provider: str
    imap_host: str = ""
    imap_port: int = 993
    use_oauth: bool = False
    is_active: bool = True


@dataclass
class Provider:
    """Anbieter-Definition"""
    id: str
    name: str
    category: str
    type: str
    sender_patterns: List[str]
    subject_patterns: List[str]
    extract_fields: List[str]
    steuer_relevant: bool = False
    steuer_typ: Optional[str] = None
    recurring: bool = False
    interval: Optional[str] = None
    hinweis: Optional[str] = None
    # Neue Filter (wie UniversalInvoiceMail)
    blacklist: List[str] = None  # Darf NICHT im Betreff/Body vorkommen
    body_must_contain: List[str] = None  # Body MUSS mindestens eines enthalten
    body_must_not_contain: List[str] = None  # Body darf keines enthalten

    def __post_init__(self):
        if self.blacklist is None:
            self.blacklist = []
        if self.body_must_contain is None:
            self.body_must_contain = []
        if self.body_must_not_contain is None:
            self.body_must_not_contain = []


@dataclass
class FinancialEmail:
    """Erkannte Finanz-E-Mail"""
    message_id: str
    provider_id: str
    provider_name: str
    category: str
    sender: str
    subject: str
    email_date: str
    document_type: str
    steuer_relevant: bool
    steuer_typ: Optional[str]
    has_attachment: bool
    attachment_path: Optional[str]
    extracted_data: Dict
    betrag: Optional[float] = None
    rechnungsnummer: Optional[str] = None


# ============ HILFSFUNKTIONEN ============

def decode_header(header_val) -> str:
    """Dekodiert MIME-encodierte Mail-Header"""
    if not header_val:
        return ""
    try:
        decoded_list = email.header.decode_header(header_val)
        result = ""
        for text, encoding in decoded_list:
            if isinstance(text, bytes):
                result += text.decode(encoding or 'utf-8', errors='ignore')
            else:
                result += str(text)
        return result.strip()
    except Exception:
        return str(header_val)


def sanitize_filename(name: str) -> str:
    """Entfernt ungueltige Zeichen aus Dateinamen"""
    if not name:
        return "unnamed"
    s = re.sub(r'[<>:"/\|?*\x00-\x1f]', '_', name)
    s = re.sub(r'\s+', '_', s)
    s = re.sub(r'_+', '_', s)
    return s.strip('_')[:100]


def extract_amount(text: str) -> Optional[float]:
    """Extrahiert Geldbetrag aus Text"""
    patterns = [
        r'(\d{1,3}(?:\.\d{3})*,\d{2})\s*(?:EUR|€)',  # 1.234,56 EUR
        r'€\s*(\d{1,3}(?:\.\d{3})*,\d{2})',           # € 1.234,56
        r'(\d+,\d{2})\s*(?:EUR|€)',                    # 123,45 EUR
        r'Gesamt[:\s]+(\d+,\d{2})',                    # Gesamt: 123,45
        r'Betrag[:\s]+(\d+,\d{2})',                    # Betrag: 123,45
        r'Summe[:\s]+(\d+,\d{2})',                     # Summe: 123,45
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            amount_str = match.group(1)
            # Deutsche Formatierung -> Float
            amount_str = amount_str.replace('.', '').replace(',', '.')
            try:
                return float(amount_str)
            except ValueError:
                continue
    return None


def extract_invoice_number(text: str) -> Optional[str]:
    """Extrahiert Rechnungsnummer aus Text"""
    patterns = [
        r'Rechnungs?(?:nummer|nr\.?)[\s:]+([A-Z0-9\-]+)',
        r'Invoice\s*(?:No\.?|Number)[\s:]+([A-Z0-9\-]+)',
        r'Beleg(?:nummer)?[\s:]+([A-Z0-9\-]+)',
        r'Nr\.[\s:]+([A-Z0-9\-]{5,})',
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


# ============ PROVIDER MATCHING ============

class ProviderMatcher:
    """Matched E-Mails gegen bekannte Anbieter"""

    def __init__(self):
        self.providers: List[Provider] = []
        self._load_providers()

    def _load_providers(self):
        """Laedt Provider aus JSON"""
        if not PROVIDERS_FILE.exists():
            logger.warning(f"providers.json nicht gefunden: {PROVIDERS_FILE}")
            return

        try:
            data = json.loads(PROVIDERS_FILE.read_text(encoding='utf-8'))
            for p in data.get('providers', []):
                # Blacklist kann als String (kommasepariert) oder Liste kommen
                blacklist_raw = p.get('blacklist', [])
                if isinstance(blacklist_raw, str):
                    blacklist = [b.strip() for b in blacklist_raw.split(',') if b.strip()]
                else:
                    blacklist = blacklist_raw or []

                body_must_raw = p.get('body_must_contain', [])
                if isinstance(body_must_raw, str):
                    body_must = [b.strip() for b in body_must_raw.split(',') if b.strip()]
                else:
                    body_must = body_must_raw or []

                body_must_not_raw = p.get('body_must_not_contain', [])
                if isinstance(body_must_not_raw, str):
                    body_must_not = [b.strip() for b in body_must_not_raw.split(',') if b.strip()]
                else:
                    body_must_not = body_must_not_raw or []

                self.providers.append(Provider(
                    id=p.get('id', ''),
                    name=p.get('name', ''),
                    category=p.get('category', 'sonstiges'),
                    type=p.get('type', 'rechnung'),
                    sender_patterns=p.get('sender_patterns', []),
                    subject_patterns=p.get('subject_patterns', []),
                    extract_fields=p.get('extract_fields', []),
                    steuer_relevant=p.get('steuer_relevant', False),
                    steuer_typ=p.get('steuer_typ'),
                    recurring=p.get('recurring', False),
                    interval=p.get('interval'),
                    hinweis=p.get('hinweis'),
                    blacklist=blacklist,
                    body_must_contain=body_must,
                    body_must_not_contain=body_must_not
                ))
            logger.info(f"{len(self.providers)} Provider geladen")
        except Exception as e:
            logger.error(f"Fehler beim Laden der Provider: {e}")

    def match(self, sender: str, subject: str, body: str = "") -> Optional[Provider]:
        """
        Findet passenden Provider fuer E-Mail.

        Matching-Logik (wie UniversalInvoiceMail):
        - Sender-Match alleine reicht aus (z.B. "amazon" im Absender)
        - ODER Subject-Match alleine reicht aus (z.B. "Rechnung" im Betreff)
        - Score-basiert: Bester Match gewinnt
        - Blacklist-Filter: Betreff/Body darf bestimmte Woerter NICHT enthalten
        - Body-Filter: Body MUSS / darf NICHT bestimmte Woerter enthalten

        Args:
            sender: Absender-Adresse (z.B. "Amazon <noreply@amazon.de>")
            subject: Betreff der E-Mail
            body: Optional - E-Mail Body fuer erweitertes Matching und Filter
        """
        sender_lower = sender.lower()
        subject_lower = subject.lower()
        body_lower = body.lower() if body else ""

        # === Erste Runde: Spezifische Provider (Score-basiert) ===
        best_match = None
        best_score = 0

        for provider in self.providers:
            # Catch-All Provider ueberspringen
            if '*' in provider.sender_patterns:
                continue

            score = 0

            # Sender-Match (im From-Header) - STARK
            sender_matched_patterns = [
                p for p in provider.sender_patterns
                if p.lower() in sender_lower
            ]
            if sender_matched_patterns:
                score += 10  # Sender-Match ist starker Indikator
                logger.debug(f"  Sender-Match: {provider.name} ({sender_matched_patterns})")

            # Subject-Match - MITTEL
            subject_matched_patterns = [
                p for p in provider.subject_patterns
                if p.lower() in subject_lower
            ]
            if subject_matched_patterns:
                score += 5  # Subject-Match
                logger.debug(f"  Subject-Match: {provider.name} ({subject_matched_patterns})")

            # Body-Match (falls vorhanden) - SCHWACH
            if body_lower:
                body_sender_match = any(
                    p.lower() in body_lower
                    for p in provider.sender_patterns
                )
                if body_sender_match:
                    score += 2

            # Match gefunden wenn Score >= 5
            # Das bedeutet: Sender-Match ODER Subject-Match reicht aus!
            if score >= 5 and score > best_score:
                best_score = score
                best_match = provider

        if best_match:
            # === Blacklist & Body-Filter pruefen (wie UniversalInvoiceMail) ===
            if not self._passes_filters(best_match, subject_lower, body_lower):
                logger.info(f"Provider {best_match.name} gefiltert (Blacklist/Body-Filter)")
                # Versuche naechstbesten Provider
                best_match = None
                best_score = 0
                for provider in self.providers:
                    if '*' in provider.sender_patterns:
                        continue
                    # Pruefe nur Provider mit niedrigerem Score...
                    # Vereinfacht: Kein Match bei Blacklist-Treffer
                    pass

        if best_match:
            logger.info(f"Provider-Match: {best_match.name} (Score: {best_score}) - {subject[:60]}")
            return best_match

        # === Zweite Runde: Catch-All Provider ===
        for provider in self.providers:
            if '*' not in provider.sender_patterns:
                continue

            # Bei Catch-All reicht Subject-Match
            subject_match = any(
                p.lower() in subject_lower
                for p in provider.subject_patterns
            )
            if subject_match:
                # Auch Catch-All muss Blacklist-Filter passieren
                if self._passes_filters(provider, subject_lower, body_lower):
                    logger.info(f"Catch-All Match: {provider.name} - {subject[:60]}")
                    return provider

        # Kein Match
        logger.debug(f"Kein Match fuer: {sender[:30]} | {subject[:50]}")
        return None

    def _passes_filters(self, provider: Provider, subject_lower: str, body_lower: str) -> bool:
        """
        Prueft Blacklist und Body-Filter (wie UniversalInvoiceMail).

        Returns:
            True wenn E-Mail alle Filter passiert, False wenn blockiert
        """
        # === Blacklist pruefen (Betreff + Body) ===
        if provider.blacklist:
            for term in provider.blacklist:
                term_lower = term.lower()
                if term_lower in subject_lower or term_lower in body_lower:
                    logger.debug(f"  Blacklist-Treffer: '{term}' in {provider.name}")
                    return False

        # === Body MUSS mindestens einen Begriff enthalten ===
        if provider.body_must_contain and body_lower:
            found_any = any(
                term.lower() in body_lower
                for term in provider.body_must_contain
            )
            if not found_any:
                logger.debug(f"  body_must_contain nicht erfuellt fuer {provider.name}")
                return False

        # === Body darf KEINE dieser Begriffe enthalten ===
        if provider.body_must_not_contain and body_lower:
            for term in provider.body_must_not_contain:
                if term.lower() in body_lower:
                    logger.debug(f"  body_must_not_contain Treffer: '{term}' in {provider.name}")
                    return False

        return True


# ============ MAIL SERVICE ============

class FinancialMailService:
    """Hauptklasse fuer E-Mail-Verarbeitung"""

    def __init__(self):
        self.config = self._load_config()
        self.matcher = ProviderMatcher()
        self._init_database()

    def _load_config(self) -> dict:
        """Laedt Service-Konfiguration"""
        if CONFIG_FILE.exists():
            return json.loads(CONFIG_FILE.read_text(encoding='utf-8'))
        return {
            "enabled": True,
            "max_emails_per_run": 50,
            "date_range_days": 90,
            "auto_extract": True,
            "export_n8n": True
        }

    def _init_database(self):
        """Initialisiert Datenbank-Tabellen"""
        if not SCHEMA_FILE.exists():
            logger.error("Schema-Datei nicht gefunden")
            return

        try:
            conn = sqlite3.connect(USER_DB)
            schema = SCHEMA_FILE.read_text(encoding='utf-8')
            conn.executescript(schema)
            conn.commit()
            conn.close()
            logger.info("Datenbank initialisiert")
        except Exception as e:
            logger.error(f"Datenbank-Fehler: {e}")

    def get_password(self, account: MailAccount) -> Optional[str]:
        """Holt Passwort aus Keyring (nutzt Account Manager)"""
        if ACCOUNT_MANAGER_AVAILABLE:
            mgr = AccountManager()
            return mgr.get_password(account.email)

        if not KEYRING_AVAILABLE:
            logger.warning("Keyring nicht verfuegbar")
            return None

        try:
            return keyring.get_password("bach_financial_mail", account.email)
        except Exception as e:
            logger.error(f"Keyring-Fehler: {e}")
            return None

    def set_password(self, email: str, password: str) -> bool:
        """Speichert Passwort in Keyring"""
        if ACCOUNT_MANAGER_AVAILABLE:
            mgr = AccountManager()
            return mgr.set_password(email, password)

        if not KEYRING_AVAILABLE:
            return False

        try:
            keyring.set_password("bach_financial_mail", email, password)
            return True
        except Exception as e:
            logger.error(f"Keyring-Fehler: {e}")
            return False

    def connect_imap(self, account: MailAccount) -> Optional[imaplib.IMAP4_SSL]:
        """Verbindet zu IMAP-Server"""
        password = self.get_password(account)
        if not password:
            logger.error(f"Kein Passwort fuer {account.email}")
            return None

        try:
            mail = imaplib.IMAP4_SSL(account.imap_host, account.imap_port)
            mail.login(account.email, password)
            logger.info(f"Verbunden mit {account.email}")
            return mail
        except Exception as e:
            logger.error(f"IMAP-Verbindungsfehler: {e}")
            return None

    def get_gmail_service(self, account: MailAccount):
        """Holt Gmail API Service fuer ein Konto"""
        if not GMAIL_API_AVAILABLE:
            return None

        if ACCOUNT_MANAGER_AVAILABLE:
            mgr = AccountManager()
            return mgr.get_gmail_service()

        return None

    def _build_gmail_query(self, days: int) -> str:
        """
        Baut einen optimierten Gmail-Query fuer serverseitiges Filtering.

        Basiert auf UniversalInvoiceMail-Logik:
        - Sender ODER Subject reichen aus
        - Mehrere Keywords werden mit ODER verknuepft
        - Filterung geschieht bei Gmail, nicht im Client
        """
        after_date = (datetime.now() - timedelta(days=days)).strftime("%Y/%m/%d")

        # Sammle alle Sender-Patterns aus allen Providern
        sender_keywords = set()
        for provider in self.matcher.providers:
            if '*' not in provider.sender_patterns:
                for pattern in provider.sender_patterns:
                    # Nur relevante Keywords (keine zu kurzen)
                    if len(pattern) >= 3:
                        sender_keywords.add(pattern.lower())

        # Sammle alle Subject-Patterns (fuer Catch-All und spezifische)
        subject_keywords = set()
        for provider in self.matcher.providers:
            for pattern in provider.subject_patterns:
                if len(pattern) >= 3:
                    subject_keywords.add(pattern)

        # Begrenze auf die wichtigsten Keywords (Gmail hat Query-Limits)
        # Priorisiere die haeufigsten/wichtigsten
        priority_senders = [
            'amazon', 'paypal', 'ebay', 'otto', 'zalando', 'mediamarkt', 'saturn',
            'telekom', 'vodafone', 'o2', 'check24', 'allianz', 'huk', 'netflix',
            'spotify', 'apple', 'google', 'microsoft', 'adobe', 'temu', 'ikea',
            'n26', 'klarna', 'strato', 'ionos', 'hetzner', 'vattenfall', 'eon'
        ]
        priority_subjects = [
            'Rechnung', 'Invoice', 'Bestellung', 'Order', 'Quittung', 'Receipt',
            'Zahlung', 'Payment', 'Versicherung', 'Police', 'Beitrag', 'Abo',
            'Abonnement', 'Subscription', 'Kontoauszug', 'Statement'
        ]

        # Kombiniere: Prioritaets-Keywords + zusaetzliche aus Providern
        final_senders = []
        for s in priority_senders:
            if s in sender_keywords or any(s in kw for kw in sender_keywords):
                final_senders.append(s)
        # Auf 20 begrenzen
        final_senders = final_senders[:20]

        final_subjects = priority_subjects[:15]

        # Query bauen - ODER-Verknuepfung innerhalb der Gruppen
        query_parts = []

        # Datumsfilter
        query_parts.append(f"after:{after_date}")

        # Sender ODER Subject (nicht UND!)
        # Format: (from:amazon OR from:paypal OR ... OR subject:Rechnung OR subject:Invoice OR ...)
        search_terms = []

        for sender in final_senders:
            search_terms.append(f"from:{sender}")

        for subj in final_subjects:
            search_terms.append(f'subject:"{subj}"')

        if search_terms:
            # Alles mit ODER verknuepfen
            query_parts.append(f"({' OR '.join(search_terms)})")

        query = " ".join(query_parts)
        return query

    def fetch_emails_gmail_api(self, account: MailAccount, days: int = 90) -> List[FinancialEmail]:
        """
        Ruft E-Mails via Gmail API ab mit SERVERSEITIGEM Filtering.

        Verwendet Gmail-Query-Syntax fuer effiziente Suche:
        - from:amazon OR from:paypal OR subject:Rechnung OR ...
        - Viel weniger API-Aufrufe als nachtraegliches Filtern
        """
        service = self.get_gmail_service(account)
        if not service:
            logger.error("Gmail API Service nicht verfuegbar")
            return []

        results = []
        max_emails = self.config.get('max_emails_per_run', 50)

        try:
            # Optimierter Query mit serverseitigem Filter
            query = self._build_gmail_query(days)
            logger.info(f"Gmail-Query: {query[:200]}...")

            all_messages = []
            page_token = None

            # Pagination - bis zu 500 Mails abrufen (bereits gefiltert!)
            fetch_limit = min(max_emails * 2, 500)

            while len(all_messages) < fetch_limit:
                response = service.users().messages().list(
                    userId='me',
                    q=query,
                    maxResults=min(100, fetch_limit - len(all_messages)),
                    pageToken=page_token
                ).execute()

                messages = response.get('messages', [])
                all_messages.extend(messages)

                page_token = response.get('nextPageToken')
                if not page_token:
                    break

            logger.info(f"Gmail API: {len(all_messages)} E-Mails gefunden (nach Server-Filter)")

            # Verarbeite alle Nachrichten
            processed = 0
            matched = 0

            for msg_info in all_messages:
                try:
                    result = self._process_gmail_message(service, msg_info['id'], account)
                    processed += 1
                    if result:
                        results.append(result)
                        matched += 1

                        # Limit erreicht?
                        if matched >= max_emails:
                            logger.info(f"Limit erreicht: {max_emails} Matches")
                            break
                except Exception as e:
                    logger.error(f"Gmail Fehler bei {msg_info['id']}: {e}")

            logger.info(f"Gmail Sync: {processed} verarbeitet, {matched} gematched")

        except Exception as e:
            logger.error(f"Gmail API Fehler: {e}")
            import traceback
            traceback.print_exc()

        return results

    def _process_gmail_message(self, service, msg_id: str, account: MailAccount) -> Optional[FinancialEmail]:
        """Verarbeitet einzelne Gmail-Nachricht mit Blacklist/Body-Filter Support"""
        msg = service.users().messages().get(
            userId='me',
            id=msg_id,
            format='full'
        ).execute()

        headers = {h['name'].lower(): h['value'] for h in msg['payload']['headers']}

        sender = headers.get('from', '')
        subject = headers.get('subject', '')
        date_str = headers.get('date', '')
        message_id = headers.get('message-id', msg_id)

        # Datum parsen (vor Body-Extraktion fuer Anhang-Pfad)
        email_date = datetime.now()
        try:
            internal_date = int(msg.get('internalDate', 0)) / 1000
            email_date = datetime.fromtimestamp(internal_date)
        except (ValueError, TypeError, OSError):
            pass

        # Body ZUERST extrahieren (fuer Blacklist-Pruefung!)
        body_text = ""
        has_attachment = False
        attachment_data = []  # Speichere Anhang-Info, schreibe spaeter

        def extract_body_and_check_attachments(payload):
            nonlocal body_text, has_attachment, attachment_data

            if 'parts' in payload:
                for part in payload['parts']:
                    extract_body_and_check_attachments(part)
            else:
                mime_type = payload.get('mimeType', '')
                body = payload.get('body', {})

                if mime_type == 'text/plain' and body.get('data'):
                    try:
                        body_text += base64.urlsafe_b64decode(body['data']).decode('utf-8', errors='ignore')
                    except (ValueError, UnicodeDecodeError):
                        pass

                elif mime_type == 'application/pdf':
                    has_attachment = True
                    filename = payload.get('filename', 'attachment.pdf')
                    attachment_id = body.get('attachmentId')
                    if attachment_id:
                        attachment_data.append({'id': attachment_id, 'filename': filename})

        extract_body_and_check_attachments(msg['payload'])

        # === Provider-Match MIT Body fuer Blacklist-Pruefung ===
        provider = self.matcher.match(sender, subject, body_text)
        if not provider:
            return None

        logger.info(f"Gmail Match: {provider.name} - {subject[:50]}")

        # Jetzt Anhaenge herunterladen (nur wenn Match erfolgreich)
        attachment_path = None
        for att_info in attachment_data:
            try:
                att = service.users().messages().attachments().get(
                    userId='me',
                    messageId=msg_id,
                    id=att_info['id']
                ).execute()

                data = base64.urlsafe_b64decode(att['data'])
                safe_name = sanitize_filename(att_info['filename'])
                attachment_path = ATTACHMENTS_DIR / f"{provider.id}_{email_date.strftime('%Y%m%d')}_{safe_name}"

                with open(attachment_path, 'wb') as f:
                    f.write(data)
                logger.info(f"Gmail Anhang: {attachment_path}")
            except Exception as e:
                logger.error(f"Anhang-Fehler: {e}")

        # Daten extrahieren
        extracted = {
            "provider": provider.name,
            "category": provider.category,
            "type": provider.type
        }

        betrag = extract_amount(body_text) if body_text else None
        rechnungsnummer = extract_invoice_number(body_text) if body_text else None

        if betrag:
            extracted["betrag"] = betrag
        if rechnungsnummer:
            extracted["rechnungsnummer"] = rechnungsnummer

        return FinancialEmail(
            message_id=message_id,
            provider_id=provider.id,
            provider_name=provider.name,
            category=provider.category,
            sender=sender,
            subject=subject,
            email_date=email_date.isoformat(),
            document_type=provider.type,
            steuer_relevant=provider.steuer_relevant,
            steuer_typ=provider.steuer_typ,
            has_attachment=has_attachment,
            attachment_path=str(attachment_path) if attachment_path else None,
            extracted_data=extracted,
            betrag=betrag,
            rechnungsnummer=rechnungsnummer
        )

    def fetch_emails(self, account: MailAccount, days: int = 90) -> List[FinancialEmail]:
        """Ruft E-Mails ab - automatisch IMAP oder Gmail API"""
        # Gmail API bevorzugen wenn verfuegbar
        if account.provider == 'gmail_api' and account.use_oauth:
            return self.fetch_emails_gmail_api(account, days)

        # Fallback auf IMAP
        mail = self.connect_imap(account)
        if not mail:
            return []

        results = []
        since_date = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")

        try:
            mail.select("INBOX")

            # Suche nach E-Mails seit Datum
            _, message_ids = mail.search(None, f'(SINCE "{since_date}")')

            if not message_ids[0]:
                logger.info("Keine neuen E-Mails gefunden")
                return []

            ids = message_ids[0].split()
            logger.info(f"{len(ids)} E-Mails gefunden")

            # Limit anwenden
            max_emails = self.config.get('max_emails_per_run', 50)
            ids = ids[-max_emails:]  # Neueste zuerst

            for email_id in ids:
                try:
                    result = self._process_email(mail, email_id, account)
                    if result:
                        results.append(result)
                except Exception as e:
                    logger.error(f"Fehler bei E-Mail {email_id}: {e}")

            mail.logout()

        except Exception as e:
            logger.error(f"IMAP-Fehler: {e}")

        return results

    def _process_email(self, mail, email_id, account: MailAccount) -> Optional[FinancialEmail]:
        """Verarbeitet einzelne E-Mail mit Blacklist/Body-Filter Support"""
        _, msg_data = mail.fetch(email_id, "(RFC822)")
        raw_email = msg_data[0][1]
        msg = email.message_from_bytes(raw_email)

        # Header dekodieren
        sender = decode_header(msg.get("From", ""))
        subject = decode_header(msg.get("Subject", ""))
        message_id = msg.get("Message-ID", "")
        date_str = msg.get("Date", "")

        # Datum parsen
        email_date = None
        try:
            from email.utils import parsedate_to_datetime
            email_date = parsedate_to_datetime(date_str)
        except (ValueError, TypeError):
            email_date = datetime.now()

        # Body ZUERST extrahieren (fuer Blacklist-Pruefung!)
        body_text = ""
        has_attachment = False
        attachment_parts = []  # Speichere Anhang-Parts, schreibe spaeter

        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition", ""))

            # PDF-Anhang merken (noch nicht speichern)
            if "attachment" in content_disposition and content_type == "application/pdf":
                has_attachment = True
                filename = part.get_filename()
                if filename:
                    attachment_parts.append({
                        'filename': decode_header(filename),
                        'payload': part.get_payload(decode=True)
                    })

            # Text-Body
            elif content_type == "text/plain":
                try:
                    payload = part.get_payload(decode=True)
                    if payload:
                        body_text += payload.decode('utf-8', errors='ignore')
                except (ValueError, UnicodeDecodeError):
                    pass

        # === Provider-Match MIT Body fuer Blacklist-Pruefung ===
        provider = self.matcher.match(sender, subject, body_text)
        if not provider:
            return None

        logger.info(f"Match: {provider.name} - {subject[:50]}")

        # Jetzt Anhaenge speichern (nur wenn Match erfolgreich)
        attachment_path = None
        for att_info in attachment_parts:
            safe_name = sanitize_filename(att_info['filename'])
            attachment_path = ATTACHMENTS_DIR / f"{provider.id}_{email_date.strftime('%Y%m%d')}_{safe_name}"

            with open(attachment_path, 'wb') as f:
                f.write(att_info['payload'])
            logger.info(f"Anhang gespeichert: {attachment_path}")

        # Daten extrahieren
        extracted = {
            "provider": provider.name,
            "category": provider.category,
            "type": provider.type
        }

        betrag = extract_amount(body_text) if body_text else None
        rechnungsnummer = extract_invoice_number(body_text) if body_text else None

        if betrag:
            extracted["betrag"] = betrag
        if rechnungsnummer:
            extracted["rechnungsnummer"] = rechnungsnummer

        return FinancialEmail(
            message_id=message_id,
            provider_id=provider.id,
            provider_name=provider.name,
            category=provider.category,
            sender=sender,
            subject=subject,
            email_date=email_date.isoformat() if email_date else None,
            document_type=provider.type,
            steuer_relevant=provider.steuer_relevant,
            steuer_typ=provider.steuer_typ,
            has_attachment=has_attachment,
            attachment_path=str(attachment_path) if attachment_path else None,
            extracted_data=extracted,
            betrag=betrag,
            rechnungsnummer=rechnungsnummer
        )

    def save_to_database(self, emails: List[FinancialEmail], account_id: int):
        """Speichert erkannte E-Mails in Datenbank"""
        conn = sqlite3.connect(USER_DB)
        cursor = conn.cursor()

        saved = 0
        for fe in emails:
            try:
                cursor.execute("""
                    INSERT OR IGNORE INTO financial_emails (
                        account_id, message_id, provider_id, provider_name,
                        category, sender, subject, email_date, document_type,
                        steuer_relevant, steuer_typ, has_attachment,
                        attachment_path, extracted_data, betrag, rechnungsnummer
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    account_id,
                    fe.message_id,
                    fe.provider_id,
                    fe.provider_name,
                    fe.category,
                    fe.sender,
                    fe.subject,
                    fe.email_date,
                    fe.document_type,
                    1 if fe.steuer_relevant else 0,
                    fe.steuer_typ,
                    1 if fe.has_attachment else 0,
                    fe.attachment_path,
                    json.dumps(fe.extracted_data, ensure_ascii=False),
                    fe.betrag,
                    fe.rechnungsnummer
                ))
                if cursor.rowcount > 0:
                    saved += 1
            except Exception as e:
                logger.error(f"DB-Fehler: {e}")

        conn.commit()
        conn.close()
        logger.info(f"{saved} E-Mails gespeichert")
        return saved

    def export_n8n_json(self, output_path: Optional[Path] = None) -> Path:
        """Exportiert Finanzdaten als JSON fuer n8n"""
        if output_path is None:
            output_path = DATA_DIR / "financial_data.json"

        conn = sqlite3.connect(USER_DB)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Alle neuen/verarbeiteten E-Mails
        cursor.execute("""
            SELECT * FROM financial_emails
            WHERE status IN ('neu', 'verarbeitet')
            ORDER BY email_date DESC
        """)

        emails = [dict(row) for row in cursor.fetchall()]

        # Aktive Abos
        cursor.execute("""
            SELECT * FROM financial_subscriptions
            WHERE aktiv = 1
              AND id IN (
                  SELECT MIN(id) FROM financial_subscriptions GROUP BY provider_id
              )
        """)
        subscriptions = [dict(row) for row in cursor.fetchall()]

        # Zusammenfassung
        cursor.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN steuer_relevant = 1 THEN 1 ELSE 0 END) as steuer_count,
                SUM(COALESCE(betrag, 0)) as total_betrag,
                SUM(CASE WHEN steuer_relevant = 1 THEN COALESCE(betrag, 0) ELSE 0 END) as steuer_betrag
            FROM financial_emails
            WHERE status != 'ignoriert'
        """)
        summary = dict(cursor.fetchone())

        conn.close()

        export_data = {
            "_info": "BACH Financial Mail Export",
            "_version": "1.0",
            "_exported": datetime.now().isoformat(),
            "summary": summary,
            "emails": emails,
            "subscriptions": subscriptions
        }

        output_path.write_text(
            json.dumps(export_data, ensure_ascii=False, indent=2, default=str),
            encoding='utf-8'
        )

        logger.info(f"Export gespeichert: {output_path}")
        return output_path

    def get_accounts(self) -> List[MailAccount]:
        """Holt alle konfigurierten E-Mail-Konten"""
        conn = sqlite3.connect(USER_DB)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM mail_accounts WHERE is_active = 1")
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
                is_active=bool(row['is_active'])
            )
            for row in rows
        ]

    def add_account(self, name: str, email_addr: str, password: str,
                    provider: str = "imap", imap_host: str = "", imap_port: int = 993) -> int:
        """Fuegt neues E-Mail-Konto hinzu"""
        conn = sqlite3.connect(USER_DB)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO mail_accounts (name, email, provider, imap_host, imap_port)
            VALUES (?, ?, ?, ?, ?)
        """, (name, email_addr, provider, imap_host, imap_port))

        account_id = cursor.lastrowid
        conn.commit()
        conn.close()

        # Passwort speichern
        self.set_password(email_addr, password)

        logger.info(f"Konto hinzugefuegt: {email_addr}")
        return account_id

    def run_sync(self, account_id: Optional[int] = None) -> dict:
        """Fuehrt Synchronisierung durch"""
        accounts = self.get_accounts()

        if account_id:
            accounts = [a for a in accounts if a.id == account_id]

        if not accounts:
            return {"status": "error", "message": "Keine Konten konfiguriert"}

        total_processed = 0
        total_matched = 0

        for account in accounts:
            logger.info(f"Sync: {account.email}")

            # Sync-Run loggen
            conn = sqlite3.connect(USER_DB)
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO mail_sync_runs (account_id, status)
                VALUES (?, 'running')
            """, (account.id,))
            run_id = cursor.lastrowid
            conn.commit()
            conn.close()

            try:
                emails = self.fetch_emails(account, self.config.get('date_range_days', 90))
                saved = self.save_to_database(emails, account.id)

                total_processed += len(emails)
                total_matched += saved

                # Sync-Run aktualisieren
                conn = sqlite3.connect(USER_DB)
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE mail_sync_runs
                    SET finished_at = CURRENT_TIMESTAMP,
                        emails_processed = ?,
                        emails_matched = ?,
                        status = 'success'
                    WHERE id = ?
                """, (len(emails), saved, run_id))
                conn.commit()
                conn.close()

            except Exception as e:
                logger.error(f"Sync-Fehler: {e}")
                conn = sqlite3.connect(USER_DB)
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE mail_sync_runs
                    SET finished_at = CURRENT_TIMESTAMP,
                        errors = ?,
                        status = 'failed'
                    WHERE id = ?
                """, (str(e), run_id))
                conn.commit()
                conn.close()

        # N8N Export
        if self.config.get('export_n8n', True):
            self.export_n8n_json()

        return {
            "status": "success",
            "processed": total_processed,
            "matched": total_matched,
            "accounts": len(accounts)
        }


# ============ CLI ============

def main():
    """CLI-Einstiegspunkt"""
    import argparse

    parser = argparse.ArgumentParser(description="BACH Financial Mail Service")
    parser.add_argument('command', choices=['sync', 'export', 'add-account', 'list', 'status'],
                        help='Befehl')
    parser.add_argument('--account', type=int, help='Account-ID')
    parser.add_argument('--email', help='E-Mail Adresse (fuer add-account)')
    parser.add_argument('--password', help='Passwort (fuer add-account)')
    parser.add_argument('--host', help='IMAP Host (fuer add-account)')
    parser.add_argument('--output', help='Ausgabepfad (fuer export)')

    args = parser.parse_args()

    service = FinancialMailService()

    if args.command == 'sync':
        result = service.run_sync(args.account)
        print(json.dumps(result, indent=2))

    elif args.command == 'export':
        output = Path(args.output) if args.output else None
        path = service.export_n8n_json(output)
        print(f"Export: {path}")

    elif args.command == 'add-account':
        if not args.email or not args.password:
            print("Fehler: --email und --password erforderlich")
            sys.exit(1)

        # IMAP-Presets
        imap_presets = {
            "gmail.com": ("imap.gmail.com", 993),
            "outlook.com": ("outlook.office365.com", 993),
            "hotmail.com": ("outlook.office365.com", 993),
            "gmx.de": ("imap.gmx.net", 993),
            "gmx.net": ("imap.gmx.net", 993),
            "web.de": ("imap.web.de", 993),
            "t-online.de": ("secureimap.t-online.de", 993),
        }

        domain = args.email.split('@')[-1].lower()
        host, port = imap_presets.get(domain, (args.host or "", 993))

        if not host:
            print("Fehler: --host erforderlich fuer unbekannten Provider")
            sys.exit(1)

        account_id = service.add_account(
            name=domain.split('.')[0].title(),
            email_addr=args.email,
            password=args.password,
            imap_host=host,
            imap_port=port
        )
        print(f"Konto hinzugefuegt: ID {account_id}")

    elif args.command == 'list':
        accounts = service.get_accounts()
        for a in accounts:
            print(f"[{a.id}] {a.name}: {a.email} ({a.imap_host})")

    elif args.command == 'status':
        conn = sqlite3.connect(USER_DB)
        conn.row_factory = sqlite3.Row

        # Letzte Syncs
        cursor = conn.cursor()
        cursor.execute("""
            SELECT account_id, status, emails_matched, finished_at
            FROM mail_sync_runs
            ORDER BY finished_at DESC
            LIMIT 5
        """)
        syncs = cursor.fetchall()

        # Statistiken
        cursor.execute("SELECT COUNT(*) FROM financial_emails")
        total = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM financial_emails WHERE status = 'neu'")
        neu = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM financial_subscriptions WHERE aktiv = 1")
        abos = cursor.fetchone()[0]

        conn.close()

        print(f"\n=== BACH Financial Mail Status ===")
        print(f"Gesamt E-Mails: {total}")
        print(f"Neue E-Mails:   {neu}")
        print(f"Aktive Abos:    {abos}")
        print(f"\nLetzte Syncs:")
        for s in syncs:
            print(f"  {s['finished_at']}: {s['status']} ({s['emails_matched']} matched)")


if __name__ == "__main__":
    main()
