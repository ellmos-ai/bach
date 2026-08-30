-- ============================================================
-- BACH v1.1.84 - USER DATA SCHEMA
-- ============================================================
-- Erstellt: 2026-01-30
-- Tasks: 779-782 (DATA-SCHEMA-01 bis DATA-SCHEMA-04)
--
-- Dieses Schema ergaenzt die existierenden Tabellen aus der
-- user.db Migration und erstellt vereinheitlichte Views.
-- ============================================================

-- ============================================================
-- TASK 779: VERSICHERUNGEN
-- ============================================================

-- Versicherungsarten-Katalog (Template-Daten)
CREATE TABLE IF NOT EXISTS insurance_types (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    category TEXT,              -- Personen, Sach, Vorsorge, etc.
    description TEXT,
    when_useful TEXT,           -- Wann sinnvoll?
    priority INTEGER DEFAULT 3, -- 1=Pflicht, 2=Wichtig, 3=Optional
    legal_requirement TEXT,     -- Gesetzliche Pflicht?
    typical_cost_range TEXT,    -- z.B. "20-50 EUR/Monat"
    dist_type INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- Initiale Versicherungsarten
INSERT OR IGNORE INTO insurance_types (name, category, description, when_useful, priority) VALUES
('Krankenversicherung', 'Personen', 'Gesetzliche oder private Krankenversicherung', 'Immer - Pflichtversicherung', 1),
('Haftpflichtversicherung', 'Personen', 'Privathaftpflicht fuer Schaeden an Dritten', 'Immer - wichtigste freiwillige Versicherung', 1),
('Berufsunfaehigkeitsversicherung', 'Vorsorge', 'Absicherung bei Berufsunfaehigkeit', 'Fuer Berufstaetige mit Einkommen', 2),
('Hausratversicherung', 'Sach', 'Schutz fuer Hausrat bei Einbruch, Feuer, Wasser', 'Bei wertvollem Hausrat', 2),
('Rechtsschutzversicherung', 'Sach', 'Kostenuebernahme bei Rechtsstreitigkeiten', 'Bei haeufigen Vertragsangelegenheiten', 3),
('KFZ-Haftpflicht', 'KFZ', 'Pflichtversicherung fuer Fahrzeughalter', 'Bei Fahrzeugbesitz - Pflicht', 1),
('KFZ-Kasko', 'KFZ', 'Teilkasko/Vollkasko fuer eigenes Fahrzeug', 'Bei neueren/wertvollen Fahrzeugen', 3),
('Unfallversicherung', 'Personen', 'Absicherung bei Unfaellen', 'Ergaenzung zur BU', 3),
('Lebensversicherung', 'Vorsorge', 'Kapitallebens- oder Risikolebensversicherung', 'Bei Familie/Krediten', 2),
('Rentenversicherung', 'Vorsorge', 'Private Altersvorsorge', 'Zusaetzlich zur gesetzlichen Rente', 2);

-- View fuer Versicherungen (vereint fin_insurances mit insurance_types)
CREATE VIEW IF NOT EXISTS v_insurances AS
SELECT
    i.id,
    i.anbieter as provider,
    i.tarif_name as policy_name,
    i.police_nr as policy_number,
    i.sparte as insurance_type,
    t.category as type_category,
    t.priority as type_priority,
    i.status,
    i.beginn_datum as start_date,
    i.ablauf_datum as end_date,
    i.kuendigungsfrist_monate as cancellation_months,
    i.beitrag as monthly_cost,
    i.zahlweise as payment_interval,
    i.steuer_relevant_typ as tax_relevant,
    i.ordner_pfad as folder_path,
    i.notizen as notes,
    i.dist_type
FROM fin_insurances i
LEFT JOIN insurance_types t ON LOWER(i.sparte) LIKE '%' || LOWER(t.name) || '%';


-- ============================================================
-- TASK 780: FINANZEN
-- ============================================================

-- Bankkonten
CREATE TABLE IF NOT EXISTS bank_accounts (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    purpose TEXT,               -- Zweck: Gehalt, Sparen, etc.
    account_number TEXT,
    bank_name TEXT,
    blz TEXT,
    iban TEXT,
    bic TEXT,
    holder_name TEXT,
    account_type TEXT,          -- Giro, Spar, Tagesgeld, Depot
    is_primary INTEGER DEFAULT 0,
    balance REAL,               -- Aktueller Kontostand (optional)
    balance_date TEXT,          -- Datum des Kontostands
    notes TEXT,
    dist_type INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- Kredite
CREATE TABLE IF NOT EXISTS credits (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    purpose TEXT,
    bank_name TEXT,
    account_number TEXT,
    iban TEXT,
    original_amount REAL,
    interest_rate REAL,         -- Zinssatz in %
    payment_interval TEXT,      -- monthly, yearly
    payment_amount REAL,
    remaining_amount REAL,
    paid_amount REAL,
    start_date TEXT,
    end_date TEXT,
    status TEXT DEFAULT 'active', -- active, paid_off
    notes TEXT,
    dist_type INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- Irregulaere Kosten (jaehrliche Zahlungen etc.)
CREATE TABLE IF NOT EXISTS irregular_costs (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    category TEXT,              -- Steuer, Versicherung, Mitgliedschaft, etc.
    expected_month INTEGER,     -- 1-12, wann faellig
    expected_amount REAL,
    is_recurring INTEGER DEFAULT 1,
    last_paid_date TEXT,
    last_paid_amount REAL,
    notes TEXT,
    dist_type INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- Unified Subscriptions View (vereint financial_subscriptions + abo_subscriptions + fin_contracts)
CREATE VIEW IF NOT EXISTS v_subscriptions AS
SELECT
    'fin_sub_' || id as uid,
    provider_name as name,
    provider_name as provider,
    category,
    betrag_monatlich as monthly_cost,
    zahlungsintervall as interval,
    CASE WHEN aktiv = 1 THEN 'active' ELSE 'inactive' END as status,
    CASE WHEN bestaetigt = 1 THEN 'confirmed' ELSE 'detected' END as source,
    letzte_zahlung as last_payment,
    naechste_zahlung as next_payment,
    kuendigungslink as cancel_link,
    'financial_subscriptions' as source_table
FROM financial_subscriptions
UNION ALL
SELECT
    'abo_' || id as uid,
    name,
    anbieter as provider,
    kategorie as category,
    betrag_monatlich as monthly_cost,
    zahlungsintervall as interval,
    CASE WHEN aktiv = 1 THEN 'active' ELSE 'inactive' END as status,
    CASE WHEN bestaetigt = 1 THEN 'confirmed' ELSE 'detected' END as source,
    NULL as last_payment,
    NULL as next_payment,
    kuendigungslink as cancel_link,
    'abo_subscriptions' as source_table
FROM abo_subscriptions
UNION ALL
SELECT
    'contract_' || id as uid,
    name,
    anbieter as provider,
    kategorie as category,
    betrag as monthly_cost,
    intervall as interval,
    CASE WHEN kuendigungs_status = 'aktiv' THEN 'active' ELSE 'inactive' END as status,
    'manual' as source,
    NULL as last_payment,
    naechste_zahlung as next_payment,
    NULL as cancel_link,
    'fin_contracts' as source_table
FROM fin_contracts;


-- ============================================================
-- TASK 781: KONTAKTE
-- ============================================================

-- Unified Contacts Tabelle
CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY,
    -- Basis
    name TEXT NOT NULL,
    first_name TEXT,
    last_name TEXT,
    -- Kategorisierung
    category TEXT,              -- privat, beruflich, arzt, versicherung, bank, behoerde
    subcategory TEXT,           -- z.B. bei arzt: Fachrichtung
    -- Organisation
    organization TEXT,
    position TEXT,
    -- Kommunikation
    phone TEXT,
    phone_mobile TEXT,
    phone_work TEXT,
    email TEXT,
    email_work TEXT,
    -- Adresse
    street TEXT,
    city TEXT,
    zip_code TEXT,
    country TEXT DEFAULT 'Deutschland',
    -- Zusatz
    website TEXT,
    birthday TEXT,
    notes TEXT,
    tags TEXT,                  -- Komma-separierte Tags
    -- Meta
    is_active INTEGER DEFAULT 1,
    source TEXT,                -- health_contacts, assistant_contacts, manual
    source_id INTEGER,          -- Original-ID aus Quelltabelle
    dist_type INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- Migrate health_contacts to contacts
INSERT OR IGNORE INTO contacts (name, category, subcategory, organization, phone, email,
                                street, notes, is_active, source, source_id)
SELECT
    name,
    'arzt' as category,
    specialty as subcategory,
    institution as organization,
    phone,
    email,
    address as street,
    notes,
    is_active,
    'health_contacts' as source,
    id as source_id
FROM health_contacts
WHERE NOT EXISTS (
    SELECT 1 FROM contacts WHERE source = 'health_contacts' AND source_id = health_contacts.id
);


-- ============================================================
-- TASK 782: ROUTINEN & TERMINE
-- ============================================================

-- Routinen (nutzt existierende household_routines, erweitert um mehr Kategorien)
CREATE TABLE IF NOT EXISTS routines (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    category TEXT,              -- haushalt, gesundheit, finanzen, arbeit, etc.
    -- Intervall
    interval_type TEXT,         -- daily, weekly, monthly, yearly
    interval_value INTEGER DEFAULT 1, -- alle X Tage/Wochen/etc.
    specific_day TEXT,          -- z.B. "monday" oder "15" (Tag im Monat)
    -- Tracking
    last_completed_at TEXT,
    next_due_at TEXT,
    -- Status
    is_active INTEGER DEFAULT 1,
    priority INTEGER DEFAULT 2, -- 1=Hoch, 2=Normal, 3=Niedrig
    duration_minutes INTEGER,
    -- Quelle
    source_file TEXT,           -- z.B. Haushaltsaufgaben.docx
    source TEXT,                -- household_routines, import, manual
    source_id INTEGER,
    -- Meta
    notes TEXT,
    dist_type INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- Migrate household_routines to routines
INSERT OR IGNORE INTO routines (name, category, interval_type, last_completed_at, next_due_at,
                                is_active, duration_minutes, notes, source, source_id)
SELECT
    name,
    category,
    frequency as interval_type,
    last_done as last_completed_at,
    next_due as next_due_at,
    is_active,
    duration_minutes,
    notes,
    'household_routines' as source,
    id as source_id
FROM household_routines
WHERE NOT EXISTS (
    SELECT 1 FROM routines WHERE source = 'household_routines' AND source_id = household_routines.id
);

-- Kalenderdaten liegen kanonisch in assistant_calendar. calendar_events ist
-- seit Migration 037 nur noch eine Read-only-Kompatibilitätsansicht.


-- ============================================================
-- HELPER VIEWS
-- ============================================================

-- Faellige Routinen diese Woche
CREATE VIEW IF NOT EXISTS v_routines_due_this_week AS
SELECT * FROM routines
WHERE is_active = 1
  AND (next_due_at IS NULL OR DATE(next_due_at) <= DATE('now', '+7 days'))
ORDER BY
    CASE WHEN next_due_at IS NULL THEN 1 ELSE 0 END,
    next_due_at;

-- Aktive Abos mit Kosten
CREATE VIEW IF NOT EXISTS v_active_subscriptions AS
SELECT * FROM v_subscriptions
WHERE status = 'active'
ORDER BY monthly_cost DESC;

-- Monatskosten Uebersicht
CREATE VIEW IF NOT EXISTS v_monthly_costs AS
SELECT
    category,
    SUM(monthly_cost) as total_monthly,
    COUNT(*) as count
FROM v_subscriptions
WHERE status = 'active'
GROUP BY category
ORDER BY total_monthly DESC;


-- ============================================================
-- INDICES
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_contacts_category ON contacts(category);
CREATE INDEX IF NOT EXISTS idx_contacts_name ON contacts(name);
CREATE INDEX IF NOT EXISTS idx_routines_next_due ON routines(next_due_at);
CREATE INDEX IF NOT EXISTS idx_routines_category ON routines(category);
CREATE INDEX IF NOT EXISTS idx_assistant_calendar_start ON assistant_calendar(start_datetime);
CREATE INDEX IF NOT EXISTS idx_bank_accounts_iban ON bank_accounts(iban);
