# Modulrücktransfer-Plan (OC-B-Nachzertifizierung #1376)

**Scope:** Dokumentation des schrittweisen Rücktransfers von sechs externen SOT-Provider-Modulen in die BACH-Kernarchitektur. Der Plan dient der Nachzertifizierung OC-B und validiert die Umsetzung gegen die SOT-Stufenregel aus `tests/test_sot_switch_gate.py` (§4 Regel 1).

**Status:** Vollständige ENV-Matrix und Seam-Contracts aus den gelesenen Provider-Quellen und Testdateien extrahiert.

---

## 1. §4 Regel 1 – SOT-Stufen-Modell

Die Stufenregel wird in `tests/test_sot_switch_gate.py` definiert und geprüft:

```
SOT_STAGES = ("P0", "P2", "P3", "P4")
SOT_MODULES = {
    "scheduler",
    "explorer",
    "memoryhooks",
    "workflowhooks",
    "transitsync",
    "agent_registry",
}
```

**Regel 1:** Jeder Eintrag in `SOT_MODULES` muss für jede Stufe in `SOT_STAGES` einen definierten Verhaltens- und Provider-Zustand besitzen. Die Stufen sind sequentiell zu durchlaufen; ein Modul darf nicht übersprungen werden. Der Übergang zwischen den Stufen wird über die Umgebungsvariablen `BACH_USE_EXTERNAL_*` gesteuert.

- **P0** – Baseline / Monolith-Modus: Modul wird intern von BACH bereitgestellt, keine externe Schaltung aktiv.
- **P2** – Abstraktion / Interface-Extraktion: Modul-Contract (Seam) ist definiert; interne und externe Implementierung teilen sich eine gemeinsame Schnittstelle.
- **P3** – External-Provider-Modus: Modul wird über den externen Provider geladen (`BACH_USE_EXTERNAL_<MODULE>=1`).
- **P4** – Rücktransfer / Re-Integration: Modul ist vollständig in BACH zurückgeführt; der Seam bleibt erhalten, der externe Provider ist inaktiv.

> Hinweis: Die Stufenbezeichnungen entsprechen der in `test_sot_switch_gate.py` verwendeten SOT-Nomenklatur. Die semantische Zuordnung P0/P2/P3/P4 ist dem Switch-Gate-Test entnommen.

---

## 2. Module × Stufen-Matrix

| Modul | P0 (Baseline) | P2 (Abstraktion) | P3 (External) | P4 (Rücktransfer) |
|---|---|---|---|---|
| **scheduler** | Interner Scheduler aktiv; direkte DB-Verwaltung. | `scheduler_provider` definiert den Seam; interner und externer Code teilen `BACH_EXTERNAL_SCHEDULER_DB`. | `BACH_USE_EXTERNAL_SCHEDULER=1` → externer Scheduler-Provider übernimmt. | Seam erhalten; Rückführung in `scheduler_provider`, externer Provider inaktiv. |
| **explorer** | Interner Explorer/Scanner aktiv; Budget intern. | `explorer_provider` definiert Scan-Seam; `BACH_EXPLORER_SCAN_BUDGET` als gemeinsamer Contract. | `BACH_USE_EXTERNAL_EXPLORER=1` → externer Explorer-Provider. | Seam erhalten; Rückführung in `explorer_provider`, externes Budget-Handling stillgelegt. |
| **memoryhooks** | Interne Memory-Hooks aktiv. | `memory_hook_provider` definiert Hook-Seam; interner und externer Hook-Satz identisch. | `BACH_USE_EXTERNAL_MEMORYHOOKS=1` → externer Memory-Hook-Provider. | Seam erhalten; Rückführung in `memory_hook_provider`. |
| **workflowhooks** | Interne Workflow-Hooks aktiv. | `workflow_hook_provider` definiert Hook-Seam. | `BACH_USE_EXTERNAL_WORKFLOWHOOKS=1` → externer Workflow-Hook-Provider. | Seam erhalten; Rückführung in `workflow_hook_provider`. |
| **transitsync** | Interne Transit-Synchronisation aktiv. | `transit_sync_provider` definiert Sync-Seam; `db_sync` als gemeinsame Abstraktion. | `BACH_USE_EXTERNAL_TRANSITSYNC=1` → externer Transit-Sync-Provider. | Seam erhalten; Rückführung in `transit_sync_provider` / `db_sync`. |
| **agent_registry** | Interne Agent-Prozessverwaltung aktiv. | `agent_process_provider` definiert Registry-Seam; `AgentProcessRegistry(Path(pid_dir))` mit `probe_running`. | `BACH_USE_EXTERNAL_AGENT_REGISTRY=1` → externer Agent-Launcher / Registry-Provider. | Seam erhalten; Rückführung in `agent_process_provider`; `probe_running` bleibt zentrale Laufzeitprüfung. |

---

## 3. ENV-Matrix

### 3.1 External-Use Flags (Boolean-Schalter)

| Umgebungsvariable | Modul | Wirkung bei `1` / `true` |
|---|---|---|
| `BACH_USE_EXTERNAL_SCHEDULER` | scheduler | Lädt `scheduler_provider` als externen Provider. |
| `BACH_USE_EXTERNAL_EXPLORER` | explorer | Lädt `explorer_provider` als externen Provider. |
| `BACH_USE_EXTERNAL_MEMORYHOOKS` | memoryhooks | Lädt `memory_hook_provider` als externen Provider. |
| `BACH_USE_EXTERNAL_WORKFLOWHOOKS` | workflowhooks | Lädt `workflow_hook_provider` als externen Provider. |
| `BACH_USE_EXTERNAL_TRANSITSYNC` | transitsync | Lädt `transit_sync_provider` / `db_sync` als externen Provider. |
| `BACH_USE_EXTERNAL_AGENT_REGISTRY` | agent_registry | Lädt `agent_process_provider` als externen Provider. |

### 3.2 Zusätzliche ENV-Contracts (Daten- und Budget-Parameter)

| Umgebungsvariable | Modul | Bedeutung |
|---|---|---|
| `BACH_EXTERNAL_SCHEDULER_DB` | scheduler | Verbindungs-/Konfigurationsstring für die externe Scheduler-Datenbank; Seam-Contract zwischen internem und externem Scheduler. |
| `BACH_EXPLORER_SCAN_BUDGET` | explorer | Budget-Parameter für Scan-Vorgänge; gemeinsamer Contract über `explorer_provider`. |

---

## 4. Seam-Contracts

Ein **Seam** ist die gemeinsame Abstraktion, über die ein Modul in P2/P3/P4 betrieben wird, ohne dass Aufrufer den aktiven Provider erkennen. Die folgenden Contracts wurden in den gelesenen Provider-Dateien identifiziert:

| Modul | Seam-Contract (Provider-Modul) | Kernpunkte |
|---|---|---|
| scheduler | `scheduler_provider` | Trennung von Planungslogik und Persistenz; `BACH_EXTERNAL_SCHEDULER_DB` als optionaler External-Datenbank-Contract. |
| explorer | `explorer_provider` | Scan-Logik und Budget (`BACH_EXPLORER_SCAN_BUDGET`) sind über den Provider austauschbar. |
| memoryhooks | `memory_hook_provider` | Hook-Set ist über den Provider injizierbar; interner und externer Hook-Satz müssen identische Signatur besitzen. |
| workflowhooks | `workflow_hook_provider` | Workflow-Hooks werden über den Provider aufgelöst; Rücktransfer behält den Hook-Seam bei. |
| transitsync | `transit_sync_provider`, `db_sync` | Synchronisationslogik und Datenbank-Abstraktion sind getrennt; `db_sync` ist der gemeinsame Persistenz-Seam. |
| agent_registry | `agent_process_provider` | `AgentProcessRegistry(Path(pid_dir))` mit `probe_running`; zentrale Laufzeitprüfung, die in allen Stufen gültig bleibt. |

---

## 5. Agent-Launcher / Registry

Der **agent-launcher**-Seam wird über `agent_process_provider` realisiert:

- **Registry:** `AgentProcessRegistry(Path(pid_dir))`
- **Laufzeitprüfung:** `probe_running`

Diese Implementierung ist in P0 intern aktiv, in P3 durch den externen Provider ersetzbar und in P4 wieder vollständig in BACH integriert, wobei `probe_running` weiterhin die zentrale Methode zur Ermittlung laufender Agent-Prozesse bleibt.

---

## 6. Validierung gegen #1376 Schritte 1–6

| Schritt | Ziel | Nachweis |
|---|---|---|
| 1 | Vollständigkeit der SOT_MODULE | `SOT_MODULES` enthält alle 6 Module; Matrix in Abschnitt 2 deckt alle Kombinationen ab. |
| 2 | Stufenregel §4 | `SOT_STAGES=("P0","P2","P3","P4")`; keine Stufe wird übersprungen; ENV-Flags steuern den Übergang. |
| 3 | ENV-Namen korrekt | Alle sechs `BACH_USE_EXTERNAL_*`-Flags konsistent mit `test_*_provider_wiring.py` und `test_sot_switch_gate.py`. |
| 4 | Zusätzliche ENV-Contracts | `BACH_EXTERNAL_SCHEDULER_DB` und `BACH_EXPLORER_SCAN_BUDGET` dokumentiert und den jeweiligen Provider-Seams zugeordnet. |
| 5 | Provider-Seams geprüft | `scheduler_provider`, `explorer_provider`, `memory_hook_provider`, `workflow_hook_provider`, `transit_sync_provider`/`db_sync`, `agent_process_provider` gelesen und validiert. |
| 6 | Agent-Launcher bestätigt | `AgentProcessRegistry(Path(pid_dir))` mit `probe_running` als stabiler Seam für `agent_registry` dokumentiert. |

---

## 7. Abnahmekriterien

1. Die Datei `docs/architecture/MODULRUECKTRANSFER-PLAN.md` ist im Repository unter `bach/docs/architecture/` vorhanden.
2. Alle sechs SOT_MODULE sind in der Matrix je Stufe beschrieben.
3. Alle sechs `BACH_USE_EXTERNAL_*`-Variablen sowie die zusätzlichen Contracts `BACH_EXTERNAL_SCHEDULER_DB` und `BACH_EXPLORER_SCAN_BUDGET` sind dokumentiert.
4. Die Stufenregel §4 Regel 1 (`SOT_STAGES`, `SOT_MODULES`) ist explizit aufgeführt.
5. Die Seam-Contracts der gelesenen Provider-Module und der agent-launcher (`AgentProcessRegistry`, `probe_running`) sind beschrieben.
6. Die Validierungstabelle zeigt die Erfüllung der Schritte 1–6 von #1376.

---

*Dokument angelegt im Rahmen der OC-B-Nachzertifizierung #1376.*
