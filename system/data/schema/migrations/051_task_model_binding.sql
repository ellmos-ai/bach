-- Migration 051: Model and Slot routing columns for tasks
-- Datum: 2026-09-28
-- Beschreibung: Erweitert tasks-Tabelle um required_model und assigned_slot

ALTER TABLE tasks ADD COLUMN required_model TEXT DEFAULT NULL;
ALTER TABLE tasks ADD COLUMN assigned_slot TEXT DEFAULT NULL;
