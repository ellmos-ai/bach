# Wiki-Autorenbericht – persoenlicher-assistent

Datum: 2026-11-10
Auftrag: Task #2110 (Korrekturrunde, review_findings_contract_not_met)

## Ausgangslage / Korrekturhinweis

Eine fruehere Korrekturrunde hatte nur die Pflege-Dateien SKILL.md,
manifest.json, wiki/_index.txt und wiki/wiki_konventionen.txt angepasst,
ohne einen echten Beitrag zum Wiki-Bestand (Review-Befund: Vertrag nicht
erfuellt). Dieser Bericht begleitet die nachgeholte Lieferung: ein
echter Wiki-Artikel wurde erstellt und der Wiki-Index bereinigt.

## Agentenauswahl (Kriterium: aelteste_pflege)

Kriterium: von den waehlbaren Agenten wird derjenige gewaehlt, dessen
SKILL.md den aeltesten Pflegestand (updated-Datum) hat – der Wiki-
Beitrag dient damit dem am laengsten ungepflegten Agenten als
Wissenszuwachs.

| Agent | created (SKILL.md) | updated (SKILL.md) | Anmerkung |
|---|---|---|---|
| bueroassistent / gesundheitsassistent | – | 2026-03-12 | |
| ati / _experts | – | 2026-09-18 | |
| entwickler | – | 2026-09-17 | |
| persoenlicher-assistent | 2026-01-23 | 2026-02-04 | GEWAEHLT (aeltester Pflegestand) |
| personas | – | 2026-03-12 | |
| queue-maintainer | – | 2026-10-16 | |
| reflection | – | 2026-09-18 | |
| research | – | 2026-09-17 | |
| test-agent | – | 2026-09-18 | |
| versicherungen | – | 2026-09-18 | |
| wiki-author | – | 2026-10-30 | |
| zuordnungsregler | – | 2026-10-16 | |

Beleg: system/agents/persoenlicher-assistent/SKILL.md, Zeilen 6–7
(created 2026-01-23, updated 2026-02-04). Alle aufgefuhrten Werte
wurden aus den jeweiligen SKILL.md-Dateien gelesen (Kontroll-Lese-
vorgaben ueber alle elf Agenten im selben Lauf).

## Luecken-Tabelle

| Wissensbereich | Im Wiki? | Aktuell? | Prioritaet |
|---|---|---|---|
| JSON-Datenformat | Nein ( zuvor nur Phantom-Eintragungen in _index.txt) | – | Hoch |
| Wissenschaftliche Recherche (research) | Nein | – | Mittel (Folgezeitraum) |

Notiz: EIN Thema pro Autorendurchlauf. JSON wurde gewählt wegen
universeller Relevanz: zahlreiche BACH-Agenten verarbeiten strukturierte
Schluessel/Wert-Daten. Das Thema Recherche wurde fuer einen spaeteren
Durchlauf vermerkt.

## Recherche-Block

Thema: JSON-Datenformat – Grundlagen

Quellen (offiziell, langlebig stabil):
1. https://www.json.org/json-de.html
2. https://docs.python.org/3/library/json.html
3. https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/JSON
4. https://de.wikipedia.org/wiki/JavaScript_Object_Notation

Kernaussagen (im Artikel enthalten):
- JSON = JavaScript Object Notation; textbasiert; Anfang der 2000er
  von Douglas Crockford etabliert; Standardisierung RFC 8259 (2017)
  und ECMA-404.
- Sechs Werttypen: null, true/false, Zahl, Zeichenkette, Array, Objekt.
- Objekt-Schluessel immer in doppelten Anfuehrungszeichen; Kommentare
  nicht vorgesehen.
- Kein eigener Datumstyp -> Konvention ISO-8601-Zeichenkette
  ("JJJJ-MM-TT", z. B. "2026-11-10").
- Standardkodierung UTF-8.
- Python: Standardmodul json mit json.loads() / json.dumps(), ueblich
  indent=2 und ensure_ascii=False.
- Browser: JSON.parse() / JSON.stringify() im JSON-Objekt (MDN).

## BACH-Relevanz

- system/agents/research/SKILL.md (Zeilen 1–80): strukturierte
  Wissensschaetze sind Arbeitsmaterial der Recherche; JSON ist das
  uebliche Austauschformat fuer solche Strukturen.
- system/agents/queue-maintainer/SKILL.md (Zeilen 1–14): Task-Verwaltung
  arbeitet mit strukturierten Feldlisten (Schluessel/Wert).
- system/agents/gesundheitsassistent/SKILL.md: gesundheitsbezogene
  Datenbestaete; strukturierte Formate wie JSON sind Basis fuer
  Metadaten.
- wiki/wiki_konventionen.txt (Zeilen 1–35): Format- und Indexregeln;
  die Frontmatter-Felder created/updated folgen derselben
  Schluessel/Wert-Logik wie JSON.

## Ehrliche Recherche-Herkunft

Es wurde kein Webtool genutzt – weder fuer diesen Bericht noch fuer den
erstellten Artikel. Die Inhalte stammen aus dem Referenzwissen des
Autoren-Agenten; die vier genannten URLs werden als offizielle,
langlebig stabile Dauerreferenzen angegeben.
