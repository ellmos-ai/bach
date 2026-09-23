# Wiki-Vollrevision: word_template_service.txt
**Datum:** 2026-09-17 | **Task:** #1327 | **Agent:** Buddha/BACH | **Modus:** Vollrevision (Folgetask aus Modus-C-Stichprobe #1318)

## Ausgangslage
Modus-C-Stichprobe 2026-09-17: 4/12 Fakten korrekt (33-42 %) -> Workflow-Konsequenz
"<50 %: Ueberarbeitung markieren, Task erstellen" -> Task #1327 mit 7-Punkte-Fehlerliste.

## Durchgefuehrte Revision
Komplette Neuauflage des Artikels (12.082 Zeichen) gegen vollstaendig gelesenen
Produktionscode hub/_services/document/word_template_service.py (v1.1.0, 15 Methoden).

### Behobene Fehler (7/7 aus Stichproben-Liste)
1. fill_template existiert nicht -> Typischer Ablauf auf load_template()+save()
   umgestellt, mit explizitem Negativ-Hinweis.
2. fill_table/filter_icf_sections -> ersetzt durch die 4 realen Tabellen-Ansaetze
   (filter_table_rows, fill_table_rows, fill_foerderziele_table,
   fill_icf_placeholders_and_cleanup) + Hilfsmethoden (set_cell_text,
   find_table_row_by_text, remove_table_row, get_table_data).
3. 3-Phasen-Algorithmus entfernt -> reale Logik von filter_table_rows dokumentiert
   (keep_column/keep_values, Leerzelle=Kapitel-Header, Loeschen von hinten).
4. vMerge-Sektion gestrichen -> grep ueber Code: 0 Treffer; als explizite Warnung
   dokumentiert (keine vMerge-Logik, Vorlagen duerfen vMerge nicht nutzen).
5. Namespace-Typo http:/schemas -> http://schemas.microsoft.com/office/word/2010/wordml
   (Code Z.262-263).
6. Fehlende Methoden ergaenzt: alle 15 inkl. set_cell_text, find_table_row_by_text,
   activate_textblock/remove_textblock, fill_icf_placeholders_and_cleanup,
   get_table_data, remove_table_row. Methoden-Referenz mit vollstaendigen
   Signaturen; Negativ-Liste der Phantom-Methoden als Bewacher gegen Rueckfall.
7. set_checkbox: Parameter label_contains (nicht checkbox_name), sucht NUR in
   Tabellenzellen (_get_cell_text), Methoden 1 (SDT/w14) + 2 (Unicode-Fallback).

### Zusatz-Verifikationen
- Ersetzungsbereiche von replace_placeholders: XML-Iteration (erfasst Textboxen),
  direkte w:t-Iteration (SDT), Tabellen, Header/Footer je Section.
- fill_icf_placeholders_and_cleanup: EINFACHE Klammern {CODE-Ziel}/{CODE-Ist}/
  {CODE-E}/{CODE-G}; erreicht 1-3 -> (1)/(2)/(3); grund 1-4 -> (1)-(4).
- fill_foerderziele_table: Header-Keywords (icf/code, ziel+formulierung, ist/stand/
  beschreibung, erreicht/bewertung, grund); erreicht-Mapping 1-3 in Klartext;
  Fallback-Reihenfolge. Kein {{Z1_*}}-Schema im Code.
- Verwender: hub/_services/document/report_workflow_service.py (Import Z.94,
  Instanziierung Z.1594) -> Zweck-Abschnitt angepasst.
- CLI: main() mit --info (Dokumentstruktur) dokumentiert.

### Korrekt geblieben (aus Stichprobe)
Run-Fragmentierung, {{NAME}}-Platzhalterformat, SDT-Checkbox-Grundmechanik
(python-docx 1.2.0 ohne Content-Control-API; val 0/1 + zusaetzliches Symbol-Update).

### Metadaten
- Zuletzt validiert: 2026-09-17 (Vollrevision)
- Status: Aktuell (Status-Marker "UEBERARBEITUNG NOETIG" entfernt)
- Naechste Pruefung: 2027-03-17 (regulaeres Intervall wiederhergestellt)
- Wiki-Index (_index.txt): Status-Zeile aktualisiert

## Nebenbefund
report_workflow_service.py Z.1724: Kommentar nennt Methode
`WordTemplateService._replace_placeholders_in_doc` — existiert nicht im Code
(real: replace_placeholders). Stiler Kommentar im Verwender, nicht im
Wiki-Artikel; Kandidat fuer kosmetischen Fix bei naechster Beruehrung der Datei.

## Rotation
Naechster geplanter wiki_author-Lauf: **Modus A** (Protokoll dokumentiert in
vorangehenden Reports; Modus B-Kandidat: word_automation.txt, unindiziert).