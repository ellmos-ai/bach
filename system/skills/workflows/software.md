# Workflow: Software-Integrationen

**Version:** 1.0.0
**Erstellt:** 2026-06-13
**Aktualisiert:** 2026-06-13

---

## Zweck

Wiederverwendbarer Ablauf für Software-bezogene BACH-Usecases, bei denen
bestehende Tools, Datenbanken, Exporte oder Spezial-Apps in BACH genutzt,
integriert oder weiterentwickelt werden sollen.

Der Workflow deckt insbesondere die Software-Usecases 41 bis 49 ab:

- FormBuilder Formulare erstellen
- HausLagerist Datenbank auslesen
- FinancialProof Dashboard integrieren
- MasterRoutine Datenbank nutzen
- MediPlaner Datenbank nutzen
- MediaBrain Datenbank nutzen
- ProFiler Wissen indizieren
- RPG-Agent Spielleitung führen
- MetaWiki erstellen und exportieren

---

## Leitlinien

1. **Bestehende BACH-Flächen zuerst prüfen.**
   Bevor neue Skripte oder Brücken entstehen, zuerst Handler, Services,
   Skills, Wiki und Help durchsuchen.

2. **Handler First.**
   Fehlt eine Fähigkeit, gehört sie nach `hub/` oder `hub/_services/`,
   damit sie über CLI, API und später auch GUI/MCP konsistent erreichbar ist.

3. **Austauschformate bevorzugen.**
   Externe Tools sollen, wenn möglich, über stabile JSON-, SQLite- oder
   Export-/Import-Pfade an BACH angebunden werden statt über fragile
   manuelle Zwischenlösungen.

4. **Release-reif abschließen.**
   Jede Integration endet mit Usecase-Prüfung, gezielten Tests und einem
   kurzen Doku-/Release-Nachzug.

---

## Schnelle Zuordnung

| Bereich | Bestehende BACH-Fläche | Fokus |
|---------|-------------------------|-------|
| FormBuilder | Skill/Handler prüfen, bei Lücke neuen Handler anlegen | Formulare erzeugen, speichern, exportieren |
| HausLagerist | `bach haushalt`, `bach household` | Inventar, Lagerorte, Kosten |
| MediPlaner | `bach mediplaner`, `bach gesundheit` | Medikamente, Kontakte, Austauschformat |
| MediaBrain | `bach media` | Medienbestand, Suche, Metadaten |
| MasterRoutine | `bach routine`, `bach haushalt` | Routinen, Turnus, Status |
| ProFiler | `bach profiler`, `bach search index` | Dateianalyse, OCR-nahe Vorarbeit, Indizierung |
| MetaWiki | `bach wiki`, `bach search` | Wissensstruktur, Export, Navigation |
| FinancialProof | `hub/_services/market/` | Analyse-Backend in BACH, UI ggf. separat |
| RPG-Agent | Agent/Prompt/Wissensfluss | Spielleitung, Welt- und Sitzungslogik |

---

## Vorbereitung

```bash
bach usecase show <id>
bach help mediplaner
bach help profiler
bach help media
bach help haushalt
bach help routine
bach help search
bach tools search <begriff>
```

Zusätzlich prüfen:

- Welche Datenquelle ist konkret gemeint: SQLite, JSON, Dateien, GUI oder API?
- Gibt es bereits einen passenden Handler oder Service?
- Ist das Ziel eine Vollintegration, ein Austauschformat oder bewusst nur ein
  Backend-Baustein?

---

## Ablauf

### 1. Zielbild festziehen

- Gewünschten Usecase konkretisieren.
- Klären, ob BACH lesen, schreiben, exportieren oder aktiv steuern soll.
- Ergebnisform festlegen: CLI-Ausgabe, DB-Import, Exportdatei, GUI-Funktion,
  Agentenfähigkeit oder wiederverwendbarer Service.

### 2. Bestand aufnehmen

- Relevante Help-Dateien lesen.
- Vorhandene Handler/Services/Wiki-Einträge suchen.
- Datenquelle und aktuelles Austauschformat prüfen.
- Bereits vorhandene Tests, Migrationsdateien oder Integrationshinweise
  sammeln.

### 3. Bestehende Fläche nutzen oder Lücke schließen

- Wenn ein Handler schon passt: erweitern, nicht duplizieren.
- Wenn nur Teilflächen existieren: fehlende Operation ergänzen.
- Wenn gar keine tragfähige Fläche existiert: neuen Handler oder Service
  anlegen und sauber an BACH anbinden.

### 4. Usecase gegen die echte Oberfläche prüfen

Mindestens:

```bash
bach usecase run <id> --dry-run
bach usecase run-all --dry-run
```

Ergänzend je nach Eingriff:

- `python -m pytest system/tests/test_<bereich>.py -q`
- `bach upgrade check --json`
- `bach lang report --surface gui --limit 20 --json` bei GUI-Änderungen

### 5. Doku und Release-Nachzug

- README / README.de nur anfassen, wenn sich die User-Oberfläche oder der
  Release-Status sichtbar verändert hat.
- `ROADMAP.md`, `CHANGELOG.md` und `.dev/NEXT_RELEASE.md` nachziehen, wenn
  ein Release-Ziel oder eine offene Lücke tatsächlich verschoben wurde.
- Bei deutschen Endnutzertexten echte Umlaute prüfen.

---

## Ergebnis

Ein sauberer Software-Usecase hat am Ende:

- eine reale BACH-Fläche statt manueller Sonderlogik,
- mindestens einen funktionierenden Dry-Run oder Smoke,
- gezielte Regressionen für neue Pfadauflösung oder Handlerlogik,
- und einen kurzen Release-/Roadmap-Nachzug, falls sich der Systemstand
  sichtbar verbessert hat.

---

## Beispiel

```bash
bach usecase show 41
bach usecase run 41 --dry-run
python -m pytest system/tests/test_tuev_handler.py -q -k software
bach usecase run-all --dry-run
```

---

## Changelog

| Version | Datum | Änderung |
|---------|-------|-----------|
| 1.0.0 | 2026-06-13 | Initiale Workflow-Datei für die Software-Usecases 41-49 |
