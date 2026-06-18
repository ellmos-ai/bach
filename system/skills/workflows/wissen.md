# Workflow: Wissen

**Version:** 1.0.0
**Erstellt:** 2026-06-17
**Aktualisiert:** 2026-06-17

---

## Zweck

Wiederverwendbarer Ablauf für Wissens-Usecases, bei denen BACH auf
bestehende Wissensbestände zugreifen, sie strukturieren oder gezielt daraus
Antworten aufbauen soll.

Der Workflow deckt insbesondere Usecase 38 ab:

- Wissensdatenbank navigieren und nutzen

Primäre BACH-Rolle: Experte `wikiquizzer`.

---

## Leitlinien

1. **Bestehendes Wissen vor Neurecherche.**
   Erst lokale Wissensbestände, Wiki und vorhandene Notizen prüfen.

2. **Navigation ist Teil der Lösung.**
   Gute Antworten zeigen auch, wo das Wissen herkommt und wie es
   wiedergefunden wird.

3. **Struktur vor Sammelwut.**
   Wichtiger als neue Einträge ist oft die bessere Verknüpfung.

4. **Unschärfen benennen.**
   Lücken, Widersprüche oder schwache Quellen dürfen sichtbar bleiben.

---

## Vorbereitung

```bash
bach usecase show 38
bach help wiki
bach help search
bach help memory
```

Zusätzlich prüfen:

- Wird ein konkreter Fakt, ein Themenüberblick oder eine Strukturantwort erwartet?
- Liegt das relevante Wissen in Wiki, Dateien, Memory oder Dokumenten?
- Fehlt Wissen oder fehlt nur die Navigation dahin?

---

## Ablauf

### 1. Wissensfrage eingrenzen

- Faktensuche, Überblick, Strukturierung oder Verknüpfung unterscheiden.

### 2. Lokale Wissensflächen durchsuchen

- Wiki, Suchflächen, Dokumente und Memory gezielt prüfen.

### 3. Strukturierte Wissensantwort bauen

- Ergebnis nicht nur beantworten, sondern Quellen- und Pfadlogik sichtbar machen.
- Bei Bedarf Hierarchien oder Themencluster bilden.

### 4. Anschluss verbessern

- Wenn Navigationslücken sichtbar werden, sinnvolle Wiki- oder
  Strukturverbesserungen notieren.

### 5. Usecase-Check

```bash
bach usecase run 38 --dry-run
bach usecase run-all WISSEN --dry-run
```

---

## Ergebnis

Ein sauberer Wissens-Usecase liefert:

- eine nachvollziehbare Antwort aus lokalen Wissensflächen,
- klare Quellen- oder Navigationshinweise,
- und bei Bedarf Vorschläge zur Strukturverbesserung.

---

## Changelog

| Version | Datum | Änderung |
|---------|-------|-----------|
| 1.0.0 | 2026-06-17 | Initiale Workflow-Datei für WISSEN-Usecases |
