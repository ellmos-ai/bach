# ARCHITEKTURKONZEPT: RHEINGOLD & BACHGRUND

**Status:** IMPLEMENTIERT & VERIFIZIERT  
**Datum:** 2026-09-11  
**Geltungsbereich:** BACH LLM-OS (Multi-Host: Mac Studio, Workstation, Laptop)  
**Autor:** BACH Architecture Working Group / Antigravity

---

## 1. Vision & Einordnung in die Wasser-Metapher

Im `ellmos`-Ökosystem folgt die Systemevolution einer durchgehenden Wassermetapher:
* **Rinnsal:** Die leichtgewichtige Quelle ohne Abhängigkeiten.
* **Bach:** Der mächtige persönliche Arbeitsstrom mit 113+ Handlern, Boss-Agenten und GUI.
* **Ocean:** Das offene, freie Community-Vollsystem auf hoher See.

Analog zu **Trithon** und **Muschelgrund** in *Ocean* trennt *BACH* saubere Ebenen zwischen latenzkritischer Aufgabensteuerung und ruhender Datenpersistenz:

| Ebene | Ocean-Pendant | BACH-Komponente | Aufgabe |
|---|---|---|---|
| **Autoritäts- & Task-Engine** | **Trithon** (Lead-Host) | **Rheingold** (Mac Studio :8000) | Zentrale Task-ID-Vergabe, Concurrency-Salts, Queue-Zuweisung, Dashboard-Echtzeit. |
| **Persistente Datenbasis** | **Muschelgrund** (USMC Modus A) | **Bachgrund** (`bach.db`) | Das Flussbett des Baches. Ruhender Persistenz-Grund für Tasks, Gedächtnis und Domänendaten. |

> **Warum „Rheingold“?**  
> Nach der Mythologie ruht das reine Rheingold auf dem Grund des Stroms und verleiht Souveränität, unverbrüchliche Ordnung und Herrschaft über die Schätze des Stroms. In BACH verkörpert Rheingold die unteilbare atomare Autorität des 24/7-Lead-Servers (`macstudvonlukas`).

---

## 2. Das Problem des bisherigen Split-Brain-Zustands

Bisher löste `system/hub/bach_paths.py` den Pfad `BACH_DB` auf jedem Rechner strikt host-lokal auf `~/.bach/bach.db` auf:
1. **Inselkopien:** Ein Aufruf von `bach task add` auf der Workstation oder dem Laptop schrieb isoliert in die lokale Windows-SQLite-Datenbank.
2. **Unsichtbarkeit:** Der 24/7-GUI-Server auf dem Mac Studio (`http://macstudvonlukas:8000/tasks-board`) sah davon nichts.
3. **Kollisionen bei Syncs:** Vergab die Workstation offline `id=1215` und der Mac Studio parallel `id=1215`, überschrieben sich Tasks bei OneDrive-Transit-Syncs (`INSERT OR REPLACE`) stillschweigend.

---

## 3. Betriebsmodi: Isolierter Standard vs. Multi-Host-Federation mit Lead-Pflicht

### A. Isolierter Modus (Default / Standalone)
* Ohne explizit festgelegten Lead arbeitet jede BACH-Instanz **völlig autark und isoliert**.
* Tasks erhalten normale lokale Integer-IDs in der lokalen `bach.db`.
* Es erfolgen **keine** Netzwerkanfragen, keine Latenzen, keine Abhängigkeiten von externen Systemen.
* Automatisierte Tests (`pytest`) laufen immer im isolierten Modus (Testverschmutzungsschutz).

### B. Multi-Host-Federation (Kollaboration über Systemgrenzen)
* **Grundsatz:** Sollen mehrere BACH-Instanzen auf verschiedenen Rechnern (Mac Studio, Workstation, Laptop) gemeinsam arbeiten, **MUSS ein Lead festgelegt werden**.
* Der festgelegte Lead (Rheingold-Lead auf Mac Studio: `http://100.119.69.90:8000` bzw. `http://macstudvonlukas:8000`) ist die **alleinige Autorität für offizielle Integer-Task-IDs**.
* **Konfiguration:**
  - CLI:
    - `bach task lead` -> Zeigt Modus (`ISOLATED`, `LEAD`, `WORKER`), Lead-URL und Erreichbarkeit.
    - `bach task lead set <url>` -> Speichert den Lead in `~/.bach/lead.json`.
    - `bach task lead clear` -> Schaltet zurück auf isolierten Standalone-Modus.
  - Environment: `BACH_LEAD_URL`, `BACH_MODE=isolated|lead|worker`.
  - Host-Erkennung: Auf dem Mac Studio schaltet `is_rheingold_lead()` automatisch auf `mode=lead`.

---

## 4. Rheingold-Routing & Hash-to-TaskID Staging

Im Modus `worker` mit festgelegtem Lead unterscheidet das System deterministisch zwischen zwei Zuständen:

```
[Lokaler Client: Workstation / Laptop]
       │
       ├─── 1. Rheingold-Lead online? ───────────────────────────────┐
       │                                                             ▼
     NEIN                                                           JA
       │                                                             │
       ▼                                                             ▼
[Lokaler Bachgrund (Staging)]                                [Rheingold (Server-Bachgrund)]
• Generiert deterministischen HASH                           • Vergibt sofort offizielle
  (z.B. draft:wks:9a3f21)                                      Integer-Task-ID (#1225)
• KEINE Integer-ID lokal! (temporär -1, -2)                  • Speichert direkt in Server-DB
• Echte Offline-Fähigkeit                                    • Sofort sichtbar auf Web-Dashboard
       │                                                             │
       │                                                             ▼
       └─── 2. Bei Reconnect / Sync ────────────────────────► [Web-Dashboard :8000]
            • Client sendet Hash & Task-Payload
            • Rheingold prüft Idempotenz (Hash existiert?)
            • Rheingold weist offizielle ID #1225 zu
            • Client ersetzt lokal Hash durch ID #1225
```

### A. Online-Modus (Rheingold erreichbar)
1. `bach task add ...` sendet den Payload via `POST /api/tasks` an den Rheingold-Lead.
2. Rheingold weist atomar die nächste offizielle Task-ID zu und speichert sie im Server-Bachgrund.
3. Der Client spiegelt den Task lokal mit derselben ID in seinen Cache.
4. Der Task ist **in Millisekunden auf dem Tasks-Board sichtbar**.

### B. Offline-Modus (Rheingold offline / kein Netz)
1. Kann der Client den Lead nicht erreichen, schaltet die CLI auf **lokales Staging**:
2. **Strikte Invariante:** Der Client vergibt **NIEMALS** eine eigene positive Integer-Task-ID.
3. Stattdessen generiert er einen eindeutigen Staging-Hash (`draft:<host_short>:<sha256_short>`) und speichert den Task mit temporärer negativer ID (`-1, -2, ...`).
4. `bach task list` stellt den Task transparent dar: `[DRAFT -1] P3 Mein Task (lokaler Entwurf)`.

---

## 5. Bidirektionale Synchronisation (Push & Pull Mirroring)

1. **Vollständiger Sync (`bach task sync`):**
   - Befördert alle lokalen Offline-Entwürfe (`source LIKE 'draft:%'`) idempotent an Rheingold.
   - Zieht anschließend den gesamten Server-Zustand ab (`pull_tasks_from_rheingold`), um Statusänderungen, neue Tasks und Audit-Historien lokal spiegelbildlich zu aktualisieren.
2. **Reines Abrufen (`bach task pull`):**
   - Spiegelt alle Tasks vom Rheingold-Lead (`GET /api/tasks?limit=10000`) in den lokalen Bachgrund (`INSERT OR REPLACE` / Feldabgleich).
   - Sorgt für exakte 0-Differenzen-Parität zwischen allen beteiligten Rechnern.

---

## 6. Dual-Database-Architektur: Bachgrund (bach.db) vs. Muschelgrund (usmc.db)

### A. Warum Muschelgrund bach.db nicht ersetzen kann
* `bach.db` umfasst über **216 Tabellen** und bildet den gesamten operativen Laufzeit-Zustand des BACH LLM-OS ab: Tasks, Task-History, Daemon-Jobs, Watcher, Chains, Tool-Registry, GUI-Templates, Chat, Buchhaltung/Accounts und System-Governance.
* **Muschelgrund** (USMC Modus A / Ocean) ist demgegenüber der spezialisierte, schlanke Speicher für das kuratierte LLM-Gedächtnis (`usmc_facts`, `usmc_lessons`, `usmc_working`, `usmc_sessions`).
* Eine vollständige Ablösung von `bach.db` durch Muschelgrund ist weder möglich noch sinnvoll, da Muschelgrund keine OS-Laufzeitstrukturen verwalten soll.

### B. Die Entflechtung: Zwei getrennte Datenbanken mit klarer Verantwortlichkeit
Statt Monolith oder Abschaffung gilt die modulare **Dual-Database-Architektur**:

1. **`bach.db` (Bachgrund):**
   - Bleibt die operative System- und Steuerungs-Datenbank für BACH.
   - Beherbergt Tasks, Queues, Workflows, Tools, Daemon, Chat und Audits.
   - Unterliegt der Rheingold-Lead-Autorität (Mac Studio :8000).

2. **`usmc.db` (Muschelgrund / USMC):**
   - Wird als **zweite, dedizierte Datenbank** parallel eingeführt (`usmc_memory.db` bzw. `usmc.db`).
   - Beherbergt persistent Fakten, Lektionen, Notizen und Session-Kontexte.
   - Dient als organisationsweites Multi-Agenten-Gedächtnis (für BACH, Rinnsal, Codex, Claude, Gemini und Ocean).

3. **Stufenweise Stilllegung redundanter Memory-Tabellen in bach.db:**
   - Die historischen Tabellen `memory_facts`, `memory_lessons`, `memory_sessions`, `memory_working` und `shared_memory_*` in `bach.db` werden entflochten und schrittweise abgestellt.
   - BACHs `MemoryHandler` (`system/hub/memory.py`) wird zu einem leichtgewichtigen Client/Adapter, der direkt auf `usmc.db` (bzw. das Python-Paket `usmc`) zugreift.
   - **Ergebnis:** Saubere Trennung von operativer Prozesssteuerung (Bachgrund) und semantischem Langzeitwissen (Muschelgrund) ohne Datenredundanz.
