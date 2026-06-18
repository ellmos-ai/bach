# Workflow: Datenmodul

**Version:** 1.0.0
**Erstellt:** 2026-06-17
**Aktualisiert:** 2026-06-17

---

## Zweck

Wiederverwendbarer Ablauf für medizinisch-analytische Daten-Usecases, bei
denen Diagnosen, Symptome, Untersuchungen oder Medikationsverläufe
strukturiert gepflegt und ausgewertet werden.

Der Workflow deckt insbesondere die Usecases 17 bis 21 ab:

- Diagnosen und Hypothesen verwalten
- Symptomverlauf dokumentieren
- Symptomabdeckung analysieren
- Medikamentationsverlauf führen
- Untersuchungsplan erstellen

Primäre BACH-Rolle: Boss-Agent `gesundheitsassistent`.
Typische Experten: `gesundheitsverwalter`, `health_import`.

---

## Leitlinien

1. **Hypothesen von Fakten trennen.**
   Gesichert, Verdacht, Hypothese und widerlegt müssen sauber unterscheidbar sein.

2. **Zeitachsen ernst nehmen.**
   Verläufe brauchen Start, Ende, Änderung, Auslöser und Quelle.

3. **Ableitungen begründen.**
   Wenn BACH Untersuchungen priorisiert oder Symptomabdeckung bewertet,
   muss die zugrunde liegende Struktur nachvollziehbar bleiben.

4. **Medizinische Unsicherheit offen lassen.**
   Fehlende Daten dürfen nicht durch Vermutungen kaschiert werden.

---

## Vorbereitung

```bash
bach usecase show <id>
bach help gesundheit
bach help docs
bach help memory
bach tools search diagnose
```

Zusätzlich prüfen:

- Welche Quelle ist maßgeblich: Bericht, Tabelle, User-Notiz, Laborwert?
- Geht es um Pflege, Analyse oder Planung?
- Ist die relevante Zeitachse vollständig genug?

---

## Ablauf

### 1. Datenart eingrenzen

- Diagnoseverwaltung, Symptomverlauf, Medikationshistorie und
  Untersuchungsplanung als getrennte Datenprodukte behandeln.

### 2. Quellen und Evidenzgrad sortieren

- Berichte, Arztangaben und strukturierte Listen priorisieren.
- Unbestätigte Aussagen als offen markieren.

### 3. Strukturierte Analyse aufbauen

- Diagnosen nach Evidenzstatus ordnen.
- Symptome über Zeit und Schweregrad bündeln.
- Medikationsverläufe mit Wirkung und Nebenwirkung verbinden.
- Untersuchungsbedarf aus offenen Hypothesen ableiten.

### 4. Restlücken sichtbar machen

- Fehlende Belege, offene Fragen und ungeklärte Symptome benennen.

### 5. Usecase-Check

```bash
bach usecase run <id> --dry-run
bach usecase run-all DATENMODUL --dry-run
```

---

## Ergebnis

Ein sauberer Datenmodul-Usecase endet mit:

- einer nachvollziehbaren, strukturierten Gesundheitsanalyse,
- sauber markierter Evidenzlage,
- und einer Basis für spätere Care-, Bericht- oder Planungsfälle.

---

## Changelog

| Version | Datum | Änderung |
|---------|-------|-----------|
| 1.0.0 | 2026-06-17 | Initiale Workflow-Datei für DATENMODUL-Usecases |
