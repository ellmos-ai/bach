---
name: dashboard-service
version: 1.0.0
type: service
author: BACH Team
created: 2026-09-17
updated: 2026-09-17
anthropic_compatible: true
status: active

dependencies:
  tools: []
  services:
    - user-DB (sqlite3, Tabellen: routines, calendar, shopping, inventory, health, literatur)
  workflows: []

description: >
  Konsolidierter Tagesstatus (INT05). Aggregiert tagesrelevante Daten aus
  allen BACH-Modulen (Routinen, Kalender, Einkaufsliste, Inventar-Ampel,
  Medikamente, Gesundheitstermine, Literatur) aus der User-DB.
---

# Dashboard Service (DailyOverview)

**Kategorie:** Integration & Aggregation
**Integration:** `hub/haushalt.py` (Lazy-Import, Zeile ~386)
**Handler:** keiner eigenstaendig — Aufruf ueber Haushalt-Handler

---

## Zweck

Aggregiert tagesrelevante Daten aus allen BACH-Modulen in einem einzigen
Dict, damit Handler den Tagesstatus ohne eigene DB-Zugriffe formatieren
koennen.

Datenquellen (Tabellen der User-DB):
- Haushalt: Routinen, Inventar-Ampel, Einkaufsliste
- Gesundheit: Medikamente, Termine
- Literatur: Ungelesene Quellen
- Kalender: Heutige Termine

---

## API

Klasse: `DailyOverview` (hub/_services/dashboard/daily_overview.py)

```python
from hub._services.dashboard.daily_overview import DailyOverview

svc = DailyOverview(db_path)          # db_path: Pfad zur User-DB (bach.db)
overview = svc.get_overview()         # -> Dict (unten)
text     = svc.format_today()         # -> formatierter Tagesstatus (str)
```

`get_overview()` liefert Dict mit Keys:
`date`, `weekday`, `routines`, `calendar`, `shopping`, `inventory`,
`health_meds`, `health_appointments`, `literatur`, `timestamp`

---

## Abhaengigkeiten

- sqlite3 (User-DB, read-only-Zugriff)
- Benutzerpfad: `self.user_db_path` des Haushalt-Handlers
- Keine externen Dienste, kein Netzwerk