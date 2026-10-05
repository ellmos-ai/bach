> Dokument-ID: BACH20-03-KANDIDATENREGISTER-2026-09-28
> Quellen: BACH20-01-INVENTAR (2026-09-27), BACH20-02-SYSTEMMANIFEST
> Task: #1427 (BACH-2.0-Rückfluss, Phasen A–C)
> Verbindlicher Input: Ticket T-20260728-12

# BACH20-03 — Kandidatenregister

## 1. Zweck und Einordnung

Dieses Register operationalisiert Phase C des Tickets T-20260728-12: Aus dem Inventar
(BACH20-01) und dem Systemmanifest-Schema (BACH20-02) werden Rückfluss-Kandidaten benannt,
nach einem einheitlichen Kriterienschema bewertet, priorisiert und mit Zulässigkeitsregeln
versehen. Das Register ist Eingang für die Register-Tasks #1187/#1188 (ROADMAP Z. 525–526).

Randbedingungen (unverändert): Es wird nicht gepusht; die Submission bleibt unangetastet
(Judging-Hold). Dieses Dokument ändert keinen Code und keine Provider-Verdrahtung.

## 2. Kandidatenliste (aus der 8er-Matrix, BACH20-01 §3)

| Nr | Kandidat | Stand (Ist, verifiziert aus BACH20-01) | Umschaltpfad | Testlage | Herkunft / Vorlauf |
|----|----------|----------------------------------------|--------------|----------|--------------------|
| 1 | ellmos-tests | checkout-basiert, Übergabepunkt hub/test.py | Flag `--native` | Transfertests grün | Bereits Kandidat laut ROADMAP (#1181) |
| 2 | ellmos-scheduler | Pin `296b6f5`, scheduler_provider | `BACH_USE_EXTERNAL_SCHEDULER=0` | Transfertests grün | 8er-Matrix Nr. 2 |
| 3 | memoryhooker | Pin `94611c25`, memory_hook_provider → ChatRuntime | `BACH_USE_EXTERNAL_MEMORYHOOKS=0` | Transfertests grün | 8er-Matrix Nr. 6 |
| 4 | workflowhooker | Pin `6d2b1908`, workflow_hook_provider → core/hooks (Interceptor) | `BACH_USE_EXTERNAL_WORKFLOWHOOKS=0` | Transfertests grün | 8er-Matrix Nr. 7 |
| 5 | sqlite-transit-sync | Pin `40e99262`, transit_sync_provider → DBSyncManager | `BACH_USE_EXTERNAL_TRANSITSYNC=0` | Transfertests grün | 8er-Matrix Nr. 8 |
| 6 | ellmos-agent_registry | Neuevaluierung; keine verifizierten Ist-Daten in der 8er-Matrix | — | Testnachweis nicht belegt | Zusatzkandidat (Neuevaluierung) |
| 7 | accounts-core | Ist `0166805` (= Tag-Commit) **weicht ab** von Soll v0.1.1 / `9e0d0e9`; Flächen gui/server.py + hub/steuer.py (Welle 2+3) | kein Env-Schalter | Abweichung offen, Transfertests nicht grün belegt | 8er-Matrix Nr. 3 |
| 8 | assistant-core | `444a1fff` v0.2.0 = Soll (seit 2026-09-17, mac-studio); Flächen hub/notify.py + _services/chat (Welle 1+2) | — | B1 gelöst (hostabhängig); Rest = Abschlussvermerk #1341 | 8er-Matrix Nr. 4 |
| 9 | agent-launcher | Nebenfluss, kein Primärkandidat | — | — | Beobachtungsfluss |

Hinweis: system-explorer (8er-Matrix Nr. 5, Pin `bd250b1a`, explorer_provider + system_audit
nativ, `BACH_USE_EXTERNAL_EXPLORER=0`) bleibt interner Pfad und ist **kein** Rückfluss-
Kandidat in dieser Runde; er bleibt über die offenen Gegenproben (§7) beobachtet.

## 3. Phase-C-Scoring

Skala je Kriterium 1–5; 5 = beste Eignung. Bei Risiko gilt: 5 = geringes Risiko. Bei
Migrationsaufwand gilt: 5 = geringer Aufwand.

- **F** Funktionsüberlappung — deckt der Kandidat eine klar abgegrenzte Kernfunktion ab?
- **W** Wiederverwendbarkeit — Nutzen als eigenständige, wiederverwendbare Einheit
- **R** Reife — Pin-Stand (Ist = Soll), Testlage
- **A** API-Kompatibilität — Vertragsschärfe der Übergabepunkte
- **Ri** Risiko (invers) — Rollback-Pfad, Datenkritikalität, offene Gegenproben
- **M** Migrationsaufwand (invers)

| Kandidat | F | W | R | A | Ri | M | Σ | Begründung (Kurz) |
|----------|---|---|---|---|----|----|---|-------------------|
| ellmos-scheduler | 5 | 4 | 5 | 4 | 4 | 4 | **26** | Sauberer Provider-Contract, Env-Schalter, Tests grün; Abzug Ri wegen offener Gegenprobe (§7) |
| memoryhooker | 4 | 4 | 5 | 4 | 4 | 4 | **25** | Klare Einspeisung in ChatRuntime, Env-Schalter, Tests grün |
| ellmos-tests | 4 | 4 | 5 | 4 | 4 | 3 | **24** | Dedizierter Testpfad (hub/test.py), `--native` sauber umschaltbar; Abzug M: checkout-basiert statt Pin → Manifest-Sonderbehandlung |
| workflowhooker | 4 | 4 | 5 | 3 | 3 | 4 | **23** | Interceptor in core/hooks = breitere Angriffsfläche; Multi-Host-Gegenprobe offen (§7) |
| sqlite-transit-sync | 4 | 3 | 5 | 4 | 3 | 3 | **22** | DBSyncManager-Vertrag datenkritisch (Sync-Pfad) → Risiko- und Aufwandsabzug trotz grüner Tests |
| assistant-core | 3 | 4 | 4 | 3 | 3 | 3 | **20** | Ist = Soll seit 2026-09-17, B1 gelöst; aber Test-Abschluss hängt an #1341 → derzeit unzulässig (R1) |
| ellmos-agent_registry | 4 | 4 | 2 | 3 | 2 | 3 | **18** | Keine verifizierten Ist-/Testdaten im Inventar → Neuevaluierung, derzeit unzulässig (R1) |
| accounts-core | 3 | 3 | 2 | 3 | 2 | 2 | **15** | Ist `0166805` ≠ Soll `9e0d0e9`; zwei Flächen (GUI + Steuer); **kein Env-Schalter** → kein sauberer Rückfallpfad; unzulässig (R1) bis Pin-Abgleich + Schalterkonzept |
| agent-launcher (Nebenfluss) | 2 | 3 | 1 | 2 | 2 | 2 | **12** | Kein Primärkandidat; nur Beobachtung, kein Register-Task |

## 4. Priorisierung

Reihenfolge bei jeweils gültiger Zulässigkeit (§5); Takt gemäß Regel R2.

| Prio | Kandidat | Σ | Voraussetzung vor Überführung |
|------|----------|---|-------------------------------|
| P1 | ellmos-scheduler | 26 | Keine weiteren; Gegenprobe-Stichtag beachten (§7) |
| P2 | memoryhooker | 25 | Keine weiteren |
| P3 | ellmos-tests | 24 | Vorlauf #1181 aufgreifen; Pin-/Checkout-Frage im Manifest klären |
| P4 | workflowhooker | 23 | Multi-Host-Gegenprobe schließen (§7) |
| P5 | sqlite-transit-sync | 22 | Datenvertrag DBSyncManager im Manifest verifizieren |
| gesperrt | assistant-core | 20 | Abschlussvermerk #1341 |
| gesperrt | ellmos-agent_registry | 18 | Neuevaluierung + Testnachweis |
| gesperrt | accounts-core | 15 | Pin-Abgleich (`0166805` vs. `9e0d0e9`) + Env-Schalter-Konzept |
| beobachtet | agent-launcher | 12 | — (Nebenfluss, kein Task) |

## 5. Regeln (Phase C)

- **R1 Unzulässigkeitsregel:** Ein Kandidat ohne grüne Transfertests ist für den Rückfluss
  unzulässig. Er wird im Register als BLOCKED geführt, bis der Nachweis vorliegt
  (Herleitung aus BACH20-01 §3/§4).
- **R2 Taktlimit:** Maximal **1 Kandidat pro Tag** wird in den Rückfluss überführt
  (Stabilisierung, vgl. ROADMAP Z. 526).
- **R3 NO_OP/BLOCKED-Option:** Ein Register-Task (#1187/#1188) darf mit NO_OP bzw. BLOCKED
  geschlossen werden, wenn kein zulässiger Kandidat ansteht (ROADMAP Z. 526).
- **R4 Rollback-Vorrang:** Solange #1340/#1341 offen sind, ist die Archivierung interner
  Fallback-Pfade kontraindiziert — sie sind Rollback-Ziele der 6 Env-Schalter
  (BACH20-01 §4).
- **R5 Submission-Hold:** Keine Änderung an Submission-Artefakten; kein Push (Judging-Hold).

## 6. Delta gegenüber Ticket T-20260728-12 (offen)

### 6.1 Phase-A-Restflächen (Inventar)

Das Inventar (BACH20-01) deckt die 8er-Module und 5 grobe Flächen ab; das Ticket verlangt
ALLE Flächen. Nachzuziehen: **Handler, API, CLI, MCP, Plugins, Services, Skills, Tools,
Workflows, Secrets, Update, Restore, GUI**.

### 6.2 Phase-B-Delta (Schema)

Im Manifest-Schema (BACH20-02) nachzuziehen: **Lizenz, Plattformen, Aktivierungsmodus**
(Enum mit 7 Werten: `absent`, `available`, `shadow`, `active`, `deprecated`,
`quarantined`, `rollback`) sowie **Provenienz**. Der Validator ist entsprechend zu
erweitern (Whitelist des Aktivierungsmodus analog V4 für env_schalter).

### 6.3 Konsequenz für Task #1427

Phase C ist mit diesem Register vorgezogen (Zwischenstand). Der Task bleibt **offen**:
Voraussetzung für den Abschluss ist die Schließung der Delta-Punkte 6.1 und 6.2.

## 7. Querverweise und offene Gates

- **Dokumente:** BACH20-01-INVENTAR (8er-Matrix, §4-Befunde), BACH20-02-SYSTEMMANIFEST
  (Schema draft-07 `bach-system-manifest-v1`, Validator V1–V7)
- **Ticket/Task:** T-20260728-12 (verbindlicher Input), #1427
- **Register-Tasks:** #1187 / #1188 (ROADMAP Z. 525–526); ellmos-tests-Vorlauf: #1181
- **Offene Gates:**
  - #1340, #1341 — Rollback-Ziele / Abschlussvermerk (blockieren Archivierung, R4)
  - Windows-Gegenproben Stufen 2, 3, 5, 7 — offen
  - Multi-Host-Gegenprobe Stufe 7 — offen

---

*Zwischenstand 2026-09-28 — angelegt im Rahmen von Task #1427. Kein Push, keine
Submission-Änderung (Judging-Hold).*
