# ARCHITEKTURKONZEPT: RHEINGOLD & BACHGRUND

**Status:** AKZEPTIERT / IN IMPLEMENTIERUNG  
**Datum:** 2026-09-11  
**Geltungsbereich:** BACH LLM-OS (Multi-Host: Mac Studio, Workstation, Laptop)  
**Autor:** BACH Architecture Working Group / Antigravity

---

## 1. Vision & Einordnung in die Wasser-Metapher

Im `ellmos`-Ökosystem folgt die Systemevolution einer durchgehenden Wassermetapher:
* **Rinnsal:** Die leichtgewichtige Quelle ohne Abhängigkeiten.
* **Bach:** Der mächtige persönliche Arbeitsstrom mit 113+ Handlern, Boss-Agenten und GUI.
* **Ocean:** Das offene, freie Community-Vollsystem auf hoher See.

Analog zu **Trithon** und **Muschelgrund** in *Ocean* benötigt auch *BACH* eine saubere Trennung zwischen flüchtiger, latenzkritischer Aufgabensteuerung und ruhender Datenpersistenz:

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

## 3. Die Lösung: Rheingold-Routing & Hash-to-TaskID Staging

Das System unterscheidet deterministisch zwischen zwei Zuständen:

```
[Lokaler Client: Workstation / Laptop]
       │
       ├─── 1. Rheingold-Server online? ─────────────────────────────┐
       │                                                             ▼
     NEIN                                                           JA
       │                                                             │
       ▼                                                             ▼
[Lokaler Bachgrund (Staging)]                                [Rheingold (Server-Bachgrund)]
• Generiert deterministischen HASH                           • Vergibt sofort offizielle
  (z.B. draft:wks:9a3f21)                                      Integer-Task-ID (#1225)
• KEINE Integer-ID lokal!                                    • Speichert direkt in Server-DB
• Echte Offline-Fähigkeit                                    • Sofort sichtbar auf Web-Dashboard
       │                                                             │
       │                                                             ▼
       └─── 2. Bei Reconnect / Auto-Flush ──────────────────► [Web-Dashboard :8000]
            • Client sendet Hash & Task-Payload
            • Rheingold prüft Idempotenz (Hash existiert?)
            • Rheingold weist offizielle ID #1225 zu
            • Client ersetzt lokal Hash durch ID #1225
```

### A. Online-Modus (Rheingold erreichbar)
1. `bach task add ...` prüft via kurzem HTTP/Socket-Check (Timeout 1.5s), ob Rheingold (`http://macstudvonlukas:8000` bzw. Tailscale `100.119.69.90:8000`) online ist.
2. **Wenn erreichbar:** Der Payload wird via `POST /api/tasks` an den Server übertragen.
3. Rheingold weist atomar die nächste aufsteigende Task-ID (z. B. `1225`) zu und persistiert im Server-Bachgrund.
4. Der Client spiegelt den Task lokal mit derselben ID in seinen Cache und gibt die Erfolgsmeldung aus:
   `[OK] Task #1225 via Rheingold (Server) erstellt: <Titel>`
5. Der Task ist **in Millisekunden auf dem Tasks-Board sichtbar**.

### B. Offline-Modus (Rheingold offline / kein Netz)
1. Wenn Rheingold nicht antwortet, schaltet die CLI auf **lokales Staging**:
2. **Strikte Invariante:** Der Client vergibt **NIEMALS** eine eigene Integer-Task-ID.
3. Stattdessen generiert er einen eindeutigen Staging-Hash:
   `draft_hash = draft:<host_short>:<sha256_short>`
4. Der Task wird im lokalen Bachgrund mit einem temporären negativen ID-Offset (z. B. negative RowID) und `source = draft_hash` gespeichert.
5. Der Nutzer kann lokal sofort mit dem Task arbeiten (`bach task list`, `bach task show draft:...`).

### C. Promotion & Idempotenter Abgleich (Sync)
1. Sobald Rheingold wieder erreichbar ist (automatisch beim nächsten `bach task`-Aufruf oder explizit via `bach task sync`):
2. Der Client listet alle offenen Entwürfe (`WHERE source LIKE 'draft:%'`).
3. Rheingold prüft bei jedem Entwurf, ob `source` bereits vergeben ist:
   - **Bereits vorhanden:** Rheingold liefert die bestehende ID zurück (Idempotenz).
   - **Neu:** Rheingold vergibt die offizielle Integer-ID (z. B. `1226`).
4. Der lokale Bachgrund aktualisiert den Datensatz:
   `UPDATE tasks SET id = ?, source = ? WHERE source = ?`
5. **Ergebnis:** 100 % kollisionsfrei, deterministisch, kein Datenverlust.

---

## 4. Spätere Konsum-Schnittstelle zu Muschelgrund (Ocean)

BACH wird nicht mit redundanter Muschelgrund-Logik überfrachtet:
* In `open-ocean` / `usmc` wird **Muschelgrund** als modulares Server-Gedächtnis (USMC Modus A) standardisiert.
* Sobald Muschelgrund fertiggestellt ist, konsumiert BACH dieses Modul für seine Wissens- und Faktenebene (`memory_facts`, `memory_lessons`) als saubere Abhängigkeit.
* Bis dahin fungiert die Server-`bach.db` auf dem Mac Studio als pragmatischer, stabiler **Server-Bachgrund**.
