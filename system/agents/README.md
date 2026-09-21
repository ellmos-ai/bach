# BACH Agenten-System

> **Stand:** 2026-09-17 | **Struktur:** `agents/` (Top-Level)

## Ueberblick

Das BACH Agenten-System organisiert KI-Assistenten in einer hierarchischen Struktur:

```
Boss-Agenten (koordinieren)
    |
    +-- Experten (spezialisiert)
    |
    +-- Fach-Agenten (autonom)
```

Jeder Agent/Experte hat einen YAML-Header (name, version, status, orchestrates,
dependencies) in seiner SKILL.md bzw. CONCEPT.md.

## Hierarchie

### Privat

**Persoenlicher Assistent** (`persoenlicher-assistent`, Boss-Agent v1.2.0)
- Terminverwaltung, Recherche, Kommunikation
- Experten: Haushaltsmanagement, Decision-Briefing, Literaturverwalter, Transkriptions-Service

**Gesundheitsassistent** (`gesundheitsassistent`, Boss-Agent v2.0.0)
- Medizinische Dokumentation und Gesundheitsverwaltung
- Experten: Gesundheitsverwalter, Psycho-Berater, Health-Import

### Beruflich

**Bueroassistent** (`bueroassistent`, Boss-Agent v1.0.0)
- Steuern, Foerderplanung, Dokumentation
- Experten: Steuer-Agent, Foerderplaner, Report-Generator, Worksheet-Generator

**Production** (`production`, Boss-Agent v1.1.0)
- Content-Erstellung: Musik, Video, Text, Storytelling, PR
- Experten: Media-Production, Press, Text-Production

**Versicherungs-Agent** (`versicherungen`, v1.1.0)
- Versicherungsmanagement, Finanzplanung, Vertragsanalyse

### Fach-Agenten (autonom)

| Agent | Verzeichnis | Zweck |
|-------|-------------|-------|
| Research-Agent | `research/` | Wissenschaftliche Recherche, Literaturanalyse |
| Entwickler-Agent | `entwickler/` | Software-Entwicklung, Projektverwaltung |
| ATI | `ati/` | Advanced Tool Integration, Projekt-Bootstrapping |
| Reflection-Agent | `reflection/` | Selbstreflexion, Performance-Analyse |
| Test-Agent | `test-agent/` | QA, Smoke-Tests (Referenz-Agent in `tests/test_smoke.py`) |

### Experten

Experten liegen unter `agents/_experts/`, z.B. `selbstmanagement/`, `bewerbungsexperte/`.
Jeder Experte hat eine SKILL.md bzw. CONCEPT.md mit Status im Header.

## Verzeichnisstruktur

```
agents/
+-- README.md                 # Diese Datei
+-- _archive/                 # Archivierte/verwaiste Agenten
+-- _experts/                 # Experten (spezialisiert)
+-- <agent-name>/
    +-- SKILL.md              # Agent-Definition mit YAML-Header
    +-- modules/             # Optionale Agent-Module (z.B. ati/)
    +-- manifest.json        # Optional: Manifest (BACH Self-Extension)
```

## Datenbank-Integration

### bach.db

- `bach_agents` - Registrierte Boss-Agenten
- `bach_experts` - Registrierte Experten
- `agent_expert_mapping` - Zuordnungen

### Expert-Tabellen (in bach.db)

Seit v1.1.84 (Task 772) ist die fruehere `user.db` in `bach.db` konsolidiert; `data/user.db` existiert nicht mehr. Jeder Experte kann eigene Tabellen in `bach.db` haben:

**Haushaltsmanagement:**
- `household_inventory`, `household_shopping_lists`, `household_finances`, `household_routines`

**Gesundheitsverwalter:**
- `health_contacts`, `health_diagnoses`, `health_medications`, `health_lab_values`,
  `health_documents`, `health_appointments`

**Psycho-Berater:**
- `psycho_sessions`, `psycho_observations`

**Persoenlicher Assistent:**
- `assistant_contacts`, `assistant_calendar`, `assistant_briefings`, `assistant_user_profile`

## CLI-Befehle

```bash
# Agenten anzeigen
python tools/agents/agent_cli.py list
python tools/agents/agent_cli.py experts

# Agent-Details
python tools/agents/agent_cli.py info gesundheitsassistent

# User-Ordner initialisieren
python tools/agents/agent_cli.py init all
python tools/agents/agent_cli.py init bueroassistent

# Datenbank einrichten
python tools/agents/agent_cli.py setup-db

# System-Status
python tools/agents/agent_cli.py status
```

## Neuen Agenten hinzufuegen

1. **Verzeichnis + SKILL.md erstellen** unter `agents/<name>/SKILL.md` mit YAML-Header
   (name, version, type, status, description)
2. **In Datenbank registrieren** (in `agent_cli.py` oder manuell)
3. **User-Ordner definieren** (host-abhaengig, siehe BACH-Config)
4. **Experten zuordnen** falls Boss-Agent (orchestrates.experts)

## Neuen Experten hinzufuegen

1. **Ordner erstellen** unter `agents/_experts/<name>/`
2. **SKILL.md / CONCEPT.md** mit Dokumentation und Status-Header
3. **Schema** in `data/schema_agents.sql` falls DB-Tabellen benoetigt
4. **Dem Boss-Agent zuordnen** (orchestrates.experts)

## Workflow

1. **Agent aktivieren**: Entweder direkt oder ueber CLI
2. **Kontext laden**: Agent laedt Skill-Datei und User-Daten
3. **Anfrage analysieren**: Agent entscheidet ob selbst oder Experte
4. **Delegation**: Bei Spezialthemen an Experten delegieren
5. **Ergebnisse sammeln**: Boss-Agent fasst zusammen