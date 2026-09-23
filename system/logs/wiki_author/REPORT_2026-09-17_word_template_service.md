# Wiki Fakten-Stichprobe

**Datum:** 2026-09-17
**Artikel:** wiki/word_template_service.txt
**Stichprobengroesse:** 12 Fakten (alle extrahierbaren pruefbaren Fakten)
**Modus:** C (Fakten-Stichprobe) — Rotation A/B/C: 12.09. A (reflection),
16.09. B (claude_code_memory, vorgezogen) + separater Backlog-Lauf
(skills_board) → heute C wie in REPORT_2026-09-16_skills_board.md geplant.
**Task:** #1318 (wiki_author recurring)
**Auswahl:** Zufall (ls wiki/*.txt, awk-rand; Meta-Dateien _index/konventionen
ausgeschlossen)

## Auffaelligkeit vorab

Der Artikel hatte **keine Validierungsmetadaten** und **keinen
Index-Eintrag** — er erschien daher nie in den Faelligkeits-Auswertungen
(grep "Naechste Pruefung") und wurde von keinem der letzten Laeufe erfasst.

## Verifizierte Fakten

| # | Fakt (Artikel, Stand 27.01.) | Quelle | Status |
|---|------------------------------|--------|--------|
| 1 | Datei: hub/_services/document/word_template_service.py, v1.1, Produktiv | Code-Header Z.36: "Version: 1.1.0", Aktualisiert: 2026-01-31 | ✓ Korrekt |
| 2 | w14-Namespace "http:/schemas.microsoft.com/office/word/2010/wordml" | Code Z.263: "http://schemas..." | ✗ Typo (fehlender "/", Code korrekt) |
| 3 | fill_template(template_path, data_dict, output_path) — Hauptmethode | Code: existiert NICHT; real: load_template() (Z.139) + save() (Z.694) | ✗ Falsch |
| 4 | fill_table(doc, table_name, rows_data) | Real: fill_table_rows() (Z.558), andere Signatur | ✗ Veraltet |
| 5 | filter_icf_sections(doc, active_sections) | Real: filter_table_rows(table, keep_column, keep_values, header_rows, keep_section_headers) (Z.199) | ✗ Veraltet |
| 6 | replace_placeholders(doc, data_dict) | Code Z.146, exakt | ✓ Korrekt |
| 7 | set_checkbox(doc, checkbox_name, checked) | Real: set_checkbox(doc, label_contains, checked) (Z.245) | ⚠ Praezisiert (Param-Name) |
| 8 | 3-Phasen-ICF-Filterung (Ueberschrift finden → Zeilen sammeln → entfernen) | Real: einfacher Spaltenfilter; Kapitel-Header = Leerzellen-Logik; nur "von unten loeschen" stimmt | ✗ Veraltet |
| 9 | vMerge-Behandlung ("entfernt alle vMerge-Attribute vor Zeilenloeschung") | grep merge/vMerge: NICHTS im Code (nur Lizenztext + continue-Stmts) | ✗ Beschreibt nicht existierende Funktion |
| 10 | Foerderziel-Tabelle mit {{Z1_C}}/{{Z1_ZIEL}}/{{Z1_IST}}/{{Z1_E}}-Zeilen, Klonen | Real: fill_foerderziele_table() (Z.623) nutzt Header-basierte Spaltenerkennung (icf/ziel/ist/erreicht/grund-Keywords); fill_icf_placeholders_and_cleanup() nutzt {CODE-Ziel}-Muster | ✗ Veraltet |
| 11 | python-docx bietet KEINEN direkten Zugriff auf SDT-Checkboxen | PyPI python-docx 1.2.0: kein Content-Control-API; Service nutzt exakt den beschriebenen XML-Fallback (w:sdt-Iter, w14:checkbox) | ✓ Korrekt (bestaetigt) |
| 12 | w14:checked val="0"=unchecked/"1"=checked + zusaetzliches Symbol-Update (☐→☒) | Code Z.281-289: exakt so; MS Learn: Checked-Klasse in Office2010.Word-NS bestaetigt | ✓ Korrekt |

## Zusammenfassung

- **Korrekt:** 4/12 (33 %) — zzgl. 1 praegzisiert = max. 5/12 (42 %)
- **Veraltet/Falsch:** 7/12 (58 %)
- Betroffen: METHODEN-REFERENZ (3 von 5 Methoden falsch), TABELLEN-VERARBEITUNG
  (beide Unterabschnitte veraltet), VMERGE-BEHANDLUNG (komplett ohne
  Codebasis), Namespace-Typo.
- Unberuehrt korrekt: RUN-FRAGMENTIERUNG, PLATZHALTER-SYSTEM,
  CHECKBOX-HANDLING (Kern).

## Empfehlung

**[X] Artikel benoetigt Ueberarbeitung** (<50 % korrekt)

Begruendung: Der Code (Erstellt 27.01., Aktualisiert 31.01., seither
erweitert um Satzbausteine/Textblöcke, Zellen-Zugriff, Tabellen-Helfer)
ist ueber den Artikel hinausgewachsen. Ein Patch einzelner Stellen
wuerde einen Mischzustand erzeugen — Vollrevision in eigenem Lauf.

## Konsequenzen (umgesetzt)

1. **Artikel markiert:** Metadaten-Header ergaenzt (Portabilitaet BACH
   System-spezifisch, Praezedenz skills_board.txt), Status-Marker
   "UEBERARBEITUNG NOETIG", verkuerzte Prueffrist 2026-09-24.
2. **Task #1327 erstellt (P3/Wiki):** Vollrevision mit konkreter
   Fehlerliste im Task-Text.
3. **Index-Luecke geschlossen:** Eintrag unter ENTWICKLUNG ergaenzt
   (fehlte komplett — ebenso wie word_automation.txt, das ebenfalls
   unindiziert ist; fuer spaeter).
4. **Nicht geaendert:** Artikelinhalt bleibt bis zur Vollrevision
   unveraendert (Modus-C-Rahmen: nur Metadaten/Markierung).

## Naechste Pruefung

- Empfehlung: 2026-09-24 (verkuerzt, bis Task #1327 durchlaufen ist;
  danach normale 6-12 Monate)
- Begruendung: Artikel beschreibt produktionsrelevanten Service
  (Foerderbericht); veraltete Doku fuehrt zu Fehlimplementierungen.

## Rotation fuer naechsten Lauf

Modus A (Neuer Artikel) — Rotation A(12.09) → B(16.09) → C(17.09) →
naechster: A.