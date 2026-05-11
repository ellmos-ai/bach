-- Migration 035: UNIQUE-Index auf bach_agents.name
-- Verhindert doppelte Agent-Einträge (Bug: 5 englische Duplikate in IDs 6-10)
CREATE UNIQUE INDEX IF NOT EXISTS idx_bach_agents_name_unique ON bach_agents(name);
