-- Migration 036: Rename epstein_runs to chunk_indexing_runs
-- Part of parallel-chunks rename (v3.11.1)
ALTER TABLE epstein_runs RENAME TO chunk_indexing_runs;
