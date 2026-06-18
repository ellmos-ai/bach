# Workflow: Gesundheit

**Version:** 1.0.0
**Erstellt:** 2026-06-17
**Aktualisiert:** 2026-06-17

---

## Zweck

Wiederverwendbarer Ablauf für Gesundheits-Usecases, bei denen ein kompakter,
aktueller medizinischer Überblick gebraucht wird.

Der Workflow deckt insbesondere Usecase 37 ab:

- Medikamente Übersicht führen

Primäre BACH-Rolle: Boss-Agent `gesundheitsassistent`.
Typische Experten: `gesundheitsverwalter`, `health_import`.

---

## Leitlinien

1. **Aktueller Plan vor Historie.**
   Für Übersichten zählt zuerst, was jetzt gilt.

2. **Medikamente präzise benennen.**
   Name, Wirkstoff, Dosierung, Tageszeit und Status nicht vermischen.

3. **Quellenbezug erhalten.**
   Arztberichte oder bestehende Listen bleiben nachvollziehbar.

4. **Medizinische Unklarheit sichtbar lassen.**
   Widersprüche oder veraltete Angaben markieren statt glätten.

---

## Vorbereitung

```bash
bach usecase show 37
bach help gesundheit
bach help mediplaner
bach help docs
```

Zusätzlich prüfen:

- Welcher Stand ist der aktuellste?
- Gibt es mehrere widersprüchliche Quellen?
- Wird nur Übersicht oder auch Pflege erwartet?

---

## Ablauf

### 1. Relevante Quellen sammeln

- Aktuelle Berichte, Medikationspläne und Notizen zusammenziehen.

### 2. Medikamentenübersicht strukturieren

- Einträge nach aktuell, pausiert, beendet oder unklar trennen.
- Dosierung und Einnahmezeit einheitlich notieren.

### 3. Risiken oder Lücken markieren

- Fehlende Mengen, unklare Wirkstoffe oder widersprüchliche Angaben sichtbar machen.

### 4. Anschluss an Care-Flächen prüfen

- Wenn Pflegebedarf entsteht, an Medikationsplan oder Care-Logik anbinden.

### 5. Usecase-Check

```bash
bach usecase run 37 --dry-run
bach usecase run-all GESUNDHEIT --dry-run
```

---

## Ergebnis

Ein sauberer Gesundheits-Usecase liefert:

- eine aktuelle, gut lesbare Medikamentenübersicht,
- gekennzeichnete Unsicherheiten,
- und Anschlussfähigkeit für weitere Care- oder Berichtsfälle.

---

## Changelog

| Version | Datum | Änderung |
|---------|-------|-----------|
| 1.0.0 | 2026-06-17 | Initiale Workflow-Datei für GESUNDHEIT-Usecases |
