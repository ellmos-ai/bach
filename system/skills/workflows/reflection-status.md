# Workflow: Reflection Status

**Version:** 1.0.0
**Erstellt:** 2026-06-17
**Aktualisiert:** 2026-06-17

---

## Zweck

Wiederverwendbarer Ablauf für Reflection-Usecases, bei denen BACH seinen
eigenen Leistungsstand, Lernfortschritt oder offene Schwachstellen
zusammenfassen soll.

Der Workflow deckt insbesondere Usecase 50 ab:

- Reflection Status

Primäre BACH-Rolle: Agent `reflection-agent`.
Zentrale Oberfläche: `bach reflection`.

---

## Leitlinien

1. **Status vor Deutung.**
   Erst Metriken, offene Tasks, Session-Volumen und vorhandene Lessons
   zeigen, dann Interpretationen ableiten.

2. **Lücken explizit benennen.**
   Reflection ist nur nützlich, wenn Schwachstellen sichtbar werden.

3. **Keine Scheingenauigkeit.**
   Wo BACH keine Metrik hat, bleibt der Befund offen.

4. **Verbesserung anschlussfähig machen.**
   Erkenntnisse sollten in Tasks, Lessons oder nächste Daily-Care-Schritte
   übersetzbar sein.

---

## Vorbereitung

```bash
bach usecase show 50
bach help reflection
bach reflection status
```

Optional ergänzen:

```bash
bach reflection review 30
bach reflection gaps
bach reflection log
```

---

## Ablauf

### 1. Reflection-Ziel festlegen

- Kurzstatus, Zeitraumanalyse oder Gap-Review unterscheiden.

### 2. Reflection-Oberfläche ausführen

- Für den Standardfall `bach reflection status` nutzen.
- Bei Zeitvergleichen `review`, bei Schwachstellen `gaps`, bei Rohmetrik
  `log` ergänzen.

### 3. Befund strukturieren

- Tasks, Sessions, Lessons und Metriken als getrennte Blöcke lesen.
- Auffällige Lücken oder Staupunkte markieren.

### 4. Nächste Schritte ableiten

- Wenn offene Schwächen sichtbar werden, in Daily-Care, Tasks oder
  Release-Planung zurückspiegeln.

### 5. Usecase-Check

```bash
bach usecase run 50 --dry-run
bach usecase run-all reflection_status --dry-run
```

---

## Ergebnis

Ein sauberer Reflection-Usecase endet mit:

- einem realen Performance-Befund statt Bauchgefühl,
- sichtbaren Lücken,
- und ableitbaren Folgeaktionen für BACH.

---

## Changelog

| Version | Datum | Änderung |
|---------|-------|-----------|
| 1.0.0 | 2026-06-17 | Initiale Workflow-Datei für reflection_status |
