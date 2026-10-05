# BACH20-04 — Kandidatenregister & Scoring (Abschlussartefakt #1352)

| Feld | Wert |
|---|---|
| Dokument-ID | BACH20-04-KANDIDATENREGISTER-SCORING-2026-09-29 |
| Version | 1.0 |
| Datum | 2026-09-29 |
| Task | #1352 (ROADMAP Eintrag 1188 = BACH20-04) |
| Änderungsregel | append-only (Korrekturen/Ergänzungen nur über neue Versionen oder Anhänge) |

Vorgängerdokumente (nur per Referenz genutzt, keine Inhaltskopie):
- BACH20-03-ID-VERTRAG-2026-09-29 (`docs/architecture/BACH20-03-ID-VERTRAG.md`)
- BACH20-03-KANDIDATENREGISTER-2026-09-28, Eigentum #1427 (`docs/architecture/BACH20-03-KANDIDATENREGISTER.md`)
- BACH20-01-INVENTAR (`docs/architecture/BACH20-01-INVENTAR.md`)
- BACH20-02-SYSTEMMANIFEST (`docs/architecture/BACH20-02-SYSTEMMANIFEST.md`)

## §1 Zweck und Abgrenzung

Dieses Dokument ist das eigene Scoring-Artefakt für Task #1352 (BACH20-04). Es schließt die
Abschlussgrenze des ROADMAP-Eintrags 1188: je Kandidat entweder eine live belegte Eignung
oder ein ehrliches NO_OP bzw. BLOCKED.

Abgrenzung:
- Das Kandidatenregister BACH20-03-KANDIDATENREGISTER-2026-09-28 gehört Task #1427 und bleibt
  **unverändert**. Es wird ausschließlich per Referenz genutzt (ID-Vertrag §8 und §9).
- Es findet **keine Inhaltskopie** aus den Vorgängerdokumenten statt (ID-Vertrag G1–G3).
  Score-Werte werden als Referenzwerte mit Quellenangabe geführt (siehe Fußnote zur Tabelle in §3).
- Dieses Dokument leitet **keinen Release-Status** ab und führt **keine operative Überführung**
  durch (Regeln R2/R5 des Kandidatenregisters: max. 1 Überführung/Tag, Submission-Hold, kein Push).

## §2 Referenzmodell

- Referenzen erfolgen als Tupel `(registry_typ, id)` gemäß BACH20-03-ID-VERTRAG §3.
  Zulässige registry_typ-Werte: `system-manifest`, `agent-manifest`, `skill-registry`,
  `policy-registry` (reserviert), `learning-registry` (reserviert).
- Pin-Kontext (Commit/Stand) ist als ergänzende Angabe erlaubt (ID-Vertrag G4).
- Die Auflösung aller Referenzen erfolgt gegen die **lebende Registry**, nicht gegen kopierte
  Inhalte (ID-Vertrag G1–G3).
- Die Verwendung der hier referenzierten IDs und Referenztypen steht #1352 und #1427 gemäß
  ID-Vertrag §9 offen.

## §3 Scoringtabelle (Abschlussbewertung #1352)

Belegbasis für "BELEGT": grüne Transfertests gemäß BACH20-01-INVENTAR (8er-Matrix). Die
Σ-Scores sind Referenzwerte aus dem #1427-Kandidatenregister (siehe Fußnote).

| Prio | Kandidat | Σ-Score¹ | Belegstatus | Begründung |
|---|---|---|---|---|
| P1 | scheduler | 26 | **BELEGT** | Transfertests grün (BACH20-01 8er-Matrix); keine weiteren Voraussetzungen offen |
| P2 | memoryhooker | 25 | **BELEGT** | Transfertests grün (BACH20-01 8er-Matrix) |
| P3 | ellmos-tests | 24 | **BELEGT (eingeschränkt)** | Transfertests grün; checkout-basiert → Manifest-Sonderbehandlung nötig (Pin/Checkout-Frage im Manifest klären) |
| P4 | workflowhooker | 23 | **BELEGT (eingeschränkt)** | Transfertests grün; Multi-Host-Gegenprobe (Stufe 7) noch offen |
| P5 | sqlite-transit-sync | 22 | **BELEGT (eingeschränkt)** | Transfertests grün; DBSyncManager-Datenvertrag datenkritisch → im Manifest verifizieren |
| gesperrt | assistant-core | 20 | **BLOCKED** | Abschlussvermerk #1341 ausstehend; Regel R1 (kein grüner Test → BLOCKED) |
| gesperrt | agent_registry | 18 | **BLOCKED** | Neuevaluierung erforderlich, kein Testnachweis vorhanden; Regel R1 |
| gesperrt | accounts-core | 15 | **BLOCKED** | Pin-Abgleich offen: Ist `0166805` ≠ Soll `9e0d0e9`; kein Env-Schalter-Konzept; Regel R1 |
| beobachtet | agent-launcher | 12 | **NO_OP (nicht-grün)** | Externer Kandidat (OC-B); ID-Vertrag §7: kein Agent-Lifecycle belegt, kein Release-Status ableitbar (Opt-in via `BACH_USE_EXTERNAL_AGENT_REGISTRY`); nur Beobachtung |

¹ Referenzwert aus BACH20-03-KANDIDATENREGISTER-2026-09-28 (#1427), §3 Scoringtabelle.
Übernahme als Referenzwert mit Quellenangabe; keine Kopie der Bewertungskriterien.

Hinweis: `system-explorer` ist **kein Kandidat** (interner Pfad, Feststellung des
#1427-Kandidatenregisters) und wird hier nicht bewertet.

## §4 Abschlussgrenze ROADMAP-1188 — Erfüllungsnachweis

Die Abschlussgrenze von ROADMAP-1188 (BACH20-04) verlangt je Kandidat entweder eine live
belegte Eignung oder ein ehrliches NO_OP/BLOCKED. Stand dieses Artefakts:

- **BELEGT (5):** scheduler, memoryhooker, ellmos-tests, workflowhooker, sqlite-transit-sync
  (jeweils grüne Transfertests per BACH20-01-Referenz; Einschränkungen in §3 benannt)
- **BLOCKED (3):** assistant-core, agent_registry, accounts-core (jeweils mit Begründung; R1)
- **NO_OP / nicht-grün (1):** agent-launcher (ID-Vertrag §7)

Damit liegt für **jeden** Kandidat des Registers entweder ein Beleg oder ein ehrliches
BLOCKED/NO_OP vor — die Abschlussgrenze ist erfüllt.

Benannte offene Gates (bleiben offen, kein Teil des Abschlusses von #1352):
- Tasks #1340 und #1341 (Rollback-Vorrang gilt solange beide offen sind — Regel R4)
- Windows-Gegenproben Stufen 2/3/5/7
- Multi-Host-Gegenprobe Stufe 7

Die **operative Überführung** der belegten Kandidaten ist **nicht** Teil von #1352. Sie
unterliegt weiterhin den Regeln des Kandidatenregisters: R2 (max. 1 Überführung/Tag),
R4 (Rollback-Vorrang), R5 (Submission-Hold, kein Push).

---
Kein Push, keine Änderung an Submission-Artefakten (Judging-Hold; Regel R5).
