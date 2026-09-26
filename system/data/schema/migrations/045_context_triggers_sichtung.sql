-- Migration 045: Sichtung der aktiven context_triggers (S3 von T-20260920-823767362)
--
-- Anlass: Der ContextInjector hat context_triggers nie gelesen (fehlender
-- sqlite3-Import, falscher DB-Pfad). Beabsichtigt war, dass die DB-Trigger die
-- Hardcode-Liste ersetzen; der Fix liegt hinter BACH_CONTEXT_TRIGGERS_DB=1.
-- Vor dem Einschalten wurden die 292 aktiven Zeilen der Laptop-DB gesichtet
-- (2026-09-26). Nichts wird geloescht: Unsinniges wird deaktiviert
-- (is_active = 0, rueckholbar), verschobene Ziele werden umgebogen.
-- Schluessel ist (source, trigger_phrase, agent_id), nie die id: die ids
-- unterscheiden sich zwischen Laptop und Mac.
-- Beim Altpfad bleibt alles wirkungslos, solange das Flag aus ist.

-- A) source='tool' (92 aktiv): automatisch aus Docstrings extrahiert
--    (tools/tool_auto_discovery.py). Phrasen sind Allerweltswoerter
--    ('the', 'from', 'via', 'over', 'main', 'app', 'type', 'sub', 'tra', ...),
--    die als Teilstring fast jeden Prompt treffen; der Hinweis ist Docstring-
--    Rest ('!/usr/bin/env python3', '=====') und traegt teils absolute
--    OneDrive-Nutzerpfade. Werkzeughinweise kommen kuenftig aus Tool-Warn.
UPDATE context_triggers SET is_active = 0, updated_at = CURRENT_TIMESTAMP
WHERE source = 'tool' AND agent_id = 'default' AND is_active = 1;

-- B) source='lesson' (34 aktiv): Einzelwoerter aus Lesson-Titeln
--    (tools/lesson_trigger_generator.py): 'gibt', 'muss', 'pro', 'sagt',
--    'stufe', 'session', 'aktive', 'dateien', 'mehrere', ... ; dazu Test-
--    Lessons ('Hook-Test', 'Test-Lesson', 'Rueckfluss Test'). Lessons erreicht
--    der Chat bereits ueber die memoryhooker-Suche in memory_lessons
--    (Block MEMORY-HOOK), der Trigger-Weg ist doppelt und ungenau.
UPDATE context_triggers SET is_active = 0, updated_at = CURRENT_TIMESTAMP
WHERE source = 'lesson' AND agent_id = 'default' AND is_active = 1;

-- C) source='theme' (30 aktiv): Themen-Pakete bleiben, nur Stoppwoerter und
--    Allerweltsverben gehen (15). Behalten: teamarbeit, partnern,
--    zusammenarbeit, problemlösung, blockaden, bugs, coding, coding-aufgaben,
--    wartung ausführen, wartungs, wartung, files and folder, dateiverwaltung,
--    dateioperationen, shutdown.
--    Achtung: tools/theme_packet_generator.py schreibt mit INSERT OR REPLACE
--    und wuerde diese Zeilen bei einem neuen Lauf wieder aktivieren.
UPDATE context_triggers SET is_active = 0, updated_at = CURRENT_TIMESTAMP
WHERE source = 'theme' AND agent_id = 'default' AND is_active = 1
  AND trigger_phrase IN ('system', 'arbeitest', 'gleichzeitig', 'triffst', 'probleme',
                         'oder', 'fixt', 'code', 'bearbeitest', 'aufgaben', 'führst',
                         'durch', 'sitzung', 'beendet', 'wird');

-- D) source='manual', Ziel existiert nicht mehr (10): Foerderplaner-Skill und
--    Wikiquizzer sind entfernt, die steuer-*-Workflows gibt es nicht mehr.
UPDATE context_triggers SET is_active = 0, updated_at = CURRENT_TIMESTAMP
WHERE source = 'manual' AND agent_id = 'default' AND is_active = 1
  AND trigger_phrase IN ('foerderplan', 'bericht status', 'quiz', 'lernen',
                         'beleg scan', 'fahrtkosten', 'homeoffice', 'finanzamt',
                         'sonderausgaben', 'werbungskosten');

-- E) source='manual', Ziel verschoben: Hinweis auf den heutigen Ort umbiegen
--    (jeweils per Dateisuche im Repo bestaetigt). 'bach c_*' und
--    'bach python_cli_editor'/'bach code_analyzer' laufen nicht mehr, weil
--    bach.py nur tools/*.py der obersten Ebene startet.
UPDATE context_triggers SET hint_text = REPLACE(hint_text, 'skills/_workflows/', 'skills/workflows/'),
       updated_at = CURRENT_TIMESTAMP
WHERE source = 'manual' AND hint_text LIKE '%skills/_workflows/%';
UPDATE context_triggers SET hint_text = REPLACE(hint_text, 'skills/_services/document/', 'hub/_services/document/'),
       updated_at = CURRENT_TIMESTAMP
WHERE source = 'manual' AND hint_text LIKE '%skills/_services/document/%';
UPDATE context_triggers SET hint_text = REPLACE(hint_text, 'skills/_services/prompt_generator/', 'hub/_services/prompt_generator/'),
       updated_at = CURRENT_TIMESTAMP
WHERE source = 'manual' AND hint_text LIKE '%skills/_services/prompt_generator/%';
UPDATE context_triggers SET hint_text = REPLACE(hint_text, 'skills/_agents/', 'agents/'),
       updated_at = CURRENT_TIMESTAMP
WHERE source = 'manual' AND hint_text LIKE '%skills/_agents/%';
UPDATE context_triggers SET hint_text = REPLACE(hint_text, 'docs/ARCHITECTURE_DIAGRAMS.md', 'ARCHITECTURE.md'),
       updated_at = CURRENT_TIMESTAMP
WHERE source = 'manual' AND hint_text LIKE '%docs/ARCHITECTURE_DIAGRAMS.md%';
UPDATE context_triggers SET hint_text = REPLACE(REPLACE(hint_text, 'tools/cv_generator.py', 'agents/_experts/bewerbungsexperte/cv_generator.py'),
                                        'user/bewerbungsexperte/', 'agents/_experts/bewerbungsexperte/'),
       updated_at = CURRENT_TIMESTAMP
WHERE source = 'manual' AND hint_text LIKE '%cv_generator.py%';
UPDATE context_triggers SET hint_text = REPLACE(REPLACE(REPLACE(hint_text,
           'tools/c_ocr_engine.py --pdf <datei>', 'tools/ocr/cli.py'),
           'tools/c_ocr_engine.py <bild>', 'tools/ocr/cli.py'),
           'tools/c_ocr_engine.py', 'tools/ocr/cli.py'),
       updated_at = CURRENT_TIMESTAMP
WHERE source = 'manual' AND hint_text LIKE '%c_ocr_engine%';
UPDATE context_triggers SET hint_text =
       REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(hint_text,
           'bach c_encoding_fixer', 'python tools/file_ops/encoding_fixer.py'),
           'bach c_json_repair', 'python tools/json/json_repair.py'),
           'bach c_emoji_scanner', 'python tools/emoji_scanner.py'),
           'bach c_indent_checker', 'python tools/coding/indent_checker.py'),
           'bach c_import_organizer', 'python tools/coding/import_organizer.py'),
           'bach c_import_diagnose', 'python tools/coding/import_diagnose.py'),
           'bach c_pycutter', 'python tools/coding/pycutter.py'),
           'bach c_sqlite_viewer', 'python tools/sqlite_viewer.py'),
           'bach c_md_to_pdf', 'python tools/converters/md_to_pdf.py'),
           'bach c_universal_converter', 'python tools/converters/universal_converter.py'),
           'bach python_cli_editor', 'python tools/coding/python_cli_editor.py'),
           'bach code_analyzer', 'python tools/coding/code_analyzer.py'),
       updated_at = CURRENT_TIMESTAMP
WHERE source = 'manual' AND (hint_text LIKE '%bach c\_%' ESCAPE '\'
                             OR hint_text LIKE '%bach python_cli_editor%'
                             OR hint_text LIKE '%bach code_analyzer%');
