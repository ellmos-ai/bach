# BACH20-08 Source-of-Truth-Umschaltgate

| Feld | Wert |
|---|---|
| dokument_id | BACH20-08-SOT-SWITCH-GATE-2026-09-29 |
| Version | 1.0 |
| Status | doku |
| Datum | 2026-09-29 |
| Task | #1356 (BACH20-08 Source-of-Truth-Umschaltgate) |
| Vorgänger-Dokumente | BACH20-02-SYSTEMMANIFEST.md; BACH20-06-MIGRATIONSGATES.md; BACH20-07-ADAPTER-DATENMIGRATIONSVERTRAG.md; MODULRUECKTRANSFER-PLAN.md |
| Änderungsregel | append-only (siehe §7) |

## §0 Zweck und Abschlussgrenze

Task #1356 (BACH20-08) ist mit folgender Abschlussgrenze angelegt (wörtlich):

> „Umschaltgate aktiv; kein Wechsel ohne grüne Gates und ohne Env-Rollback-Schalter möglich."

Dieses Dokument definiert das Umschaltgate, das jeden Wechsel des führenden Systems eines Moduls zur externen Variante nur nach grünen Gates (BACH20-06) und gesetztem Env-Rollback-Schalter freigibt.

Selbstklärung: Dieses Dokument ist definierend und abschließend für die Umschaltgate-Logik. Es führt selbst keinen Wechsel durch, installiert nichts und verändert keinen Bestandscode.

## §1 Zweck und Vertrag

(1) Fail-Closed: Ohne vollständige grüne Nachweise, ohne gesetzte Rollback-Schalter, ohne Journal-Vorgaben ist jeder Wechsel verboten; die Probe liefert allowed=False.

(2) Die Nachweisform folgt BACH20-06 §3 (siehe §3).

(3) Der Rollback-Schalter wird live je Aufruf gelesen, niemals gecacht (siehe §4).

(4) Die Stufenfolge je Modul ist P0→P2→P3→P4 (BACH20-06 §4); alle Vorgängerstufen müssen grün sein; zusätzlich single-writer: der letzte offene Journal-Eintrag blockiert ALLE Module (siehe §5).

(5) Unbekanntes modul/stufe → ValueError; Whitelist-Enforcement (siehe §2).

Bezeichnerkonvention (angelehnt an BACH20-06): Gates werden ausgeschrieben „Gate 1" bis „Gate 5". Die Kurzform „G1–G5" wird bewusst nicht verwendet (Kollision mit den Regelbezeichnern G5.1–G6.4 des Vertrags BACH20-07, dort §5/§6). Die Nachweis-JSON-Keys lauten gate_1..gate_5.

## §2 API und Defaults

Modul: `system/hub/sot_switch_gate.py`

Defaults:

- `DEFAULT_EVIDENCE_DIR = BACH_ROOT/data/state/sot-gate/evidence`
- `DEFAULT_JOURNAL_PATH = BACH_ROOT/data/state/sot-gate/journal.jsonl`
- `SOT_MODULES` = 6 Einträge (V4-Whitelist-Pflichtmenge; die 5 Auftragsmodule sind Teilmenge, agent_registry kommt dazu)

Tabelle Modul → Env-Rollback-Schalter (§4.1):

| Modul | Env-Rollback-Schalter |
|---|---|
| scheduler | BACH_USE_EXTERNAL_SCHEDULER |
| explorer | BACH_USE_EXTERNAL_EXPLORER |
| memoryhooks | BACH_USE_EXTERNAL_MEMORYHOOKS |
| workflowhooks | BACH_USE_EXTERNAL_WORKFLOWHOOKS |
| transitsync | BACH_USE_EXTERNAL_TRANSITSYNC |
| agent_registry | BACH_USE_EXTERNAL_AGENT_REGISTRY |

`SOT_STAGES = ("P0","P2","P3","P4")`

Signaturen:

- `probe_sot_switch(modul, stufe, *, environ=None, evidence_dir=None, journal_path=None)` → `SotSwitchProbe(allowed, modul, stufe, reasons:tuple)`; `environ=None` → `os.environ`; reine Prüfung, schreibt nichts.
- `record_switch(modul, stufe, *, host, timestamp, journal_path=None, evidence_dir=None, environ=None)` → schreibt Journal `offen` NUR wenn die Probe erlaubt; Rückgabe = Probe.
- `confirm_green(modul, stufe, *, host, timestamp, journal_path=None, evidence_dir=None)` — KEIN environ (Verwaltung, kein Wechsel); prüft, dass der Nachweis grün ist und der letzte Journal-Status (modul, stufe) == `offen` ist → schreibt `gruen`. Modul-Docstring dazu (wortgetreu): „Ohne environ-Parameter: Das Bestaetigen ist Verwaltung, kein Wechsel; der Rollback-Schalter gehoert zur Wechsel-Anfrage, nicht hierher."

ValueError-Zitate (wortgetreu aus dem Modul):

- `Unbekanntes SoT-Modul {!r}. Bekannte Module: {}`
- `Unbekannte Stufe {!r}. Bekannte Stufen: {}`

## §3 Nachweisform

Nachweis-JSON: `{evidence_dir}/{modul}/{stufe}.json` mit dem Aufbau `{modul, stufe, offene_hostlaeufe: [], gates: {gate_1..gate_5 je {status: "gruen", host, timestamp, exit_code: 0}}}`; `gates` enthält exakt diese 5 Keys.

- `offene_hostlaeufe` nicht leer → nicht grün (BACH20-06 §3).
- Je Gate: `status == "gruen"`, `host`/`timestamp` nicht-leere Zeichenketten, `exit_code` Ganzzahl == 0. Boolean ist explizit verboten (bool ist int-Subklasse).

Reason-Liste Nachweis (wortgetreu aus dem Modul, ASCII):

- `Nachweis fehlt: {}`
- `Nachweis {} ist kein gueltiges JSON`
- `Nachweis {} ist kein JSON-Objekt`
- `Nachweis {}: modul ist {!r}, erwartet {!r}`
- `Nachweis {}: stufe ist {!r}, erwartet {!r}`
- `Nachweis {}: offene_hostlaeufe fehlt`
- `Nachweis {}: offene_hostlaeufe ist keine Liste`
- `Nachweis {}: offene_hostlaeufe nicht leer ({}): offene Hostlaeufe heissen nach BACH20-06 §3 nicht gruen`
- `Nachweis {}: gates fehlt`
- `Nachweis {}: gates ist kein Objekt`
- `Nachweis {}: gates enthaelt {} statt {}`

Reason-Liste je Gate (wortgetreu aus dem Modul, ASCII):

- `Nachweis {}: {} fehlt`
- `Nachweis {}: {} ist kein Objekt`
- `Nachweis {}: {} status ist {!r}, erwartet 'gruen' (BACH20-06 §3)`
- `Nachweis {}: {} {} ist {!r}, keine nicht-leere Zeichenkette`
- `Nachweis {}: {} exit_code ist ein Boolean ({!r}), keine Ganzzahl`
- `Nachweis {}: {} exit_code ist {!r}, keine Ganzzahl`
- `Nachweis {}: {} exit_code ist {} statt 0`

## §4 Rollback-Schalter

- Der Rollback-Schalter (Env-Variable je Modul, siehe §2-Tabelle) wird live je Aufruf gelesen, niemals gecacht.
- Der Wert wird normalisiert (strip+lower).
- `_ROLLBACK_OFF_VALUES = {"0","false","no","off"}` = Aus → blockiert (Rücktransfer erzwungen).
- Abwesend oder leer → blockiert (fail-closed).
- Jeder andere Wert → an.

Reason-Liste Rollback (wortgetreu aus dem Modul, ASCII):

- `Rollback-Schalter {} ist nicht gesetzt: kein Wechsel moeglich (MODULRUECKTRANSFER-PLAN §4 Regel 1)`
- `Rollback-Schalter {} ist leer gesetzt: kein Wechsel moeglich (Fail-Closed)`
- `Rollback-Schalter {} steht auf Aus ({!r}): Ruecktransfer erzwungen, kein Wechsel moeglich`

## §5 Journal

- Append-only JSONL unter `DEFAULT_JOURNAL_PATH`.
- Einträge: `{modul, stufe, status, host, timestamp}`.
- Serialisierung: `json.dumps(sort_keys=True, ensure_ascii=False)`; Verzeichnis wird mit `mkdir parents` angelegt.
- `status` ∈ `{"offen","gruen"}`.
- last-wins je (modul, stufe).
- Offener Eintrag blockiert ALLE Module (single-writer).
- Journal fehlt → nur die erste Stufe P0 möglich.
- `record_switch` → `offen`; `confirm_green` → `gruen`.

Reason-Liste Journal bei der Probe (wortgetreu aus dem Modul, ASCII):

- `Journal fehlt: ohne Journal ist nur die erste Stufe {} moeglich` ({} = "P0")
- `Offener Wechsel fuer {}/{} im Journal blockiert ALLE Module (single-writer, BACH20-08)`
- `Vorgaenger-Stufe {} fuer {} ist im Journal nicht gruen (BACH20-06 §4 Stufenfolge)`

Ungültige Journal-Zeilen → Blockade-Reasons (wortgetreu aus dem Modul, ASCII):

- `Journal Zeile {}: leere Zeile ist ungueltig`
- `Journal Zeile {}: kein gueltiges JSON`
- `Journal Zeile {}: kein JSON-Objekt`
- `Journal Zeile {}: unbekanntes Modul {!r}`
- `Journal Zeile {}: unbekannte Stufe {!r}`
- `Journal Zeile {}: status {!r} ist weder 'offen' noch 'gruen'`

Reason-Liste Journal bei confirm_green (wortgetreu aus dem Modul, ASCII):

- `Journal fehlt: kein offener Eintrag fuer {}/{} zu bestaetigen`
- `Kein offener Eintrag fuer {}/{} im Journal: nichts zu bestaetigen`

## §6 Status 2026-09-29

Status dieses Dokuments: doku (unblockiert).

Heute existieren keine Nachweise (§3) und kein Journal (§5). Damit ist alles blockiert: Jede Probe liefert allowed=False (fail-closed, §1 (1)). Das Gate ist damit im Sinne der Abschlussgrenze aktiv.

Dokumentiert offen (analog BACH20-07 §7):

a) Windows-Gegenproben zu §4 (BACH20-06 §3)

b) echter 3-Host-Lauf (WORKSTATION-LG, ASUS-GEI, mac-studio; BACH20-07 G5.2)

Keine weiteren Blocker.

## §7 Änderungsregel

Dieses Dokument ist append-only (analog BACH20-06 §6): Bestehende Abschnitte werden nicht nachträglich geändert oder umgedeutet. Nachträge erfolgen ausschließlich durch Anfügen neuer, datierter Abschnitte bzw. neuer Anhang-A-Zeilen mit eigenem Datum. Korrekturen falscher Aussagen erfolgen als datierter Berichtigungsabschnitt, nicht durch Überschreiben. Änderungen, die dieser Regel widersprechen, sind ungültig.

## Anhang A — Abschlussnachweis (2026-09-29, Verfasser: bach)

Abschlussgrenze Task #1356 (wörtlich): „Umschaltgate aktiv; kein Wechsel ohne grüne Gates und ohne Env-Rollback-Schalter möglich."

| Teilschritt Task #1356 | Fundstelle (dieses Dokument) |
|---|---|
| SoT-Umschaltgate definieren | §1, §2 |
| Wechsel nacheinander nur nach grün | §1 (4), §5 |
| §4.1 Env-Rollback-Schalter einbinden | §4 |

Quellen: ROADMAP.md BACH20-08; BACH20-06-MIGRATIONSGATES.md §3–§6; BACH20-07-ADAPTER-DATENMIGRATIONSVERTRAG.md §4–§8; MODULRUECKTRANSFER-PLAN.md §4.