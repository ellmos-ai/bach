# Workflow: Therapie

**Version:** 1.0.0
**Erstellt:** 2026-06-17
**Aktualisiert:** 2026-06-17

---

## Zweck

Wiederverwendbarer Ablauf für Therapie-Usecases, bei denen BACH Übungen,
Arbeitsblätter oder beratungsnahe Materialien auf Basis vorhandener Wissens-
 und Falldaten erstellen soll.

Der Workflow deckt insbesondere die Usecases 39 und 40 ab:

- Arbeitsblätter für Autismus-Förderung erstellen
- Arbeitsblätter für psychologische Beratung erstellen

Primäre BACH-Rollen: Experten `foerderplaner`, `psycho-berater`.

---

## Leitlinien

1. **Material folgt Ziel und Kliententyp.**
   Übungen ohne klaren Anlass sind unbrauchbar.

2. **Wissensbasis vor Generierung.**
   Erst vorhandene Daten, Förderziele und relevante Quellen sichten.

3. **Praktikabilität vor Theorielast.**
   Arbeitsblätter sollen anwendbar und verständlich sein.

4. **Sensiblen Kontext eng führen.**
   Persönliche oder therapeutische Details nur zweckgebunden nutzen.

---

## Vorbereitung

```bash
bach usecase show <id>
bach help docs
bach help wiki
bach tools search therapie
```

Zusätzlich prüfen:

- Für wen ist das Material gedacht?
- Welche Ziele, Schwierigkeiten und Rahmenbedingungen sind bekannt?
- Geht es um Förderung, Beratung oder Psychoedukation?

---

## Ablauf

### 1. Zielgruppe und Zielbild klären

- Kliententyp, Altersgruppe, Setting und Förderziel festziehen.

### 2. Wissensbasis sichten

- Relevante Materialien, Wissenseinträge, Berichte oder Förderziele lesen.

### 3. Material strukturieren

- Übungen, Arbeitsblätter oder Gesprächsimpulse passend zum Zielbild
  zusammenstellen.
- Schwierigkeit, Umfang und Sprache am Fall ausrichten.

### 4. Sicherheit und Nutzbarkeit prüfen

- Unpassende Komplexität, unklare Anweisungen oder fehlende Zielbezüge
  bereinigen.

### 5. Usecase-Check

```bash
bach usecase run <id> --dry-run
bach usecase run-all THERAPIE --dry-run
```

---

## Ergebnis

Ein sauberer Therapie-Usecase endet mit:

- zielgerichtetem, praktisch nutzbarem Material,
- sichtbarer Bindung an Fall und Zielsetzung,
- und klarer Abgrenzung von offenen Annahmen.

---

## Changelog

| Version | Datum | Änderung |
|---------|-------|-----------|
| 1.0.0 | 2026-06-17 | Initiale Workflow-Datei für THERAPIE-Usecases |
