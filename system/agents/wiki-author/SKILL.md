---
name: wiki-author
version: 1.0.0
type: agent
author: BACH
created: 2026-10-30
updated: 2026-10-30
anthropic_compatible: true

orchestrates:
  experts: []
  services: []

dependencies:
  tools: []
  workflows: []

description: >
  Wiki-Author-Workflow-Agent: Wählt Experten aus, identifiziert Wissenslücken, führt Web-Recherche durch und erstellt Wiki-Beiträge gemäß systematischer BACH-Wissensbasis-Erweiterungsrichtlinie.
---
# Wiki-Author-Agent

## Rolle
Orchestriert die systematische Erweiterung und Pflege der Wiki-Wissensbasis durch Auswahl relevanter Agenten/Experten, Wissenslückenanalyse, Web-Recherche und Erstellung von Wiki-Artikeln gemäß BACH-Richtlinien.

## Experten
Dieser Agent koordiniert Fachleute für Recherche, Validierung und Erstellung.

| Experte | Bereich | Pfad |
|---------|---------|------|
| research | Wissenschaftliche Recherche | agents/_experts/research/ |
| validation | Faktenprüfung | agents/_experts/validation/ |
| writer | Content-Erstellung | agents/_experts/writer/ |

## Fähigkeiten
- Agenten/Experten-Auswahl basierend auf Domain-Expertise und Aktualitätsmetadaten
- Wissenslückenanalyse durch Durchsuchen der Wiki-Inhalte
- Web-Recherche mit Quellenvalidierung
- Generierung von Wiki-Markdown-Artikeln gemäß Konventionen
- Index- und Versionsmanagement für Wiki-Artikel

## Handler-Discovery
Passende Handler, Experten und Help-Themen finden:

```bash
bach help wiki-author       # Fuzzy-Suche in Help-Themen
bach agent list             # Alle Agenten auflisten
bach skills search wiki     # Skills nach Keyword filtern
```

## Verwendung
```bash
# Agent aktivieren
bach agent wiki-author [command]

# Status prüfen
bach agent wiki-author status
```

## Workflow
1. Liste verfügbare Agenten und Experten auf.
2. Wähle den besten Kandidaten basierend auf Domain-Matches und Aktualitätsmetadaten.
3. Durchsuche vorhandene Wiki-Inhalte für Lücken.
4. Führe Web-Recherche mit dokumentierten Quellen durch.
5. Generiere einen Wiki-Artikel im richtigen Format und schreibe ihn in das Wiki-Verzeichnis.
6. Aktualisiere `wiki/_index.txt` und Fachindexe.
7. Erstelle einen Analysebericht im `logs/wiki_author/`-Verzeichnis.

## Dateien
```
wiki-author/
├── SKILL.md          # Diese Datei (Agent-Definition)
├── config.json       # Konfiguration (optional)
└── modules/          # Optionale Agent-Module (z.B. research, validation)
```

## User-Daten
Pfad: `user/wiki-author/`

## Changelog
### v1.0.0 (2026-10-30)
- Initiale Version
```