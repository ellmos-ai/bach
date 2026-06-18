# Workflow: Karriere

**Version:** 1.0.0
**Erstellt:** 2026-06-17
**Aktualisiert:** 2026-06-17

---

## Zweck

Wiederverwendbarer Ablauf für Karriere-Usecases, bei denen Ziele,
Qualifikationen, Weiterbildungen oder berufliche Entwicklungslinien
strukturiert verfolgt werden sollen.

Der Workflow deckt insbesondere die Usecases 34 und 35 ab:

- Berufsziele und Kernkomplexe verfolgen
- Fortbildungen und Selbststudium dokumentieren

Primäre BACH-Rollen: Boss-Agent `bueroassistent`, Experte `bewerbungsexperte`.

---

## Leitlinien

1. **Zielpfade explizit halten.**
   Karrierefelder, Qualifikationen und nächste Schritte müssen klar getrennt sein.

2. **Nachweise vor Wunschdenken.**
   Zertifikate, Fortbildungen und dokumentierte Schritte priorisieren.

3. **Planung und Dokumentation verbinden.**
   BACH soll nicht nur archivieren, sondern Fortschritt sichtbar machen.

4. **Mehrgleisigkeit bewusst führen.**
   Parallele Berufsstränge sauber nebeneinander verwalten.

---

## Vorbereitung

```bash
bach usecase show <id>
bach help tasks
bach help docs
bach help memory
```

Zusätzlich prüfen:

- Geht es um Zielplanung, Verlauf oder Belegsammlung?
- Welche Nachweise oder Dokumente sind schon vorhanden?
- Gibt es konkurrierende Prioritäten zwischen mehreren Karrierepfaden?

---

## Ablauf

### 1. Karriereobjekt definieren

- Zielkomplex, Weiterbildung, Zertifikat oder offenes Thema einordnen.

### 2. Bestehende Belege und Ziele lesen

- Dokumente, frühere Pläne, Aufgaben und Memory-Einträge zusammenziehen.

### 3. Strukturierte Laufbahnübersicht bauen

- Ziele, Status, Qualifikationen, Hürden und nächste Schritte bündeln.
- Selbststudium und formale Weiterbildungen getrennt erfassen.

### 4. Fortschrittslogik ergänzen

- Fehlende Nachweise, offene Bewerbungs- oder Lernschritte sichtbar machen.

### 5. Usecase-Check

```bash
bach usecase run <id> --dry-run
bach usecase run-all KARRIERE --dry-run
```

---

## Ergebnis

Ein sauberer Karriere-Usecase liefert:

- eine nachvollziehbare Ziel- und Fortschrittsstruktur,
- belastbare Nachweise statt loser Absichten,
- und klare nächste Entwicklungsschritte.

---

## Changelog

| Version | Datum | Änderung |
|---------|-------|-----------|
| 1.0.0 | 2026-06-17 | Initiale Workflow-Datei für KARRIERE-Usecases |
