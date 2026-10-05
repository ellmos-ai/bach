---
name: personal-assistant
version: 1.2.0
type: skill
created: 2026-09-29
description: Boss-Agent für Alltags- und Arbeitsorganisation — Briefings/Dossiers, Termine, Locations, Kalender, Haushalt (Spiegel/Index von system/agents/persoenlicher-assistent)
last_updated: 2026-09-29
---

# Personal Assistant (Skill-Spiegel)

> Index/Spiegel des Boss-Agenten `persoenlicher-assistent`. Kanonische Definition liegt unter `system/agents/persoenlicher-assistent/SKILL.md` (v1.2.0) — diese Datei macht den Agenten im Skills-Verzeichnis auffindbar und fasst Schnittstellen, Kernaufgaben und Bezüge zusammen. Bei Konflikten gilt die Agent-Datei.

## Quick Start

```bash
# Status / geführte Dokumente:
bach assistent status
bach assistent kalender
bach assistent kontakte list

# Delegation an Experten (Haushaltsmanagement):
bach haushalt inventar list
bach haushalt liste show

# Nutzung aus Claude heraus: Skill "persoenlicher-assistent" laden;
# Bridge-Kontext: wird vom skill_loader der claude_bridge beim Session-Start
# als persoenlicher-assistent.txt erwartet (siehe Betriebshinweise).
```

## Agent-Referenz

| Komponente | Pfad |
|------------|------|
| Boss-Agent (kanonisch) | `system/agents/persoenlicher-assistent/SKILL.md` |
| User-Daten | `user/persoenlicher_assistent/` (dokumente/, briefings/, dossiers/, haushalt/) |
| Orchestrierte Experten | `system/agents/_experts/haushaltsmanagement/` (+ decision-briefing, literaturverwalter, transkriptions-service) |
| Workflow-Erweiterung | `system/skills/workflows/assistent.md` |

### Tools (system/agents/persoenlicher-assistent/tools/)

| Tool | Zweck |
|------|-------|
| `dossier_generator.py` | Personen-Dossiers erstellen → `user/persoenlicher_assistent/dossiers/` |
| `location_search.py` | Orte/Hotels/Restaurants suchen, Kontaktdaten, Öffnungszeiten |
| `route_planner.py` | Reiserouten (Zug/Auto) recherchieren |

## Kernaufgaben

1. **Information & Recherche:** Sachverhalte recherchieren, Briefings → `briefings/`, Dossiers → `dossiers/`
2. **Wege, Ziele & Locations:** Termine/Meetings vorbereiten, Locations suchen, Routen planen
3. **Kommunikation & Organisation:** Termin-Koordination mit Kontakten, Buchungslinks, Kalender pflegen
4. **Assistenz:** Nutzerpräferenzen lernen (CHARAKTERSHEET.md), proaktiv mitdenken

## Geführte Dokumente

| Datei | Inhalt |
|-------|--------|
| `KALENDER.md` | Termine, Beschreibungen, Aufgaben, Orte, Personen, Buchungen, Verbindungen |
| `AUFGABEN.md` | Nicht-terminierte Aufgaben |
| `KONTAKTE.md` | Name, Kontext, Mail, Tel, Mobil, Privat/Beruflich, Geburtstag, Sonstiges |
| `DOKUMENTENVERZEICHNIS.md` | Alle Dokumente im Projekt |
| `CHARAKTERSHEET.md` | Gelerntes über Nutzer, Präferenzen, Eigenheiten |

## Integrationen & Daten

- **Google Calendar:** Termine synchronisieren und verwalten
- **Google Drive:** Dokumente durchsuchen/referenzieren
- **Gmail:** Kommunikationshistorie
- **Websearch:** Locations, Routen, Kontaktdaten (Quellen stets dokumentieren)
- **DB (bach.db):** `assistant_contacts`, `assistant_calendar`, `assistant_briefings`, `assistant_user_profile`; Experte: `household_inventory/shopping_lists/finances/routines`; Registry: `bach_agents`, `bach_experts`, `agent_expert_mapping`

## Fackelträger

- **Typ:** `personal_assistant` — eine von max. 2 Fackeln pro 24h/Benutzer (neben `bridge_assistant`); Single-24h-Privileg pro system_id
- **Ortsgebunden:** Fackel hängt an (user_id, system_id), NICHT am Prozess
- **Handover (4 Schritte):** (1) Request → (2) Regeln prüfen + Paket schnüren → (3) alte komprimiert + sendet → (4) neue startet; alte beendet sich erst nach Bestätigung. Fackel-ID = (user_id, system_id, session_id, timestamp)
- **API (Bridge, Port 8091):** GET /api/fackel/status, POST /api/fackel/request|handover|release
- **State:** SQLite-Tabelle fackel_state in BACH_DB (system_id, pc_name, user_id, Heartbeats, Handover-Felder); kein Datei-Store

## Betriebshinweise

- **Start-/End-Prozeduren:** Sitzungsstart = Archiv scannen → DOKUMENTENVERZEICHNIS aktualisieren → Kontext/Zeit laden → tageszeitabhängige Begrüßung (morgens: Tagesablauf + Briefings). Sitzungsende = Übergabe-Notiz + Kalender/Dokumente aktualisieren.
- **skill_loader (claude_bridge):** Erwartet optional `persoenlicher-assistent.txt` unter `BACH_DIR/skills/` oder `BACH_DIR/agents/` als Session-Kontext. Stub liegt in `skills/persoenlicher-assistent.txt` und verweist hierher.
- **Sicherheit/Policy:** Bei therapeutisch relevanten Inhalten gilt `system/skills/therapie/ETHICS.md` (Policy vor Skill-Logik).

## Changelog

- **1.2.0 (2026-02-04):** Agent-Update (Import/Konsolidierung, siehe `agents/persoenlicher-assistent/SKILL.md`)
- **2026-09-29:** Skill-Spiegel im Rahmen von Task #1600 angelegt; Fackelträger-Kontext ergänzt (Typ personal_assistant, 24h-Regeln, Handover, /api/fackel/*); angelegt (Auffindbarkeit in `system/skills/`, Bridge-Kontext-Stub)
