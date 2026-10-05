---
name: skill-md-aenderung
version: 1.0.1
type: workflow
author: Claude Opus 4.6
created: 2026-03-12
updated: 2026-03-12
anthropic_compatible: true

trigger: Aenderung am zentralen BACH SKILL.md geplant oder durchgefuehrt
duration: 10-20 Minuten
complexity: low

dependencies:
  tools: []
  skills: []

description: >
  Workflow fuer Aenderungen am zentralen BACH SKILL.md.
  Regelt die Abfolge von Aenderung, Versionierung, Synchronisation
  und Uebersetzung.
---

# SKILL.md Aenderungs-Workflow

> Workflow fuer Aenderungen am zentralen BACH SKILL.md (Abfolge, Versionierung, Synchronisation, Uebersetzung).

## Wann anwenden

Bei jeder Aenderung am zentralen BACH `SKILL.md` (Root: `BACH/SKILL.md`).

## Ablauf

### 1. Aenderung planen

- Welche Sektion wird geaendert/ergaenzt?
- Ist die Aenderung rueckwaertskompatibel?
- Betrifft sie auch das englische Template oder andere Sprachversionen?

### 2. Version hochzaehlen

```
Patch (X.Y.Z+1): Tippfehler, kleine Korrekturen
Minor (X.Y+1.0): Neue Sektionen, neue Themen-Pakete
Major (X+1.0.0): Strukturelle Umbauten, Breaking Changes
```

Im YAML-Header:
- `version:` hochzaehlen
- `updated:` auf aktuelles Datum setzen

### 3. Aenderung durchfuehren

- Primaere Datei: `BACH/SKILL.md` (Root)
- Changelog-Eintrag unter `## CHANGELOG` hinzufuegen (neueste Version oben)
- Navigations-Karte in `Dokument-Struktur` aktualisieren falls neue Sektionen

### 4. Synchronisation

Die folgenden Dateien muessen nach Aenderung synchronisiert werden:

| Datei | Pfad | Aktion |
|-------|------|--------|
| Claude-Skill-Kopie | `~/.claude/skills/bach/SKILL.md` | Kopieren oder `bach skills reload` |
| English Version | `BACH/SKILL_EN.md` (falls vorhanden) | Uebersetzen |
| Templates | `system/_templates/TEMPLATE_SKILL.md` | Pruefen ob betroffen |
| LobeHub | automatisch (crawlt GitHub) | Kein manueller Schritt |

### 5. Validierung

```bash
# Version pruefen
bach skills version bach

# Help-System pruefen (falls neue Help-Verweise)
bach help <neues_thema>

# Skill-Reload
bach skills reload
```

### 6. Folge-Tasks anlegen

Wenn die Aenderung auch andere Dateien betrifft:

```bash
bach task add "SKILL.md v<X.Y.Z>: English version aktualisieren" --priority medium
bach task add "SKILL.md v<X.Y.Z>: Templates pruefen" --priority low
```

## Checkliste

- [ ] Version hochgezaehlt
- [ ] updated-Datum gesetzt
- [ ] Changelog-Eintrag hinzugefuegt
- [ ] Navigations-Karte aktualisiert (falls noetig)
- [ ] Claude-Skill-Kopie synchronisiert
- [ ] English Version Task angelegt
- [ ] Templates geprueft

## Siehe auch

- `system-synopse.md` -- Systemvergleich und Ueberblick
- `cross-system-sync.md` -- Synchronisation zwischen Systemen

## Changelog

### v1.0.1 (2026-03-12)
- Fix: type von `protocol` auf `workflow` korrigiert
- Fehlende Header-Felder ergaenzt (trigger, duration, complexity)
- Template-konforme Sektionen hinzugefuegt (Siehe auch, Changelog, Footer)

### v1.0.0 (2026-03-12)
- Initiale Version

---
BACH Skill-Architektur v2.0
