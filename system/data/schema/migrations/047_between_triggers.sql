-- Migration 047: Between-Injektor als Trigger-Zeile (S3 von T-20260920-823767362)
--
-- tools/injectors.py BetweenInjector.check_task_done als context_triggers mit
-- source='between'. Nur der CLI-Pfad (bach.py _run_injectors) prueft sie, und
-- zwar gegen '<command> <operation>' ("done" wie im Altpfad), nie gegen einen
-- Prompt. Planabweichung (Entscheid team-lead 2026-09-26): memoryhooker statt
-- workflowhooker. Ohne aktive Zeile bleibt BACH beim Altpfad. Hinweis
-- byte-gleich zum Altpfad (mehrzeilig). Idempotent.
-- Phrase 'done|task done' statt 'done': trifft genau dieselben Texte, kollidiert
-- aber nicht mit der (inaktiven) lesson-Zeile 'done' am UNIQUE(agent_id, phrase).

INSERT OR IGNORE INTO context_triggers
    (trigger_phrase, hint_text, source, confidence, is_active, is_protected, status, agent_id)
VALUES
    ('done|task done',
     '[BETWEEN-TASKS]' || char(10) ||
     '1. Zeit-Check: Noch im Limit?' || char(10) ||
     '2. Memory OK? (--memory size)' || char(10) ||
     '3. Nächste Aufgabe oder Shutdown?' || char(10) ||
     '' || char(10) ||
     'Tipp: --status für Übersicht',
     'between', 1.0, 1, 1, 'approved', 'default');
