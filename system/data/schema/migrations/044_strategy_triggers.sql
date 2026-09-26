-- Migration 044: Strategy-Injektor als Trigger-Zeilen (S3 von T-20260920-823767362)
-- BACH-SEED: idempotent
--
-- Die sechs Gruppen aus tools/injectors.py StrategyInjector.STRATEGIES als
-- context_triggers mit source='strategy'. Der memoryhooker-Seam
-- (hub/memory_hook_provider.py) liest sie und uebernimmt damit den Injektor;
-- solange keine aktive Zeile existiert, bleibt BACH beim Altpfad.
--
-- Eine Zeile je Gruppe, Alternativen mit '|' getrennt: so kollidieren
-- 'fehler' und 'bug' nicht mit den gleichlautenden manual-Triggern am
-- UNIQUE(agent_id, trigger_phrase). Hinweis = letzte Strategie der Gruppe,
-- denn alle Aufrufer uebergeben keinen context (StrategyInjector.check waehlt
-- dann strategies[-1]). Reihenfolge = Gruppenreihenfolge (erste passende
-- Gruppe gewinnt, wie im Altpfad).
--
-- Idempotent: INSERT OR IGNORE auf UNIQUE(agent_id, trigger_phrase).

INSERT OR IGNORE INTO context_triggers
    (trigger_phrase, hint_text, source, confidence, is_active, is_protected, status, agent_id)
VALUES
    ('fehler|error|bug|kaputt', '[STRATEGIE] Erst verstehen, dann fixen.', 'strategy', 1.0, 1, 1, 'approved', 'default'),
    ('komplex|kompliziert|schwierig|gross', '[STRATEGIE] Was ist der kleinste erste Schritt?', 'strategy', 1.0, 1, 1, 'approved', 'default'),
    ('blockiert|blocked|stuck|komme nicht weiter', '[STRATEGIE] Frage an User in chat.json notieren.', 'strategy', 1.0, 1, 1, 'approved', 'default'),
    ('wenig zeit|schnell|eilt|dringend', '[STRATEGIE] Lieber weniger aber richtig.', 'strategy', 1.0, 1, 1, 'approved', 'default'),
    ('unsicher|weiss nicht|vielleicht|unklar', '[STRATEGIE] Annahmen explizit dokumentieren.', 'strategy', 1.0, 1, 1, 'approved', 'default'),
    ('fertig|geschafft|done|erledigt', '[STRATEGIE] Between-Tasks Check nicht vergessen.', 'strategy', 1.0, 1, 1, 'approved', 'default');
