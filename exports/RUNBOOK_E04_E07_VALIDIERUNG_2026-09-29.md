# RUNBOOK E04/E07 — Validierung im Lieferfall

**Stand:** 2026-09-29 (Autonome Runde 9) · **Status:** Vorbereitung abgeschlossen; Ausführung nur im Lieferfall
**Gegenstand:** Validierung und ggf. Import von Bank-Export-Dateien — E07 = CAMT.053-Kontoauszug (XML), E04 = sonstige Exportformate (CSV, anderes XML)

---

## 1. Zweck und Gates

**Zweck:** Schritt-für-Schritt-Ablauf für den Lieferfall. Der Lieferfall tritt ein, wenn der USER
1. den Pfad zu einer E04- oder E07-Datei im Chat liefert, **oder**
2. explizit die Freigabe erteilt, den letzten offenen Kanal `connector poll telegram_main` abzufragen (fünf weitere Kanäle wurden bereits geprüft — alle negativ; nicht wiederholen).

**Gates (in jeder Runde einhalten):**
- **Produktive Schritte nur nach expliziter Freigabe:** Import in die Datenbank, Backup/Restore, DELETE sowie `connector poll telegram_main` / `dispatch` niemals autonom ausführen. Read-only-Identifikation und Dry-Run sind erlaubt.
- **Keine sensiblen Inhalte in Task-Beschreibungen oder Chat:** nur Aggregate (Transaktionszahl, Salden) und maskierte Kennungen (IBAN `****1234`). Keine vollständigen IBANs, keine Klarnamen aus Zahlungspartnern, keine Zwecktexte.
- **safe_shell nur read-only:** erlaubt sind `file`, `head`, `ls`, `stat`, `find`; nicht erlaubt sind `sqlite3` und Metazeichen (`|`, `;`, `&&`, `2>/dev/null`).
- **E06-Apply** (`--apply --confirm`) ist NICHT Teil dieses Runbooks und bleibt separat über #1568/#1569 gegated.

---

## 2. E07-Lieferfall (CAMT.053-Kontoauszug)

Voraussetzung: USER hat Pfad geliefert oder Freigabe erteilt; Datei liegt lokal vor.

### Schritt 1 — Read-only Identifikation (safe_shell)
- `file <pfad>`: Dateityp bestätigen.
- `head -n 40 <pfad>`: Ist es XML? Document-Root prüfen; CAMT.053-Namespace prüfen (`urn:iso:std:iso:20022:tech:xsd:camt.053.…`).
- Struktur gegen das Feld-Mapping aus `system/wiki/camt053.txt` prüfen:
  - **IBAN** = `Stmt/Acct/Id/IBAN`
  - **Betrag** = `Stmt/Ntry/Amt`
  - **Typ** = `CdtDbtInd` (CRDT/DBIT)
  - **Datum** = `Stmt/Ntry/BookgDt/Dt`
  - **Partner** = `RltdPties/Dbtr/Nm` (Fallback `UltmtDbtr`/`UltmtCdtr`)
  - **Zweck** = `RmtInf/Ustrd` (mehrere Einträge werden mit „ | “ konkateniert)
- Parser-Basis: ElementTree mit dynamischen Namespaces; defusedxml >= 0.7.1 (requirements.txt).

### Schritt 2 — Dry-Run (schreibt nichts)
```
bach steuer import camt <pfad> --dry-run
```
- Erwartete Ausgabe: „[DRY-RUN] Würde N Transaktionen importieren. Salden: …“ — es wird nichts geschrieben.
- Prüfen: N plausibel? IBAN passt zur erwarteten Bankverbindung? UNKNOWN-Warnungen?
  - `parse_balances` (camt_parser.py) liest nur CLBD (OPBD bewusst nicht); ohne IBAN → UNKNOWN-Sentinel-Warnung.
- Dry-Run-Kette (Belege): `system/bach.py:203/376/580/776/804` — `dry_run = "--dry-run" in args or "-n" in args` → `handler.handle(operation, args, dry_run)`; `steuer.py:90` `handle(operation, args, dry_run=False)`, `steuer.py:116–117` `import camt` → `_import_camt(args[1:], dry_run)`; Implementierung `steuer.py:2783–2840`.

### Schritt 3 — Maskierter Bericht an USER
- Nur Aggregate + maskierte IBAN melden, z. B.: „E07-Datei validiert: 42 Transaktionen, Salden von/bis, IBAN ****1234, UNKNOWN-Warnungen: keine.“
- Keine Rohdaten (Partner, Zwecktexte, vollständige IBAN) in Task oder Chat.

### Schritt 4 — Produktivjob + Saldencheck (NUR nach expliziter USER-Freigabe)
1. **Vorab Backup:** `bach backup` (create_backup, bach.py:242).
2. **Import:** `bach steuer import camt <pfad>` (ohne `--dry-run`).
3. **Persistenz-Mechanik** (steuer.py ~2855+, `_persist_camt_transactions` / `_persist_camt_balances`):
   - SHA256-Hash aus `iban|datum|betrag|typ|partner|zweck` → `INSERT OR IGNORE` → **Reimport ist idempotent und gefahrlos**.
   - DBIT-Beträge werden negativ gespeichert.
   - Salden: `accounts_core.AccountStore.persist_camt_balances` — UPDATE über IBAN-normalisierte Zuordnung; ohne Zuordnung → INSERT mit Platzhalter-Name `CAMT-Import ****1234`.
4. **Saldencheck:** `bank_accounts.balance` / `balance_date` nach Import prüfen (Schema s. Quellen-Register; Spalten: id, name, purpose, account_number, bank_name, blz, iban, bic, holder_name, account_type [Giro/Spar/Tagesgeld/Depot], is_primary, balance, balance_date, notes, dist_type, created_at, updated_at).
   - **Achtung:** kein `sqlite3` in safe_shell → Saldencheck read-only im Full-Modus oder über BACH-Anzeige nach Freigabe.
5. **Fehl-INSERT** (Platzhalter `CAMT-Import ****1234`, falls Zuordnung gescheitert) nur mit Freigabe entfernbar; ansonsten Zuordnung (IBAN ↔ Bankverbindung) mit USER klären.

---

## 3. E04-Lieferfall (sonstige Bank-Exportformate)

### Schritt 1 — Format-Identifikation (read-only)
- `file <pfad>`: Typ und Encoding.
- **CSV:** `head -n 5 <pfad>` → Trennzeichen (Semikolon/Komma/Tab), Kopfzeile (Spaltennamen), Datums-/Betragsformate abschätzen (dt. TT.MM.JJJJ bzw. Komma vs. intl. YYYY-MM-DD bzw. Punkt).
- **XML:** Document-Root/Namespace bestimmen.
- **CAMT.053** → direkt E07-Ablauf (Abschnitt 2).

### Schritt 2 — Generische Schema-Validierung
- Datumsformate (dt./intl.), Betragsformate (Komma/Punkt), Encoding/Umlaute prüfen.
- Vergleichsreferenz: Test-Mocks `system/data/test/mock_camt053.xml` und `mock_camt053_complex.xml` (Pfad laut Wiki).

### Schritt 3 — Dry-Run vor Produktivjob
- `--dry-run` / `-n` ist global (bach.py: `dry_run = "--dry-run" in args or "-n" in args`) und für alle Handler wirksam.
- Existierender Importer deckt nur CAMT.053 ab. Für andere Formate gibt es bislang keinen Importer → kein Dry-Run möglich, nur Validierungs-Dokumentation.

### Schritt 4 — Kein neuer Importer/Parser ohne Freigabe
- `camt_parser.py` steht in GUARDED_FILES; ein neuer Importer/Parser wird nur nach expliziter USER-Freigabe über einen eigenen Task mit Anforderungs-Spec angelegt.
- Bis dahin: Validierung dokumentieren (Format, Spalten-Mapping-Vorschlag), kein Code.

---

## 4. Quellen-Register

| Quelle | Fundstelle | Inhalt |
|---|---|---|
| system/bach.py (Haupt-CLI) | :203, :376, :580, :776, :804 | dry_run-Setzung `--dry-run`/`-n`, Dispatch an Handler; bach.py im Stammverzeichnis ist nicht die Haupt-CLI (0 Treffer) |
| bach.py | :242 | `create_backup` → `bach backup` |
| steuer.py | :90, :116–117 | `handle(operation, args, dry_run)`; `import camt` → `_import_camt(args[1:], dry_run)` |
| steuer.py | :2783–2840 | `_import_camt` (Import-Orchestrierung, Dry-Run-Ausgabe) |
| steuer.py | ~:2855+ | `_persist_camt_transactions` (SHA256-Idempotenz, INSERT OR IGNORE, DBIT negativ), `_persist_camt_balances` |
| camt_parser.py | gesamt | CAMT-053-Parser (ElementTree, dynamische Namespaces, `parse_balances` nur CLBD, UNKNOWN-Sentinel ohne IBAN); in GUARDED_FILES |
| schema.sql | :1169–1188 | `bank_accounts`-Schema (Spaltenliste s. Abschnitt 2, Schritt 4); identisch schema_user_data.sql:72 |
| system/wiki/camt053.txt | gesamt (60 Z.) | Feld-Mapping (Abschnitt 2, Schritt 1), Mock-Dateien, Doku aus Task #464 |
| requirements.txt | :67 | accounts-core pin v0.1.0 |
| CHANGELOG | :344–360, :725–728 | CAMT-Import-Historie; USER-Gate T-20260902-162225801 blockt jede CAMT-Annahme ohne echte Datei |
| safe_shell | Zulässigkeit | erlaubt: `file`, `head`, `ls`, `stat`, `find`; verboten: `sqlite3`, Metazeichen (`|`, `;`, `&&`, `2>/dev/null`) |

---

*Erstellt: Autonome Runde 9, 2026-09-29. Gültig bis zu Änderungen an camt_parser.py / steuer.py / bank_accounts-Schema.*