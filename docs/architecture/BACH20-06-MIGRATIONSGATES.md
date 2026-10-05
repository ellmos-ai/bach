# BACH20-06 Migrations-Gates: Baseline, Contract, Shadow, Rollback

| Feld | Wert |
|---|---|
| dokument_id | BACH20-06-MIGRATIONSGATES-2026-09-29 |
| Version | 1.0 |
| Status | doku |
| Datum | 2026-09-29 |
| Task | #1354 (BACH20-06 Baseline-/Contract-/Shadow-/Rollback-Gates) |
| Vorgänger-Dokumente | BACH20-03-ID-VERTRAG.md (dokument_id BACH20-03-ID-VERTRAG-2026-09-29); BACH20-02-SYSTEMMANIFEST.md; MODULRUECKTRANSFER-PLAN.md |
| Änderungsregel | append-only (siehe §6) |

## §0 Zweck und Abschlussgrenze

Task #1354 (BACH20-06) ist mit folgender Abschlussgrenze angelegt (wörtlich):

> „Gates definiert und nachweisbar; Gates auf offenen Hostläufen nicht grün zählen."

Dieses Dokument definiert die fünf Migrations-Gates, die der Adapter-Datenmigrationsvertrag BACH20-07-ADAPTER-DATENMIGRATIONSVERTRAG.md in seinem §5 („Anbindung an die Gates aus BACH20-06 (#1354)") als Ausführbarkeitsbedingung referenziert.

Selbstklärung: Dieses Dokument ist definierend und abschließend für die Gate-Lehre. Es führt selbst keine Migration durch, installiert nichts und verändert keinen Bestandscode.

## §1 Geltungsbereich

1. Die Gates greifen vor jeder Modulablösung und jeder Datenmigration. MODULRUECKTRANSFER-PLAN.md Regel 4 verlangt: Baseline, gleiche Contracts, single-writer-Shadow und vollständiger Rollback vor jeder Migration; ROADMAP.md (BACH20-06) fasst dies in Sicherheitsregel Nr. 4 zusammen.
2. Die Geltung ist pro Modul und pro Stufe des MODULRUECKTRANSFER-PLANS: Jedes Gate wird je Modul/Stufe eigenständig geprüft und nachgewiesen. Grünfärbung überträgt sich nicht auf andere Module oder Stufen.
3. Auslöser ist jede Änderung an Adapter-Seam oder Store — auch eine scheinbar triviale.
4. Phasenbezug: Die Phasen P0–P7 folgen dem Vertrag BACH20-07; die Abbildung Gates ↔ Phasen steht in §4 dieses Dokuments.

## §2 Die fünf Gates

Bezeichnerkonvention: In diesem Dokument heißen die Gates ausgeschrieben „Gate 1" bis „Gate 5". Die Kurzform „G1–G5" wird bewusst nicht verwendet, um Kollisionen mit den Regelbezeichnern G5.1–G6.4 des Vertrags BACH20-07 (dort §5/§6) zu vermeiden.

Jedes Gate gliedert sich in Definition, Nachweisform, Fehlerbedingung (rot) und Anbindung an BACH20-07.

### Gate 1 — Baseline-Gate (Ist-Zustand gesichert vor jeder Änderung)

- Definition: Bevor irgendeine Änderung am betroffenen Modul oder Store beginnt, ist der Ist-Zustand aufgezeichnet und wiederherstellbar. Keine Migration beginnt ohne vorherige Baseline-Aufzeichnung.
- Nachweisform: Manifest-Vergleich, Hash oder Snapshot — z. B. Snapshot nach `~/.bach/backups/` gemäß MODULRUECKTRANSFER-PLAN.md Regel 2 —, Run-Receipts, JSONL-/Log-Eintrag mit Zeitstempel und Host. Zu leisten vor P1 (erste Änderung am System).
- Fehlerbedingung (rot): Änderung ohne vorherige Baseline-Aufzeichnung; Baseline ohne Host- und Zeitstempelbeleg.
- Anbindung BACH20-07: P0.

### Gate 2 — Contract-Gates (gleiche Contracts vor und nach)

- Definition: Die relevanten Contracts (z. B. `create_bach_adapter`-Contract, fail-closed) liefern vor UND nach der Änderung identische Ergebnisse.
- Nachweisform: Contract-Prüfung vor und nach der Änderung, dokumentiert als Testlauf mit Exit-Code und identischem Ergebnis.
- Fehlerbedingung (rot): Contract-Drift (Ergebnis nach weicht von Ergebnis vor ab); fehlende Nach-Prüfung.
- Anbindung BACH20-07: P2.

### Gate 3 — Shadow-Gate (strikt single-writer)

- Definition: Während des Parallelbetriebs hat genau EIN Writer den führenden Pfad. Der Legacy-Pfad bleibt unberührt (BACH20-07 §3.4). Der Adapter schreibt ausschließlich in den isolierten Store mit Provenienz `bach:<id>`; kein Eigen-Import, kein Doppel-Schreiben.
- Nachweisform: Log/JSONL der Schreibzugriffe (Writer, Pfad, Zeitstempel, Host) plus Test des Parallelbetriebs.
- Fehlerbedingung (rot): Ein zweiter Schreibpfad ist aktiv; Legacy-Schreibzugriff außerhalb dokumentierter Reparaturläufe.
- Anbindung BACH20-07: P3.

### Gate 4 — Rollback-Nachweis (vollständig, live verifiziert)

- Definition: Der vollständige Rollback-Pfad folgt BACH20-07 §4.1–§4.5: ausschließlich Env-Schalter aus der V4-Whitelist des Systemmanifests (BACH20-02-SYSTEMMANIFEST.md §3, Validator V4) — `BACH_USE_EXTERNAL_SCHEDULER`, `BACH_USE_EXTERNAL_EXPLORER`, `BACH_USE_EXTERNAL_MEMORYHOOKS`, `BACH_USE_EXTERNAL_WORKFLOWHOOKS`, `BACH_USE_EXTERNAL_TRANSITSYNC`, `BACH_USE_EXTERNAL_AGENT_REGISTRY` (zuzüglich NATIVE_FLAG-Familie) —; live pro Aufruf gelesen (nicht gecacht); live verifiziert vor P4; Daten-Rollback ist Pfadwechsel, kein Rückschreiben (Provenienz `bach:<id>`, isolierter Store stillgelegt, nicht gelöscht; Entscheidung über Daten in P7).
- Nachweisform: Dokumentierter Verifizierungslauf: Schalter=0 → Legacy-Pfad aktiv, Adapter sauber aus dem Verkehr (Muster Stufe 3: `BACH_USE_EXTERNAL_SCHEDULER=0` → fail-closed).
- Fehlerbedingung (rot): Rollback-Pfad ungeprüft; Schalter gecacht statt live gelesen; Schalter außerhalb der V4-Whitelist; Rückschreiben statt Pfadwechsel.
- Anbindung BACH20-07: §4.3.

### Gate 5 — AST-/Contract-Wächter und §1-Gatung vor Ablösung

- Definition: Dauerwächter in der Regressionssuite — AST-Guards gegen Direktimporte außerhalb des Seams (Muster: test_scheduler_provider_wiring.py) und Contract-Wächter — plus Prüfung der §1-Prinzipien (MODULRUECKTRANSFER-PLAN.md Abschnitt 1; BACH20-07 §1: Gattung vor Ablösung, Fail-Closed) vor jeder Ablösung. Ablösung nur, wenn Parallelbetrieb grün und Rollback nachgewiesen ist.
- Nachweisform: Wächter-Testlauf grün (Exit 0) auf dem betroffenen Host; dokumentierte §1-Prüfung vor der Ablösung.
- Fehlerbedingung (rot): Wächter fehlt oder ist rot; Ablösung ohne grünen Parallelbetrieb; Ablösung ohne Rollback-Nachweis.
- Anbindung BACH20-07: P4/§1.

## §3 Grünfärbungs- und Nachweislehre

1. „Nachweisbar" zählt nur als geleisteter Nachweis: JSONL-/Log-Eintrag mit Zeitstempel, Host und Exit-Code; dokumentierter Testlauf; Manifest-Vergleich; Hash. Absichtserklärungen, reine Code-Lektüre oder „müsste funktionieren" zählen nicht.
2. Ein Gate gilt als grün ausschließlich mit geleistetem Hostlauf-Nachweis auf dem betroffenen Host. Was auf einem anderen Host lief, ist kein Nachweis für diesen Host.
3. Offene Hostläufe: Solange die Windows-Gegenproben zu §4.3 (Stufen 2, 3, 5, 7 des MODULRUECKTRANSFER-PLANS) und der echte 3-Host-Lauf (WORKSTATION-LG, ASUS-GEI, mac-studio über OneDrive-Transit) offen sind, sind die betroffenen Gates definitionsgemäß NICHT GRÜN. Genau das besagt die zweite Hälfte der Abschlussgrenze von #1354: Gates auf offenen Hostläufen zählen nicht als grün.
4. Diese Nicht-Grünfärbung ist Teil der Abschlussgrenze von #1354 und damit KEIN Blocker für dessen Status done (Vorbild: #1351 wurde mit dokumentiert-offenem Blocker abgeschlossen). Sie ist konsistent mit BACH20-07 G5.2.

## §4 Kompatibilitätsmatrix zu BACH20-07

| Referenz in BACH20-07 | Gate in diesem Dokument |
|---|---|
| P0 (Baseline) | Gate 1 — Baseline-Gate |
| P2 (Contract-Prüfung) | Gate 2 — Contract-Gates |
| P3 (Shadow/Parallelbetrieb) | Gate 3 — Shadow-Gate |
| §4.3 (Rollback-Gate, live verifiziert) | Gate 4 — Rollback-Nachweis |
| P4/§1 (Wächter, Ablösungs-Gatung) | Gate 5 — AST-/Contract-Wächter und §1-Gatung |

Konsistenz zu BACH20-07 G5.2: bestätigt — solange nicht alle Gates grün sind, ist die Ausführung einer Migration disqualifiziert. Dieses Dokument präzisiert in §3, was „grün" konkret bedeutet.

## §5 Status und Blocker

- Status dieses Dokuments: doku. Die Definitions- und Doku-Arbeit von #1354 ist damit abgeschlossen; der Status doku ist unblockiert.
- Die Ausführung von Migrationen gemäß BACH20-07 bleibt gemäß dessen G5.2 gesperrt, bis alle Gates (§2) auf den betroffenen Hosts grün sind (§3).
- Dokumentiert offen (analog BACH20-07 §7):
  - a) Windows-Gegenproben zu §4.3 für die Stufen 2, 3, 5, 7 des MODULRUECKTRANSFER-PLANS (MODULRUECKTRANSFER-PLAN.md Z. 122, 283, 303).
  - b) Echter 3-Host-Lauf (WORKSTATION-LG, ASUS-GEI, mac-studio über OneDrive-Transit) inklusive Windows-Gegenprobe (Stufe-7-Nachlauf).
- Keine weiteren Blocker.

## §6 Append-only

Dieses Dokument ist append-only (analog BACH20-07 §8): Bestehende Abschnitte werden nicht nachträglich geändert oder umgedeutet. Nachträge erfolgen ausschließlich durch Anfügen neuer, datierter Abschnitte bzw. neuer Anhang-A-Zeilen mit eigenem Datum. Korrekturen falscher Aussagen erfolgen als datierter Berichtigungsabschnitt, nicht durch Überschreiben. Änderungen, die dieser Regel widersprechen, sind ungültig.

## Anhang A — Abschlussnachweis (2026-09-29, Verfasser: bach)

Abschlussgrenze Task #1354 (wörtlich): „Gates definiert und nachweisbar; Gates auf offenen Hostläufen nicht grün zählen."

| Teilschritt Task #1354 | Fundstelle (dieses Dokument) |
|---|---|
| 1) Baseline-Gate | §2, Gate 1 — Baseline-Gate |
| 2) Contract-Gates | §2, Gate 2 — Contract-Gates |
| 3) Shadow strikt single-writer | §2, Gate 3 — Shadow-Gate |
| 4) vollständiger Rollback-Nachweis | §2, Gate 4 — Rollback-Nachweis |
| 5) AST-/Contract-Wächter + §1-Gatung vor Ablösung (Parallelbetrieb grün + Rollback) | §2, Gate 5 — AST-/Contract-Wächter und §1-Gatung |
| „Gates definiert und nachweisbar" | §0, §2, §3 |
| „Gates auf offenen Hostläufen nicht grün zählen" | §3 (Nr. 2–4), §5 |

Quellen: ROADMAP.md BACH20-06 (Z. 500–569); BACH20-07-ADAPTER-DATENMIGRATIONSVERTRAG.md §4–§8; MODULRUECKTRANSFER-PLAN.md Z. 100–140 und 275–315 (Stufen 3, 7, 8).