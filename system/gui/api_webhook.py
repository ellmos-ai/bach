#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
BACH Webhook API v1.0
=====================
Empfaengt Rechnungsdaten von n8n und importiert sie in steuer_posten.

Endpoints:
- POST /api/webhook/invoice     Rechnung importieren
- POST /api/webhook/invoice/batch   Mehrere Rechnungen
- GET  /api/webhook/providers   Bekannte Anbieter abrufen
"""

import sqlite3
import json
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Optional, List
from pydantic import BaseModel

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

# Pfade
BACH_DIR = Path(__file__).parent.parent
DATA_DIR = BACH_DIR / "data"
USER_DB = BACH_DB
PROVIDERS_FILE = Path(__file__).parent.parent.parent / "n8n" / "invoice_providers.json"


# =========================================================================
# PYDANTIC MODELS
# =========================================================================

class InvoiceData(BaseModel):
    """Rechnungsdaten von n8n."""
    unternehmen: str
    bezeichnung: str
    rechnungsnummer: Optional[str] = None
    rechnungsdatum: str  # YYYY-MM-DD
    netto: Optional[float] = None
    brutto: Optional[float] = None
    mwst: Optional[float] = None
    steuersatz: Optional[float] = 19.0
    waehrung: str = "EUR"

    # Abo-Informationen
    ist_abo: bool = False
    abo_intervall: Optional[str] = None  # monatlich, jaehrlich, quartalsweise
    kuendigungslink: Optional[str] = None
    kategorie: Optional[str] = "sonstiges"

    # Metadaten
    quelle: str = "n8n"
    email_von: Optional[str] = None
    email_betreff: Optional[str] = None
    email_datum: Optional[str] = None
    erfasst_am: Optional[str] = None


class InvoiceBatch(BaseModel):
    """Mehrere Rechnungen auf einmal."""
    invoices: List[InvoiceData]


class WebhookResponse(BaseModel):
    """Standard-Antwort."""
    success: bool
    message: str
    posten_id: Optional[int] = None
    duplicate: bool = False


# =========================================================================
# DATABASE HELPERS
# =========================================================================

def get_user_db():
    """User-DB Verbindung."""
    conn = sqlite3.connect(USER_DB)
    conn.row_factory = sqlite3.Row
    return conn


def compute_invoice_hash(invoice: InvoiceData) -> str:
    """Berechnet eindeutigen Hash fuer Duplikat-Erkennung."""
    data = f"{invoice.unternehmen}|{invoice.rechnungsnummer}|{invoice.rechnungsdatum}|{invoice.brutto}"
    return hashlib.md5(data.encode()).hexdigest()


def check_duplicate(conn: sqlite3.Connection, invoice_hash: str) -> bool:
    """Prueft ob Rechnung bereits existiert."""
    result = conn.execute(
        "SELECT id FROM steuer_posten WHERE hash = ?",
        (invoice_hash,)
    ).fetchone()
    return result is not None


def insert_steuer_posten(conn: sqlite3.Connection, invoice: InvoiceData) -> int:
    """Fuegt Rechnung in steuer_posten ein."""
    invoice_hash = compute_invoice_hash(invoice)

    # Steuerjahr aus Datum
    try:
        steuerjahr = int(invoice.rechnungsdatum[:4])
    except (ValueError, IndexError):
        steuerjahr = datetime.now().year

    cursor = conn.execute("""
        INSERT INTO steuer_posten (
            steuerjahr, rechnungssteller, bezeichnung,
            rechnungsnummer, datum, netto, brutto, mwst_betrag, mwst_satz,
            kategorie, quelle, hash, erfasst_am
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        steuerjahr,
        invoice.unternehmen,
        invoice.bezeichnung,
        invoice.rechnungsnummer,
        invoice.rechnungsdatum,
        invoice.netto,
        invoice.brutto,
        invoice.mwst,
        invoice.steuersatz,
        invoice.kategorie,
        invoice.quelle,
        invoice_hash,
        datetime.now().isoformat()
    ))
    conn.commit()
    return cursor.lastrowid


def upsert_abo_subscription(conn: sqlite3.Connection, invoice: InvoiceData, posten_id: int):
    """Aktualisiert oder erstellt Abo-Eintrag."""
    if not invoice.ist_abo:
        return

    # Pruefe ob Abo bereits existiert
    existing = conn.execute(
        "SELECT id, betrag_monatlich FROM abo_subscriptions WHERE anbieter = ? AND aktiv = 1",
        (invoice.unternehmen,)
    ).fetchone()

    # Berechne monatlichen Betrag
    betrag_monatlich = invoice.brutto
    if invoice.abo_intervall == "jaehrlich":
        betrag_monatlich = invoice.brutto / 12
    elif invoice.abo_intervall == "quartalsweise":
        betrag_monatlich = invoice.brutto / 3

    if existing:
        # Abo aktualisieren
        conn.execute("""
            UPDATE abo_subscriptions
            SET betrag_monatlich = ?, zahlungsintervall = ?,
                kuendigungslink = ?, updated_at = ?
            WHERE id = ?
        """, (
            betrag_monatlich,
            invoice.abo_intervall or "monatlich",
            invoice.kuendigungslink,
            datetime.now().isoformat(),
            existing['id']
        ))
        abo_id = existing['id']
    else:
        # Neues Abo anlegen
        cursor = conn.execute("""
            INSERT INTO abo_subscriptions (
                name, anbieter, kategorie, betrag_monatlich,
                zahlungsintervall, kuendigungslink, erkannt_am,
                bestaetigt, aktiv, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, 1, ?)
        """, (
            invoice.bezeichnung,
            invoice.unternehmen,
            invoice.kategorie,
            betrag_monatlich,
            invoice.abo_intervall or "monatlich",
            invoice.kuendigungslink,
            datetime.now().isoformat(),
            datetime.now().isoformat()
        ))
        abo_id = cursor.lastrowid

    # Verknuepfung zu steuer_posten
    conn.execute("""
        INSERT OR IGNORE INTO abo_payments (subscription_id, posten_id, betrag, datum, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (
        abo_id,
        posten_id,
        invoice.brutto,
        invoice.rechnungsdatum,
        datetime.now().isoformat()
    ))
    conn.commit()


# =========================================================================
# API ENDPOINTS (als FastAPI Router)
# =========================================================================

def register_webhook_routes(app):
    """Registriert Webhook-Routen bei der FastAPI App."""

    @app.post("/api/webhook/invoice", response_model=WebhookResponse)
    async def receive_invoice(invoice: InvoiceData):
        """
        Empfaengt eine Rechnung von n8n und importiert sie.

        Duplikate werden erkannt und uebersprungen.
        Bei Abos wird automatisch abo_subscriptions aktualisiert.
        """
        conn = get_user_db()

        # Duplikat-Check
        invoice_hash = compute_invoice_hash(invoice)
        if check_duplicate(conn, invoice_hash):
            conn.close()
            return WebhookResponse(
                success=True,
                message=f"Rechnung bereits vorhanden (Hash: {invoice_hash[:8]}...)",
                duplicate=True
            )

        try:
            # In steuer_posten einfuegen
            posten_id = insert_steuer_posten(conn, invoice)

            # Abo-Tracking aktualisieren
            upsert_abo_subscription(conn, invoice, posten_id)

            conn.close()
            return WebhookResponse(
                success=True,
                message=f"Rechnung importiert: {invoice.unternehmen} - {invoice.bezeichnung}",
                posten_id=posten_id,
                duplicate=False
            )
        except Exception as e:
            conn.close()
            return WebhookResponse(
                success=False,
                message=f"Fehler: {str(e)}",
                duplicate=False
            )

    @app.post("/api/webhook/invoice/batch")
    async def receive_invoice_batch(batch: InvoiceBatch):
        """Importiert mehrere Rechnungen auf einmal."""
        results = []
        for invoice in batch.invoices:
            result = await receive_invoice(invoice)
            results.append({
                "unternehmen": invoice.unternehmen,
                "success": result.success,
                "message": result.message,
                "duplicate": result.duplicate
            })

        imported = sum(1 for r in results if r["success"] and not r["duplicate"])
        duplicates = sum(1 for r in results if r["duplicate"])

        return {
            "success": True,
            "total": len(batch.invoices),
            "imported": imported,
            "duplicates": duplicates,
            "results": results
        }

    @app.get("/api/webhook/providers")
    async def get_providers():
        """Liefert die Liste bekannter Rechnungssteller."""
        if PROVIDERS_FILE.exists():
            with open(PROVIDERS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return {
                    "success": True,
                    "providers": data.get("providers", []),
                    "categories": data.get("categories", {})
                }
        return {
            "success": False,
            "message": "invoice_providers.json nicht gefunden"
        }

    @app.get("/api/webhook/stats")
    async def get_webhook_stats():
        """Statistiken zu importierten Rechnungen."""
        conn = get_user_db()

        # Anzahl n8n-Importe
        total = conn.execute(
            "SELECT COUNT(*) FROM steuer_posten WHERE quelle = 'n8n'"
        ).fetchone()[0]

        # Nach Kategorie
        by_category = conn.execute("""
            SELECT kategorie, COUNT(*) as count, SUM(brutto) as summe
            FROM steuer_posten
            WHERE quelle = 'n8n'
            GROUP BY kategorie
        """).fetchall()

        # Letzte Imports
        recent = conn.execute("""
            SELECT rechnungssteller, bezeichnung, brutto, datum, erfasst_am
            FROM steuer_posten
            WHERE quelle = 'n8n'
            ORDER BY erfasst_am DESC
            LIMIT 10
        """).fetchall()

        conn.close()

        return {
            "success": True,
            "total_imports": total,
            "by_category": [dict(row) for row in by_category],
            "recent": [dict(row) for row in recent]
        }

    print("[BACH] Webhook-Routen registriert:")
    print("       POST /api/webhook/invoice")
    print("       POST /api/webhook/invoice/batch")
    print("       GET  /api/webhook/providers")
    print("       GET  /api/webhook/stats")


# =========================================================================
# STANDALONE TEST
# =========================================================================

if __name__ == "__main__":
    print("Webhook API-Modul - Importiere in server.py:")
    print("")
    print("  from api_webhook import register_webhook_routes")
    print("  register_webhook_routes(app)")
