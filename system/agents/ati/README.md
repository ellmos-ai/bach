# ATI - Advanced Tool Integration Agent

> Software-Entwickler-Agent für BACH

## Konzept

```text
BATCHI = _BATCH + _CHIAH (Best-of Synopse)
ATI    = BATCHI - BACH (Delta zu BACH-Core)
BACH + ATI = BATCHI (vollständiger Software-Entwickler)
```

## Wichtig: Eigene Task-Verwaltung

ATI verwaltet **eigene** Software-Entwicklungs-Tasks:

- Scanner für `AUFGABEN.txt`, `TODO.md`, `AUFGABEN.md`, `ROADMAP.md` und `DONE.md`
- `bach.db` / `ati_tasks` für ATI-Tasks, getrennt von BACH-Core-Tasks
- Onboarding neuer Projekte als ATI-Feature

BACH-System-Tasks (`bach.db/tasks`) bleiben separat.

## Ordnerstruktur

```text
agents/ati/
├── ATI.md
├── README.md
├── data/
│   └── config.json
├── prompt_templates/
├── scanner/
│   └── task_scanner.py
├── session/
├── tools/
└── export/
```

## CLI

```bash
bach ati start           # Headless-Daemon starten
bach ati stop            # Daemon stoppen
bach ati status          # Status anzeigen
bach ati task list       # ATI-Tasks (Software-Entwicklung)
bach ati scan            # Task-Dateien in Software-Projekten scannen
bach ati onboard PATH    # Neues Projekt onboarden
bach ati export          # Als BATCHI exportieren
```

## Export: BATCHI

ATI kann als "BATCHI" exportiert werden:

```bash
bach ati export          # -> batchi.zip
```

Das Paket enthält alles, was ein standalone Software-Entwickler-Agent braucht.

## Status

- [x] Konzept dokumentiert
- [x] Ordnerstruktur angelegt
- [x] `config.json` erstellt
- [x] Prompt-Templates erstellt (`task`, `review`, `analysis`)
- [x] CLI-Handler (`hub/ati.py`)
- [x] Scanner-Migration
- [ ] Headless Sessions
- [ ] Export-System
