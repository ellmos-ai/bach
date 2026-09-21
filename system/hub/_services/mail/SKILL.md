---
name: mail-service
version: 1.1.0
type: service
author: BACH Team
created: 2026-09-17
updated: 2026-09-17
anthropic_compatible: true
status: active

dependencies:
  tools: [keyring (IMAP-Passwoerter), imaplib, Gmail API (OAuth2)]
  services:
    - abo-Verwaltung (abo_subscriptions, via mail_abo_sync_service)
    - N8N (JSON-Export)
    - Daemon-Integration
  workflows: []

description: >
  E-Mail-Datenquelle und -Versand mit Fokus auf Finanzdaten.
  IMAP- und Gmail-OAuth2-Abruf, Anbieter-Erkennung per Pattern-Matching,
  PDF-Anhang-Extraktion, automatische Steuer-Kategorisierung und
  Two-Step-Versand (immer erst Draft, Versand nur nach expliziter
  User-Bestaetigung).
---

# Mail Service

**Kategorie:** Kommunikation & Finanz-Datenquellen
**Integration:** `tools/send_report.py` (Gmail-Versand),
`tools/llmauto/chains/session_financial_mail.json`
**Handler:** keiner eigenstaendig (Mail-Handler-Paket in hub/email.py
getrennt hiervon)

---

## Zweck

Finanzrelevante E-Mails erfassen, extrahieren und kategorisieren sowie
E-Mails sicher versenden. Sicherheitsprinzip: Es wird nie direkt
versendet — jede Mail wird zunaechst als Draft in der DB gespeichert
und erst nach `confirm <id>` durch den User gesendet.

---

## API / Module

| Modul | Funktion |
|---|---|
| `mail_service.py` | Financial Mail Service v1.1: IMAP- + Gmail-OAuth2-Abruf, Pattern-Matching (Anbieter-Erkennung), PDF-Anhang-Extraktion, Steuer-Kategorisierung, N8N-JSON-Export, Daemon-Integration |
| `email_sender.py` | E-Mail-Versand via Gmail API (OAuth2); Draft-zuerst-Prinzip, Versand nur nach `confirm <id>` |
| `account_manager.py` | Verwaltung von IMAP-Konten (Keyring-Passwortspeicher) und Gmail-API-Konten |
| `mail_setup.py` | OAuth2-Einrichtung: `python mail_setup.py check` (Status), `python mail_setup.py refresh` (Token erneuern) |
| `mail_abo_sync_service.py` | Sync: financial_subscriptions (Mail-Extraktion) → abo_subscriptions (zentrale Abo-Verwaltung) |

Konfiguration im Ordner:
- `config.json` — Service-Konfiguration
- `providers.json` / `providers.schema.json` — Anbieter-Patterns (valide against Schema)
- `schema_financial.sql` — Tabellen-Schema der Finanz-Extraktion

---

## Abhaengigkeiten

- keyring (IMAP-Passwoerter), imaplib
- Gmail API: credentials.json / token.json (OAuth2, read + send)
- User-DB: financial_subscriptions, Draft-Tabelle
- abo-Verwaltung (abo_subscriptions) fuer Abo-Sync
- N8N (optionaler JSON-Export)