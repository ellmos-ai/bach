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

## 6. Spätere Konsum-Schnittstelle zu Muschelgrund (Ocean)

BACH wird nicht mit redundanter Muschelgrund-Logik überfrachtet:
* In `open-ocean` / `usmc` wird **Muschelgrund** als modulares Server-Gedächtnis (USMC Modus A) standardisiert.
* Sobald Muschelgrund fertiggestellt ist, konsumiert BACH dieses Modul für seine Wissens- und Faktenebene (`memory_facts`, `memory_lessons`) als saubere Abhängigkeit.
* Bis dahin fungiert die Server-`bach.db` auf dem Mac Studio als pragmatischer, stabiler **Server-Bachgrund**.
