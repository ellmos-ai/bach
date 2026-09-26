-- Migration 046: Tool-Warn-Injektor als Trigger-Zeile (S3 von T-20260920-823767362)
--
-- tools/injectors.py ToolInjector.check_before_create als context_triggers
-- mit source='tool_warn'. Der memoryhooker-Seam (hub/memory_hook_provider.py)
-- liest sie und uebernimmt den Injektor; ohne aktive Zeile bleibt BACH beim
-- Altpfad. Alternativen mit '|' in derselben Reihenfolge wie create_signals,
-- Hinweis byte-gleich zum Altpfad (mehrzeilig). Idempotent.

INSERT OR IGNORE INTO context_triggers
    (trigger_phrase, hint_text, source, confidence, is_active, is_protected, status, agent_id)
VALUES
    ('erstelle|create|neues tool|schreibe ein script|baue ein|implementiere ein tool|write a tool|new script|neues script',
     '[TOOL-CHECK] Bevor du ein neues Tool erstellst:' || char(10) ||
     '  1. bach tools search <begriff>  (DB-Suche)' || char(10) ||
     '  2. bach tool suggest ''<beschreibung>''  (Empfehlung)' || char(10) ||
     '  3. Pruefe tools/ und skills/_services/ Ordner' || char(10) ||
     '  Tools sind die Haende der LLMs - Duplikate vermeiden!',
     'tool_warn', 1.0, 1, 1, 'approved', 'default');
