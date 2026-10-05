# TaskDB Salt-Lease Client- und Trithon-Integration v1 (T793 / BACH-Task #1722)

**Status:** Umgesetzt und testiert (Stand: 2026-10-05, Commit auf Branch `feat/t1722-task-clients-trithon-leases-20261005`).  
**Bezug:** BACH-Task #1722 (LEASE 3/4). Baut auf #1720 (Vertrag v1), #1721 (Lead-Dienst), #1725 (ACK-Atomarität) und #1726 (Status-Fence-Schutz) auf. Vorgänger-PRs: #195, #198, #199.  
**Autor:** gemini@ASUS-GEI.

---

## 1. Zweck und Überblick

Dieses Dokument legt fest, wie alle Konsumenten von Aufgaben (Clients, CLI, Python-API, Trithon-Dispatcher sowie künftige Ocean- und Task-Master-Worker) an die gefencten Salt-Leases der autoritativen Lead-TaskDB angebunden sind.

Die Umsetzung erfüllt die Vorgaben aus Task #1722:
1. **Einheitliche Client-Schicht:** `TaskLeaseClient` in `system/hub/_services/task_lease_client.py` als universeller Adapter für lokale (SQLite) und netzwerkbasierte (HTTP / Lead) Aufrufe.
2. **Kanonische Identität:** `tasks.id` (positive Ganzzahl) bleibt die operative Identität. Ticket-Hashes und Ledger-IDs dienen als Provenienz- und Triage-Spur, begründen jedoch keine eigene Claim-Autorität.
3. **Fencing & Fail-Closed:** Schreibende Abschlüsse (`release` mit `outcome="done"`) erfordern die passende `lease_id` und den monotonen `claim_fence`. Fremde, veraltete oder abgelaufene Fences werden strikt abgewiesen (`stale_fence` / `expired`), ohne den Task-Status zu verändern.
4. **Offline-Sicherheitsgrenze:** Gemäss Vertrag §8.1 berechnet der Client:
   `local_deadline = local_receive_time + (expires_at - server_now) - 60s`.
   Nach Verstreichen dieser Frist dürfen keine schreibenden Operationen ohne vorheriges erfolgreiches Renewal erfolgen.
5. **Strikte Trennung von Claim und Modellstart:** Der Lease-Erwerb (Acquire) ist vom Modellstart (Inferenz/Executor) entkoppelt. Fehlerhafte oder abgebrochene Ausführungen geben die Task via `release(outcome="return")` wieder frei.

---

## 2. Komponenten und Schnittstellen

### 2.1 `TaskLeaseClient` (`system/hub/_services/task_lease_client.py`)

Die zentrale Adapterklasse bietet folgende Signatur:

```python
class TaskLeaseClient:
    def acquire(
        self,
        task_id: int,
        *,
        worker_id: str,
        host: str,
        request_id: Optional[str] = None,
        ttl_profile: str = "M",
        intent: str = "",
    ) -> LeaseAck: ...

    def read(
        self,
        task_id: int,
        *,
        lease_id: Optional[str] = None,
    ) -> LeaseHolderView: ...

    def renew(
        self,
        task_id: int,
        *,
        lease_id: str,
        fence: int,
    ) -> LeaseAck: ...

    def release(
        self,
        task_id: int,
        *,
        lease_id: str,
        fence: int,
        outcome: str = "done",  # "done" | "return" | "blocked"
        result_ref: str = "",
        note: str = "",
    ) -> LeaseReleaseAck: ...
```

#### Dataclasses:
- `LeaseAck`: Enthält `task_id`, `lease_id`, `fence`, `worker_id`, `host`, `issued_at`, `expires_at`, `ttl_profile`, `server_now`, `local_receive_time`, `local_deadline`.
- `LeaseHolderView`: Holder-Ansicht gemäss Vertrag §5.2. Verbirgt `lease_id` für Fremde; zeigt `own: True` nur bei Vorlage der passenden `lease_id`.
- `LeaseReleaseAck`: Bestätigung über Statuswechsel (`done`, `pending`, `blocked`) und aktuellen Fence.

### 2.2 CLI-Befehle (`system/hub/task.py`)

Folgende Subcommands stehen zur Verfügung:

| Befehl | Syntax | Beschreibung |
|---|---|---|
| `lease` | `bach task lease <id> --by <worker> [--host <host>] [--ttl S\|M\|L\|XL] [--intent <text>]` | Beansprucht die Task exklusiv und gibt `lease_id` und `fence` aus. |
| `lease-show` | `bach task lease-show <id> [--lease-id <uuid>]` | Zeigt den aktuellen Halter und Prüfstatus an. |
| `lease-renew` | `bach task lease-renew <id> --lease-id <uuid> --fence <int>` | Verlängert die Frist einer aktiven Lease. |
| `lease-release`| `bach task lease-release <id> --lease-id <uuid> --fence <int> [--outcome done\|return\|blocked] [--ref <ref>] [--note <note>]` | Gibt die Lease frei oder schliesst sie ab. |

### 2.3 Python API (`system/bach_api.py`)

In der Klasse `_TaskAPI` stehen die Methoden bereit:
- `bach_api.task.lease_acquire(...)`
- `bach_api.task.lease_read(...)`
- `bach_api.task.lease_renew(...)`
- `bach_api.task.lease_release(...)`

### 2.4 Trithon Dispatcher (`system/hub/_services/trithon_dispatch.py`)

In `execute_intent_v1`:
1. **Schritt 2:** Ruft `acquire_lease` auf. Bei Ablehnung bricht die Zuweisung mit `status="claim_failed"` ab.
2. **Schritt 4/5:** Führt Executor aus und bettet `lease_id`, `claim_fence`, `worker_id` und `host` in das `evidence`-Dictionary des `ExecutionReceipt` ein.
3. **Schritt 6b:** Ruft atomar `release_lease` auf (`outcome="done"` bzw. `"return"`). Bei Stale-Fence oder Fristablauf bricht Trithon fail-closed ab (`status="release_failed"`), ohne den Task-Status in der Datenbank zu korrumpieren.

---

## 3. Abgrenzung und Übergabevertrag für andere Bausteine

### 3.1 Unberührte Bereiche (Lock-Schutz)
- **#1697 (`gui-running`, `tray`, `worker-runtime`):** Die bestehenden Worker-Dateien in `system/hub/_services/chat/` wurden nicht verändert.
- **#1718 (`ellmos-tray`):** Die Tray-Applikation auf ASUS-GEI bleibt unberührt.

### 3.2 Schnittstelle für künftige Worker (Ocean, Task-Master, MCP)
Künftige Worker (z. B. Ocean Agent-Worker oder Task-Master TASKSOLVER) binden sich nicht direkt an SQLite-Tabellen, sondern importieren `TaskLeaseClient`:

```python
from hub._services.task_lease_client import TaskLeaseClient, LeaseError

client = TaskLeaseClient()  # Erkennt automatisch Lead-URL oder lokale DB
try:
    ack = client.acquire(task_id, worker_id="ocean-worker@mac-studio", host="mac-studio")
    # ... Inferenz / Ausführung ...
    ack.assert_locally_valid()
    client.release(task_id, lease_id=ack.lease_id, fence=ack.fence, outcome="done")
except LeaseError as err:
    # Abfangen und ordentlich melden
    pass
```
