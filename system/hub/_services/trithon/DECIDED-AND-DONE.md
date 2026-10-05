# Trithon Open-Ocean T3: BACH-Verträge neutralisieren

## Projektkennungen-Inventar

| Kennung | Thema | Status in diesem Verzeichnis |
|---------|-------|------------------------------|
| #1460 | open-ocean T3: BACH-Verträge in `hub/_services/trithon/` neutralisieren, Rückwärts-Fassade beibehalten, Tests anlegen | aktiver Auftrag |
| #1378 | BACH-Kernverträge / Task-Transport neutralisieren | Vorarbeit / Designziel |
| #1368 | Receipt-Provider-Integration | Betroffen (lazy Import) |
| #1448 | Muschelgrund-Projektion kuratierter Facts | Konsument der Ledger-API |

## Entscheidungsprotokoll

1. **Neutralisierung in-situ**
   - Die neutralisierten Klassennamen (`TaskTransportContract`, `WorkItem`,
     `ExecutorReceipt`, `ContractError` + `ContractAlreadyClaimed` /
     `ContractNotFound` / `InvalidReceipt`, `LedgerEntry`) werden im
     bestehenden Modul `routing_contract.py` eingeführt.
   - Die alten Datei- und Ledger-Pfade bleiben unverändert, damit
     bestehende State-Dateien (`*.ledger`, `facts.jsonl`, `outbox.jsonl`,
     `cursor.json`, `epochs.jsonl`) weiter lesbar sind.

2. **Rückwärts-Aliase**
   - `ExecutionReceipt = ExecutorReceipt`
   - `RoutingError = ContractError`
   - Alle öffentlichen Funktions-Signaturen (`claim_contract`,
     `record_receipt`, `create_pending_contract`, `read_ledger`,
     `_validate_receipt`) bleiben erhalten.
   - Intern wird `ticket_id` als Alias für `transport_id` geführt; alte
     Ledger-Einträge verwenden weiter das Feld `ticket_id`.

3. **Keine History-Umschreibung**
   - Bestehende JSON-Lines-History wird nicht migriert.
   - Lediglich neue Code-Klassen schreiben/lesen dieselben Spalten.
   - Fail-closed-Verhalten und Ledger-Endzustände (`done`/`blocked`) bleiben
     identisch.

4. **Abhängigkeiten**
   - `receipt_providers.py`: Lazy-Import auf `ExecutorReceipt` erweitern,
     `_normalize` weiter mit neutraler/evtl. legacy-Klasse funktionsfähig.
   - `muschelgrund.py`: Importe kompatibel halten; neutraler `WorkItem`-Alias
     optional nutzbar.

5. **Tests**
   - `tests/test_trithon_open_ocean_t3.py` ablegen: Legacy-API, Neutral-API,
     Host-Partitioning, Fencing, Idempotenz.
