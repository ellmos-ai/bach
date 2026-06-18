# Workflow: Haushalt

**Version:** 1.0.0
**Erstellt:** 2026-06-17
**Aktualisiert:** 2026-06-17

---

## Zweck

Wiederverwendbarer Ablauf für Haushalts-Usecases, bei denen Routinen,
Turnusse und praktische Organisationsaufgaben gepflegt oder geprüft werden.

Der Workflow deckt insbesondere Usecase 31 ab:

- Haushaltsaufgaben nach Turnus verwalten

Primäre BACH-Rolle: Experte `haushaltsmanagement`.

---

## Leitlinien

1. **Turnus ist die Kernlogik.**
   Täglich, wöchentlich, monatlich und jährlich müssen getrennt auswertbar sein.

2. **Praktische Erledigung vor schöner Theorie.**
   Der Workflow soll reale nächste Aufgaben sichtbar machen.

3. **Wiederholbarkeit sichern.**
   Einträge sollen für den nächsten Haushaltsscan nutzbar bleiben.

4. **Status sauber halten.**
   Erledigt, offen, überfällig und unbekannt nicht vermischen.

---

## Vorbereitung

```bash
bach usecase show 31
bach help routine
bach help tasks
bach tools search haushalt
```

Zusätzlich prüfen:

- Gibt es eine vorhandene Haushaltsliste oder Turnusquelle?
- Geht es um reine Anzeige oder um Statuspflege?
- Welche Aufgaben sind zeitkritisch?

---

## Ablauf

### 1. Haushaltsquelle prüfen

- Bestehende Listen, Routinen oder Dokumente als Referenzbasis nutzen.

### 2. Aufgaben nach Turnus ordnen

- Intervalle, letzter Erledigungszeitpunkt und nächster Fälligkeitspunkt
  nachvollziehbar machen.

### 3. Priorisierte Übersicht erzeugen

- Besonders überfällige oder seltene Aufgaben hervorheben.

### 4. Anschluss an Aufgabenlogik sichern

- Wenn nötig, aus Routinen konkrete Tasks oder Erinnerungen ableiten.

### 5. Usecase-Check

```bash
bach usecase run 31 --dry-run
bach usecase run-all HAUSHALT --dry-run
```

---

## Ergebnis

Ein sauberer Haushalts-Usecase endet mit:

- einer klaren Turnusübersicht,
- sichtbaren offenen oder überfälligen Aufgaben,
- und einer Basis für wiederkehrende Routinepflege.

---

## Changelog

| Version | Datum | Änderung |
|---------|-------|-----------|
| 1.0.0 | 2026-06-17 | Initiale Workflow-Datei für HAUSHALT-Usecases |
