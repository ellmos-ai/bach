---
name: delivery-engine
version: 1.0.0
type: service
author: BACH Team
created: 2026-09-17
updated: 2026-09-17
anthropic_compatible: true
status: ready

dependencies:
  tools: []
  services:
    - Mail-Driver (Gmail, fuer Kanal email)
    - Connector-Driver (Telegram)
    - Cloud-Ordner (OneDrive/Google Drive/Dropbox, fuer cloud_local)
  workflows: []

description: >
  Zentrale Zustellungs-Engine fuer Dossiers, Analysen und Berichte.
  Kanaluebergreifende Zustellung mit User-Folder, Browser-Preview,
  E-Mail, Telegram, Cloud-Local und System-Inbox. Stand 2026-09-17:
  vollstaendig implementiert, aber noch von keinem Handler importiert
  (nur Standalone-Nutzung/Demo vorhanden).
---

# Delivery Engine

**Kategorie:** Ausgabe & Zustellung
**Integration:** keine (Stand 2026-09-17) — Verwendung als Bibliothek
**Handler:** keiner — Aufruf nur programmatisch

---

## Zweck

Zentrale Zustellungs-Engine fuer Dossiers, Analysen, Berichte.
Alle erzeugten Inhalte sollen ohne Handler-Sonderfaelle an alle
konfigurierten Ziel-Kanaele verteilt werden koennen.

---

## API

Klasse: `DeliveryEngine` (hub/_services/delivery/delivery_engine.py)

```python
from hub._services.delivery.delivery_engine import DeliveryEngine

engine = DeliveryEngine()
result = engine.deliver(
    content="# Mein Report\n\nInhalt...",
    title="Steuer-Analyse 2024",
    format="pdf",            # pdf, md, txt, json, html
    skill="steuer-agent",    # optional: Skill-Kontext
    agent=None,              # optional: Agent-Kontext
    metadata=None,           # optional: Metadaten
    delivery_override=None,  # optional: Methoden-Override
)
```

Kanaele (delivery_methods):
- `user_folder` — Standard-Ablage im User-Ordner
- `browser_preview` — PDF auto-open im Browser
- `email` — Gmail via Mail-Driver
- `telegram` — via Connector-Driver
- `cloud_local` — lokale Cloud-Ordner (OneDrive, Google Drive, Dropbox)
- `system_inbox` — fuer externe Abholung

Modi: `parallel` (alle konfigurierten Methoden parallel) oder
`only` (nur angegebene Methode(n)).

Konfiguration: Config-Datei, sonst Default
(`default_delivery`: mode=parallel, methods=[user_folder]).

---

## Abhaengigkeiten

- Mail-Driver (Gmail) fuer Kanal `email`
- Connector-Driver (Telegram) fuer Kanal `telegram`
- Cloud-Sync-Ordner fuer Kanal `cloud_local`
- PDF-Erzeugung fuer `format="pdf"`

**Hinweis (Stand 2026-09-17):** Engine ist funktionsfaehig, wird aber
von keinem Handler referenziert (nur eigene Datei + directory_truth).
Bei erster Integration diesen Status auf `active` heben.