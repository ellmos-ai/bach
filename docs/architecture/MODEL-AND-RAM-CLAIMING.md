# Modell- & RAM-Claiming: RAM-Distributor, Modell-Runtime und Agenten-Bindung

> **Kanonische Gesamtdokumentation (Stand: 02.11.2026)**
> Fasst die Architekturverträge aus [`ANFORDERUNGEN-DETAIL.md`](file:///C:/Users/User/OneDrive/Desktop/OCEAN/ANFORDERUNGEN-DETAIL.md), [`ocean-resources`](file:///C:/_Local_DEV/repos/ocean-resources/README.md), [`MODEL-SOCKETS.md`](MODEL-SOCKETS.md), [`LOCAL-MODEL-RESERVE.md`](LOCAL-MODEL-RESERVE.md), [`local-inference-queue.md`](local-inference-queue.md), [`watchdog-inference-unload.md`](../operations/watchdog-inference-unload.md) und [`TORCH-KONZEPT.md`](../../system/docs/TORCH-KONZEPT.md) an einer zentralen Stelle zusammen.

---

## 1. Grundsatz: Warum es keine starren „Slots" mehr gibt

Gemäß den verbindlichen Nutzerentscheidungen vom **24.10.2026** gilt in BACH und Ocean:

1. **Agenten statt Slots:**
   Es gibt keine allgemeine Slotpflicht mehr für die Aufgabenauswahl. Alle Agenten (**„Deine Agenten"**, darunter die mitgelieferten Systemagenten `buddha_chat`, `buddha_talk`, `buddha_connector`, `buddha_always_on` sowie alle aus Vorlagen der **„Agenten-Bibliothek"** angelegten Agenten) sind gleichberechtigt und **direkt an ein Primärmodell plus Fallback-Kette gebunden** (`model` + `model_fallbacks`).
   *Hinweis zum Code-Bestand:* Der JSON-Schlüssel `"slots"` in `slots_config.json` und der Endpunkt `/api/slots` heißen aus reiner Speicher-Abwärtskompatibilität noch so, speichern aber fachlich **Agentenprofile und ihre Modellbindungen** ([`model_sockets.py`](../../system/hub/_services/chat/model_sockets.py)).

2. **Zweistufiges Claiming zur Laufzeit (wie Großrechner-Nutzungszeit):**
   Da auf einem lokalen Host (z. B. Mac Studio mit 32 GiB Unified Memory) ein großes 27B-Modell und eine große Forschungs-Compute-Pipeline nicht gleichzeitig ohne Swap-Druck im RAM liegen können, erfolgt der Ressourcenzugriff zur Laufzeit in **zwei getrennten Stufen**:

   | Stufe | Technischer Name | Oberflächen-Name | Was wird geclaimt? | Wer konkurriert hier? |
   |---|---|---|---|---|
   | **Stufe 1** | **`RAMDistributor`** (`ocean-resources`) | **Hauptfackel (RAM-Claim)** | Physische RAM-/VRAM-Zulassung für Modellgewichte + KV-Reserve vs. Compute-Pipelines | Lokales LLM (z. B. `qwen3.8:27b-mlx`) ↔ Wissenschaftliche Rechenjobs / Media-Renderings |
   | **Stufe 2** | **`Modell-Runtime` & `HostInferenceGate`** | **Modellfackel (Turn-Claim)** | Exklusive Nutzungszeit (ein Modellaufruf / Werkzeug-Turn) auf dem bereits geladenen Modell | Interaktiver Chat ↔ `ellmos-talk` Funkgerät ↔ Delegierter Experte ↔ Routine-Agent ↔ Hintergrund-Worker |

---

## 2. SOLL-Stand vs. IST-Stand (Stand 02.11.2026)

| Komponente | SOLL-Stand (Zielbild laut Plan 24.10./02.11.) | Aktuell belegter IST-Stand im Code & Betrieb |
|---|---|---|
| **RAM-Distributor (`ocean-resources`)** | Einziger Scheduler für RAM-Fackel, Modell-Residenz und Compute-Jobs; 4 Nutzernähe-Klassen (`UserProximity`); Hysterese-Schutz (`WatchdogHysteresisPolicy`) beim Kaltstart; automatisches Routing von Verlierern in ihre `fallback_chain`. | Im eigenständigen Repo `ellmos-ai/ocean-resources` (`ram_distributor.py`, `inference_queue_policy.py`) vollständig implementiert, getestet und über `ocean_stack_bridge.py` in `open-ocean` und `bach` gebunden (`bound: true`). |
| **Prozessübergreifendes Turn-Gate (`HostInferenceGate`)** | Alle lokalen Modellaufrufe auf dem Host durchlaufen eine faire FIFO-Queue mit 3:1 Vordergrund-Fairness, Prozess-Liveness-Prüfung (PID + Startzeit) und Crash-Auto-Release. | Produktiv aktiv in [`host_inference_gate.py`](../../system/hub/_services/chat/host_inference_gate.py) unter `~/.bach/runtime/local-inference/` (`inference.lock`, `owner.json`, `ticket-*.json`). |
| **Lokale Ressourcenreserve (`local_resource_reserve.py`)** | Prüft vor jedem lokalen Modellaufruf OS-RAM-Reserve (`memory_reserve_bytes`), Modellgewicht, KV-Headroom und Disk-Reserve (`bach.local-resource-reserve.v1`). | Produktiv aktiv in [`local_resource_reserve.py`](../../system/hub/_services/chat/local_resource_reserve.py) über `~/.bach/runtime/local-inference/resource-reserve.json`. |
| **Koordinierter Watchdog-Unload** | Memory-Watchdog entlädt Modelle nur koordiniert unter `inference.lock` mit `unload-pending.json`-Nachweis, niemals mitten in einem aktiven Turn. | Implementiert in [`memory_pressure_unload_guard.py`](../../system/tools/maintenance/memory_pressure_unload_guard.py) und `memory_pressure_watchdog.sh` (`#2419`/`#2420`). |
| **Tray & GUI-Darstellung** | Keine alte „Slot"-Terminologie mehr in der Oberfläche; stattdessen **„🤖 Deine Agenten (Modell-Bindung)"** und **„🔥 RAM-Distributor & Modell-Claim"** inkl. 1-Klick-Freigabe für andere Prozesse. | In `ellmos-tray` (`v0.1.2`), `chat_tray.py` und `ellmos-system-gui` (`/agenten/running`) umgesetzt. |

---

## 3. Die 4 Prioritätsklassen nach Nutzernähe (`UserProximity`)

Wenn mehrere Agenten oder Prozesse gleichzeitig ein Modell oder RAM beanspruchen, entscheidet streng die **Nutzernähe** ([`ocean_resources/ram_distributor.py`](file:///C:/_Local_DEV/repos/ocean-resources/ocean_resources/ram_distributor.py)):

1. **Klasse 1 – Interaktiv (`DIRECT_INTERACTIVE = 1`):**
   Der Nutzer wartet gerade unmittelbar auf eine Antwort (GUI-Chat `buddha_chat`, Live-Funkgerät `ellmos-talk`, direkter Konsolenbefehl). Klasse 1 hat immer höchsten Vorrang und wird durch den Tray-Tendenzschalter niemals herabgestuft.
2. **Klasse 2 – Aktiver Nutzerauftrag (`DELEGATED_FOREGROUND = 2`):**
   Ein Experte, Subagent oder Connector-Auftrag (`buddha_connector`), den der Nutzer oder der Klasse-1-Chat gerade aktiv losgeschickt hat. **Er erbt die Vordergrund-Priorität des Auslösers (`inherited_from_proximity`)**, während der Hauptchat die Modellfackel sofort freigibt.
3. **Klasse 3 – Geplant / Terminiert (`SCHEDULED_ROUTINE = 3`):**
   Ein fälliger Kalender-Terminagent oder wiederkehrender Routine-Agent.
4. **Klasse 4 – Hintergrund (`AUTONOMOUS_BACKGROUND = 4`):**
   Autonome Hintergrundarbeit ohne akuten Nutzerbezug (`buddha_always_on`, Task-Master-Hintergrundläufe). Weicht sofort an der nächsten Turn-Grenze, sobald Klasse 1 oder 2 anklopft.

---

## 4. Praxis-Leitfaden: Wie andere Prozesse das Modell oder den RAM claimen

### Szenario 1: Ein anderer Prozess braucht den RAM / VRAM (für eigene Berechnungen oder ein eigenes Modell)

Wenn ein externer Prozess (z. B. wissenschaftliches Compute, MLX-/PyTorch-Training, Video-Rendering oder ein externes LLM-Skript) den Speicher braucht, den BACH/Ollama gerade hält:

#### Weg 1A: 1-Klick im System-Tray oder in der GUI (`/agenten/running`)
- **Im Tray (`ellmos-tray`):** Rechtsklick auf das Tray-Icon → **`🔥 RAM-Distributor & Modell-Claim`** → **`🔓 Modell & RAM jetzt für andere Prozesse freigeben (Compute-Vorrang + Unload)`**.
- **In der GUI (`/agenten/running`):** Klick auf den Button **„🔓 Modell & RAM freigeben"** in der Karte *RAM-Distributor & Modell-Runtime*.
- **Wirkung:** Setzt die Distributor-Tendenz auf `compute`, pausiert `buddha_always_on` und sendet `keep_alive: 0` an Ollama, sodass das Modell sofort aus dem VRAM/RAM entladen wird.

#### Weg 1B: Per HTTP-API / CLI aus einem externen Skript
```bash
# 1. Distributor-Tendenz auf Compute setzen (Hintergrund-Worker starten keine Modell-Loads mehr)
curl -X POST http://127.0.0.1:8081/api/fackel \
  -H "Content-Type: application/json" \
  -d '{"preference": "compute"}'

# 2. Optional: Always-On-Hintergrundagent pausieren
curl -X POST http://127.0.0.1:8081/api/slots \
  -H "Content-Type: application/json" \
  -d '{"slot_id": "buddha_always_on", "updates": {"enabled": false}}'

# 3. Geladenes Modell sofort aus dem Ollama-RAM/VRAM entladen
curl -X POST http://127.0.0.1:11434/api/generate \
  -d '{"model": "qwen3.8:27b-mlx", "keep_alive": 0}'
```

#### Weg 1C: Über den Compute-Lock (`~/.memwatchdog/compute_active.lock`)
Externe Rechenjobs können ihre PID in `~/.memwatchdog/compute_active.lock` eintragen (geprüft durch [`system/hub/compute_lock.py`](../../system/hub/compute_lock.py)):
```json
{
  "active_compute_jobs": [
    {"pid": 48210, "name": "nemofold-simulation", "rss_kb": 16777216}
  ]
}
```
Solange ein lebender Prozess dort eingetragen ist und die Tendenz auf `compute` steht, blockiert BACH automatische Hintergrund-Modellstarts, damit der Rechenjob niemals in den Swap gedrängt wird.

---

### Szenario 2: Ein anderer Prozess will dasselbe lokale Modell nutzen / claimen (Modell-Runtime)

Wenn ein zweiter Prozess auf demselben Rechner (oder über den Tunnel) **Inferenz mit dem lokalen Modell** ausführen möchte, ohne dass ihm der Hintergrund-Worker (`buddha_always_on`) dazwischenfunkt:

#### Weg 2A: Kooperativer Vordergrund-Claim über `HostInferenceGate` (Python)
Jeder lokale Python-Prozess kann sich mit `priority="foreground"` in das [`HostInferenceGate`](../../system/hub/_services/chat/host_inference_gate.py) einreihen. Laufende Hintergrund-Worker geben das Modell nach ihrem aktuellen Tool-Turn automatisch an deinen Vordergrund-Prozess ab:
```python
import asyncio
from hub._services.chat.host_inference_gate import HostInferenceGate

async def run_my_model_task():
    gate = HostInferenceGate()
    # "foreground" (Klasse 1/2) überholt "background" (Klasse 4) automatisch!
    async with gate.turn("mein-prozess-id", "foreground"):
        # Hier gehört das Modell exklusiv deinem Prozess.
        # Selbst bei einem Absturz wird der Lock vom Betriebssystem sofort freigegeben.
        ...

asyncio.run(run_my_model_task())
```

#### Weg 2B: Über die BACH Control API (`:8081/api/chat`)
Wenn dein Prozess einfach einen Prompt an das verwaltete Modell schicken will, erledigt `:8081/api/chat` den Vordergrund-Claim im `HostInferenceGate` vollautomatisch:
```bash
curl -X POST http://127.0.0.1:8081/api/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $(cat ~/.credentials/bach_control_api_token)" \
  -d '{"prompt": "Fasse zusammen...", "chat_id": "mein-externer-prozess"}'
```

#### Weg 2C: Modellbindung eines Agenten umstellen (`bach model-sockets` / API)
```bash
# Alle angebotenen lokalen Modelle und aktuelle Agenten-Bindungen anzeigen:
python system/bach.py model-sockets list --json
python system/bach.py model-sockets catalog --json

# Einen Agenten auf ein anderes Modell umbinden (atomar inkl. Fallback-Abgleich):
PUT /api/system/model-sockets/profiles/{agent_id}/rebind
```

---

## 5. Weiterführende Detaildokumente

- [`ocean-resources/README.md`](file:///C:/_Local_DEV/repos/ocean-resources/README.md) — Modul-Referenz für `RAMDistributor`, `ConsumerCapability`, `UserProximity` und `WatchdogHysteresisPolicy`
- [`docs/architecture/MODEL-SOCKETS.md`](MODEL-SOCKETS.md) — Schema `bach.model-sockets.v1` und Ablösung der historischen Slots durch Agenten-Modellbindungen
- [`docs/architecture/LOCAL-MODEL-RESERVE.md`](LOCAL-MODEL-RESERVE.md) — Schema `bach.local-resource-reserve.v1` (Gewichts-, KV-, Overhead- und Disk-Reserven)
- [`docs/architecture/local-inference-queue.md`](local-inference-queue.md) — `HostInferenceGate`-Ticketformat und 3:1 Foreground-Fairness
- [`docs/operations/watchdog-inference-unload.md`](../operations/watchdog-inference-unload.md) — Koordinierter Modell-Unload bei Speicherdruck (`unload-pending.json`)
- [`system/docs/TORCH-KONZEPT.md`](../../system/docs/TORCH-KONZEPT.md) — Das 10-Fackeln-Messprinzip (*„gemessen, nicht gebucht"*)
