# foerderplaner_provider — Standalone Module

> **Version:** 0.2.0 · **Typ:** Provider-Seam (Secure Forward-Only) · **Kompatibilität:** BACH ≥ 3.15.0, Ocean ≥ 1.0.0

## Secure Forward-Only Provider-Vertrag

- `probe` importiert nichts. Der Rollback-Schalter `BACH_USE_EXTERNAL_FOERDERPLANER` mit den Werten `0`, `false`, `no` oder `off` erzwingt den internen Legacy-Pfad (MODULRUECKTRANSFER-PLAN Abschnitt 4, Regel 1).
- `load_external_foerderplaner` lädt das private Bundle ausschließlich per `importlib.import_module` — kein Silent-Fallback.
- `create_external_foerderplaner_adapter` ist die einzige Adapter-Quelle (fail-closed): Ohne BACH-Adapter-Factory wird `foerderplaner >= 0.3 with the BACH adapter contract is required` ausgelöst.
- Native Fehler werden maskiert (`error="foerderplaner_dispatch_failed"`), da sie private Konfiguration enthalten können.
- Das private Bundle `foerderplaner` 0.2.0/Source7d7c8c9 bleibt isoliert unter `/Users/lukas/foerderplaner-private` (`network=none`).

## Installation & Re-Import in BACH

- `bach skills verify` — Modul validieren
- `bach skills install` — Modul in BACH installieren bzw. re-importieren

## Struktur

- `src/` — Implementierung (`foerderplaner_provider.py`)
- `tests/` — Unittests (4 Tests)
- `manifest.json` — Modul-Manifest (selfcontained, entrypoints library)
