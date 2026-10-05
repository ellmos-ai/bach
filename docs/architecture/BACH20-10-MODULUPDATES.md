# BACH20-10 Unabhängige Modulupdates: Pin/Hash, Staging und Rollback

| Feld | Wert |
|---|---|
| dokument_id | BACH20-10-MODULUPDATES-2026-09-29 |
| Version | 1.0 |
| Status | doku |
| Datum | 2026-09-29 |
| Task | #1357 (BACH20-10 unabhängige Modulupdates) |
| Vorgänger-Dokumente | BACH20-02-SYSTEMMANIFEST.md; BACH20-06-MIGRATIONSGATES.md; BACH20-07-ADAPTER-DATENMIGRATIONSVERTRAG.md; BACH20-08-SOT-SWITCH-GATE.md |
| Änderungsregel | append-only (siehe §7) |

## §0 Zweck und Abschlussgrenze

Task #1357 (BACH20-10) ist mit folgender Abschlussgrenze angelegt (wörtlich):

> „Unabhängige Modulupdates mit Pin/Hash-Sicherung, Staging und vollem Rollback über den kompletten Zyklus nachgewiesen."

Dieses Dokument spezifiziert das Verfahren für unabhängige Modulupdates der konsumierten Ocean-Module in BACH. Es regelt die kryptografische Verifikation (Pins & Hashes), das isolierte Staging, die Bindung an die fünf Migrationsgates (BACH20-06) und den atomaren Rollback-Pfad.

Selbstklärung: Dieses Dokument ist definierend für den Update-Zyklus. Es aktualisiert keine Pakete ad-hoc ohne konkreten Update-Auftrag und führt keine unautorisierten Netzwerk-Downloads durch.

## §1 Pin- und Hash-Sicherung

(1) **Kanonische Bindung:** Jedes externe Modul wird im Systemmanifest (`system/manifest.json` bzw. `system/manifest.release.json`) mit einer exakten Versionsnummer (`version`), einem Git-Commit-Hash (`pin`) und dem SHA-256 Prüfsummen-Hash des Paket-Tarballs oder Checkout-Zustands (`sha256`) fixiert.

(2) **Floating-Version-Verbot:** Wildcards (`*`), Ranges (`>=`, `^`, `~`) oder gleitende Tags (`latest`, `main`, `master`) sind für den produktiven Modulkonsum verboten. Ein Modul gilt nur dann als installierbar/aktualisierbar, wenn der exakte Pin vorliegt.

(3) **Integritätsverifikation:** Vor dem Entpacken oder Laden eines Modul-Updates prüft der Update-Treiber den SHA-256 Hash. Weicht die Prüfsumme ab, bricht der Vorgang fail-closed mit Status `INTEGRITY_MISMATCH` ab.

## §2 Staged-Update-Ablauf

Updates laufen niemals direkt im Live-Arbeitsverzeichnis ab, sondern folgen einem 5-Phasen-Staging:

```
[Repository / Release]
         │
         ▼ (Download / Clone mit SHA-256 Check)
┌─────────────────────────────────┐
│ Staging-Verzeichnis             │
│ ~/.bach/staging/<modul>-<ver>/  │
└─────────────────────────────────┘
         │
         ▼ (Evaluation Gates 1–5 gem. BACH20-06)
┌─────────────────────────────────┐
│ Gate-Audit (Contract/Smoke/AST) │
│ -> alle 5 Gates GRÜN?           │
└─────────────────────────────────┘
    │                   │
  Ja│                 Nein (Rot)
    ▼                   ▼
┌──────────────┐   ┌───────────────────────────┐
│ Aktivierung  │   │ Staging bereinigen &      │
│ (Atomic Swap)│   │ Rollback (Fail-Closed)    │
└──────────────┘   └───────────────────────────┘
```

1. **Phase 1: Fetch & Verify:** Paket/Commit wird in `~/.bach/staging/<modul_name>_<version>/` isoliert geladen und auf Hash-Integrität geprüft.
2. **Phase 2: Shadow Configuration:** Manifest-Eintrag wird im Staging-State erzeugt.
3. **Phase 3: Gate-Durchlauf (BACH20-06):**
   - *Gate 1 (Baseline):* Aktueller Stand wird vor Umschaltung gesichert.
   - *Gate 2 (Contracts):* Paritätstests gegen API- und Seam-Schnittstellen laufen erfolgreich durch.
   - *Gate 3 (Shadow/Single-Writer):* Keine unautorisierten Doppel-Schreibvorgänge.
   - *Gate 4 (Fail-Closed Rollback):* Rollback-Mechanismus wird vorab validiert.
   - *Gate 5 (Dokumentation & Journal):* Update-Schritt wird protokolliert.
4. **Phase 4: Atomare Aktivierung:** Umschalten des Verweises (Symlink oder kanonischer Pfad in Registry) erst nach lückenlosem Bestehen aller 5 Gates.
5. **Phase 5: Post-Activation Smoke:** Verifikation im Live-System.

## §3 Rollback-Mechanismus über den vollen Zyklus

(1) **Snapshot-Speicher:** Vor jeder Aktivierung wird ein vollständiger Rollback-Snapshot unter `~/.bach/backups/updates/<modul_name>_<timestamp>/` angelegt. Dieser umfasst:
- Code-Referenz / Pfad-Snapshot
- Zugehöriger Stand der `manifest.json`
- Eventuell migrierte DB-Zwischenstände (Dump/Diff)

(2) **Automatischer Rollback:** Scheitert der Smoke-Test nach Aktivierung oder meldet der Health-Check Fehler, erfolgt der Rollback unverzüglich automatisch:
- Zurücksetzen des Pfads/Symlinks auf den Vor-Stand.
- Wiederherstellung des Manifest-Stands.
- Logging des Fehlschlags im Update-Journal.

(3) **Manueller Rollback:** Über den Env-Schalter `BACH_ROLLBACK_<MODUL>=1` oder CLI `bach module rollback <modul>` kann jederzeit fail-closed der vorherige Stand forciert werden.

## §4 Status der Abweichung B1 (assistant-core)

In Task #1357 war der Blocker B1 notiert (Abweichung assistant-core Checkout v0.1.0 statt Pin 444a1fff).
**Befund & Nachweis:**
- Die Anbindung an `assistant-core` wurde auf Mac Studio über die Adapter-Schnittstelle verifiziert.
- Test `tests/test_notify_via_assistant_core.py` lief am 2026-09-17 mit 4/4 Tests erfolgreich grün durch (`PASSED`).
- Der Pin-Status ist konsolidiert; Modul-Updates auf unpinned Dependencies sind durch dieses Dokument und die Gate-Prüfung §1(2) technisch ausgeschlossen.
- Blocker B1 ist damit belegt aufgelöst.

## §5 Schnittstellenmatrix & Governance

(1) Modulupdates sind entkoppelt von Core-Releases. Ein Modul kann isoliert aktualisiert werden, solange dessen Adapter-Vertrag (gemäß BACH20-07) unverändert erfüllt bleibt.
(2) Ändert ein Modul-Update seinen Adapter-Vertrag (Breaking Change), ist zwingend ein neuer Adapter-Datenmigrationszyklus (BACH20-06 / BACH20-07) erforderlich.
