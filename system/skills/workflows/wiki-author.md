# Workflow: Wiki-Autoren

**Version:** 2.0.0
**Erstellt:** 2026-01-24
**Aktualisiert:** 2026-06-13
**Service:** hub/_services/wiki/
**Recurring:** wiki_author (21 Tage)

---

## Zweck

Systematische Erweiterung und Pflege der Wiki-Wissensbasis.
Der Wiki-Autor hat drei Hauptaufgaben:

1. **ERSTELLEN** - Neue Artikel basierend auf Agenten/Experten-Bedarfen
2. **AKTUALISIEREN** - Bestehende Artikel auf Aktualitaet pruefen
3. **VALIDIEREN** - Fakten durch Stichproben verifizieren

---

## MODUS A: NEUEN ARTIKEL ERSTELLEN

### Schritt 1: Agent/Experte auswaehlen

#### 1.1 Kandidaten sammeln

```bash
# Alle Agenten auflisten
ls agents/

# Alle Experten auflisten
ls agents/_experts/

# Zuletzt geaenderte ermitteln
ls -lt agents/ | head -10
```

#### 1.2 Auswahl-Kriterien

**Zufaellig:** Wuerfeln aus der Liste

**Prioritaet:** Nach zuletzt gepflegt
- Wiki-Author Log pruefen: logs/wiki_author/
- Agenten ohne kuerzlichen Eintrag bevorzugen

**Nach Anfrage:** Spezifischer Agent/Experte vom Nutzer

#### 1.3 Dokumentieren

```
Ausgewaehlter Agent: [Name]
Pfad: agents/[name]/
Begruendung: [zufaellig | aelteste_pflege | nutzer_anfrage]
```

---

### Schritt 2: Wissen analysieren

#### 2.1 Agent-Profil lesen

```
Lies: agents/[name]/SKILL.md
Lies: agents/[name]/manifest.json (falls vorhanden)
```

Extrahiere:
- **Hauptaufgabe:** Was macht der Agent?
- **Tools:** Welche Tools nutzt er?
- **APIs:** Welche externen Dienste?
- **Domain:** Welches Fachgebiet?

#### 2.2 Wissensbedarfe identifizieren

Frage dich:
- Welches Fachwissen braucht der Agent?
- Welche Technologien muss er verstehen?
- Welche externen Dienste werden genutzt?
- Welche Konzepte sind fuer seine Aufgabe relevant?

#### 2.3 Existierendes Wiki pruefen

```bash
# Wiki-Index lesen
cat wiki/_index.txt

# Relevante Artikel suchen
grep -l "[keyword]" wiki/*.txt

# Unterordner pruefen (falls Agent-spezifisch)
ls wiki/[agent-domain]/
```

Dokumentiere:
- Welche relevanten Artikel existieren?
- Welche sind aktuell?
- Welche fehlen komplett?

---

### Schritt 3: Luecken identifizieren

#### 3.1 Gap-Analyse

```
| Wissensbereich | Im Wiki? | Aktuell? | Prioritaet |
|----------------|----------|----------|------------|
| [Thema 1]      | Ja/Nein  | Ja/Nein  | H/M/N      |
| [Thema 2]      | Ja/Nein  | Ja/Nein  | H/M/N      |
```

#### 3.2 Priorisierung

**Hoch:** Agent kann ohne Wissen nicht arbeiten
**Mittel:** Wuerde Qualitaet verbessern
**Niedrig:** Nice-to-have, Hintergrundwissen

#### 3.3 Ein Thema waehlen

Waehle EIN Thema mit hoechster Prioritaet fuer diesen Durchlauf.
Weitere Luecken fuer spaeter dokumentieren.

---

### Schritt 4: Recherche durchfuehren

#### 4.1 Quellen-Strategie

```
1. Offizielle Dokumentation (technisch korrekt, primaer)
2. Wikipedia (Grundlagen, Ueberblick)
3. Web-Suche (aktuelle Infos)
4. Fach-Datenbanken (bei Bedarf):
   - PubMed (medizinisch)
   - arXiv (wissenschaftlich)
   - WHO (Gesundheit, ICF)
   - GitHub (Code/Tools)
```

#### 4.2 Recherche dokumentieren

```
Thema: [gewaehltes Thema]

Quellen:
1. [URL/Referenz] - [Was gefunden]
2. [URL/Referenz] - [Was gefunden]
3. [URL/Referenz] - [Was gefunden]

Kernaussagen:
- [Punkt 1]
- [Punkt 2]
- [Punkt 3]
```

#### 4.3 BACH-Relevanz pruefen

- Wie ist das Thema fuer BACH relevant?
- Welche BACH-spezifischen Aspekte ergaenzen?
- Gibt es Integrationen/Schnittstellen?

---

### Schritt 5: Wiki-Beitrag erstellen

#### 5.1 Speicherort bestimmen

**Einzelartikel (allgemein):**
```
wiki/[thema].txt
```

**Agenten/Experten-Wissensordner (umfangreich):**
```
wiki/[domain]/
├── _index.txt
├── grundlagen.txt
└── [thema].txt
```

Entscheidung:
- Gehoert zum Wissen eines spezifischen Agenten? -> Unterordner
- Allgemeines Hintergrundwissen? -> Einzelartikel
- Mehr als 3 verwandte Artikel? -> Unterordner anlegen

#### 5.2 Format beachten

Lies: `wiki/wiki_konventionen.txt`

Standard-Format mit Validierungsmetadaten:
```
# Portabilitaet: UNIVERSAL
# Zuletzt validiert: 2026-01-24 (Claude/BACH wiki-author)
# Naechste Pruefung: 2027-01-24
# Quellen: [URL1], [URL2]

TITEL IN GROSSBUCHSTABEN
========================

Stand: YYYY-MM-DD

WAS IST X?
----------
Kurze Erklaerung (1-3 Saetze)

DETAILS
-------
Ausfuehrliche Informationen...

BACH-INTEGRATION
----------------
(falls zutreffend)

QUELLEN
-------
[1] URL - Beschreibung
[2] URL - Beschreibung

SIEHE AUCH
----------
wiki/verwandt.txt    Beschreibung
```

#### 5.3 Index aktualisieren

Bei Einzelartikel: `wiki/_index.txt` aktualisieren
Bei Unterordner: Sowohl Haupt-Index als auch `wiki/[domain]/_index.txt`

---

### Schritt 6: Dokumentieren

Speichern unter: `logs/wiki_author/REPORT_YYYY-MM-DD_[agent].md`

---

## MODUS B: ARTIKEL AKTUALISIEREN

### Ausloeser

- Validierungsmetadaten zeigen "Naechste Pruefung" ist faellig
- Recurring Task (alle 21 Tage: einen Artikel pruefen)
- Nutzer-Anfrage

### Vorgehen

1. **Artikel auswaehlen**
   ```bash
   # Artikel mit aeltester Validierung finden
   grep -l "Zuletzt validiert:" wiki/*.txt | xargs grep "Zuletzt validiert"
   ```

2. **Aktualitaet pruefen**
   - Quellen erneut aufrufen
   - Hat sich etwas geaendert?
   - Sind Links noch gueltig?

3. **Bei Aenderungsbedarf**
   - Artikel aktualisieren
   - Validierungsmetadaten erneuern
   - CHANGELOG eintragen

4. **Bei Aktualitaet**
   - Nur Validierungsdatum erneuern:
     ```
     # Zuletzt validiert: 2026-01-24 (Claude/BACH wiki-author)
     # Naechste Pruefung: 2027-01-24
     ```

### Analysebericht

```markdown
# Wiki-Aktualisierung

**Datum:** YYYY-MM-DD
**Artikel:** [Pfad]
**Letzte Validierung:** [Datum]

## Pruefung

### Quellen geprueft
- [URL1]: Noch aktuell / Geaendert / Nicht erreichbar
- [URL2]: ...

### Fakten geprueft
- [Fakt 1]: Korrekt / Veraltet / Falsch
- [Fakt 2]: ...

## Ergebnis

**Status:** Aktuell / Aktualisiert / Ueberarbeitung noetig

### Aenderungen
- [Falls Aenderungen]

### Naechste Pruefung
- Empfehlung: [Datum]
- Begruendung: [Schnelllebiges Thema / Stabiles Wissen]
```

---

## MODUS C: FAKTEN-STICHPROBE (VALIDIERUNG)

### Zweck

Qualitaetssicherung durch Verifizierung einzelner Fakten.
Erkennt veraltete oder fehlerhafte Informationen.

### Vorgehen

1. **Artikel zufaellig auswaehlen**
   ```bash
   # Zufaelliger Artikel
   ls wiki/*.txt | shuf | head -1
   ```

2. **Fakten extrahieren**
   Lese Artikel und identifiziere:
   - Zahlen, Daten, Statistiken
   - Versionsnummern
   - URLs und Referenzen
   - Behauptungen ueber externe Systeme

3. **Stichprobe ziehen**
   Waehle 3-5 Fakten zur Verifizierung:
   - Mindestens 1 Zahl/Datum
   - Mindestens 1 technische Behauptung
   - Mindestens 1 URL

4. **Recherche durchfuehren**
   Jeder Fakt wird geprueft:
   ```
   FAKT: "ICF wurde 2001 von der WHO eingefuehrt"
   QUELLE: WHO Website
   ERGEBNIS: BESTAETIGT (Resolution WHA 54.21, Mai 2001)
   ```

5. **Ergebnisse dokumentieren**

### Stichproben-Bericht

```markdown
# Wiki Fakten-Stichprobe

**Datum:** YYYY-MM-DD
**Artikel:** [Pfad]
**Stichprobengroesse:** 5 Fakten

## Verifizierte Fakten

| # | Fakt | Quelle | Status |
|---|------|--------|--------|
| 1 | [Behauptung] | [URL] | ✓ Korrekt |
| 2 | [Behauptung] | [URL] | ⚠ Veraltet |
| 3 | [Behauptung] | [URL] | ✗ Falsch |
| 4 | [Behauptung] | [URL] | ✓ Korrekt |
| 5 | [Behauptung] | [URL] | ? Nicht pruefbar |

## Zusammenfassung

- **Korrekt:** 3/5 (60%)
- **Veraltet:** 1/5 (20%)
- **Falsch:** 1/5 (20%)

## Empfehlung

[X] Artikel benoetigt Ueberarbeitung
[ ] Artikel ist aktuell
```

### Konsequenzen

- **>80% korrekt:** Validierungsdatum erneuern
- **50-80% korrekt:** Artikel aktualisieren (Modus B)
- **<50% korrekt:** Artikel zur Ueberarbeitung markieren, Task erstellen

---

## Checkliste (alle Modi)

### Modus A: Erstellen
```
[ ] Agent/Experte ausgewaehlt
[ ] SKILL.md des Agenten gelesen
[ ] Wissensbedarfe identifiziert
[ ] wiki/_index.txt geprueft
[ ] Unterordner-Bedarf geprueft
[ ] Luecken dokumentiert
[ ] Ein Thema gewaehlt
[ ] Recherche durchgefuehrt
[ ] Quellen dokumentiert
[ ] Wiki-Artikel erstellt
[ ] Validierungsmetadaten eingefuegt
[ ] Format-Konventionen eingehalten
[ ] _index.txt aktualisiert
[ ] Analysebericht gespeichert
[ ] CHANGELOG aktualisiert
```

### Modus B: Aktualisieren
```
[ ] Artikel mit faelliger Validierung gefunden
[ ] Quellen erneut geprueft
[ ] Aenderungen identifiziert
[ ] Artikel aktualisiert (falls noetig)
[ ] Validierungsmetadaten erneuert
[ ] Analysebericht gespeichert
[ ] CHANGELOG aktualisiert (bei Aenderungen)
```

### Modus C: Stichprobe
```
[ ] Artikel zufaellig gewaehlt
[ ] 3-5 Fakten extrahiert
[ ] Fakten recherchiert
[ ] Ergebnisse dokumentiert
[ ] Konsequenzen abgeleitet
[ ] Bei Bedarf: Task fuer Ueberarbeitung erstellt
```

---

## Recurring Task Ausfuehrung

Bei jedem Recurring-Durchlauf (21 Tage):

1. **Rotation:** Abwechselnd Modi A, B, C
   - Durchlauf 1: Modus A (Neuer Artikel)
   - Durchlauf 2: Modus B (Aktualisierung)
   - Durchlauf 3: Modus C (Stichprobe)
   - Durchlauf 4: Modus A ...

2. **Protokollierung:**
   - Letzten Modus in config.json merken
   - Naechsten Modus automatisch waehlen

---

## Siehe auch

- `hub/_services/wiki/SKILL.md` - Service-Beschreibung
- `wiki/wiki_konventionen.txt` - Format-Regeln
- `wiki/_index.txt` - Wiki-Verzeichnis
- `skills/workflows/help-forensic.md` - Help-Forensik Workflow
