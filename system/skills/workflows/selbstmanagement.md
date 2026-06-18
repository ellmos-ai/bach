# Workflow: Selbstmanagement

**Version:** 1.0.0
**Erstellt:** 2026-06-17
**Aktualisiert:** 2026-06-17

---

## Zweck

Wiederverwendbarer Ablauf für Selbstmanagement-Usecases, bei denen
Routinen, ADHS-Strategien, Lebensbalance oder persönliche Arbeitsweisen
unterstützt werden sollen.

Der Workflow deckt insbesondere die Usecases 33 und 36 ab:

- Lebenskreise-Bereiche Balance prüfen
- ADHS-Strategien anwenden

Primäre BACH-Rolle: Boss-Agent `persoenlicher-assistent`.

---

## Leitlinien

1. **Entlastung vor Vollstopfen.**
   Selbstmanagement soll reduzieren, priorisieren und handhabbar machen.

2. **Praktische Strategien vor abstrakten Idealen.**
   Hilfreich sind Routinen, Listen, Trigger und nächste kleine Schritte.

3. **Überforderung sichtbar machen.**
   Balance-Fragen brauchen klare Engpasssignale.

4. **Wiederverwendbare Muster sichern.**
   Funktionierende Strategien sollten in BACH wieder auffindbar bleiben.

---

## Vorbereitung

```bash
bach usecase show <id>
bach help tasks
bach help memory
bach help reflection
```

Zusätzlich prüfen:

- Geht es um Tagesstruktur, Balance, Fokus oder Strategiepflege?
- Welche bestehenden Routinen oder Hilfen gibt es schon?
- Wo liegt die aktuelle Überlastung oder Reibung?

---

## Ablauf

### 1. Selbstmanagement-Thema eingrenzen

- Balance, Fokusproblem, ADHS-Strategie oder Routinenutzung unterscheiden.

### 2. Bestehende Hilfen lesen

- Vorhandene Listen, Tasks, Routinen, Memory-Einträge und Lessons sichten.

### 3. Handhabbare Struktur bauen

- Lebensbereiche, Belastungen und nächste Schritte sichtbar machen.
- Strategien so formulieren, dass sie im Alltag wiederverwendbar bleiben.

### 4. Überforderungspunkte benennen

- Unnötige Komplexität, fehlende Priorität oder Engpässe explizit zeigen.

### 5. Usecase-Check

```bash
bach usecase run <id> --dry-run
bach usecase run-all SELBSTMANAGEMENT --dry-run
```

---

## Ergebnis

Ein sauberer Selbstmanagement-Usecase liefert:

- eine entlastende, praktisch nutzbare Struktur,
- sichtbare Engpässe oder Balance-Lücken,
- und wiederverwendbare Strategien für spätere Fälle.

---

## Changelog

| Version | Datum | Änderung |
|---------|-------|-----------|
| 1.0.0 | 2026-06-17 | Initiale Workflow-Datei für SELBSTMANAGEMENT-Usecases |
