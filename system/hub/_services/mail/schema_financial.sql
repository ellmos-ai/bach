-- ============================================================
-- BACH FINANCIAL MAIL - DATENBANKSCHEMA
-- ============================================================
-- Erstellt: 2026-01-20
-- Version: 1.0.0
-- Zweck: Finanzdaten aus E-Mails extrahieren und speichern
-- Integration: user.db
-- ============================================================

PRAGMA foreign_keys = ON;

-- ============================================================
-- MAIL_ACCOUNTS - E-Mail Konten Konfiguration
-- ============================================================

CREATE TABLE IF NOT EXISTS mail_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,                    -- "Hauptkonto", "Geschaeftlich"
    email TEXT NOT NULL UNIQUE,            -- E-Mail Adresse
    provider TEXT NOT NULL,                -- "gmail", "outlook", "gmx", "imap"
    imap_host TEXT,                        -- IMAP Server
    imap_port INTEGER DEFAULT 993,
    use_oauth INTEGER DEFAULT 0,           -- 1 = OAuth (Gmail), 0 = Passwort
    is_active INTEGER DEFAULT 1,
    last_sync TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- MAIL_SYNC_RUNS - Synchronisierungslaeufe
-- ============================================================

CREATE TABLE IF NOT EXISTS mail_sync_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER REFERENCES mail_accounts(id),
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP,
    duration_seconds REAL,
    emails_processed INTEGER DEFAULT 0,
    emails_matched INTEGER DEFAULT 0,
    attachments_saved INTEGER DEFAULT 0,
    errors TEXT,                           -- JSON array
    triggered_by TEXT DEFAULT 'manual',    -- manual, daemon, startup
    status TEXT DEFAULT 'running' CHECK(status IN ('running', 'success', 'failed'))
);

CREATE INDEX IF NOT EXISTS idx_mail_sync_account ON mail_sync_runs(account_id);

-- ============================================================
-- FINANCIAL_EMAILS - Erkannte Finanz-E-Mails
-- ============================================================

CREATE TABLE IF NOT EXISTS financial_emails (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER REFERENCES mail_accounts(id),
    message_id TEXT UNIQUE,                -- RFC Message-ID
    provider_id TEXT NOT NULL,             -- ID aus providers.json
    provider_name TEXT NOT NULL,           -- Anzeigename
    category TEXT NOT NULL,                -- telekommunikation, versicherung, etc.

    -- E-Mail Metadaten
    sender TEXT NOT NULL,
    subject TEXT NOT NULL,
    email_date TIMESTAMP,
    received_at TIMESTAMP,

    -- Erkannte Daten
    document_type TEXT,                    -- rechnung, police, kontoauszug, etc.
    steuer_relevant INTEGER DEFAULT 0,
    steuer_typ TEXT,                       -- Werbungskosten, Versicherung, etc.

    -- Status
    status TEXT DEFAULT 'neu' CHECK(status IN ('neu', 'verarbeitet', 'exportiert', 'ignoriert')),
    has_attachment INTEGER DEFAULT 0,
    attachment_path TEXT,                  -- Pfad zur gespeicherten PDF

    -- Extrahierte Werte (durch LLM oder Regex)
    extracted_data TEXT,                   -- JSON mit allen extrahierten Feldern
    betrag REAL,                           -- Hauptbetrag (Brutto)
    betrag_netto REAL,
    rechnungsnummer TEXT,
    faelligkeit TEXT,
    zeitraum TEXT,

    -- Verknuepfung zu Steuer
    steuer_posten_id INTEGER,              -- Referenz auf steuer_posten falls uebernommen

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_financial_emails_provider ON financial_emails(provider_id);
CREATE INDEX IF NOT EXISTS idx_financial_emails_category ON financial_emails(category);
CREATE INDEX IF NOT EXISTS idx_financial_emails_status ON financial_emails(status);
CREATE INDEX IF NOT EXISTS idx_financial_emails_steuer ON financial_emails(steuer_relevant);
CREATE INDEX IF NOT EXISTS idx_financial_emails_date ON financial_emails(email_date);

-- ============================================================
-- FINANCIAL_SUBSCRIPTIONS - Erkannte Abonnements
-- ============================================================

CREATE TABLE IF NOT EXISTS financial_subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_id TEXT NOT NULL UNIQUE,
    provider_name TEXT NOT NULL,
    category TEXT NOT NULL,

    -- Abo-Details
    betrag_monatlich REAL,
    betrag_jaehrlich REAL,
    zahlungsintervall TEXT,                -- monatlich, quartalsweise, jaehrlich
    naechste_zahlung TEXT,
    kuendigungslink TEXT,

    -- Tracking
    letzte_rechnung_id INTEGER REFERENCES financial_emails(id),
    letzte_zahlung TEXT,
    zahlungen_count INTEGER DEFAULT 0,

    -- Status
    aktiv INTEGER DEFAULT 1,
    bestaetigt INTEGER DEFAULT 0,          -- Manuell bestaetigt
    steuer_relevant INTEGER DEFAULT 0,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_subscriptions_aktiv ON financial_subscriptions(aktiv);

-- ============================================================
-- FINANCIAL_SUMMARY - Monatliche/Jaehrliche Zusammenfassung
-- ============================================================

CREATE TABLE IF NOT EXISTS financial_summary (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    jahr INTEGER NOT NULL,
    monat INTEGER,                          -- NULL = Jahreszusammenfassung

    -- Summen nach Kategorie (JSON)
    summen_kategorie TEXT,                  -- {"telekom": 45.00, "versicherung": 120.00, ...}

    -- Totals
    total_ausgaben REAL DEFAULT 0,
    total_steuer_relevant REAL DEFAULT 0,
    total_abos REAL DEFAULT 0,

    -- Counts
    anzahl_rechnungen INTEGER DEFAULT 0,
    anzahl_abos INTEGER DEFAULT 0,

    berechnet_am TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(jahr, monat)
);

-- ============================================================
-- VIEWS
-- ============================================================

-- Offene/Neue Finanz-E-Mails
CREATE VIEW IF NOT EXISTS v_financial_inbox AS
SELECT
    fe.id,
    fe.provider_name,
    fe.category,
    fe.subject,
    fe.email_date,
    fe.document_type,
    fe.betrag,
    fe.steuer_relevant,
    fe.steuer_typ,
    fe.status,
    fe.has_attachment
FROM financial_emails fe
WHERE fe.status = 'neu'
ORDER BY fe.email_date DESC;

-- Steuer-relevante Posten
CREATE VIEW IF NOT EXISTS v_financial_steuer AS
SELECT
    fe.id,
    fe.provider_name,
    fe.category,
    fe.email_date,
    fe.document_type,
    fe.steuer_typ,
    fe.betrag,
    fe.betrag_netto,
    fe.rechnungsnummer,
    fe.zeitraum,
    fe.steuer_posten_id
FROM financial_emails fe
WHERE fe.steuer_relevant = 1
ORDER BY fe.email_date DESC;

-- Aktive Abonnements mit Kosten
CREATE VIEW IF NOT EXISTS v_aktive_abos AS
SELECT
    fs.id,
    fs.provider_name,
    fs.category,
    fs.betrag_monatlich,
    fs.zahlungsintervall,
    fs.naechste_zahlung,
    fs.kuendigungslink,
    fs.zahlungen_count,
    fs.steuer_relevant,
    fs.bestaetigt
FROM financial_subscriptions fs
WHERE fs.aktiv = 1
ORDER BY fs.betrag_monatlich DESC;

-- Monatliche Kosten-Uebersicht
CREATE VIEW IF NOT EXISTS v_monatliche_kosten AS
SELECT
    strftime('%Y-%m', email_date) as monat,
    category,
    COUNT(*) as anzahl,
    SUM(betrag) as summe,
    SUM(CASE WHEN steuer_relevant = 1 THEN betrag ELSE 0 END) as steuer_summe
FROM financial_emails
WHERE betrag IS NOT NULL
GROUP BY strftime('%Y-%m', email_date), category
ORDER BY monat DESC, summe DESC;

-- ============================================================
-- TRIGGER - Automatische Updates
-- ============================================================

-- Abo-Erkennung: Wenn mehr als 3 Zahlungen vom gleichen Anbieter
CREATE TRIGGER IF NOT EXISTS trg_detect_subscription
AFTER INSERT ON financial_emails
WHEN NEW.betrag IS NOT NULL
BEGIN
    -- Pruefe ob bereits Subscription existiert
    INSERT OR IGNORE INTO financial_subscriptions (
        provider_id, provider_name, category,
        betrag_monatlich, zahlungsintervall,
        letzte_rechnung_id, letzte_zahlung, zahlungen_count,
        steuer_relevant
    )
    SELECT
        NEW.provider_id,
        NEW.provider_name,
        NEW.category,
        NEW.betrag,
        'monatlich',
        NEW.id,
        NEW.email_date,
        1,
        NEW.steuer_relevant
    WHERE (
        SELECT COUNT(*) FROM financial_emails
        WHERE provider_id = NEW.provider_id
    ) >= 3;

    -- Update existierende Subscription
    UPDATE financial_subscriptions
    SET letzte_rechnung_id = NEW.id,
        letzte_zahlung = NEW.email_date,
        zahlungen_count = zahlungen_count + 1,
        betrag_monatlich = NEW.betrag,
        updated_at = CURRENT_TIMESTAMP
    WHERE provider_id = NEW.provider_id;
END;

-- Updated-At Trigger
CREATE TRIGGER IF NOT EXISTS trg_financial_emails_updated
AFTER UPDATE ON financial_emails
BEGIN
    UPDATE financial_emails SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;

-- ============================================================
-- ENDE SCHEMA
-- ============================================================
