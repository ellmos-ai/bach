# BACH20-07 — Atomarer Adapter-/Datenmigrationsvertrag

| Feld | Wert |
|---|---|
| dokument_id | BACH20-07-ADAPTER-DATENMIGRATIONSVERTRAG-2026-09-29 |
| Version | 1.0 |
| Status | doku |
| Datum | 2026-09-29 |
| Task | #1355 |
| Vorgänger-Dokumente | BACH20-03-ID-VERTRAG.md (dokument_id BACH20-03-ID-VERTRAG-2026-09-29); MODULRUECKTRANSFER-PLAN.md; Gates aus BACH20-06 (#1354, pending) |
| Änderungsregel | append-only (siehe §8) |

## §0 Zweck und Abschlussgrenze

Dieser Vertrag definiert, wie Adapter (externe Module hinter einer Seam) und Daten (State-Stores, Tabellen, Sync-Bestände) im Modulrücktransfer atomar migriert werden: idempotent, transaktional, crash- und rollbackfähig. Er bindet die Prinzipien aus MODULRUECKTRANSFER-PLAN.md Abschnitt 1, die Gates aus BACH20-06 (#1354) und den referenziellen ID-Vertrag aus BACH20-03 (#1351) zu einem ausführbaren, aber gegenwärtig nur dokumentierten Migrationsvertrag zusammen.

Abschlussgrenze (Task #1355):

1. Der Vertrag ist dokumentiert (vorliegendes Dokument).
2. Eine Migration ist nur nach grünen Gates (BACH20-06) und mit vollständigem Rollback-Pfad (§4) ausführbar. Sind die Gates nicht grün, ist keine Migration ausführbar — der Vertrag bleibt dennoch gültig.

Dieses Dokument führt selbst keine Migration durch, installiert nichts und verändert keinen Bestandscode.

## §1 Prinzipien

Verankerung der Grundsätze aus MODULRUECKTRANSFER-PLAN.md, Abschnitt 1 (Grundsätze):

- **P1 Funktionale Parität an Usecases.** Ein Adapter oder Datenbestand gilt erst dann als Ersatz, wenn die Usecases des abzulösenden internen Teils belegt gleichwertig erfüllt sind — nicht anhand von Funktionsnamen oder Oberflächenähnlichkeit.
- **P2 Gattung vor Ablösung.** Ein externes Modul ersetzt interne Teile erst bei (a) belegter Gleichwertigkeit, (b) grünem Parallelbetrieb (Shadow, §2 Phase P3) und (c) nachgewiesenem Rollback-Pfad (§4). Keine Ablösung auf Verdacht.
- **P3 Fail-Closed & Archivierung.** Schlägt eine Vertragsprüfung fehl, fällt das System auf den internen Pfad zurück (fail-closed), niemals in einen undefinierten Zustand. Altteile werden nie blind gelöscht; sie werden nach Haltefrist strukturiert unter `system/hub/_archive/` archiviert.
- **P4 AST- & Contract-Wächter.** Statische AST-Tests und Contract-Tests wachen gegen Drift und Re-Monolithisierung der Seam. Sie laufen als Gates und als Dauerwächter.

Ergänzend gelten die allgemeinen Sicherheitsregeln aus Task #1355 (Nachtrag 2026-09-27): Planer read-only; Locks/Ownerarbeit/Drift/rote Gates disqualifizieren; Wechsel laufen nacheinander (nächster startet erst, wenn der vorige nachweislich grün ist); Umschaltung/Modulupdate/Entfernung sind drei getrennte Ereignisse (§2, Phase P4–P7).

## §2 Atomarer Migrationsablauf

Eine Migration von Adapter oder Daten folgt ausschließlich diesem Phasenmodell. Keine Phase darf übersprungen, zusammengelegt oder mit der nächsten verschmolzen werden. Jede Phase erzeugt einen nachprüfbaren Nachweis (Log-/JSONL-Eintrag bzw. Testlauf); ein Phasenabbruch hinterlässt einen wohldefinierten, rückholbaren Zustand (§3, §4).

### P0 Baseline-Sicherung

Vor jeder Änderung wird der Ist-Zustand eingefroren (Baseline-Gate aus BACH20-06). Die Baseline umfasst: Manifest-Zustand (bach-system-manifest-v1), relevante State-Stores, Contract-Erwartungen der betroffenen Seam. Ohne gespeicherte Baseline startet keine Migration.

### P1 Prämigration (idempotent)

Datenmigration in einen **isolierten State-Store** (Muster Stufe 3: `system/data/scheduler_external/state.db`; Muster Stufe 7: verifizierte Snapshots push/pull/pending/sync/cleanup). Regeln:

- Erstlauf und Wiederholungslauf sind unterscheidbar; Wiederholung ändert kein bereits migriertes Ziel (Idempotenz, §3.1).
- Jedem migrierten Datensatz wird die **Provenienz `bach:<id>`** eingestempelt (Namespace `bach`), damit Herkunft und Rückrechnung eindeutig bleiben.
- Der Legacy-Store wird **nicht angefasst**; er bleibt unverändert und dient als Fail-Closed-Fallback (§4.4).
- Default ist Dry-Run (`verify`); Schreiben nur mit explizitem `--apply` (§3.3).

### P2 Contract-Gates vor und nach

Dieselben Contracts werden vor und nach der Migration gegen die Seam geprüft (Contract-Gates aus BACH20-06). Bricht ein Contract nach der Migration, gilt die Phase als rot: keine Fortsetzung, Rollback-Pfad aktiv halten. Die Contract-Erwartungen sind die der Baseline (P0), nicht neu erfundene.

### P3 Shadow-Parallelbetrieb (single-writer)

Neuer und alter Pfad laufen parallel; das Shadow-Gate aus BACH20-06 gilt **strikt single-writer**: Der Legacy-Pfad bleibt führender Schreiber, bis die Umschaltung (P4) erfolgt. Der Adapterpfad schreibt ausschließlich in den isolierten Store. Drift zwischen den Pfaden disqualifiziert die Migration.

### P4 Umschaltung (Ereignis 1 von 3)

Erstes getrenntes Ereignis: Der führende Pfad wechselt per Env-Schalter (§4.1) zum Adapterpfad. Dieses Ereignis steht allein; es wird kein Modulupdate und kein Removal damit verbunden. Nach der Umschaltung läuft der Legacy-Pfad als heißes Fallback mit (per Schalter pro Aufruf zurückholbar).

### P5 Modulupdate (Ereignis 2 von 3)

Zweites getrenntes Ereignis: Aktualisierung des Adapters (Pin-Wechsel gemäß V2-Format, requirements.txt-Pin). Ein Modulupdate findet frühestens nach grüner Umschaltung statt und darf nie mit P4 oder P7 verschmolzen werden.

### P6 Haltefrist

Nach Umschaltung und Update-/Rollbackzyklus gilt eine Haltefrist, in der der Legacy-Pfad archivierungsfähig, aber unangetastet bleibt. Die Haltefrist ist eine Bedingung, kein Zeitpunkt: Sie endet erst nach einem durchlaufenen Update-/Rollbackzyklus mit grünen Gates.

### P7 Archivierung mit Nullreferenznachweis (Ereignis 3 von 3)

Drittes getrenntes Ereignis: Erst nach Haltefrist + Update-/Rollbackzyklus + **repositoryweitem Nullreferenznachweis** (kein Code, kein Manifest, kein Test referenziert den Altbestand noch) wird der Altteil strukturiert nach `system/hub/_archive/` archiviert (P3: Archivierung statt Löschung). Physische Löschung ist kein vorgesehener Schritt dieses Vertrags.

## §3 Idempotenz, Transaktionalität, Crash-Sicherheit

### §3.1 Idempotenz

Jeder Migrationsschritt ist idempotent: Erstlauf und Wiederholungslauf ergeben denselben Zielzustand. Erreicht durch: (a) Provenienz-Markierung `bach:<id>` (bereits migrierte Sätze werden erkannt und übersprungen), (b) Installation/Setup idempotent (Muster Stufe 6 memoryhooker/workflowhooker), (c) Prämigration mit `verify` vor `--apply` (Muster Stufe 3).

### §3.2 Transaktionalität

Ein Phasenübergang gilt erst mit seinem Nachweis als vollzogen. Zustandswechsel des State-Stores erfolgen transaktional (SQLite-Transaktion je Schreibbatch); ein abgebrochener Batch hinterlässt den Store im Zustand vor dem Batch. Zwischenzustände werden nicht als gültige Zielzustände akzeptiert.

### §3.3 Crash-Sicherheit und Wiederanlauf

Kill oder Absturz an beliebiger Stelle ist ein erwarteter Fall, kein Ausnahmefall:

- **Wiederanlauf:** Derselbe Kommandoaufruf nach dem Crash setzt am letzten vollzogenen Nachweis an (Idempotenz §3.1), nicht am Anfang und nicht mitten im Batch.
- **Dry-Run/apply-Trennung:** Ohne `--apply` schreibt nichts. Ein gecrashter Dry-Run kann keine Seiteneffekte haben.
- **Kein Auto-Install:** Fehlende externe Module werden nicht automatisch nachinstalliert; der Seam fällt fail-closed auf den internen Pfad zurück (Muster Stufe 7: `find_spec`-Probe ohne Import; schlägt die Probe fehl, greift der Fallback).
- **Fail-Closed bei unvollständigem Vertrag:** Ist der Adapter-Contract nicht vollständig prüfbar (Muster Stufe 3: `create_bach_adapter`-Contract; Muster Stufe 7: fail-closed Contract), wird der Adapter nicht aktiviert — unabhängig davon, was der Env-Schalter sagt.

### §3.4 Unberührtheit des Legacy-Pfads

Der Legacy-Store und der interne Altcode bleiben während aller Phasen P1–P6 unverändert. Sie sind das Fail-Closed-Fallback. Jede Regelverletzung (Schreibzugriff auf Legacy außerhalb eines expliziten, dokumentierten Reparaturlaufs) disqualifiziert die Migration.

## §4 Rollback-Pfad

### §4.1 Rollback-Auslöser

Rollback erfolgt ausschließlich über Env-Schalter aus der V4-Whitelist des Systemmanifests (BACH20-02 §3, Validator V4): `BACH_USE_EXTERNAL_SCHEDULER`, `BACH_USE_EXTERNAL_EXPLORER`, `BACH_USE_EXTERNAL_MEMORYHOOKS`, `BACH_USE_EXTERNAL_WORKFLOWHOOKS`, `BACH_USE_EXTERNAL_TRANSITSYNC`, `BACH_USE_EXTERNAL_AGENT_REGISTRY` (plus `NATIVE_FLAG`-Familie gemäß Manifest). Rückstellung auf `0` aktiviert den Legacy-Pfad (Muster Stufe 3: `BACH_USE_EXTERNAL_SCHEDULER=0`; Stufe 7: `BACH_USE_EXTERNAL_TRANSITSYNC=0`). Kein anderer Mechanismus (Config-Dateien, DB-Flags, Code-Edits) ist als Rollback-Auslöser zulässig.

### §4.2 Live gelesen

Der Schalter wird **live pro Aufruf** gelesen (Muster Stufe 6: Rollback live pro Aufruf gelesen), nicht beim Prozessstart gecacht. Ein Rollback wirkt damit ohne Restart und ohne Migration „rückwärts".

### §4.3 Rollback-Gate

Der Rollback-Pfad ist vor der Umschaltung (P4) **live zu verifizieren** (Rollback-Gate aus BACH20-06): Nachweis, dass Schalterstellung `0` den Legacy-Pfad tatsächlich aktiviert und der Adapterpfad sauber aus dem Verkehr geht. Ein nicht verifizierter Rollback-Pfad disqualifiziert die Umschaltung.

### §4.4 Daten-Rollback

Weil der Legacy-Store nach §3.4 unberührt bleibt und die Provenienz `bach:<id>` migrierte Sätze identifiziert, ist der Daten-Rollback kein Rückschreiben: Der führende Pfad wechselt zurück zum Legacy-Store; der isolierte Store wird stillgelegt (nicht gelöscht). Erst in P7 (Archivierung) wird über den isolierten Store abschließend entschieden.

### §4.5 Vollständigkeit

Der Rollback-Pfad gilt als vollständig, wenn: Schalter aus V4-Whitelist (§4.1), live gelesen (§4.2), live verifiziert (§4.3), Daten-Rollback ohne Rückschreiben (§4.4). Fehlt ein Element, ist die Abschlussbedingung „vollständiger Rollback-Pfad" nicht erfüllt und keine Migration ausführbar (§0.2).

## §5 Anbindung an die Gates aus BACH20-06 (#1354)

Die Ausführbarkeitsbedingung dieses Vertrags sind die Gates aus BACH20-06: Baseline-Gate (Ist-Zustand vor Änderung), Contract-Gates (gleiche Contracts vor/nach), Shadow-Gate (strikt single-writer), vollständiger Rollback-Nachweis, AST-/Contract-Wächter gegen Drift.

Regeln der Anbindung:

- **G5.1:** Alle vier Gates (Baseline, Contract, Shadow, Rollback) müssen vor einer Migration grün sein. Ein einzelnes rotes oder fehlendes Gate disqualifiziert.
- **G5.2:** Gates auf offenen Hostläufen zählen **nicht** als grün. Solange BACH20-06 (#1354) pending ist (§7), ist keine Ausführung nach diesem Vertrag möglich — der Vertrag selbst bleibt gültig und ist die Prüfgrundlage für die spätere Ausführung.
- **G5.3:** Die Phasen P0–P4 (§2) bilden die Gates 1:1 ab: P0 = Baseline-Gate, P2 = Contract-Gates, P3 = Shadow-Gate, §4.3 = Rollback-Gate. Eine Phase ohne grünes Gate gilt als nicht vollzogen.

## §6 Anbindung an den ID-Vertrag aus BACH20-03 (#1351)

Adapter und Daten werden in diesem Vertrag ausschließlich referenziert, nie kopiert (G1/G2 aus BACH20-03 §1):

- **G6.1:** Eine Adapter- oder Datenreferenz ist das Tupel `(registry_typ, id)` gemäß BACH20-03 §3, mit `registry_typ = system-manifest` und `id` = Manifest-`name` (Pattern `^[a-z][a-z0-9-]*$`). Die `klassifikation` ist `adapter` bzw. `daten` (V5-Enum).
- **G6.2:** Auflösung erfolgt gegen die lebende Quell-Registry (Systemmanifest, `sot_kennzeichnung=aktiv`), nie gegen eine Kopie (BACH20-03 §4, Auflösbarkeitskriterium §4.5). Das gilt auch für Manifest-Einträge mit `sot_kennzeichnung=fallback` (Rollback-Ziel) und `legacy` (Altbestand bis P7): Ihre Rolle ergibt sich aus dem Manifest, nicht aus lokalen Notizen.
- **G6.3:** Pin-Felder (`pin_commit` ∈ `^[0-9a-f]{7,8}$` oder `""`; `pin_version` ∈ `^v\d+\.\d+\.\d+$` oder `""`; `null` verboten) sind Referenzattribute gemäß G4 aus BACH20-03 und legen den vertraglich geprüften Modulstand fest (Muster: `ellmos-scheduler` v0.3.3 @ `296b6f5`; `memoryhooker` @ `94611c2`). Ein Adapter mit Pin-Abweichung vom Manifest ist kein gültiges Migrationsziel.
- **G6.4:** Validatoren V1 (draft-07-JSONSchema), V3 (Ist/Soll-Abgleich), V4 (env_schalter-Whitelist), V5 (klassifikation-Enum) und V7 (Rückgabe `list[str]`, keine Exceptions) gelten für jeden Manifest-Eingriff im Rahmen einer Migration. Ein Validator-Fund disqualifiziert den Schritt; es wird nicht „im Vorbeigehen" korrigiert.

## §7 Blocker-Vermerke

Offene Punkte, die die **Ausführung** von Migrationen nach diesem Vertrag derzeit sperren, die **Dokumentation** aber nicht blockieren:

- **#1354 (BACH20-06 Gates) pending:** §4.3 Windows-Gegenproben der Stufen 2/3/5/7 offen; Stufe-7-Nachlauf ausstehend: echter 3-Host-Lauf (WORKSTATION-LG / ASUS-GEI / mac-studio über OneDrive-Transit) inklusive Windows-Gegenprobe. Konsequenz gemäß G5.2: Ohne grüne Gates ist keine Migration nach diesem Vertrag ausführbar; der Vertrag gilt trotzdem.
- Keine weiteren Blocker für den Dokumentationsstatus (Status `doku`).

## §8 Append-only

Dieses Dokument ist append-only: Bestehende Abschnitte werden nicht verändert oder gelöscht. Korrekturen, Präzisierungen und neue Befunde werden als neue Anhänge mit Datum und Task-/Quellenangabe angefügt. Bei Widerspruch zwischen Altabschnitt und Anhang gilt der Anhang; der Widerspruch ist im Anhang ausdrücklich zu benennen.

## Anhang A — Abschlussnachweis (2026-09-29, Verfasser: bach)

| Anforderung (Task #1355) | Nachweis im Dokument |
|---|---|
| Vertrag idempotent, transaktional, crash- und rollbackfähig | §3.1–§3.4, §4.1–§4.5 |
| §1-Prinzipien verankert: Parität, Gattung vor Ablösung, Fail-Closed | §1 (P1–P4, Verweis MODULRUECKTRANSFER-PLAN.md Abschnitt 1) |
| Anbindung an Gates aus BACH20-06 (#1354) | §5 (G5.1–G5.3), §2 P0/P2/P3, §4.3 |
| Anbindung an ID-Vertrag aus BACH20-03 (#1351) | §6 (G6.1–G6.4) |
| Abschlussgrenze: Vertrag dokumentiert; Migration nur nach grünen Gates mit vollständigem Rollback-Pfad ausführbar | §0; §5 G5.2; §4.5; Blocker-Stand §7 |
| Atomarer Ablauf inkl. 3-getrennte-Ereignisse-Regel | §2 (P0–P7; P4/P5/P7 getrennt) |
