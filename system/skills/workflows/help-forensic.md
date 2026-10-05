# Workflow: Help-Forensik

**Version:** 1.0.0
**Erstellt:** 2026-01-24
**Service:** hub/_services/skills/docs/help/
**Recurring:** help_forensic (14 Tage)

---

## Zweck

Systematische Ueberpruefung der Help-Dokumentation auf Aktualitaet.
Vergleicht dokumentierten Soll-Zustand mit tatsaechlicher Implementierung.
Bei Abweichungen: Help anpassen ODER Roadmap/Tasks erweitern.

Prinzip: `skills/docs/help/*.txt ist die WAHRHEIT` - aber nur wenn sie aktuell ist!

---

## Ausloeser

- Recurring Task (alle 14 Tage)
- Nach Code-Aenderungen
- Nutzer meldet "Doku stimmt nicht"
- Manueller Aufruf

---

## Schritt 1: Help-Datei auswaehlen

### 1.1 Kandidaten ermitteln

```bash
# Alle Help-Dateien auflisten
ls skills/docs/help/*.txt

# Nach Aenderungsdatum sortiert (aelteste zuerst)
ls -lt skills/docs/help/*.txt | tail -10

# Zufaellig waehlen
ls skills/docs/help/*.txt | shuf | head -1
```

### 1.2 Auswahl-Kriterien

**Zufaellig:** Fuer regulaere Checks

**Aelteste zuerst:** Priorisiert laenger nicht geprueft

**Spezifisch:** Nach Nutzer-Auftrag oder Code-Aenderung

### 1.3 Dokumentieren

```
Ausgewaehlte Datei: skills/docs/help/[name].txt
Letzte Aenderung: [Datum]
Auswahl-Grund: [zufaellig | aelteste | auftrag]
```

---

## Schritt 2: Dokumentierten Zustand erfassen

### 2.1 Datei lesen

```bash
cat skills/docs/help/[name].txt
```

### 2.2 Strukturiert erfassen

```
DOKUMENTIERTER ZUSTAND
======================

BEFEHLE (beschrieben):
- bach [command1] [args]     → [Beschriebene Funktion]
- bach [command2] [args]     → [Beschriebene Funktion]

FUNKTIONEN (beschrieben):
- [Feature 1]: [Beschreibung]
- [Feature 2]: [Beschreibung]

DATEIPFADE (referenziert):
- [Pfad 1]: [Beschriebener Zweck]
- [Pfad 2]: [Beschriebener Zweck]

OPTIONEN/FLAGS:
- --[option1]: [Beschreibung]
- --[option2]: [Beschreibung]
```

---

## Schritt 3: Forensische Untersuchung

### 3.1 Befehle testen

Fuer jeden dokumentierten Befehl:

```bash
# Befehl testen
python bach.py [command] [args]

# Oder Help pruefen
python bach.py --help [command]
```

Ergebnis dokumentieren:
- Funktioniert wie beschrieben?
- Andere/erweiterte Funktionalitaet?
- Fehlermeldung/nicht gefunden?

### 3.2 Code pruefen

```bash
# Handler finden
grep -r "[command]" hub/handlers/

# Implementierung lesen
cat hub/handlers/[handler].py
```

Vergleiche:
- Alle Optionen implementiert?
- Zusaetzliche Optionen im Code?
- Verhalten wie beschrieben?

### 3.3 Pfade verifizieren

```bash
# Existenz pruefen
ls -la [referenzierter_pfad]

# Bei Ordnern: Inhalt pruefen
ls [ordner]/
```

### 3.4 Ergebnisse tabellieren

```
| Element        | Dokumentiert | Tatsaechlich    | Status    |
|----------------|--------------|-----------------|-----------|
| bach --X       | Ja           | Funktioniert    | OK        |
| bach --X --opt | Ja           | Fehlt           | LUECKE    |
| bach --Y       | Nein         | Existiert       | UNDOK     |
| pfad/zu/file   | Ja           | Existiert nicht | FEHLT     |
```

---

## Schritt 4: Abweichungen klassifizieren

### 4.1 Entscheidungsbaum

```
Abweichung gefunden?
│
├─> NEIN: Dokumentation ist aktuell → FERTIG
│
└─> JA: Abweichung bewerten:
        │
        ├─> System BESSER als Doku?
        │   │
        │   └─> Feature existiert, ist nur undokumentiert
        │       └─> Klassifikation: VERBESSERUNG
        │       └─> Aktion: Help aktualisieren
        │
        └─> System SCHLECHTER als Doku?
            │
            ├─> Feature teilweise implementiert?
            │   └─> Klassifikation: TEILWEISE
            │   └─> Pruefen: Geplant in Roadmap/Tasks?
            │
            └─> Feature fehlt komplett?
                └─> Klassifikation: ZIELZUSTAND_FEHLT
                └─> Pruefen: Geplant in Roadmap/Tasks?
```

### 4.2 Klassifikationen

**VERBESSERUNG:**
- System hat mehr/bessere Features als dokumentiert
- Aktion: Help anpassen, CHANGELOG Eintrag

**TEILWEISE:**
- Teilimplementierung, Rest noch offen
- Aktion: Pruefen ob geplant, ggf. Tasks ergaenzen

**ZIELZUSTAND_FEHLT:**
- Dokumentiertes Feature fehlt komplett
- Aktion: Zu Roadmap/Tasks hinzufuegen

**VERALTET:**
- Dokumentiertes Feature wurde absichtlich entfernt
- Aktion: Help korrigieren, Entfernung dokumentieren

---

## Schritt 5: Kontext-Recherche (bei Zweifeln)

### 5.1 Roadmap pruefen

```bash
grep -i "[feature]" ROADMAP.md
```

Fragen:
- Ist das Feature dort geplant?
- In welcher Phase?
- Als OFFEN oder ERLEDIGT markiert?

### 5.2 Tasks pruefen

```bash
python bach.py --tasks list | grep -i "[feature]"
```

Oder direkt in DB:
```sql
SELECT * FROM tasks WHERE description LIKE '%[feature]%';
```

### 5.3 Logs durchsuchen

```bash
grep -r "[feature]" logs/
```

### 5.4 Memory/Sessions

```bash
grep -r "[feature]" data/memory/
```

### 5.5 Ergebnis dokumentieren

```
KONTEXT-RECHERCHE
=================
ROADMAP.md: [gefunden/nicht gefunden] - [Details]
Tasks: [Task-IDs falls vorhanden]
Logs: [relevante Eintraege]
Memory: [relevante Fakten]

Schlussfolgerung: [geplant | vergessen | absichtlich_entfernt]
```

---

## Schritt 6: Aktion durchfuehren

### 6.1 Bei VERBESSERUNG

```
1. Help-Datei oeffnen
2. Fehlende Dokumentation ergaenzen
3. "Stand: YYYY-MM-DD" aktualisieren
4. CHANGELOG.md Eintrag:
   - Help: [name].txt aktualisiert (neu: [feature])
```

### 6.2 Bei ZIELZUSTAND_FEHLT (nicht geplant)

```
1. In ROADMAP.md eintragen:
   | HELP_[NNN] | [Feature] implementieren (aus skills/docs/help/[name].txt) | OFFEN |

2. Oder als Task:
   python bach.py --tasks add "[Feature] implementieren" --priority P3

3. Help-Datei: Hinweis ergaenzen
   HINWEIS: [Feature] noch nicht implementiert (geplant)
```

### 6.3 Bei VERALTET

```
1. Help-Datei korrigieren
2. Entferntes Feature streichen
3. CHANGELOG.md:
   - Help: [name].txt korrigiert (entfernt: [feature])
```

---

## Schritt 7: Bericht erstellen

### 7.1 Speicherort

```
logs/help_forensic/REPORT_YYYY-MM-DD_[name].md
```

### 7.2 Berichts-Template

```markdown
# Help-Forensik Bericht

**Datum:** YYYY-MM-DD
**Datei:** skills/docs/help/[name].txt
**Analyst:** [Claude/Gemini]

## Dokumentierter Zustand

### Befehle
- `bach --X`: [Beschreibung]
- `bach --Y`: [Beschreibung]

### Funktionen
- [Feature 1]
- [Feature 2]

## Forensische Befunde

| Element | Dokumentiert | Tatsaechlich | Status |
|---------|--------------|--------------|--------|
| ... | ... | ... | ... |

## Abweichungen

### 1. [Abweichung]
- **Klassifikation:** [VERBESSERUNG/ZIELZUSTAND_FEHLT/VERALTET]
- **Details:** [Beschreibung]
- **Begruendung:** [Warum diese Klassifikation]

## Kontext-Recherche

- ROADMAP.md: [Ergebnis]
- Tasks: [Ergebnis]
- Logs: [Ergebnis]

## Durchgefuehrte Aktionen

- [x] Help aktualisiert: [Details]
- [ ] Roadmap erweitert: [Task-ID]
- [x] CHANGELOG Eintrag erstellt

## Fazit

[Zusammenfassung: Datei war aktuell / wurde korrigiert / Tasks erstellt]
```

---

## Checkliste

```
[ ] Help-Datei ausgewaehlt
[ ] Dokumentierten Zustand erfasst
[ ] Alle Befehle getestet
[ ] Code geprueft
[ ] Pfade verifiziert
[ ] Abweichungen tabelliert
[ ] Abweichungen klassifiziert
[ ] Kontext-Recherche (bei Bedarf)
[ ] Aktion durchgefuehrt:
    [ ] Help angepasst ODER
    [ ] Roadmap/Tasks erweitert
[ ] Analysebericht erstellt
[ ] CHANGELOG aktualisiert
```

---

## Siehe auch

- `hub/_services/skills/docs/help/SKILL.md` - Service-Beschreibung
- `skills/docs/help/practices.txt` - Best Practices (#7: HELP ALS WAHRHEIT)
- `bach --maintain docs` - Dokumentations-Checker Tool
- `skills/workflows/wiki-author.md` - Wiki-Autoren Workflow