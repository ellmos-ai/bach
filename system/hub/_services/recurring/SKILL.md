---
name: recurring
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
  System-Service fuer periodische Tasks in BACH: prueft und startet
  wiederkehrende Wartungs- und Folgeauftraege. Explizit nicht ATI-
  spezifisch — fuer alle Agenten und die System-Wartung; Taskdefinitionen
  stehen in config.json.
---

# BACH Recurring Tasks

**Kategorie:** Systemdienst (Wartung/Timer)

## Zweck
Der Recurring-Tasks-Service fuehrt periodische Tasks aus. Er ist explizit
**nicht** ATI-spezifisch, sondern fuer alle Agenten und die System-Wartung
da. Die Tasks sind in config.json definiert. Der Service wird von
`hub/_services/chat/chat_runtime.py` lazy importiert;
ARCHITECTURE.md nennt ihn als Hintergrund-Service.

## Nutzung
```bash
python recurring_tasks.py check       # Faelligkeiten pruefen
python recurring_tasks.py list        # Tasks auflisten
python recurring_tasks.py trigger ID  # Task ausloesen
```

## Dateien
- `recurring_tasks.py` — Task-Service und CLI
- `config.json` — Task-Definitionen