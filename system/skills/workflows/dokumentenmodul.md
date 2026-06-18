# Workflow: Dokumentenmodul

**Version:** 1.0.0
**Erstellt:** 2026-06-17
**Aktualisiert:** 2026-06-17

---

## Zweck

Wiederverwendbarer Ablauf für dokumentzentrierte Usecases, bei denen
medizinische oder organisatorische Dateien erkannt, einsortiert, gelesen oder
in BACH-Verzeichnisse übernommen werden sollen.

Der Workflow deckt insbesondere Usecase 16 ab:

- Medizin-Dokumentenverzeichnis aktualisieren

Primäre BACH-Rolle: Boss-Agent `gesundheitsassistent`.
Typische Experten: `gesundheitsverwalter`, `report_generator`.

---

## Leitlinien

1. **Dateiwahrheit zuerst.**
   Vor Einträgen in Listen oder DBs immer den realen Dateibestand prüfen.

2. **Lesbarkeit sichern.**
   Unleserliche PDFs oder Bilder zuerst per OCR/Textkonvertierung aufbereiten.

3. **Kategorien klein und stabil halten.**
   Neue Dateien an bestehende BACH-Kategorien und Verzeichnisse anschließen,
   statt neue Sonderordner zu erzeugen.

4. **Änderungen nachvollziehbar machen.**
   Neue, geänderte oder fehlende Dokumente getrennt benennen.

---

## Vorbereitung

```bash
bach usecase show 16
bach help docs
bach help search
bach tools search ocr
```

Zusätzlich prüfen:

- Welche Ordner gelten als Quelle der Wahrheit?
- Sind Dateien neu, verschoben, gelöscht oder nur umbenannt?
- Müssen PDFs erst in Text umgewandelt werden?

---

## Ablauf

### 1. Dateibestand erfassen

- Quellenordner, Dateinamen und vorhandene Verzeichnisstände vergleichen.

### 2. Neue oder geänderte Dokumente lesbar machen

- Bei Bedarf OCR oder Textkonvertierung anwenden.
- Dokumenttyp und Relevanz bestimmen.

### 3. Verzeichnisstand aktualisieren

- Neue Dokumente einsortieren, entfernte markieren, Metadaten ergänzen.
- Wissen- und Patientendokumente sauber trennen, wenn BACH das erwartet.

### 4. Anschluss prüfen

- Bei relevanten Inhalten Folgeflächen wie Gesundheit, Memory oder
  Berichtslogik verlinken.

### 5. Usecase-Check

```bash
bach usecase run 16 --dry-run
bach usecase run-all DOKUMENTENMODUL --dry-run
```

---

## Ergebnis

Ein sauberer Dokumentenmodul-Usecase liefert:

- ein aktuelles, belastbares Dokumentenverzeichnis,
- saubere Lesbarkeit oder OCR-Basis,
- und klare Hinweise auf neue oder fehlende Dokumente.

---

## Changelog

| Version | Datum | Änderung |
|---------|-------|-----------|
| 1.0.0 | 2026-06-17 | Initiale Workflow-Datei für DOKUMENTENMODUL-Usecases |
