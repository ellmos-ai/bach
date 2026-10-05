# Trithon-Schema-Abgleich – agents_heart v1 ↔ Trithon Transport

> **Ticket:** T-20261003-793817309
> **Status:** pending (kein Runtime-Nachweis, statischer Mapping-Abgleich)
> **Trithon-Referenz:** `transport_contract.py` (LedgerEntry, ExecutionReceipt)

---

## 1. Mapping: agents_heart → LedgerEntry

| agents_heart-Feld   | LedgerEntry-Feld   | Typ / Hinweis |
|----------------------|--------------------|---------------|
| `assignment_id`      | `assignment_id`    | string (UUID-hex, Präfix `asgn-`); 1:1 identisch |
| `role_id`            | `host`             | string; Trithon verwendet `host` für die Ausführende Instanz |
| `agent_instance_id`  | `runner`           | string; Trithon `runner` = konkreter Prozess/Instanz |
| `backend_id`         | `actual_provider`  | string (z.B. `ollama`); Trithon: welcher Provider lief |
| `model_id`           | `actual_model`     | string (z.B. `qwen3.8:27b-mlx`); Trithon: welches Modell lief |
| `task_id`            | `work_item_id`     | int/string; Trithon `work_item_id` = Ticket-/Work-Item-Referenz |
| `started_at`         | `occurred_at`      | ISO-8601; Start-Ereignis → `occurred_at` im Ledger |
| `ended_at`           | `occurred_at`      | ISO-8601; Ende-Ereignis → `occurred_at` im Receipt |
| `status` (finish)    | `status`           | `completed`→`done`; `error`/`interrupted`→`blocked`; `released`→`done` (mit `evidence=release`) |
| `event` (started)    | `state`            | `pending` (beim Start) |
| `event` (ended)      | `state`            | `done` oder `blocked` (beim Ende) |
| `details` (dict)     | `evidence`         | dict → JSON-String in `evidence`-Feld des LedgerEntry |
| _(kein Feld)_        | `signature`        | Phase 3: kryptographische Signatur; derzeit `null` |
| _(kein Feld)_        | `line_number`      | Phase 3: append-only Ledger-Zeilennummer; derzeit nicht gesetzt |

### Status-Mapping (Detail)

| agents_heart `status`  | Trithon `state`     | `ExecutionReceipt.status` |
|------------------------|---------------------|---------------------------|
| `running` (begin)      | `claimed`           | – (kein Receipt beim Start) |
| `completed`            | `done`              | `done`                    |
| `released`             | `done`              | `done`                    |
| `error`                | `blocked`           | `blocked`                 |
| `interrupted`          | `blocked`           | `blocked`                 |

---

## 2. Mapping: agents_heart → ExecutionReceipt

| agents_heart-Feld   | ExecutionReceipt-Feld | Hinweis |
|----------------------|----------------------|---------|
| `assignment_id`      | `assignment_id`      | 1:1 |
| `task_id`            | `work_item_id`       | identisch |
| `status`             | `status`             | `completed`/`released`→`done`; `error`/`interrupted`→`blocked` |
| `backend_id`         | `actual_provider`    | 1:1 |
| `model_id`           | `actual_model`       | 1:1 |
| `ended_at`           | `occurred_at`        | 1:1 |
| `result`             | `evidence`           | string → dict `{"result": ...}` in evidence |
| `reason`             | `evidence`           | string → dict `{"reason": ...}` in evidence (bei blocked) |
| _(kein Feld)_        | `executed_by`        | Phase 3: Fackel-Instanz-ID; derzeit nicht gesetzt |
| _(kein Feld)_        | `run_id`             | Phase 3: Trithon-interner Run-Identifier; derzeit nicht gesetzt |
| _(kein Feld)_        | `signature`          | Phase 3: kryptographische Signatur; derzeit `null` |

---

## 3. Phase-3-Felder (derzeit ausgeschaltet)

| Feld                | In agents_heart v1 | In Trithon v1     | Aktion |
|---------------------|--------------------|--------------------|--------|
| `capability`        | nicht vorhanden    | optional in LedgerEntry | **future**: agents-heart-team muss `capability: str` als optionalen Parameter in `begin_assignment()` ergänzen (MINOR-Bump, v1.1) |
| `budget`            | nicht vorhanden    | optional in LedgerEntry | **future**: `budget: int` (Token-Budget) als optionaler Parameter; v1.1 |
| `idempotency_key`   | nicht vorhanden    | optional in ExecutionReceipt | **future**: `idempotency_key: str` in `finish_assignment()`; v1.1 |
| `executed_by`       | nicht vorhanden    | Pflicht in ExecutionReceipt | **future**: Fackel-Injektion; v1.2 |
| `run_id`            | nicht vorhanden    | Pflicht in ExecutionReceipt | **future**: Trithon-Transport erzeugt; v1.2 |
| `signature`         | nicht vorhanden    | optional (Phase 3) | **future**: kryptographisch; v2.0 (MAJOR) |
| `line_number`       | nicht vorhanden    | append-only Ledger | **future**: Trithon-Transport; v2.0 |

---

## 4. Kompatibilitätsprüfung

| Prüfpunkt                                    | Status    | Bemerkung |
|----------------------------------------------|-----------|-----------|
| `assignment_id` 1:1                          | ✅ OK     | Feld identisch |
| `role_id` → `host`                          | ⚠ Mapping | Naming-Unterschied; Adapter nötig |
| `agent_instance_id` → `runner`              | ⚠ Mapping | Naming-Unterschied; Adapter nötig |
| `backend_id` → `actual_provider`            | ⚠ Mapping | Naming-Unterschied; Adapter nötig |
| `model_id` → `actual_model`                 | ⚠ Mapping | Naming-Unterschied; Adapter nötig |
| `task_id` → `work_item_id`                  | ⚠ Mapping | routing_contract.py Alias bestätigt |
| `status` → `state` / `status`               | ⚠ Mapping | Enum-Mapping (siehe §1) |
| Phase-3-Felder (capability, budget, etc.)   | ❌ AUS    | Nicht implementiert, v1.1/v1.2/v2.0 |
| `signature` / `line_number`                  | ❌ AUS    | Phase 3, v2.0 |

---

## 5. Adapter-Konzept (zukünftiger TrithonSink)

```python
# Konzept – noch nicht implementiert (Phase 3)
class TrithonTransportSink:
    """AssignmentEventSink, der LedgerEntry / ExecutionReceipt schreibt."""

    def __init__(self, ledger_path: str | None = None):
        self._ledger = ledger_path  # JSON-Lines Datei

    def record(self, slot_id, activity, status, details, path=None):
        from trithon.transport_contract import LedgerEntry, ExecutionReceipt
        # Feld-Mapping: role_id→host, agent_instance_id→runner,
        # backend_id→actual_provider, model_id→actual_model,
        # task_id→work_item_id, status→state
        entry = LedgerEntry(
            assignment_id=details["assignment_id"],
            run_id=None,           # Phase 3
            host=details["role_id"],
            runner=details["agent_instance_id"],
            actual_provider=details["backend_id"],
            actual_model=details["model_id"],
            status=details["status"],
            evidence=details,
            signature=None,        # Phase 3
            line_number=None,      # Phase 3
        )
        # append to JSON-Lines ledger
        ...
```

> **Hinweis:** Der Adapter ist **nicht** Teil von agents_heart v1.
> Er wird in `system/hub/_services/trithon/` implementiert und
> als externer `AssignmentEventSink` injiziert.

---

## 6. Open Items

- [ ] TrithonSink-Implementierung (trithon-team, Phase 3)
- [ ] Feld-Naming-Übereinkunft: `host` vs `role_id` – Trithon-Team bestätigen
- [ ] Phase-3-Parameter in `begin_assignment()` / `finish_assignment()` ergänzen (v1.1)
- [ ] `capability`, `budget`, `idempotency_key` als optionale Parameter (v1.1)
- [ ] `signature` + `line_number` für append-only Ledger (v2.0)
- [ ] Integrationstest: TrithonSink ↔ agents_heart ↔ transport_contract
