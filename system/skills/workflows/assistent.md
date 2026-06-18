# Workflow: Assistent

**Version:** 1.0.0
**Erstellt:** 2026-06-17
**Aktualisiert:** 2026-06-17

---

## Zweck

Wiederverwendbarer Ablauf für Assistenz-Usecases, bei denen BACH Tagesplanung,
Briefings, Reisen, Kalender oder ein dauerhaftes User-Bild unterstützen soll.

Der Workflow deckt insbesondere die Usecases 25 bis 30 ab:

- Dossier oder Briefing erstellen
- Location Restaurant Hotel suchen
- Reiseroute planen
- Tagesablauf-Briefing Morgens
- Kalender führen
- Charaktersheet über User pflegen

Primäre BACH-Rolle: Boss-Agent `persoenlicher-assistent`.

---

## Leitlinien

1. **Kontext vor Aktion.**
   Erst klären, ob es um Recherche, Terminlogik, Buchungsstruktur oder
   längerfristige User-Präferenzen geht.

2. **Bestehende Quellen vor Neudaten.**
   Vor neuen Listen oder Profilen zuerst Memory, Tasks, Wiki, vorhandene
   Briefings und Dokumente prüfen.

3. **Ergebnisse als Arbeitsoberfläche denken.**
   Nützlich sind strukturierte Briefings, Terminübersichten, Listen,
   Entscheidungsoptionen und klare nächste Schritte.

4. **Privates knapp und zweckgebunden halten.**
   Persönliche Details nur speichern, wenn sie für spätere Assistenzfälle
   wirklich wiederverwendbar sind.

---

## Vorbereitung

```bash
bach usecase show <id>
bach help memory
bach help tasks
bach help wiki
bach tools search briefing
```

Zusätzlich prüfen:

- Gibt es bereits einen Tages-, Reise- oder Meeting-Kontext?
- Ist das Ziel eine einmalige Antwort oder dauerhafte Pflege?
- Welche Informationen sind privat, flüchtig oder wiederverwendbar?

---

## Ablauf

### 1. Assistenzziel scharf machen

- Briefing, Suche, Planung oder Profilpflege unterscheiden.
- Gewünschtes Ausgabeformat festlegen: Liste, Zeitplan, Kurzbriefing,
  Steckbrief oder Entscheidungshilfe.

### 2. Vorhandene BACH-Flächen prüfen

- Relevante Tasks, Memory-Einträge, Wiki-Artikel und Dateien sichten.
- Bestehende Kalender-, Reise- oder Personendaten wiederverwenden, statt
  Parallelstrukturen zu erzeugen.

### 3. Assistenzprodukt erstellen

- Bei Briefings: Thema, Kontext, offene Fragen, nächste Schritte bündeln.
- Bei Reisen/Locations: Optionen strukturiert nach Ort, Zeit, Kosten und
  Relevanz sortieren.
- Bei Profilpflege: Präferenzen, Routinen und Abneigungen sauber von
  gesicherten Fakten trennen.

### 4. Anschlussfähigkeit sichern

- Wenn Informationen später wieder wichtig sind, in eine stabile BACH-Fläche
  überführen statt nur als Freitext zu belassen.
- Offene Entscheidungen klar markieren.

### 5. Usecase-Check

```bash
bach usecase run <id> --dry-run
bach usecase run-all ASSISTENT --dry-run
```

---

## Ergebnis

Ein sauberer Assistent-Usecase endet mit:

- einer verständlichen Übersicht oder Planung,
- klar getrennten Fakten, Annahmen und offenen Punkten,
- und einer Form, die spätere BACH-Assistenz leichter macht.

---

## Changelog

| Version | Datum | Änderung |
|---------|-------|-----------|
| 1.0.0 | 2026-06-17 | Initiale Workflow-Datei für ASSISTENT-Usecases |
