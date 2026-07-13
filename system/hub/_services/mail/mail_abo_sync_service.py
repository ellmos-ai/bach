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
BACH Mail-Abo Synchronization Service v1.0
==========================================
Synchronisiert Abonnements aus financial_subscriptions (Mail-Extraktion)
mit abo_subscriptions (Zentrale Abo-Verwaltung).
"""

import sqlite3
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple

import sys
# Den DB-Pfad zentral erfragen, nicht selbst bauen: ein repo-relativer Pfad zeigt auf die
# veraltete Kopie im OneDrive-Ordner (bzw. auf ein Verzeichnis, das es gar nicht gibt —
# dort legt sqlite3.connect() still eine leere 0-KB-Datenbank an).
_SYSTEM_ROOT = next(
    p for p in Path(__file__).resolve().parents if (p / "hub" / "bach_paths.py").exists()
)
if str(_SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(_SYSTEM_ROOT))
from hub.bach_paths import BACH_DB

# Logger konfigurieren
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class MailAboSyncService:
    def __init__(self, db_path: Path):
        self.db_path = db_path

    def run_sync(self, dry_run: bool = False) -> Dict:
        """Führt die Synchronisation aus."""
        result = {
            "mail_subscriptions_found": 0,
            "synced": 0,
            "skipped": 0,
            "errors": []
        }

        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # 1. Alle neuen/unbestätigten Mail-Abos laden
            # Hinweis: Wir nehmen alle aus financial_subscriptions, die aktiv sind
            cursor.execute("""
                SELECT id, provider_id, provider_name, category, betrag_monatlich, 
                       zahlungsintervall, naechste_zahlung, kuendigungslink
                FROM financial_subscriptions
                WHERE aktiv = 1
            """)
            mail_subs = cursor.fetchall()
            result["mail_subscriptions_found"] = len(mail_subs)

            if not mail_subs:
                logger.info("Keine Mail-Abos zur Synchronisation gefunden.")
                conn.close()
                return result

            # 2. Bestehende Abo-Management-Einträge laden (für Deduplizierung)
            cursor.execute("SELECT anbieter, kategorie FROM abo_subscriptions")
            existing_abos = {(row['anbieter'].lower(), row['kategorie'].lower() if row['kategorie'] else None) for row in cursor.fetchall()}

            # 3. Synchronisieren
            now = datetime.now().isoformat()
            
            for sub in mail_subs:
                provider_name = sub['provider_name']
                category = sub['category']
                
                # Check ob bereits vorhanden (einfaches Matching auf Namen)
                if provider_name.lower() in {name for name, kat in existing_abos}:
                    logger.info(f"Überspringe '{provider_name}': Bereits in Abo-Verwaltung vorhanden.")
                    result["skipped"] += 1
                    continue

                if dry_run:
                    logger.info(f"[DRY-RUN] Würde Abo synchronisieren: {provider_name} ({category})")
                    result["synced"] += 1
                    continue

                # In abo_subscriptions einfügen
                try:
                    cursor.execute("""
                        INSERT INTO abo_subscriptions 
                        (name, anbieter, kategorie, betrag_monatlich, zahlungsintervall, 
                         kuendigungslink, erkannt_am, bestaetigt, aktiv, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, 0, 1, ?)
                    """, (
                        provider_name,
                        provider_name,
                        category,
                        sub['betrag_monatlich'],
                        sub['zahlungsintervall'] or 'monatlich',
                        sub['kuendigungslink'],
                        now,
                        now
                    ))
                    logger.info(f"Abo erfolgreich synchronisiert: {provider_name}")
                    result["synced"] += 1
                except Exception as e:
                    logger.error(f"Fehler beim Einfügen von {provider_name}: {e}")
                    result["errors"].append(f"{provider_name}: {str(e)}")

            if not dry_run:
                conn.commit()
            
            conn.close()
            return result

        except Exception as e:
            logger.error(f"Synchronisations-Fehler: {e}")
            result["errors"].append(str(e))
            return result

if __name__ == "__main__":
    # Test-Aufruf
    script_dir = Path(__file__).parent.resolve()
    db_path = BACH_DB
    
    sync_service = MailAboSyncService(db_path)
    res = sync_service.run_sync(dry_run=True)
    print(res)
