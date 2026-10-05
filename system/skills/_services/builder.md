---
name: builder
metadata:
  version: 3.0.0
  last_updated: 2026-01-18
  type: service
  status: active
description: >
  Erstellt neue Skills/Agents nach BACH-Regeln, exportiert Komponenten,
  erstellt Distributions-Pakete, verwaltet Backups, testet externe Systeme
  und synthetisiert neue Systeme aus Best-of-Elementen.
---

# Builder Skill v3.0

**Skill/Agent-Erstellung, Export, Distribution, Backup, Test & Synthese**

---

## Übersicht

Der Builder Skill orchestriert acht Kern-Funktionen:

```
┌─────────────────────────────────────────────────────────────────────┐
│                      BUILDER SKILL v3.0                             │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  1. CREATE      Neue Skills/Agents nach BACH-Regeln erstellen       │
│  2. EXPORT      Skills/Agents zum Mitnehmen verpacken               │
│  3. DISTRIBUTE  Cleanes BACH-Installationspaket (dist_type >= 1)    │
│  4. BACKUP      User-Daten sichern (dist_type = 0)                  │
│  5. RESTORE     Aus Paket/Snapshot wiederherstellen                 │
│  6. SYNTHESIZE  Neues System aus Best-of bauen             [NEU]    │
│  7. TEST        Externe Systeme testen (B/O/E-Tests)       [NEU]    │
│  8. COMPARE     Systeme vergleichen (Synopse)              [NEU]    │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘

Ersetzt: BACH_STREAM (archiviert in _ARCHIV/BACH_STREAM/)
```

---

## Das dist_type System

Alle Komponenten haben einen `dist_type` der bestimmt, wie sie behandelt werden:

```
┌─────────────────────────────────────────────────────────────────────┐
│                      DISTRIBUTION TYPES                             │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  dist_type = 2 (CORE)                                               │
│  ├── Systemdateien, unveränderlich                                  │
│  ├── Distribution IST das Backup                                    │
│  └── Beispiele: bach.py, schema.sql, hub.py                         │
│                                                                     │
│  dist_type = 1 (TEMPLATE)                                           │
│  ├── Veränderbar, aber zurücksetzbar                                │
│  ├── 1x Snapshot bei Installation                                   │
│  └── Beispiele: SKILL.md, config.json, identity                     │
│                                                                     │
│  dist_type = 0 (USER_DATA)                                          │
│  ├── Reine Userdaten, nicht in Distribution                         │
│  ├── Normale Backup-Rotation (NAS, lokal)                           │
│  └── Beispiele: tasks, memory, sessions, logs                       │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Wann nutzen?

Nutze diesen Skill wenn der User:
- Einen neuen Skill/Agent erstellen möchte
- Skills/Agents exportieren möchte
- Ein BACH-System weitergeben will
- Ein Backup seiner Userdaten erstellen will
- Daten aus einem Backup wiederherstellen möchte
- Das System auf einen früheren Stand zurücksetzen will

**Trigger-Wörter:** skill erstellen, agent erstellen, exportieren, verpacken, 
distribution, release, installer, weitergeben, backup, sichern, wiederherstellen,
restore, zurücksetzen, reset

---

## 1. CREATE - Neue Komponenten erstellen

### CLI-Tools

| Tool | Zweck | Pfad |
|------|-------|------|
| `structure_generator.py` | Skills & Agents erstellen | `skills/tools/` |
| `os_generator.py` | Vollständiges OS erstellen | `skills/tools/` |

### Profile-Spektrum

```
MICRO        Nur SKILL.md (1 Datei)
LIGHT        Minimale Struktur (~5 Dateien)
STANDARD     Mit Memory (~12 Dateien)
EXTENDED     Mit Mikro-Skills (~20 Dateien)
AGENT        Mit Workflows (~30 Dateien)
AGENT_FULL   Vollständig (~50 Dateien)
```

### Verwendung

```bash
# Skill erstellen (für externes Projekt)
python skills/tools/structure_generator.py analyse MICRO

# Skill erstellen (für BACH)
python skills/tools/structure_generator.py analyse --embedded skill
# → Erstellt nur SKILL.md in hub/_services/

# Agent erstellen
python skills/tools/structure_generator.py schreib-assistent AGENT

# OS erstellen
python skills/tools/os_generator.py mein-os "C:\Projekte"
```

### BACH-Regeln für neue Skills

Bei Erstellung **innerhalb BACH** gelten:

1. **Benennung:** kebab-case, lowercase (`analyze-system.md`)
2. **Format:** Markdown mit Frontmatter
3. **Speicherort:**
   - Service-Skills → `hub/_services/`
   - Agents → `agents/`
   - Workflows → `skills/workflows/`
   - Templates → `skills/_templates/`
4. **Frontmatter-Pflicht:**

```yaml
---
name: skill-name
metadata:
  version: 1.0.0
  last_updated: 2026-01-14
  type: service|agent|workflow
  dist_type: 2  # 0=user, 1=template, 2=core
description: >
  Beschreibung in 1-3 Sätzen
---
```

---

## 2. EXPORT - Komponenten zum Mitnehmen

### CLI-Tool

```bash
python skills/tools/exporter.py <befehl> [optionen]
```

### Befehle

| Befehl | Beschreibung |
|--------|--------------|
| `skill <n>` | Skill aus BACH exportieren |
| `agent <n>` | Agent mit seinen Skills exportieren |
| `os-fresh` | BACH ohne Userdaten exportieren |

### Beispiele

```bash
# Skill exportieren
python skills/tools/exporter.py skill recherche --output recherche.zip

# Agent exportieren (inkl. Dependencies)
python skills/tools/exporter.py agent entwickler --output entwickler.zip

# BACH-Installer erstellen (ohne Userdaten)
python skills/tools/exporter.py os-fresh --output BACH_fresh.zip
```

---

## 3. DISTRIBUTE - Installationspakete (dist_type >= 1)

Distribution erstellt cleane Pakete OHNE Userdaten:

### CLI über bach.py

```bash
# Distribution erstellen
bach dist create base              # → distributions/base.zip
bach dist create base --version 1.1.0

# Verfügbare Distributionen anzeigen
bach dist list

# Distribution installieren (in neuem Ordner)
bach dist install base "C:\Projekte\MeinBach"
```

### Was wird eingepackt?

```sql
-- Nur System-Komponenten (dist_type >= 1)
SELECT * FROM skills WHERE dist_type >= 1;
SELECT * FROM tools WHERE dist_type >= 1;
-- etc.
```

### Distribution-Struktur

```
distributions/
├── base_v1.1.0_2026-01-14.zip
│   ├── SKILL.md            (dist_type=2)
│   ├── bach.py             (dist_type=2)
│   ├── schema.sql          (dist_type=2)
│   ├── hub/                (dist_type=2)
│   ├── skills/tools/              (dist_type=2)
│   ├── skills/             (dist_type=2)
│   ├── skills/docs/help/               (dist_type=2)
│   └── snapshots/          (dist_type=1, Template-Originale)
│       ├── SKILL.md.orig
│       └── config.json.orig
│
└── manifest.json           # Paket-Metadaten
```

---

## 4. BACKUP - User-Daten sichern (dist_type = 0) [NEU]

Backup sichert alle Userdaten (dist_type = 0) als Paket:

### CLI über bach.py

```bash
# Backup erstellen
bach backup create                    # → system/data/system/data/system/data/system/data/backups/userdata_2026-01-14_001.zip
bach backup create --to-nas           # → Direkt auf NAS kopieren

# Backup-Liste anzeigen
bach backup list                      # Lokale Backups
bach backup list --nas                # NAS-Backups

# Backup-Info
bach backup info userdata_2026-01-14_001
```

### Was wird gesichert?

```
dist_type = 0 (USER_DATA):
├── tasks (alle Tasks, Status, History)
├── memory/ (Sessions, Longterm, Archive)
├── logs/ (Session-Logs)
├── ../user/inbox/ (Nachrichten, Agenda)
├── connections/_profiles/ (User-spezifisch)
└── bach.db (nur User-Tabellen)
```

### Backup-Struktur

```
system/data/system/data/system/data/system/data/backups/
├── userdata_2026-01-14_001.zip
│   ├── manifest.json       # Metadaten, Timestamp, Version
│   ├── db_export.json      # Tasks, Memory-Einträge etc.
│   ├── memory/             # Session-Dateien
│   ├── logs/               # Log-Dateien
│   └── ../user/               # Inbox, Agenda
│
├── userdata_2026-01-13_001.zip
└── userdata_2026-01-12_001.zip
```

### Backup-Rotation

| Ort | Aufbewahrung | Intervall |
|-----|--------------|-----------|
| Lokal (`system/data/system/data/system/data/system/data/backups/`) | 7 Backups | Bei Bedarf |
| NAS | 30 Backups | Täglich/Wöchentlich |
| OneDrive | Automatisch | Kontinuierlich |

### NAS-Konfiguration

```json
/ In system_config
{
  "backup_nas_path": "\\NAS-HOST\fritz.nas\Extreme_SSD\BACKUP\BACH_Backups",
  "backup_nas_enabled": true,
  "backup_local_retention": 7,
  "backup_nas_retention": 30
}
```

---

## 5. RESTORE - Wiederherstellen [NEU]

Restore stellt Daten aus verschiedenen Quellen wieder her:

### CLI über bach.py

```bash
# Aus Backup wiederherstellen
bach restore backup userdata_2026-01-14_001
bach restore backup latest            # Neuestes Backup

# Template zurücksetzen (dist_type = 1)
bach restore template SKILL.md        # Einzelne Datei
bach restore template --all           # Alle Templates

# Aus Distribution wiederherstellen (dist_type = 2)
bach restore dist base             # System-Reset auf Basis-Distribution
```

### Restore-Modi

```
┌─────────────────────────────────────────────────────────────────────┐
│                       RESTORE MODI                                  │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  bach restore backup <name>                                         │
│  ├── Stellt Userdaten (dist_type=0) wieder her                      │
│  ├── Überschreibt: tasks, memory, logs, ../user/                       │
│  └── Erstellt vorher Auto-Backup                                    │
│                                                                     │
│  bach restore template <file>                                       │
│  ├── Setzt Datei auf Original zurück (dist_type=1)                  │
│  ├── Nutzt snapshots/*.orig                                         │
│  └── Beispiel: SKILL.md, config.json                                │
│                                                                     │
│  bach restore dist <name>                                           │
│  ├── System-Reset auf Distribution                                  │
│  ├── ACHTUNG: Löscht alle Userdaten!                                │
│  └── Erstellt vorher Full-Backup                                    │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Sicherheits-Checks

```bash
# Restore mit Bestätigung
bach restore backup latest
# → "Achtung: Dies überschreibt aktuelle Userdaten. Fortfahren? [y/N]"

# Restore erzwingen (für Scripts)
bach restore backup latest --force --auto-backup

# Dry-Run (nur anzeigen was passieren würde)
bach restore backup latest --dry-run
```

---

## Entscheidungsbaum

```
Was will ich?
│
├─► Skill/Agent für BACH erstellen?
│   └─► bach create skill <name>
│       └─► structure_generator.py --embedded
│
├─► Skill/Agent als eigenes Projekt?
│   └─► structure_generator.py (MICRO-AGENT_FULL)
│
├─► Skill/Agent aus BACH mitnehmen?
│   └─► exporter.py skill/agent
│
├─► BACH weitergeben (frisch)?
│   └─► bach dist create base
│
├─► Meine Daten sichern?
│   └─► bach backup create [--to-nas]
│
├─► Daten wiederherstellen?
│   └─► bach restore backup <name>
│
├─► Datei auf Original zurücksetzen?
│   └─► bach restore template <file>
│
└─► Komplett-Reset auf Distribution?
    └─► bach restore dist base
```

---

## CLI Schnellreferenz

### bach.py Befehle

```bash
# Distribution
bach dist create <name>               # Paket erstellen
bach dist list                        # Verfügbare anzeigen
bach dist install <name> <pfad>       # Installieren

# Backup
bach backup create                    # Userdaten sichern
bach backup create --to-nas           # Direkt auf NAS
bach backup list                      # Backups anzeigen
bach backup info <name>               # Details

# Restore
bach restore backup <name>            # Aus Backup
bach restore backup latest            # Neuestes
bach restore template <file>          # Template-Reset
bach restore dist <name>              # System-Reset
```

### Direkte Tool-Aufrufe

```bash
# Neuer Skill
python skills/tools/structure_generator.py <n> --embedded skill

# Export
python skills/tools/exporter.py skill <n> --output <n>.zip

# Distribution
python skills/tools/distribution_system.py create base

# Backup
python skills/tools/backup_manager.py create [--to-nas]
python skills/tools/backup_manager.py restore <name>
```

---

## Datenbank-Integration

### dist_type Spalten

```sql
-- Skills
ALTER TABLE skills ADD COLUMN dist_type INTEGER DEFAULT 2;
ALTER TABLE skills ADD COLUMN template_content TEXT;

-- Tools
ALTER TABLE tools ADD COLUMN dist_type INTEGER DEFAULT 2;

-- Tasks (immer User-Daten)
ALTER TABLE tasks ADD COLUMN dist_type INTEGER DEFAULT 0;

-- Memory
ALTER TABLE memory_sessions ADD COLUMN dist_type INTEGER DEFAULT 0;
ALTER TABLE memory_lessons ADD COLUMN dist_type INTEGER DEFAULT 0;
```

### Abfragen

```sql
-- Distribution: Nur System-Komponenten
SELECT * FROM skills WHERE dist_type >= 1;

-- Backup: Nur User-Daten
SELECT * FROM tasks WHERE dist_type = 0;

-- Reset: Template auf Original
UPDATE skills 
SET content = template_content 
WHERE name = ? AND dist_type = 1;
```

---

## Zusammenspiel

```
┌─────────────────────────────────────────────────────────────────────┐
│                        DATENFLUSS                                   │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  CREATE                                                             │
│     │                                                               │
│     ▼                                                               │
│  [skills/, skills/tools/, ...]                                             │
│     │                                                               │
│     ├── dist_type=2 ──► DISTRIBUTE ──► distributions/*.zip          │
│     │                                        │                      │
│     │                                        ▼                      │
│     │                               RESTORE dist ◄──────────────┐   │
│     │                                                           │   │
│     ├── dist_type=1 ──► SNAPSHOT ──► snapshots/*.orig           │   │
│     │                                        │                  │   │
│     │                                        ▼                  │   │
│     │                               RESTORE template            │   │
│     │                                                           │   │
│     └── dist_type=0 ──► BACKUP ──► system/data/system/data/system/data/system/data/backups/*.zip ──► NAS        │   │
│                                        │                        │   │
│                                        ▼                        │   │
│                               RESTORE backup ───────────────────┘   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 6. SYNTHESIZE - Neues System aus Best-of [NEU v3.0]

Synthesize erstellt ein neues LLM-OS System aus den besten Elementen mehrerer Quellsysteme.

### Konzept

```
┌─────────────────────────────────────────────────────────────────────┐
│                      SYNTHESIZE WORKFLOW                             │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Phase 1: ANALYSE                                                   │
│  ├── Quellsysteme testen (B/O/E-Tests)                              │
│  ├── Feature-Mapping erstellen                                      │
│  └── Synopse generieren                                             │
│                                                                     │
│  Phase 2: DESIGN                                                    │
│  ├── Best-of Features identifizieren                                │
│  ├── Architektur festlegen                                          │
│  └── Konzept-Dossier erstellen                                      │
│                                                                     │
│  Phase 3: BUILD                                                     │
│  ├── Struktur generieren                                            │
│  ├── Features portieren                                             │
│  └── Integration testen                                             │
│                                                                     │
│  Phase 4: VALIDATE                                                  │
│  ├── Neues System testen                                            │
│  ├── Vergleich mit Quellsystemen                                    │
│  └── Report generieren                                              │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### CLI-Tools

| Tool | Zweck | Pfad |
|------|-------|------|
| `run_external.py` | Externe Systeme testen | `skills/tools/testing/` |
| `compare_systems.py` | Synopse erstellen | `skills/tools/testing/` |
| `os_generator.py` | Neues OS generieren | `skills/tools/` |

### Verwendung

```bash
# Schritt 1: Quellsysteme testen
python skills/tools/testing/run_external.py --all --profile STANDARD

# Schritt 2: Synopse erstellen
python skills/tools/testing/compare_systems.py --all --output synopse.md

# Schritt 3: Neues OS generieren (mit besten Features)
python skills/tools/os_generator.py BACH_v2 "C:\Projekte" --template EXTENDED

# Schritt 4: Neues System testen
python skills/tools/testing/run_external.py "C:\Projekte\BACH_v2"
```

### Bekannte Systeme

```python
KNOWN_SYSTEMS = {
    "recludOS": "C:\...\.AI\recludOS",
    "BACH": "C:\...\.AI\BACH",
    "_BATCH": "C:\...\.SOFTWARE\_BATCH",
    "_CHIAH": "C:\...\.SOFTWARE\_CHIAH",
    "universal-llm-os-v2": "C:\...\Templates\OS\universal-llm-os-v2",
}
```

### Best-of Herkunft (BACH v1.1)

| Feature | Quelle | Status |
|---------|--------|--------|
| SQLite-First (27 Tabellen) | Eigenentwicklung | ✓ |
| CLI-Hub (bach.py) | _CHIAH | ✓ |
| Steuer-Agent | Eigenentwicklung | ✓ |
| ATI-Agent-Architektur | _BATCH | ✓ |
| Hilfe-System (39 Dateien) | _CHIAH | ✓ |
| Headless-Modus | _BATCH | geplant |
| Distribution-System | recludOS | ✓ |
| Backup/Restore | recludOS | ✓ |

### Archivierte Meta-Systeme

Das ursprüngliche BACH_STREAM Entwicklungssystem wurde archiviert:

```
_ARCHIV/BACH_STREAM/
├── SKILL.txt           # Original Entry Point
├── PRODUCTION/
│   ├── WORKFLOWS/      # 5 Workflows (Synthese, Mapping, etc.)
│   ├── TESTS/          # Test-Framework (jetzt in skills/tools/testing/)
│   └── MAPPING/        # Feature-Mapping DB
└── MEMORY/             # Entwicklungs-Gedächtnis
```

Die relevanten Funktionen sind jetzt in BACH integriert:
- Tests → `skills/tools/testing/`
- Synthese → `builder.md` (dieses Dokument)
- Workflows → `../docs/archived_workflows/`

---

## 7. TEST - Externe Systeme testen [NEU v3.0]

### CLI über Tools

```bash
# Einzelnes System testen
python skills/tools/testing/run_external.py recludOS
python skills/tools/testing/run_external.py "C:\Pfad\zum\System"

# Alle bekannten Systeme testen
python skills/tools/testing/run_external.py --all

# Mit Profil
python skills/tools/testing/run_external.py --all --profile FULL
```

### Test-Profile

| Profil | B-Tests | O-Tests | E-Tests | Dauer |
|--------|:-------:|:-------:|:-------:|-------|
| QUICK | ✓ | - | - | ~2 Min |
| STANDARD | ✓ | ✓ | - | ~5 Min |
| FULL | ✓ | ✓ | manuell | ~10 Min |

### Ergebnisse

```
skills/tools/testing/results/
├── recludOS/
│   ├── B_TEST_recludOS_2026-01-18.json
│   ├── O_TEST_recludOS_2026-01-18.json
│   └── EXTERNAL_TEST_recludOS_2026-01-18.json
├── _BATCH/
├── _CHIAH/
└── SYNOPSE_2026-01-18.md
```

---

## 8. COMPARE - Systeme vergleichen [NEU v3.0]

### CLI

```bash
# Zwei Systeme vergleichen
python skills/tools/testing/compare_systems.py recludOS BACH

# Alle bekannten Systeme
python skills/tools/testing/compare_systems.py --all

# Aus vorhandenen Testergebnissen
python skills/tools/testing/compare_systems.py --from-results

# Mit Output-Datei
python skills/tools/testing/compare_systems.py --all --output vergleich.md
```

### Output

Generiert:
- Markdown-Report mit Ranking
- JSON mit Detail-Daten
- Vergleichstabellen

---

## Entscheidungsbaum (erweitert)

```
Was will ich?
│
├─► Skill/Agent für BACH erstellen?
│   └─► bach create skill <name>
│
├─► Skill/Agent als eigenes Projekt?
│   └─► structure_generator.py
│
├─► Skill/Agent aus BACH mitnehmen?
│   └─► exporter.py skill/agent
│
├─► BACH weitergeben (frisch)?
│   └─► bach dist create base
│
├─► Meine Daten sichern?
│   └─► bach backup create
│
├─► Daten wiederherstellen?
│   └─► bach restore backup <name>
│
├─► Externes System testen?              [NEU]
│   └─► python skills/tools/testing/run_external.py <pfad>
│
├─► Systeme vergleichen?                 [NEU]
│   └─► python skills/tools/testing/compare_systems.py --all
│
└─► Neues System aus Best-of bauen?      [NEU]
    └─► Synthesize-Workflow (siehe oben)
```

---

## Verwandte Skills

- `handle_files.md` - Datei-Sicherheitsregeln
- `archiv.md` - Archivierung
- `skill-export.md` - Anthropic-Upload Format
- `analyze-system.md` - System-Analyse

---

## Changelog

| Version | Datum | Änderungen |
|---------|-------|------------|
| 3.0.0 | 2026-01-18 | SYNTHESIZE, TEST, COMPARE hinzugefügt; BACH_STREAM integriert |
| 2.0.0 | 2026-01-14 | BACKUP & RESTORE hinzugefügt, dist_type integriert |
| 1.0.0 | 2026-01-14 | Initial: CREATE, EXPORT, DISTRIBUTE |