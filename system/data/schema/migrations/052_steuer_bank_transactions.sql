-- Migration 052: CAMT-Transaktions-Persistenz steuer_bank_transactions + Matching-Spalten auf steuer_posten (Task #1397)
-- Wird von hub/steuer.py verwendet: steuer import camt (_persist_camt_transactions) und steuer match (_match).
-- Idempotent: reines CREATE IF NOT EXISTS / CREATE INDEX IF NOT EXISTS.
-- ALTER TABLE steuer_posten ist hier bewusst erlaubt: SQLite kennt kein ADD COLUMN IF NOT EXISTS;
--   die 1x-Buchung in _migrations verhindert ein Doppel-Exec (anders als steuer_001, wo
--   executescript ohne Tracking laeuft). Setzt steuer_posten aus der Schema-Baseline voraus.
--   Bewusst KEIN ALTER auf den 051-Tabellen (steuer_bank_matches, steuer_bank_match_regeln).
-- match_status Werte: AUTO_MATCHED / SUGGESTED / UNMATCHED (siehe hub/steuer.py _match).
-- bank_tx_id referenziert steuer_bank_transactions.id (kein FOREIGN KEY, damit auch
--   SUGGESTED/UNMATCHED-Zustaende ohne Constraint getragen werden koennen).

-- Jede CAMT-Buchung (Ntry) aus camt_parser, vorzeichenbehaftet (DBIT negativ).
-- hash: sha256(iban|datum|betrag|typ|partner|zweck) -- stabil je CAMT-Buchung,
-- INSERT OR IGNORE macht Re-Import desselben Kontos/Zeitraums idempotent.
CREATE TABLE IF NOT EXISTS steuer_bank_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT,
    steuerjahr INTEGER,
    buchungsdatum TEXT,
    wertstellungsdatum TEXT,
    betrag REAL,                     -- vorzeichenbehaftet: DBIT = negativ
    typ TEXT,                        -- CRDT/DBIT
    partner TEXT,
    zweck TEXT,
    iban TEXT,
    partner_iban TEXT,
    waehrung TEXT DEFAULT 'EUR',
    hash TEXT UNIQUE,
    quelle TEXT DEFAULT 'CAMT',
    datei TEXT,
    imported_at TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_steuer_bank_tx_hash ON steuer_bank_transactions(hash);
CREATE INDEX IF NOT EXISTS idx_steuer_bank_tx_user_jahr ON steuer_bank_transactions(username, steuerjahr);

ALTER TABLE steuer_posten ADD COLUMN match_status TEXT;
ALTER TABLE steuer_posten ADD COLUMN bank_tx_id INTEGER;