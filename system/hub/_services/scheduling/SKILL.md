---
name: scheduling
version: 1.0.0
type: service
author: BACH Team
created: 2026-01-23
updated: 2026-09-18
anthropic_compatible: true
status: concept

dependencies:
  tools: []
  services: []
  workflows: []

description: >
  Scheduling Service für Tagesplanung, Routinen und Termine. Basiert auf der
  UpToday Routines Engine.
---
# Scheduling Service

**Tagesplanung, Routinen und Terminverwaltung**

> **HINWEIS:** Dieser Service ist eine Extraktion der `UpToday` Engines (Routines).

## Übersicht

Der Scheduling Service verwaltet den täglichen Ablauf, wiederkehrende Routinen, einmalige Aufgaben und Termine. Er basiert auf dem Ampel-System (Grün/Gelb/Rot) für den Tagesstatus.

## Features (aus UpToday)

* **Routinen:** Schritte, Dauer, Fortschrittstracking.
* **Aufgaben:** Einmalige ToDos.
* **Termine:** Zeitgebundene Events.
* **Wiederholungen:** Täglich, Wöchentlich, etc.
* **Today-Board:** Aggregierte Tagesansicht.

## Ordnerstruktur

```text
scheduling/
├── SKILL.md            # Diese Datei
└── stubs/              # Extrahierter Code (Stubs)
    ├── engine.py       # Core Logic (RoutinesEngine)
    └── models.py       # Dataclasses (Item, Step, etc.)
```

## Status

* [x] Struktur angelegt
* [x] DB-Schema erstellt (schema_scheduling.sql) - 2026-01-25
* [ ] Abhängigkeiten auflösen (DatabaseManager)
* [ ] API definieren

## DB-Schema (v1.0.0)

Tabellen:
- `scheduling_items` - Routinen, Tasks, Termine
- `scheduling_steps` - Schritte in Routinen
- `scheduling_instances` - Tägliche Instanzen
- `scheduling_step_completions` - Fortschritt pro Step
- `scheduling_today_board` - Heute-Board Config

View: `v_scheduling_today` - Aggregierte Tagesansicht
