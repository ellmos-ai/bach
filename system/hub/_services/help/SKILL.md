---
name: help-forensik
version: 1.0.0
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
    - help-forensic.md

description: >
  Systematische Ueberpruefung der Help-Dokumentation auf Aktualitaet.
  Vergleicht dokumentierten Soll-Zustand mit tatsaechlicher Implementierung
  und aktualisiert entweder Help oder Roadmap. Recurring: 14 Tage.
---

# Help-Forensik Service

**Kategorie:** Qualitaetssicherung & Dokumentation
**Recurring:** help_forensic (alle 14 Tage)

---

## Zweck

Systematische Ueberpruefung der Help-Dokumentation auf Aktualitaet.
Vergleicht dokumentierten Soll-Zustand mit tatsaechlicher Implementierung
und aktualisiert entweder Help oder Roadmap.

---

## Trigger

### Automatisch (Recurring Task)
- Intervall: 14 Tage
- Task: "Help-Forensik: Eine docs/help/*.txt pruefen..."
- Ziel: Dokumentation immer aktuell halten

### Manuell
- Nach groesseren Code-Aenderungen
- Bei Nutzer-Meldung "Doku stimmt nicht"
- Nach Implementierung von Roadmap-Tasks

### Ereignis-basiert
- CLI-Handler geaendert (hub/*.py)
- Neuer Befehl hinzugefuegt
- Feature-Implementierung abgeschlossen

---

## Workflow (Kurzfassung)

```
1. HELP-DATEI AUSWAEHLEN
   └─> Zufaellig aus docs/help/*.txt
   └─> Oder nach Auftrag spezifisch
   └─> Priorisierung: aelteste zuerst

2. DOKUMENTIERTEN ZUSTAND ERFASSEN
   └─> Beschriebene Befehle extrahieren
   └─> Beschriebene Funktionen notieren
   └─> Beschriebene Dateipfade merken

3. FORENSISCHE UNTERSUCHUNG
   └─> Befehle testen (bach --help X)
   └─> Code pruefen (hub/)
   └─> Pfade verifizieren
   └─> Funktionen aufrufen

4. ABWEICHUNGEN KLASSIFIZIEREN
   ┌─> VERBESSERUNG: System besser als dokumentiert
   │   └─> Help aktualisieren
   │   └─> CHANGELOG Eintrag
   │
   └─> ZIELZUSTAND NICHT ERREICHT: Feature fehlt
       └─> In Tasks/Roadmap pruefen
       └─> Wenn nicht geplant: Hinzufuegen
       └─> Status dokumentieren

5. KONTEXT-RECHERCHE (bei Zweifeln)
   └─> ROADMAP.md pruefen
   └─> Tasks-Tabelle pruefen
   └─> Logs durchsuchen
   └─> Memory/Sessions lesen

6. AKTION DURCHFUEHREN
   └─> Help anpassen ODER
   └─> Roadmap/Tasks erweitern
   └─> Analysebericht speichern
   └─> CHANGELOG aktualisieren
```

---

## Analyse-Schema (standardisiert)

```
HELP-FORENSIK ANALYSEBERICHT
============================
Datum: YYYY-MM-DD
Datei: docs/help/[name].txt
Letzte Aenderung: [Datum der Datei]

DOKUMENTIERTER ZUSTAND
----------------------
Befehle: [Liste der beschriebenen Befehle]
Funktionen: [Liste der beschriebenen Features]
Pfade: [Referenzierte Dateien/Ordner]

FORENSISCHE BEFUNDE
-------------------
| Befehl/Feature | Dokumentiert | Tatsaechlich | Status |
|----------------|--------------|--------------|--------|
| bach --X       | Ja           | Funktioniert | OK     |
| bach --Y       | Ja           | Fehlt        | LUECKE |
| bach --Z       | Nein         | Existiert    | NEU    |

ABWEICHUNGEN
------------
1. [Beschreibung der Abweichung]
   Klassifikation: [VERBESSERUNG | ZIELZUSTAND_FEHLT]
   Begruendung: [Warum diese Klassifikation]

DURCHGEFUEHRTE AKTION
---------------------
[ ] Help aktualisiert: [Details]
[ ] Roadmap erweitert: [Task-ID]
[ ] CHANGELOG Eintrag erstellt
```

---

## Dateien

```
hub/_services/docs/help/
├── SKILL.md              # Diese Datei
├── help_forensic.py      # Hauptlogik (TODO)
├── templates/
│   └── report_template.md    # Bericht-Vorlage
└── reports/
    └── [archivierte Berichte]
```

---

## Integration

### Mit Recurring Tasks
- config.json: help_forensic (14 Tage)
- Automatische Task-Erstellung

### Mit Help-System
- Liest docs/help/*.txt
- Schreibt docs/help/*.txt (bei Korrekturen)
- Beachtet docs/help/practices.txt (#7: HELP ALS WAHRHEIT)

### Mit Roadmap
- Liest ROADMAP.md
- Schreibt neue Tasks zu ROADMAP.md

### Mit Task-System
- Liest bach.db/tasks
- Erstellt neue Tasks bei Luecken

---

## Abgrenzung

| Dieser Service | Wiki-Autoren Service |
|----------------|---------------------|
| Prueft BESTEHENDES | Erstellt NEUES |
| Fokus: Ist vs Soll | Fokus: Agenten-Bedarfe |
| Output: Help-Korrekturen | Output: Wiki-Artikel |
| Forensische Analyse | Recherche & Synthese |

---

## Siehe auch

- `skills/workflows/help-forensic.md` - Detaillierter Workflow
- `docs/help/practices.txt` - Best Practices (#7: HELP ALS WAHRHEIT)
- `bach --maintain docs` - Dokumentations-Checker
- `hub/_services/wiki/SKILL.md` - Wiki-Autoren Service
