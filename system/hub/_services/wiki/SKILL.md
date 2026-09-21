---
name: wiki-autoren
version: 2.0.0
type: service
author: BACH Team
created: 2026-01-24
updated: 2026-09-18
anthropic_compatible: true
status: active

dependencies:
  tools: []
  services: []
  workflows:
    - wiki-author.md

description: >
  Automatische Erweiterung, Aktualisierung und Qualitaetssicherung
  der Wiki-Wissensbasis in wiki/. Drei Modi: Erstellen,
  Aktualisieren, Validieren. Recurring: 21 Tage.
---

# Wiki-Autoren Service

**Kategorie:** Dokumentation & Wissen
**Recurring:** wiki_author (alle 21 Tage)

---

## Zweck

Automatische Erweiterung, Aktualisierung und Qualitaetssicherung der
Wiki-Wissensbasis in `wiki/`.

Der Service hat drei Hauptaufgaben:

1. **ERSTELLEN** - Neue Artikel basierend auf Agenten/Experten-Bedarfen
2. **AKTUALISIEREN** - Bestehende Artikel auf Aktualitaet pruefen
3. **VALIDIEREN** - Fakten durch Stichproben verifizieren

---

## Modi

### Modus A: Neuen Artikel erstellen

Identifiziert Wissensluecken bei Agenten/Experten und erstellt
gezielte Wiki-Beitraege durch Web-Recherche.

- Analysiert Agent-Profile (SKILL.md, manifest.json)
- Identifiziert fehlende Wissensartikel
- Recherchiert in Web, Wikipedia, Fach-Datenbanken
- Erstellt formatierten Wiki-Artikel
- Entscheidet: Einzelartikel oder Themenordner

### Modus B: Artikel aktualisieren

Prueft bestehende Artikel auf Aktualitaet basierend auf
Validierungsmetadaten.

- Findet Artikel mit faelliger Pruefung
- Verifiziert Quellen (noch erreichbar? aktuell?)
- Aktualisiert Inhalte bei Bedarf
- Erneuert Validierungsmetadaten

### Modus C: Fakten-Stichprobe

Qualitaetssicherung durch Verifizierung einzelner Fakten.

- Waehlt zufaelligen Artikel
- Extrahiert 3-5 pruefbare Fakten
- Recherchiert jeden Fakt
- Bewertet Artikelqualitaet
- Empfiehlt Massnahmen

---

## Trigger

### Automatisch (Recurring Task)
- Intervall: 21 Tage
- Rotation: A → B → C → A → ...
- Task: "Wiki-Autoren: [Modus] durchfuehren..."

### Manuell
- Bei Erstellung neuer Agenten/Experten
- Bei Identifikation von Wissenslucken
- Nach Nutzer-Anfrage zu fehlendem Wissen

### Ereignis-basiert
- Neuer Agent in agents/ erkannt
- Nutzer fragt nach Thema das nicht in Wiki ist
- Agent meldet fehlendes Kontextwissen

---

## Validierungsmetadaten

Jeder Wiki-Artikel sollte diese Metadaten haben:

```
# Portabilitaet: UNIVERSAL|SYSTEM|PRIVAT
# Zuletzt validiert: YYYY-MM-DD (Autor)
# Naechste Pruefung: YYYY-MM-DD
# Quellen: [URL1], [URL2]
```

---

## Ordnerstruktur

Wiki-Artikel koennen in zwei Formen existieren:

**Einzelartikel (allgemeines Wissen):**
```
wiki/icf.txt
wiki/datev.txt
```

**Themenordner (Domain-Wissen fuer Agenten/Experten):**
```
wiki/foerderung/
├── _index.txt
├── icf.txt
├── teacch.txt
└── pecs.txt
```

---

## Dateien

```
hub/_services/wiki/
├── SKILL.md              # Diese Datei
├── wiki_author.py        # Hauptlogik (TODO)
└── templates/
    └── article_template.txt  # Wiki-Artikel-Vorlage
```

---

## Integration

### Mit Recurring Tasks
- config.json: wiki_author (21 Tage)
- Modus-Rotation gespeichert in config
- Automatische Task-Erstellung

### Mit Agenten
- Liest agents/*/SKILL.md
- Liest agents/_experts/*/SKILL.md
- Identifiziert Wissensbedarfe
- Erstellt Agent-spezifische Unterordner

### Mit Wiki-System
- Schreibt nach wiki/ oder wiki/[domain]/
- Aktualisiert wiki/_index.txt
- Beachtet wiki_konventionen.txt
- Verwaltet Validierungsmetadaten

---

## Abgrenzung

| Dieser Service | Help-Forensik Service |
|----------------|----------------------|
| Erstellt/pflegt WIKI-Wissen | Prueft HELP-Anleitungen |
| Fokus: Agenten-Bedarfe | Fokus: Ist vs Soll |
| Output: Wiki-Artikel | Output: Help-Korrekturen |
| 3 Modi: Erstellen/Aktualisieren/Validieren | 1 Modus: Forensische Pruefung |

---

## Siehe auch

- `skills/workflows/wiki-author.md` - Detaillierter Workflow (v2.0)
- `wiki/_index.txt` - Wiki-Verzeichnis
- `wiki/wiki_konventionen.txt` - Format-Regeln
- `hub/_services/docs/help/SKILL.md` - Help-Forensik Service
