-- Migration 051: Bank-Matching-Tabellen fuer CAMT-Import (Steuer-Modul)
-- Wird von tools/steuer/bank_matcher.py verwendet (aufgerufen u.a. durch tools/inbox_watcher.py).
-- Idempotent: reines CREATE IF NOT EXISTS / CREATE INDEX IF NOT EXISTS.
-- Bewusst KEIN ALTER TABLE (steuer_001-Stil), da executescript bei doppeltem ALTER fehlschlaegt.

-- Regeln, die einen PARTIAL-Match automatisiert zu MATCHED heben koennen.
-- partner_pattern: Substring (case-insensitiv) in Partner+Verwendungszweck; NULL = egal.
-- betrag_min/betrag_max: Betragsfenster; NULL = egal.
-- datum_toleranz | maximale Abweichung Tx-Datum zu Posten-Datum in Tagen.
-- Eine Regel ohne jedes Kriterium trifft nie.
CREATE TABLE IF NOT EXISTS steuer_bank_match_regeln (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    partner_pattern TEXT,
    betrag_min REAL,
    betrag_max REAL,
    datum_toleranz INTEGER DEFAULT 5,
    aktiv INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now'))
);

-- Ergebnis des Matchings pro Bank-Transaktion (idempotent ueber tx_hash).
-- tx_hash: sha256(datum|betrag|typ|partner|zweck)[:16] -- stabiler Schluessel je CAMT-Buchung.
-- status: MATCHED (auto bestaetigt), PARTIAL (manuell pruefen, via --resolve), UNMATCHED.
CREATE TABLE IF NOT EXISTS steuer_bank_matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tx_hash TEXT UNIQUE NOT NULL,
    camt_datei TEXT,
    datum TEXT,
    betrag REAL,
    typ TEXT,
    partner TEXT,
    zweck TEXT,
    username TEXT,
    steuerjahr INTEGER,
    dokument_id INTEGER,
    posten_id INTEGER,
    status TEXT DEFAULT 'UNMATCHED' CHECK(status IN ('MATCHED', 'PARTIAL', 'UNMATCHED')),
    confidence REAL DEFAULT 0.0,
    regel_id INTEGER,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_steuer_bank_matches_status ON steuer_bank_matches(status);
CREATE INDEX IF NOT EXISTS idx_steuer_bank_matches_user ON steuer_bank_matches(username, steuerjahr);
