---
name: financial
version: 1.2.0
type: service
author: BACH Team
created: 2026-01-25
updated: 2026-01-25
anthropic_compatible: true
status: active

dependencies:
  tools: []
  services: []
  workflows: []

description: >
  Financial Mail Service zur automatischen Analyse von Finanz-E-Mails. Erkennt
  Rechnungen, Abonnements, steuer-relevante Belege. Voll integriert in BACH
  GUI mit Dashboard und Konten-Verwaltung.
---
# Financial Mail Service

**Automatische Finanz-E-Mail-Analyse für BACH**

## Übersicht

Der Financial Mail Service analysiert eingehende E-Mails auf finanzrelevante Inhalte:
- Rechnungen und Belege erkennen
- Abonnements automatisch tracken
- Steuer-relevante E-Mails markieren
- Beträge und Kategorien extrahieren

## GUI-Dashboard

Erreichbar über: `http://127.0.0.1:8000/financial`

**Features:**
- Statistiken (Konten, neue E-Mails, steuer-relevante, monatliche Kosten)
- E-Mail-Übersicht mit Filtern (Kategorie, Steuer-relevant)
- Abonnement-Tracking (erkannte wiederkehrende Zahlungen)
- Konten-Verwaltung (Gmail API, IMAP)
- False-Positive-Handling

## API-Endpoints

| Endpoint | Beschreibung |
|----------|--------------|
| `GET /api/financial/status` | Dashboard-Statistiken |
| `GET /api/financial/emails` | E-Mail-Liste mit Filtern |
| `GET /api/financial/subscriptions` | Aktive Abonnements |
| `GET /api/financial/accounts` | Konfigurierte E-Mail-Konten |
| `POST /api/financial/accounts` | Konto hinzufügen |
| `DELETE /api/financial/accounts/{id}` | Konto entfernen |

## Datenbank-Schema

Tabellen in `user.db`:

| Tabelle | Beschreibung |
|---------|--------------|
| `mail_accounts` | E-Mail-Konten Konfiguration |
| `mail_sync_runs` | Synchronisierungs-Protokoll |
| `financial_emails` | Erkannte Finanz-E-Mails |
| `financial_subscriptions` | Automatisch erkannte Abos |
| `financial_summary` | Monatliche/Jährliche Zusammenfassungen |

Die Zusammenfassung wird über `bach haushalt financial-summary refresh`
aktualisiert. `--dry-run` berechnet ausschließlich lesend. Beobachtete
E-Mail-Ausgaben werden nicht mit der aktuellen Abo-Laufkostenrate addiert.
Historische Abo-Duplikate werden nach `provider_id` dedupliziert; bei fachlich
widersprüchlichen Duplikaten bricht die Berechnung sicher ab.

**Views:**
- `v_financial_inbox` - Unbearbeitete Finanz-E-Mails
- `v_financial_steuer` - Steuer-relevante Posten
- `v_aktive_abos` - Aktive Abonnements
- `v_monatliche_kosten` - Kosten-Übersicht nach Monat

## Integration

### Mit Steuer-Agent

```bash
# Steuer-relevante E-Mails als Belege übernehmen
bach steuer import --from-financial
```

### Mit Daemon

Automatische Sync über Daemon-Profil:
- `hub/_services/daemon/profiles/financial_mail.json`

## Ordnerstruktur

```text
financial/
├── SKILL.md          # Diese Datei
└── stubs/            # Reserviert für zukünftige Module
```

Schema: `hub/_services/mail/schema_financial.sql`
GUI: `gui/templates/financial.html`
API: `gui/server.py` (ab Zeile 1780)

## Unterstützte Provider

- Gmail (via API mit OAuth)
- IMAP-Konten (Outlook, GMX, Web.de, etc.)

## Status

- [x] Datenbank-Schema implementiert
- [x] GUI-Dashboard vollständig
- [x] API-Endpoints aktiv
- [x] E-Mail-Sync (manuell)
- [x] Abonnement-Erkennung (automatisch via Trigger)
- [x] False-Positive-Handling
- [ ] Automatischer Daemon-Sync
- [ ] Steuer-Import Integration
- [ ] OCR für Anhänge

## Changelog

| Version | Datum | Änderung |
|---------|-------|----------|
| 1.2.0 | 2026-08-15 | Fail-closed Monats-/Jahressummary und Abo-Duplikatschutz |
| 1.1.0 | 2026-01-25 | SKILL.md von Stub auf Implementierung aktualisiert |
| 1.0.0 | 2026-01-23 | Initial Stub erstellt |
