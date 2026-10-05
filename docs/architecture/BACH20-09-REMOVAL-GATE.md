# BACH20-09 Haltefrist-, Nullreferenz- und Removal-Gate

| Feld | Wert |
|---|---|
| dokument_id | BACH20-09-REMOVAL-GATE-2026-09-29 |
| Version | 1.0 |
| Status | doku |
| Datum | 2026-09-29 |
| Task | #1358 (BACH20-09 Haltefrist-/Nullreferenz-/Removal-Gate) |
| Vorgänger-Dokumente | BACH20-08-SOT-SWITCH-GATE.md; BACH20-10-MODULUPDATES.md; MODULRUECKTRANSFER-PLAN.md |
| Änderungsregel | append-only (siehe §7) |

## §0 Zweck und Abschlussgrenze

Task #1358 (BACH20-09) ist mit folgender Abschlussgrenze angelegt (wörtlich):

> „Removal nur nach Haltefrist + Update-/Rollbackzyklus (BACH20-10, #1357) + Nullreferenznachweis."

Dieses Dokument definiert die strikten Bedingungen, unter denen abgelöste interne Legacy-Komponenten aus dem BACH-Repository entfernt oder archiviert werden dürfen. Es verhindert Codeverlust, unterbrochene Abhängigkeiten und Datenverlust.

Selbstklärung: Dieses Dokument ist definierend für das Removal-Gate. Es löscht selbst keine Dateien und archiviert keinen Live-Code.

## §1 Die Dreiteilige Trennung

Gemäß Sicherheitsregel Nr. 5 aus `ROADMAP.md` gilt:
**Umschaltung, Modulupdate und Entfernung sind drei strikt getrennte, sequentielle Ereignisse.**

1. **Ereignis 1 (Umschaltung - SoT Switch):** Externes Modul übernimmt die Führung (BACH20-08). Interner Code verbleibt unverändert als passiver Fallback.
2. **Ereignis 2 (Modulupdate):** Nachweis, dass Updates und Rollbacks des externen Moduls im Betrieb fehlerfrei funktionieren (BACH20-10).
3. **Ereignis 3 (Removal/Archivierung):** Erst wenn Ereignis 1 und 2 stabil belegt sind, die Haltefrist verstrichen ist und der Nullreferenznachweis vorliegt, darf eine Bereinigung stattfinden.

## §2 Die Haltefrist (§1.3)

(1) **Fristdauer:** Für jede abzulösende Kernkomponente gilt eine Mindest-Haltefrist von 30 Kalendertagen nach erfolgreicher Umschaltung (SoT-Switch) und stabiler Paritätsbestätigung.
(2) **Stichtag:** Beginnend mit der Konsolidierung am 2026-09-12 endet die Haltefrist für die Primär-Module frühestens am **2026-10-12**.
(3) **Sperrwirkung:** Bis zum Ablauf der Haltefrist ist jedes physische Löschen von Legacy-Code im Repository fail-closed untersagt.

## §3 Repositoryweiter Nullreferenznachweis

Vor jedem Archivierungs- oder Löschschritt muss ein automatisierter Nullreferenznachweis erbracht werden:

(1) **AST- & Import-Scan:** Ein statischer Prüflauf über das gesamte Repository (`system/`, `tests/`, `tools/`, `gui/`) muss belegen, dass kein aktiver Code mehr direkt auf das abzulösende Modul oder dessen interne Pfade importiert (`import ...`, `from ... import ...`).
(2) **String- & Dynamic-Dispatch-Scan:** Prüfung auf dynamische Aufrufe (`getattr`, `importlib.import_module`, Handler-Registrierungen in DB oder Konfigurationen).
(3) **Negative-Finding-Pflicht:** Ergibt der Scan auch nur eine einzige Referenz, schlägt das Removal-Gate fehl (`Gate 5: REF_REMAINING`). Der betroffene Code muss zuerst auf die kanonische Seam-Schnittstelle umgestellt werden.

## §4 Recoverable Archivierung VOR Entfernung

(1) **Archivierungsziel:** Kein Legacy-Code wird je mit `rm` / `git rm` vernichtet, ohne zuvor in `system/hub/_archive/<modul_name>_<iso_datum>/` überführt worden zu sein.
(2) **Commit-Separation:** Die Archivierung erfolgt in einem eigenständigen, dedizierten Commit mit aussagekräftiger Dokumentation über die Ablösung.
(3) **Wiederherstellbarkeit:** Jedes archivierte Modul behält eine `README.md` im Archiv-Verzeichnis, welche die ursprüngliche Funktion, das Ablösedatum, das Nachfolgemodul und den Weg zur Reaktivierung beschreibt.

## §5 Schutz von Daten, Schemata und Credentials

(1) **Unantastbarkeit:** Das Removal-Gate gilt ausschließlich für redundanten Code.
(2) **Datenbankschemata:** Bestehende Tabellen, Views und Migrationen in SQLite werden NICHT gelöscht. Historische Datensätze bleiben erhalten oder werden gemäß Migrationsvertrag (BACH20-07) transformiert.
(3) **Credentials & Secrets:** Keine Bereinigung darf Zugangsdaten, API-Keys oder Konfigurationsparameter löschen.
