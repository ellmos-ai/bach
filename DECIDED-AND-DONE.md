# DECIDED-AND-DONE – open-ocean T3 (#1460 / #1368 / #1378)

## 1. Autonom getroffene Vorentscheidung
- **Ticket:** #1368 (Nutzerwahl open-ocean T3)
- **Auftrag:** #1460 (BACH open-ocean T3 – neutrale öffentliche Vertragsfassung)
- **Abhängigkeiten:** #1378 (T1 – fail-closed default sources / private schema loader)
- **Entscheidung:** Option B – **NEUTRALISIEREN** statt verschieben.
- **Status:** Protokolliert, revidierbar bei Nutzereinwand (siehe `TO-DECIDE-USER.txt`).

## 2. Begründung
- T1 (#1378) etabliert fail-closed Defaults und einen private schema loader, wodurch
  private/vertrauliche Kennungen zur Laufzeit injiziert werden können.
- Das `routing_contract`-Interface ist in `system/hub/_services/trithon` tief mit
  Dispatch- und Partition-Safety-Tests verwoben. Eine physische Verschiebung
  würde #1460 blockieren und bestehende E2E-/Safety-Tests brechen.
- Eine öffentliche, neutrale Vertragsfassung mit rückwärtskompatiblen
  Aliassen/Facade erfüllt beide Ziele: öffentlich auditierbar und intern kompatibel.

## 3. Inventar projektspezifischer Kennungen in `routing_contract.py`

Datei: `system/hub/_services/trithon/routing_contract.py`

| # | Kennung / Begriff | Vorkommen / Kontext | Neutralisierungsvorschlag |
|---|-------------------|---------------------|---------------------------|
| 1 | `ticket-master` | Docstring Zeile 5: externes Repo, aus dem das Interface synthetisiert wurde | In öffentlicher Fassung entfernen oder neutral als "externes Vertrags-Interface" bezeichnen |
| 2 | `Routing-Tickets` | Docstring Zeile 2: "Dateibasierte Transportzustandsmaschine für Routing-Tickets" | "Work-Item-Transport" oder "Task-Transport" |
| 3 | `Ticket` (allgemein) | Docstring und Fehlermeldungen: "Ticket wurde ... beansprucht", "Ticket nicht im Ledger" | "Work item" / "Task" / "WorkUnit" |
| 4 | `ticket_id` | Feld in `LedgerEntry`, Parameter in fast allen Funktionen (`read_ledger`, `claim_contract`, `record_receipt`, `create_pending_contract`, `_ledger_path`) | `work_item_id` / `item_id` / `unit_id` |
| 5 | `RoutingError` | Basisklasse. Im Kontext neutraler Fassung ggf. `TransportError` oder `ContractError`. | `ContractError` / `TransportContractError` |
| 6 | `ContractAlreadyClaimed` | Ausnahme. Neutraler: `ContractAlreadyClaimed` ist akzeptabel, Meldungen ersetzen "Ticket" durch "Work item". | Behalten, Meldungen neutralisieren |
| 7 | `ContractNotFound` | Ausnahme. Meldung "Ticket nicht im Ledger vorhanden" → neutralisieren. | Behalten, Meldung neutralisieren |
| 8 | `agents-heart` | Docstring Zeile 193: "Korrelations-ID zur Besetzung (agents-heart)" | "assignment correlation id" |
| 9 | `assignment_id` / `run_id` | Technische Korrelationsfelder. Sind eigentlich neutral, stammen aber aus agents-heart. | Behalten, nur Docstring neutralisieren |
| 10 | `actual_provider`, `actual_model`, `executed_by` | Felder im `ExecutionReceipt`. Sind fachlich neutral (Provider/Model/Executor), können aber auf LLM-Implementierungen hindeuten. | Behalten; ggf. umbenennen in `executor`, `provider`, `model` |
| 11 | `Trithon` | **Nicht im Code von `routing_contract.py`** vorhanden; nur im Verzeichnisnamen `system/hub/_services/trithon`. | Keine Code-Änderung nötig; bei Bedarf Verzeichnis/Modul in öffentlicher Fassung neutral benennen |
| 12 | `SyntheticTicket` | **Nicht im Code von `routing_contract.py`** vorhanden. | Keine Änderung nötig |
| 13 | `execute_intent_v1` | **Nicht im Code von `routing_contract.py`** vorhanden. | Keine Änderung nötig |

## 4. Geplante neutrale öffentliche Vertragsfassung

Ziel: `system/hub/_services/trithon/routing_contract.py` erhält eine parallele,
generische Fassung, die das gleiche Interface beibehält.

Vorgeschlagene generische Namen:

| Aktueller Name | Neutraler öffentlicher Name |
|----------------|----------------------------|
| `RoutingError` | `ContractError` |
| `ContractAlreadyClaimed` | `ContractAlreadyClaimed` (beibehalten) |
| `ContractNotFound` | `ContractNotFound` (beibehalten) |
| `InvalidReceipt` | `InvalidReceipt` (beibehalten) |
| `LedgerEntry` | `LedgerEntry` (beibehalten) |
| `ExecutionReceipt` | `ExecutorReceipt` / `CompletionReceipt` |
| `claim_contract(..., ticket_id)` | `claim_contract(..., work_item_id)` |
| `record_receipt(..., ticket_id)` | `record_receipt(..., work_item_id)` |
| `read_ledger(..., ticket_id)` | `read_ledger(..., work_item_id)` |
| `create_pending_contract(..., ticket_id)` | `create_pending_work_item(..., work_item_id)` |

Rückwärtskompatibilität:
- `routing_contract.py` exportiert **Aliasse** für alte Namen (`ticket_id` → `work_item_id`).
- Optional: Eine `Facade`-Klasse `TaskTransportContract`, die dieselben Methoden
  bereitstellt und intern auf die neutralen Funktionen delegiert.
- Private Kennungen (`ticket_id`, `ticket-master`, `agents-heart`) werden nur noch
  aus privatem Schema/Config/Env geladen (Blocker #1378).

## 5. Nächste Schritte
1. Neutrale Vertragsfassung in `routing_contract.py` implementieren (Aliasse + Facade).
2. Dedizierten open-ocean T3-Test anlegen (`test_trithon_open_ocean_t3.py`):
   - prüft, dass öffentliche Defaults neutral sind
   - prüft, dass private Kennungen via Config/Env injiziert werden können
3. Testsuite laufen lassen (`pytest system/tests/test_trithon*.py`).
4. Zwei PRs vorbereiten:
   - PR A: neutrale Vertragsfassung + T3-Test
   - PR B: private Config/Schema-Loader-Anpassungen aus T1 (#1378)
5. Task-Status aktualisieren: #1460 → `in_progress`, #1368 protokollieren.
