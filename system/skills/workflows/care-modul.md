# Workflow: Care-Modul

**Version:** 1.0.0
**Erstellt:** 2026-06-17
**Aktualisiert:** 2026-06-17

---

## Zweck

Wiederverwendbarer Ablauf für Care-Usecases rund um laufende medizinische
Organisation: Termine, Erinnerungen, Medikationspflege und Vorsorge.

Der Workflow deckt insbesondere die Usecases 22 bis 24 ab:

- Vorsorgeplan verwalten
- Medikamentenplan aktuell halten
- Arzttermine und Erinnerungen verwalten

Primäre BACH-Rolle: Boss-Agent `gesundheitsassistent`.
Typische Experten: `gesundheitsverwalter`, `health_import`.

---

## Leitlinien

1. **Aktualität vor Vollständigkeit.**
   Bei Care-Daten zählt zuerst der aktuelle Stand für Termine, Medikamente
   und nächste medizinische Schritte.

2. **Berichte vor Freitext.**
   Neue Einträge möglichst an belastbare Quellen wie Arztberichte,
   Medikationspläne oder bestehende Tabellen koppeln.

3. **Strukturiert statt erzählerisch.**
   Für Care-Fälle sind Datum, Status, Dosierung, Anlass und nächste Aktion
   wichtiger als lange Fließtexte.

4. **Sicherheitsrelevantes sichtbar machen.**
   Unklare Dosierungen, offene Termine oder fehlende Vorsorge dürfen nicht
   versteckt werden.

---

## Vorbereitung

```bash
bach usecase show <id>
bach help gesundheit
bach help mediplaner
bach help docs
bach tools search medikament
```

Zusätzlich prüfen:

- Gibt es einen aktuellen Bericht oder Plan als Quelle?
- Geht es um Pflege des Ist-Stands oder um eine neue Empfehlungsliste?
- Welche Angaben sind verifiziert und welche nur User-Hinweise?

---

## Ablauf

### 1. Care-Fokus festlegen

- Terminverwaltung, Medikationspflege und Vorsorge nicht vermischen, wenn
  unterschiedliche Datenquellen betroffen sind.

### 2. Bestehende Gesundheitsdaten lesen

- Relevante Berichte, bestehende Medikationspläne, Termine und Notizen
  heranziehen.
- Bei PDF- oder Bildquellen erst lesbare Textgrundlage sicherstellen.

### 3. Strukturierten Care-Stand bauen

- Medikamente mit Wirkstoff, Dosierung, Tageszeit und Status erfassen.
- Termine mit Datum, Fachrichtung, Anlass und Erinnerungslogik bündeln.
- Vorsorgepunkte nach offen, geplant, erledigt trennen.

### 4. Risiken und Lücken markieren

- Unklare Dosierungen, widersprüchliche Angaben oder fehlende Zeitpunkte
  explizit kennzeichnen.

### 5. Usecase-Check

```bash
bach usecase run <id> --dry-run
bach usecase run-all CARE-MODUL --dry-run
```

---

## Ergebnis

Ein sauberer Care-Usecase liefert:

- einen aktuellen, strukturierten Gesundheitsorganisationsstand,
- sichtbare offene Punkte oder Risiken,
- und eine Oberfläche, die für spätere Berichte oder Erinnerungen nutzbar bleibt.

---

## Changelog

| Version | Datum | Änderung |
|---------|-------|-----------|
| 1.0.0 | 2026-06-17 | Initiale Workflow-Datei für CARE-MODUL-Usecases |
