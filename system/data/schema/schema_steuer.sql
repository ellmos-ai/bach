-- ============================================================
-- BACH STEUER-AGENT - DATENBANKSCHEMA
-- ============================================================
-- Erstellt: 2026-01-15
-- Version: 1.1.0
-- Zweck: Tabellen fuer Steuer-Agent (Werbungskosten)
-- Update: Watch-Ordner Tabelle hinzugefuegt
-- ============================================================

PRAGMA foreign_keys = ON;

-- ============================================================
-- STEUER_PROFILE - User-Profile fuer Steuer-Agent
-- ============================================================

CREATE TABLE IF NOT EXISTS steuer_profile (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    name TEXT,
    beruf TEXT,
    branche TEXT,
    kategorien_json TEXT,          -- JSON: Typische Werbungskosten
    anbieter_regeln_json TEXT,     -- JSON: TEMU, Amazon etc.
    keywords_json TEXT,            -- JSON: Automatische Zuordnungen
    gemischte_defaults_json TEXT,  -- JSON: Standard-Anteile
    notizen TEXT,
    aktiv INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- ============================================================
-- STEUER_WATCH_ORDNER - Ueberwachte Ordner
-- ============================================================

CREATE TABLE IF NOT EXISTS steuer_watch_ordner (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    pfad TEXT NOT NULL,
    scan_modus TEXT DEFAULT 'bei_start',  -- bei_start/intervall/manuell
    intervall_min INTEGER,                 -- Minuten (wenn modus=intervall)
    nach_scan TEXT DEFAULT 'KOPIEREN',     -- KOPIEREN/VERSCHIEBEN/BELASSEN
    aktiv INTEGER DEFAULT 1,
    letzter_scan TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    
    FOREIGN KEY (username) REFERENCES steuer_profile(username),
    UNIQUE(username, pfad)
);

-- ============================================================
-- STEUER_POSTEN - Alle erfassten Posten
-- ============================================================

CREATE TABLE IF NOT EXISTS steuer_posten (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    steuerjahr INTEGER NOT NULL,
    postennr INTEGER NOT NULL,
    bezeichnung TEXT NOT NULL,
    datum TEXT,                     -- Rechnungsdatum (YYYY-MM-DD)
    typ TEXT DEFAULT 'Werbungskosten',  -- Werbungskosten/Versicherung/Nachweis
    rechnungsnr TEXT,
    rechnungssteller TEXT,
    dateiname TEXT,
    beschreibung TEXT,
    netto REAL,
    brutto REAL,
    mwst_betrag REAL,               -- MwSt-Betrag (STEUER_001)
    mwst_satz INTEGER DEFAULT 19,   -- Steuersatz 7 oder 19 (STEUER_001)
    bemerkung TEXT,
    liste TEXT NOT NULL,            -- WERBUNGSKOSTEN/GEMISCHTE/ZURUECKGESTELLT/VERWORFEN
    anteil REAL,                    -- Fuer GEMISCHTE (0.1-0.9)
    absetzbar_netto REAL,           -- Berechnet: anteil * netto
    absetzbar_brutto REAL,          -- Berechnet: anteil * brutto
    filtergrund TEXT,               -- Grund bei GEFILTERT
    dokument_id INTEGER,            -- Referenz auf steuer_dokumente
    ist_eigenbeleg INTEGER DEFAULT 0, -- 1 = Eigenbeleg (STEUER_002)
    zahlungsart TEXT,               -- Ueberweisung/PayPal/Kreditkarte/Bar
    bank_referenz TEXT,             -- CAMT Entry-Reference fuer Bank-Matching
    match_status TEXT,              -- AUTO_MATCHED/SUGGESTED/UNMATCHED (Migration 052)
    bank_tx_id INTEGER,             -- Referenz auf steuer_bank_transactions.id (Migration 052)
    version INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),

    FOREIGN KEY (username) REFERENCES steuer_profile(username),
    FOREIGN KEY (dokument_id) REFERENCES steuer_dokumente(id)
);

-- ============================================================
-- STEUER_DOKUMENTE - Alle erfassten Dokumente
-- ============================================================

CREATE TABLE IF NOT EXISTS steuer_dokumente (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    steuerjahr INTEGER NOT NULL,
    dateiname TEXT NOT NULL,
    dateipfad TEXT,
    original_pfad TEXT,             -- Urspruenglicher Pfad vor Kopieren
    status TEXT NOT NULL,           -- ERFASST/NICHT_ERFASST/ZURUECKGESTELLT
    posten_anzahl INTEGER DEFAULT 0,
    quelle TEXT,                    -- UPLOAD/WATCHER/MANUELL
    erfasst_am TEXT,
    hochgeladen_am TEXT DEFAULT (datetime('now')),
    created_at TEXT DEFAULT (datetime('now')),
    
    FOREIGN KEY (username) REFERENCES steuer_profile(username),
    UNIQUE(username, steuerjahr, dateiname)
);

-- ============================================================
-- STEUER_AUSWERTUNG - Jaehrliche Zusammenfassungen
-- ============================================================

CREATE TABLE IF NOT EXISTS steuer_auswertung (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    steuerjahr INTEGER NOT NULL,
    anzahl_posten INTEGER DEFAULT 0,
    anzahl_dokumente INTEGER DEFAULT 0,
    werbungskosten_netto REAL DEFAULT 0,
    werbungskosten_brutto REAL DEFAULT 0,
    gemischte_absetzbar_netto REAL DEFAULT 0,
    gemischte_absetzbar_brutto REAL DEFAULT 0,
    gesamt_absetzbar_netto REAL DEFAULT 0,
    gesamt_absetzbar_brutto REAL DEFAULT 0,
    letzte_aktualisierung TEXT DEFAULT (datetime('now')),
    
    FOREIGN KEY (username) REFERENCES steuer_profile(username),
    UNIQUE(username, steuerjahr)
);

-- ============================================================
-- STEUER_ANBIETER - Anbieter-spezifische Regeln
-- ============================================================

CREATE TABLE IF NOT EXISTS steuer_anbieter (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    anbieter TEXT NOT NULL,         -- TEMU, Amazon, eBay, etc.
    besonderheit TEXT,
    workaround TEXT,
    hinweise TEXT,
    aktiv INTEGER DEFAULT 1,
    
    FOREIGN KEY (username) REFERENCES steuer_profile(username),
    UNIQUE(username, anbieter)
);

-- ============================================================
-- INDICES
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_steuer_posten_user_jahr 
    ON steuer_posten(username, steuerjahr);
    
CREATE INDEX IF NOT EXISTS idx_steuer_posten_liste 
    ON steuer_posten(liste);
    
CREATE INDEX IF NOT EXISTS idx_steuer_dokumente_status 
    ON steuer_dokumente(status);

CREATE INDEX IF NOT EXISTS idx_steuer_watch_aktiv
    ON steuer_watch_ordner(username, aktiv);

-- ============================================================
-- VIEWS
-- ============================================================

-- Werbungskosten-Uebersicht pro Jahr
CREATE VIEW IF NOT EXISTS v_werbungskosten AS
SELECT 
    username,
    steuerjahr,
    COUNT(*) as anzahl,
    SUM(netto) as summe_netto,
    SUM(brutto) as summe_brutto
FROM steuer_posten
WHERE liste = 'WERBUNGSKOSTEN'
GROUP BY username, steuerjahr;

-- Gemischte Posten mit Absetzbarkeit
CREATE VIEW IF NOT EXISTS v_gemischte_absetzbar AS
SELECT 
    username,
    steuerjahr,
    COUNT(*) as anzahl,
    SUM(absetzbar_netto) as summe_absetzbar_netto,
    SUM(absetzbar_brutto) as summe_absetzbar_brutto
FROM steuer_posten
WHERE liste = 'GEMISCHTE'
GROUP BY username, steuerjahr;

-- Gesamtuebersicht pro User/Jahr
CREATE VIEW IF NOT EXISTS v_steuer_gesamt AS
SELECT 
    p.username,
    p.steuerjahr,
    COUNT(*) as gesamt_posten,
    SUM(CASE WHEN p.liste = 'WERBUNGSKOSTEN' THEN p.brutto ELSE 0 END) as werbungskosten_brutto,
    SUM(CASE WHEN p.liste = 'GEMISCHTE' THEN p.absetzbar_brutto ELSE 0 END) as gemischte_absetzbar,
    SUM(CASE WHEN p.liste = 'WERBUNGSKOSTEN' THEN p.brutto 
             WHEN p.liste = 'GEMISCHTE' THEN p.absetzbar_brutto 
             ELSE 0 END) as gesamt_absetzbar
FROM steuer_posten p
GROUP BY p.username, p.steuerjahr;

-- ============================================================
-- TRIGGER - Automatische Updates
-- ============================================================

-- Absetzbare Betraege bei GEMISCHTE automatisch berechnen
CREATE TRIGGER IF NOT EXISTS trg_steuer_posten_gemischte
AFTER INSERT ON steuer_posten
WHEN NEW.liste = 'GEMISCHTE' AND NEW.anteil IS NOT NULL
BEGIN
    UPDATE steuer_posten 
    SET absetzbar_netto = NEW.netto * NEW.anteil,
        absetzbar_brutto = NEW.brutto * NEW.anteil
    WHERE id = NEW.id;
END;

-- ============================================================
-- STEUER_BANK_TRANSACTIONS - CAMT-Buchungen (Migration 052, Task #1397)
-- ============================================================

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
    hash TEXT UNIQUE,                -- sha256(iban|datum|betrag|typ|partner|zweck)
    quelle TEXT DEFAULT 'CAMT',
    datei TEXT,
    imported_at TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_steuer_bank_tx_hash
    ON steuer_bank_transactions(hash);

CREATE INDEX IF NOT EXISTS idx_steuer_bank_tx_user_jahr
    ON steuer_bank_transactions(username, steuerjahr);

-- ============================================================
-- ENDE SCHEMA
-- ============================================================
