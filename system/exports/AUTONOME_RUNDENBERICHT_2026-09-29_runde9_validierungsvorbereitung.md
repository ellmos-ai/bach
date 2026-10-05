# Autonomer Rundenbericht — Runde 9: Validierungsvorbereitung E04/E07

**Datum:** 2026-09-29, 09:56 Uhr
**Bearbeiter:** Autonomer Agent (Runde 9)
**Auftrag:** Runbook E04/E07-Validierung erstellen + Task-Ergänzungen #1463/#1462 (description-only). Keine produktiven Schritte.

---

## (a) Ziel der Runde

Ziel der Runde 9 war die abschließende **Validierungsvorbereitung** für die USER-gated Tasks #1462 (E07: CAMT-Import-Validierung) und #1463 (E04: Import-Formatvalidierung):

1. **Runbook schreiben** für die E04/E07-Validierung, damit nach Lieferung der CAMT.053- bzw. CSV/XML-Dateien durch den USER ein reproduzierbarer, gegateter Ablauf vorliegt: Identifikation (read-only) → Dry-Run → maskierter Bericht → Produktivjob nur nach ausdrücklicher Freigabe.
2. **Task-Descriptions ergänzen** (#1463, #1462) um den Runbook-Verweis — ausschließlich das Feld `description` (alte Description vollständig übernommen + wörtlicher Anhang „ — [RUNBOOK 2026-09-29, Agent, Runde 9]: … Task bleibt USER-gated pending."). Status, Priorität und Delegation unverändert.

**In dieser Runde keine produktiven Schritte:** kein Import, kein `connector poll telegram_main`, kein `--dispatch`, kein E06-Apply, keine Status-Änderungen an Tasks.

---

## (b) Recherche-Ergebnisse

### 1. bank_accounts-Schema

Quelle: `system/schema.sql:1169–1188` (identisch `system/schema_user_data.sql:72`)

| Spalte | Typ / Besonderheit |
|---|---|
| `id` | INTEGER PRIMARY KEY |
| `name` | TEXT NOT NULL |
| `purpose` | TEXT |
| `account_number` | TEXT |
| `bank_name` | TEXT |
| `blz` | TEXT |
| `iban` | TEXT |
| `bic` | TEXT |
| `holder_name` | TEXT |
| `account_type` | TEXT (Werte: Giro / Spar / Tagesgeld / Depot) |
| `is_primary` | INTEGER DEFAULT 0 |
| `balance` | REAL |
| `balance_date` | TEXT |
| `notes` | TEXT |
| `dist_type` | INTEGER DEFAULT 0 |
| `created_at` / `updated_at` | TEXT (Timestamps) |

**Bedeutung für E07:** Beim Produktiv-Import werden Salden über die IBAN-normalisiert auf vorhandene Konten aktualisiert (UPDATE); existiert kein passendes Konto, wird automatisch ein Konto namens `CAMT-Import ****3000` (maskiert) angelegt.

### 2. dry_run-Kette (system/bach.py → system/modules/steuer.py)

- `system/bach.py:203, 376, 580, 776, 804`:
  `dry_run = "--dry-run" in args or "-n" in args` → Übergabe als Parameter an `handler.handle(operation, args, dry_run)`.
- `system/modules/steuer.py:90`: `handle(operation, args, dry_run)`; **:116–117**: `import camt` → `_import_camt(args[1:], dry_run)`.
- Dry-Run-Ausgabe: **„[DRY-RUN] Würde N Transaktionen importieren. Salden: …"** — keine Schreiboperationen auf der Datenbank; sicher als Vorab-Check verwendbar.
- **E06-Apply separat gegated:** `tools/maintenance/e06_path_deprecation_dryrun.py` läuft per Default nur als Dry-Run; produktiver Apply nur mit `--apply --confirm` nach USER-Freigabe.

**Hinweis:** Haupt-CLI ist `system/bach.py`. Die `bach.py` im Stammverzeichnis ist NICHT die Haupt-CLI.

### 3. CAMT.053-Wiki-Mapping (Feld-Mapping, Quelle: Wiki `camt053.txt`)

| BACH-Feld | CAMT.053-Pfad |
|---|---|
| IBAN | `Stmt / Acct / Id / IBAN` |
| Betrag | `Ntry / Amt` |
| Typ | `Ntry / CdtDbtInd` (CRDT/DBIT) |
| Datum | `Ntry / BookgDt / Dt` |
| Partner | `Ntry / RltdPties / Dbtr / Nm`, mit Fallback auf `UltmtDbtr` / `UltmtCdtr` |
| Zweck | `Ntry / RmtInf / Ustrd` |

- Parser-Basis: `xml.etree.ElementTree` mit **dynamischer Namespace-Erkennung** (robust gegen unterschiedliche Namespace-URIs).
- Test-Mocks vorhanden: `data/test/mock_camt053.xml` + `data/test/mock_camt053_complex.xml`.

### 4. CAMT-Persistenz-Mechanik

- **`_import_camt`** (`system/modules/steuer.py:2783–2840`): liest und validiert die CAMT-Datei, orchestriert Parsing und Persistenz; respektiert `dry_run`.
- **`_persist_camt_transactions`** (~`steuer.py:2855+`): SHA256-Hash aus `iban|datum|betrag|typ|partner|zweck` → **Idempotenz** via `INSERT OR IGNORE` (mehrfaches Importieren derselben Datei erzeugt keine Duplikate). **DBIT-Beträge werden negativ gespeichert.**
- **`_persist_camt_balances`** → `accounts_core.AccountStore.persist_camt_balances`: UPDATE des passenden Kontos über IBAN-normalisiert; sonst INSERT eines neuen Kontos `CAMT-Import ****3000`.
- **`parse_balances`**: berücksichtigt nur CLBD (Closing Booked Balance).
- **XML-Sicherheit:** `defusedxml>=0.7.1`; **Dependency-Pin:** `accounts-core v0.1.0` (`requirements.txt:67`).
- **Guard:** `camt_parser.py` steht in GUARDED_FILES (Schutz vor unbefugter Modifikation).
- **Tests:** `tests/test_accounts_via_accounts_core.py` — 23 Tests, grün (Gesamt: pytest 61 passed, Runde 8).

### 5. Task-Details #1463 / #1462

- Beide Tasks: **pending, P2, delegated_to USER, category bach, depends_on 1570**.
- Beide Descriptions um den RUNBOOK-Anhang ergänzt (description-only): „ — [RUNBOOK 2026-09-29, Agent, Runde 9]: … Task bleibt USER-gated pending." Alte Description (inkl. QUEUE-CHECK + MAILPROCESSOR-BEFUND) vollständig erhalten.
- Keine Status-, Prioritäts- oder Delegationsänderung.

---

## (c) Deliverables der Runde

1. **Runbook:** `exports/RUNBOOK_E04_E07_VALIDIERUNG_2026-09-29.md` (7368 Zeichen)
   - Kopf: Zweck/Lieferfall (USER liefert Pfad im Chat ODER Freigabe `connector poll telegram_main`), Gates (produktive Schritte nur nach Freigabe; nur Aggregate + IBAN `****1234` als generisches Maskierungs-Beispiel; safe_shell read-only; E06-Apply separat gegated).
   - E07-Ablauf: (1) read-only Identifikation (file/head, CAMT.053-Namespace, Feld-Mapping), (2) Dry-Run `bach steuer import camt <pfad> --dry-run`, (3) Maskierung, (4) Produktivjob + Saldencheck nur nach Freigabe — inkl. `bach backup` (bach.py:242), SHA256-Idempotenz, kein sqlite3 → Saldencheck über Full-Modus/BACH-Anzeige.
   - E04-Ablauf: (1) Format-Identifikation CSV/XML/CAMT→E07, (2) generische Schema-Validierung, (3) globaler Dry-Run, (4) kein neuer Importer ohne Freigabe.
   - Quellen-Register: `bach.py:203/376/580/776/804`, `:242`; `steuer.py:90/116–117/2783–2840/~2855+`; `camt_parser.py`; `schema.sql:1169–1188`; Wiki `camt053.txt`; `requirements.txt:67`; CHANGELOG 344–360 / 725–728.
2. **Kopie des Runbooks:** `system/exports/RUNBOOK_E04_E07_VALIDIERUNG_2026-09-29.md` (copy_file OK).
3. **2 Task-Updates:** #1463 + #1462, ausschließlich `description` (RUNBOOK-Anhang), beide Outputs „Task aktualisiert: description" OK.

**Maskierungs-Hinweis:** Das Runbook nutzt `****1234` als generisches Maskierungs-Beispiel; der Task-Anhang #1462 nennt `****3000` gemäß Spezifikation (Kontoname `CAMT-Import ****3000`). Beide Darstellungen sind maskiert — kein Handlungsbedarf.

---

## (d) Status: 4 P2-Tasks unverändert pending, USER/OPERATOR-gated

| Task | Thema | Gate |
|---|---|---|
| **#1462** | E07: CAMT-Import-Validierung | USER — wartet auf Dateilieferung (Chat/Pfad) ODER Freigabe `connector poll telegram_main` |
| **#1463** | E04: Import-Formatvalidierung | USER — dito (gemeinsame Lieferung, depends_on 1570) |
| **#1568 / #1569** | E06-Apply: TO-DECIDE F1&F4 + Punkte A–D; Scan-Befund `data/E06_scan_befund.md` | USER/OPERATOR — Apply nur mit `--apply --confirm` |
| **#1250** | RDP-Testlauf WORKSTATION-LG.local (192.168.9.129) | USER/OPERATOR — Erwartung 110 passed → schließt #1251/#1243 |

Alle Status-Änderungen bleiben dem USER/OPERATOR vorbehalten. E04/E07-Lieferchecks über 5 Kanäle waren in den Vorrunden komplett negativ (nicht wiederholt).

---

## (e) Gates eingehalten

- **Kein `connector poll telegram_main`** und kein `--dispatch` (nur nach ausdrücklicher Freigabe; würde ggf. ~5 Monate Nachrichten holen).
- **Kein E06-Apply** (nur mit `--apply --confirm` nach Freigabe).
- **safe_shell ausschließlich read-only:** kein sqlite3, keine Metazeichen (`|`, `;`, `&&`, `2>/dev/null`).
- **Keine sensiblen Inhalte** in Bericht/Runbook: nur Aggregate, IBAN ausschließlich maskiert (`****1234` / `****3000`).
- **Keine Status-Änderungen** an den 4 P2-Tasks.
- **Nicht angefasst:** `skills/_services`, Parallel-Session-Tasks (#1341, #1357–1359, #1536/1537/1549, #1370ff.).

---

## Nächste Schritte (alle USER/OPERATOR-gated)

1. **E04/E07-Dateien liefern** (Chat/Pfad) ODER Freigabe `connector poll telegram_main` — danach Validierung laut Runbook (Identifikation → Dry-Run → maskierter Bericht → Produktivjob nur nach Freigabe).
2. **E06-A/B-Entscheidung** zu #1568 (F1&F4 + TO-DECIDE A–D) — Apply nur mit `--apply --confirm`.
3. **RDP #1250** auf WORKSTATION-LG.local (192.168.9.129) — Erwartung 110 passed → schließt #1251/#1243.

*Ende des Berichts. Autonome Runde 9 abgeschlossen — Vorrunden 1–8 komplett, nichts halbfertig.*