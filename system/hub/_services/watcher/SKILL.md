---
name: watcher
version: 1.0.0
type: service
author: BACH Team
created: 2026-10-30
updated: 2026-10-30
last_updated: 2026-10-30
anthropic_compatible: true
status: active
dependencies: []
description: >
  Always-on-Hintergrundprozess: lauscht auf konfigurierte Event-Quellen,
  klassifiziert Events via Mistral (classifier.py, prompts/) und reagiert
  via responder.py; startet bei Bedarf Claude-Code-Sessions.
---

# BACH Mistral Watcher Daemon

**Kategorie:** Systemdienst (Hintergrundprozess)

## Zweck
Der Watcher Daemon ist ein Always-on-Hintergrundprozess. Er lauscht auf die
in `event_sources.py` definierten Quellen, klassifiziert eingehende Events
via Mistral (`classifier.py`, Prompts in `prompts/`) und reagiert via
`responder.py`. Bei Bedarf startet er Claude-Code-Sessions.
Konfiguration in config.json.

## Nutzung
```bash
python watcher_daemon.py            # Start
python watcher_daemon.py --stop     # Stop
python watcher_daemon.py --status   # Status
```

## Dateien
- `watcher_daemon.py` — Daemon (Start/Stop/Status)
- `classifier.py` — Event-Klassifikation via Mistral
- `event_sources.py` — Event-Quellen
- `responder.py` — Reaktionslogik
- `config.json` — Konfiguration
- `prompts/` — Mistral-Prompts