# BACH20-02 — Versioniertes Systemmanifest (Schema, Beispiel, Validatorvertrag)

> **Dokument-ID:** BACH20-02-SYSTEMMANIFEST-2026-09-27
> **Schema-Version:** bach-system-manifest-v1 (JSON Schema draft-07)
> **Quellen:** BACH20-01-INVENTAR-2026-09-27 (Primärquelle, Stufe-1-Wiederverwendung), system/agents/ati/export/manifest.schema.json ($id bach-agent-manifest-v1 — Schema-Konventionsvorbild)
> **Task:** #1350
> **Verbindlicher Input für:** #1351 (nächster Tag)

Zweck: Ein einzelnes, versioniertes, maschinell prüfbares Manifest beschreibt den realen Bestand des Systems — Core, externe Module, Adapterfläche, Daten und Legacy-Fläche — mit Versionen, Pins, Abhängigkeitskanten, Datenverträgen, SoT-Kennzeichnung und Abweichungen. Das Beispiel-Manifest in §2 bildet den Stand 2026-09-27 exakt so ab, wie ihn das Inventar BACH20-01 belegt hat — inklusive der ehrlich ausgewiesenen Abweichung B1 (nicht wegretuschiert).

## §1 Manifest-Schema (bach-system-manifest-v1)

Das Schema folgt den Konventionen des Agenten-Manifestschemas `system/agents/ati/export/manifest.schema.json` (JSON Schema draft-07, kebab-case-Namensmuster, klare Pflichtfeldlehre) — Wiederverwendung der Konvention, keine Parallelinstallation (siehe §3, Wiederverwendungs-Vermerk).

Konventionen zu leeren Feldern: Unversionierte Komponenten (core/daten/legacy) und checkout-basierte Komponenten ohne Commit-Pin (ellmos-tests) führen `""` (leerer String) in Versions- und Pin-Feldern — nicht `null`. Das gilt gleichermaßen für Soll- und Ist-Felder; die Cross-Field-Regel V3 in §3 wertet `""` == `""` als „keine Abweichung".

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "$id": "bach-system-manifest-v1",
  "title": "BACH Versioniertes Systemmanifest",
  "description": "Versioniertes Systemmanifest gemäß Task #1350: Version/Pin/Hash, Abhängigkeitskanten, Datenverträge, SoT-Kennzeichnung, Klassifikation Core/Modul/Adapter/Daten/Legacy.",
  "type": "object",
  "required": ["schema_version", "dokument_id", "stand", "quellen", "komponenten"],
  "properties": {
    "schema_version": {
      "type": "string",
      "const": "bach-system-manifest-v1"
    },
    "dokument_id": {
      "type": "string",
      "minLength": 1
    },
    "stand": {
      "type": "string",
      "format": "date"
    },
    "quellen": {
      "type": "array",
      "items": { "type": "string", "minLength": 1 }
    },
    "komponenten": {
      "type": "array",
      "minItems": 1,
      "items": { "$ref": "#/definitions/komponente" }
    }
  },
  "definitions": {
    "komponente": {
      "type": "object",
      "required": ["name", "klassifikation", "sot_kennzeichnung", "status"],
      "properties": {
        "name": {
          "type": "string",
          "pattern": "^[a-z][a-z0-9-]*$",
          "description": "Kebab-case, Konvention übernommen aus bach-agent-manifest-v1."
        },
        "version": {
          "type": "string",
          "description": "Freie Versionsangabe; leerer String erlaubt (unversionierte Core-/Daten-/Legacy-Komponenten)."
        },
        "pin_commit_soll": {
          "type": "string",
          "pattern": "^([0-9a-f]{7,8})?$",
          "description": "Kurzer Commit-Hash (7-8 hex) oder leer bei checkout-basierten/ungepinnten Komponenten (z.B. ellmos-tests)."
        },
        "pin_commit_ist": {
          "type": "string",
          "pattern": "^([0-9a-f]{7,8})?$",
          "description": "Wie pin_commit_soll, jedoch der tatsächlich ausgecheckte Stand."
        },
        "pin_version_soll": {
          "type": "string",
          "pattern": "^(v\\d+\\.\\d+\\.\\d+)?$",
          "description": "Semver-Tag vMAJOR.MINOR.PATCH oder leer."
        },
        "pin_version_ist": {
          "type": "string",
          "pattern": "^(v\\d+\\.\\d+\\.\\d+)?$"
        },
        "klassifikation": {
          "type": "string",
          "enum": ["core", "modul", "adapter", "daten", "legacy"]
        },
        "sot_kennzeichnung": {
          "type": "string",
          "enum": ["aktiv", "fallback", "legacy"],
          "description": "Source-of-Truth-Kennzeichnung: aktiv = lebender Pfad; fallback = Rollback-Ziel eines Env-Schalters; legacy = Prä-Transfer-Altlast."
        },
        "adapter": {
          "type": "array",
          "items": { "type": "string" },
          "description": "Adapter-/Seam-Pfade, über die die Komponente angeschlossen ist."
        },
        "abhaengigkeiten": {
          "type": "array",
          "items": {
            "type": "object",
            "required": ["von", "nach"],
            "properties": {
              "von": { "type": "string" },
              "nach": { "type": "string" },
              "art": { "type": "string" }
            },
            "additionalProperties": false
          },
          "description": "Abhängigkeitskanten name->name zwischen Manifest-Komponenten."
        },
        "datenvertraege": {
          "type": "array",
          "items": { "type": "string" },
          "description": "Freie Vertrags-Ids oder Pfade (z.B. 'liest BACH_DB read-only')."
        },
        "env_schalter": {
          "type": "array",
          "items": {
            "type": "string",
            "enum": [
              "BACH_USE_EXTERNAL_SCHEDULER",
              "BACH_USE_EXTERNAL_EXPLORER",
              "BACH_USE_EXTERNAL_MEMORYHOOKS",
              "BACH_USE_EXTERNAL_WORKFLOWHOOKS",
              "BACH_USE_EXTERNAL_TRANSITSYNC",
              "BACH_USE_EXTERNAL_AGENT_REGISTRY",
              "NATIVE_FLAG"
            ]
          },
          "description": "Whitelist der 6 Env-Schalter + NATIVE_FLAG der ellmos-tests. Leere Liste erlaubt: accounts-core, assistant-core und der Tests-Adapter-Anschluss ohne Env-Schalter haben keinen Umschaltpfad (bzw. nur --native)."
        },
        "rollback": {
          "type": "string",
          "description": "Konkreter Rückfallpfad (z.B. 'BACH_USE_EXTERNAL_SCHEDULER=0' oder '--native-Flag')."
        },
        "status": {
          "type": "string",
          "enum": ["zertifiziert", "offen", "doku"],
          "description": "zertifiziert = Ist==Soll und Teil der Zertifizierung; offen = Abweichung eingetragen (siehe Regel V3 in §3); doku = Bestandsdokumentation ohne Zertifizierungsaussage."
        },
        "abweichungen": {
          "type": "array",
          "items": {
            "type": "object",
            "required": ["id", "befund", "klaerung_task"],
            "properties": {
              "id": { "type": "string" },
              "befund": { "type": "string" },
              "klaerung_task": { "type": "string" }
            },
            "additionalProperties": false
          }
        },
        "kommentar": {
          "type": "string"
        }
      }
    }
  }
}
```

Klassifikations-Legende: `core` = hub-freie Kernmodule unter `system/core/` (z.B. hooks.py mit Interceptor-Slot, safe_db.py); `modul` = externes Repo, über Provider-Seam angeschlossen; `adapter` = Adapterfläche in `system/hub/`; `daten` = Runtime-Persistenz (BACH_DB); `legacy` = Prä-Transfer-Altlasten und Kompat-Wrapper.

## §2 Beispiel-Manifest (Stand 2026-09-27)

Schema-valide Instanz, die den im Inventar BACH20-01 belegten realen Bestand abbildet: 1 Core, 8 externe Module, Adapterfläche, Daten, Legacy-Fläche — plus der dokumentierte Nebenfluss agent-launcher (OC-B opt-in, nicht Teil der 8er-Zertifizierung). Die Abweichung B1 bei assistant-core ist seit 2026-09-17 gelöst (mac-studio, Test 2026-09-27: 4/4 grün); sie verbleibt nur als Abschluss-Vermerk in #1341.

```json
{
  "schema_version": "bach-system-manifest-v1",
  "dokument_id": "BACH20-02-SYSTEMMANIFEST-2026-09-27",
  "stand": "2026-09-27",
  "quellen": [
    "BACH20-01-INVENTAR-2026-09-27",
    "#1349",
    "#1350",
    "system/agents/ati/export/manifest.schema.json (Schema-Konventionsvorbild, bach-agent-manifest-v1)"
  ],
  "komponenten": [
    {
      "name": "bach-core",
      "version": "",
      "pin_commit_soll": "",
      "pin_commit_ist": "",
      "pin_version_soll": "",
      "pin_version_ist": "",
      "klassifikation": "core",
      "sot_kennzeichnung": "aktiv",
      "adapter": ["system/core/hooks.py", "system/core/safe_db.py"],
      "abhaengigkeiten": [],
      "datenvertraege": [],
      "env_schalter": [],
      "rollback": "",
      "status": "zertifiziert",
      "abweichungen": [],
      "kommentar": "Hub-freier Kern unter system/core/; hooks.py Interceptor-Slot, safe_db.py."
    },
    {
      "name": "ellmos-tests",
      "version": "",
      "pin_commit_soll": "",
      "pin_commit_ist": "",
      "pin_version_soll": "",
      "pin_version_ist": "",
      "klassifikation": "modul",
      "sot_kennzeichnung": "aktiv",
      "adapter": ["system/hub/test.py"],
      "abhaengigkeiten": [],
      "datenvertraege": [],
      "env_schalter": ["NATIVE_FLAG"],
      "rollback": "--native-Flag",
      "status": "zertifiziert",
      "abweichungen": [],
      "kommentar": "Checkout-basiert, KEIN pip-Pin; Ist == Soll."
    },
    {
      "name": "ellmos-scheduler",
      "version": "",
      "pin_commit_soll": "296b6f5",
      "pin_commit_ist": "296b6f5",
      "pin_version_soll": "",
      "pin_version_ist": "",
      "klassifikation": "modul",
      "sot_kennzeichnung": "aktiv",
      "adapter": ["system/hub/scheduler_provider.py"],
      "abhaengigkeiten": [],
      "datenvertraege": [],
      "env_schalter": ["BACH_USE_EXTERNAL_SCHEDULER"],
      "rollback": "BACH_USE_EXTERNAL_SCHEDULER=0",
      "status": "zertifiziert",
      "abweichungen": [],
      "kommentar": "Ist == Soll."
    },
    {
      "name": "accounts-core",
      "version": "",
      "pin_commit_soll": "9e0d0e9",
      "pin_commit_ist": "0166805",
      "pin_version_soll": "v0.1.1",
      "pin_version_ist": "v0.1.1",
      "klassifikation": "modul",
      "sot_kennzeichnung": "aktiv",
      "adapter": ["system/gui/server.py", "system/hub/steuer.py"],
      "abhaengigkeiten": [],
      "datenvertraege": [],
      "env_schalter": [],
      "rollback": "",
      "status": "zertifiziert",
      "abweichungen": [],
      "kommentar": "Welle 2+3 abgeschlossen: Fachkern ersetzt, Wächter scharf, kein Env-Schalter. pin_commit_ist 0166805 ist exakt der Tag-Commit von v0.1.1; der Soll-Pin 9e0d0e9 ist die taggleiche Referenz aus dem Inventar — Versionsgleichstand, keine Abweichung."
    },
    {
      "name": "assistant-core",
      "version": "",
      "pin_commit_soll": "444a1fff",
      "pin_commit_ist": "444a1fff",
      "pin_version_soll": "v0.2.0",
      "pin_version_ist": "v0.2.0",
      "klassifikation": "modul",
      "sot_kennzeichnung": "aktiv",
      "adapter": ["system/hub/notify.py", "system/hub/_services/chat"],
      "abhaengigkeiten": [],
      "datenvertraege": [],
      "env_schalter": [],
      "rollback": "",
      "status": "konform (B1 gelöst 2026-09-17 auf mac-studio, Test 2026-09-27: 4/4 grün; Abschluss-Vermerk #1341 offen)",
      "abweichungen": [
        {
          "id": "B1",
          "befund": "GELÖST (2026-09-17 auf mac-studio): Ist ccadcf9/v0.1.0 am 2026-09-17 per Reflog-Checkout auf Soll 444a1fff/v0.2.0 gezogen; HEAD geprüft 2026-09-27, Testnachweis 2026-09-27 (test_notify_via_assistant_core.py 4/4 grün). Ursprünglicher Befund: Ist ccadcf9 statt 444a1fff; hostabhängig: WORKSTATION-LG 4/4 grün, mac-studio Collection-Error.",
          "klaerung_task": "#1341"
        }
      ],
      "kommentar": "Welle 1+2 angeschlossen (notify.py, _services/chat/), kein Env-Schalter."
    },
    {
      "name": "system-explorer",
      "version": "",
      "pin_commit_soll": "bd250b1a",
      "pin_commit_ist": "bd250b1a",
      "pin_version_soll": "",
      "pin_version_ist": "",
      "klassifikation": "modul",
      "sot_kennzeichnung": "aktiv",
      "adapter": ["system/hub/explorer_provider.py"],
      "abhaengigkeiten": [],
      "datenvertraege": [],
      "env_schalter": ["BACH_USE_EXTERNAL_EXPLORER"],
      "rollback": "BACH_USE_EXTERNAL_EXPLORER=0",
      "status": "zertifiziert",
      "abweichungen": [],
      "kommentar": "Stellt system/hub/system_audit.py nativ bereit. Ist == Soll."
    },
    {
      "name": "memoryhooker",
      "version": "",
      "pin_commit_soll": "94611c25",
      "pin_commit_ist": "94611c25",
      "pin_version_soll": "",
      "pin_version_ist": "",
      "klassifikation": "modul",
      "sot_kennzeichnung": "aktiv",
      "adapter": ["system/hub/memory_hook_provider.py"],
      "abhaengigkeiten": [],
      "datenvertraege": ["liest BACH_DB read-only"],
      "env_schalter": ["BACH_USE_EXTERNAL_MEMORYHOOKS"],
      "rollback": "BACH_USE_EXTERNAL_MEMORYHOOKS=0",
      "status": "zertifiziert",
      "abweichungen": [],
      "kommentar": "Ist == Soll."
    },
    {
      "name": "workflowhooker",
      "version": "",
      "pin_commit_soll": "6d2b1908",
      "pin_commit_ist": "6d2b1908",
      "pin_version_soll": "",
      "pin_version_ist": "",
      "klassifikation": "modul",
      "sot_kennzeichnung": "aktiv",
      "adapter": ["system/hub/workflow_hook_provider.py"],
      "abhaengigkeiten": [],
      "datenvertraege": [],
      "env_schalter": ["BACH_USE_EXTERNAL_WORKFLOWHOOKS"],
      "rollback": "BACH_USE_EXTERNAL_WORKFLOWHOOKS=0",
      "status": "zertifiziert",
      "abweichungen": [],
      "kommentar": "Ist == Soll."
    },
    {
      "name": "sqlite-transit-sync",
      "version": "",
      "pin_commit_soll": "40e99262",
      "pin_commit_ist": "40e99262",
      "pin_version_soll": "",
      "pin_version_ist": "",
      "klassifikation": "modul",
      "sot_kennzeichnung": "aktiv",
      "adapter": ["system/hub/transit_sync_provider.py"],
      "abhaengigkeiten": [],
      "datenvertraege": [],
      "env_schalter": ["BACH_USE_EXTERNAL_TRANSITSYNC"],
      "rollback": "BACH_USE_EXTERNAL_TRANSITSYNC=0",
      "status": "zertifiziert",
      "abweichungen": [],
      "kommentar": "Ist == Soll."
    },
    {
      "name": "hub-adapterflaeche",
      "version": "",
      "pin_commit_soll": "",
      "pin_commit_ist": "",
      "pin_version_soll": "",
      "pin_version_ist": "",
      "klassifikation": "adapter",
      "sot_kennzeichnung": "aktiv",
      "adapter": ["system/hub/*_provider.py", "system/hub/test.py", "system/hub/notify.py", "system/hub/steuer.py", "system/gui/server.py"],
      "abhaengigkeiten": [],
      "datenvertraege": [],
      "env_schalter": [],
      "rollback": "",
      "status": "doku",
      "abweichungen": [],
      "kommentar": "Provider-Seams der 8 externen Module; steuer.py und gui/server.py sind die Welle-2/3-Seams von accounts-core."
    },
    {
      "name": "bach-db",
      "version": "",
      "pin_commit_soll": "",
      "pin_commit_ist": "",
      "pin_version_soll": "",
      "pin_version_ist": "",
      "klassifikation": "daten",
      "sot_kennzeichnung": "aktiv",
      "adapter": [],
      "abhaengigkeiten": [],
      "datenvertraege": ["kanonisches Runtime-DB-Verzeichnis; memoryhooker liest read-only"],
      "env_schalter": [],
      "rollback": "",
      "status": "doku",
      "abweichungen": [],
      "kommentar": "BACH_DB ist das kanonische Runtime-DB-Verzeichnis — NICHT system/data/."
    },
    {
      "name": "legacy-flaeche",
      "version": "",
      "pin_commit_soll": "",
      "pin_commit_ist": "",
      "pin_version_soll": "",
      "pin_version_ist": "",
      "klassifikation": "legacy",
      "sot_kennzeichnung": "legacy",
      "adapter": ["system/hub/_archive", "system/hub/daemon.py = Dauer-Kompat-Wrapper", "interne Fallback-Pfade (Rollback-Ziele der 6 Env-Schalter)"],
      "abhaengigkeiten": [],
      "datenvertraege": [],
      "env_schalter": [],
      "rollback": "",
      "status": "doku",
      "abweichungen": [],
      "kommentar": "system/hub/_archive/ enthält nur Prä-Transfer-Altlasten; hub/prosync.py existiert nicht mehr. Archivierung KONTRAINDIZIERT bis #1340/#1341 geklärt sind."
    },
    {
      "name": "agent-launcher-nebenfluss",
      "version": "",
      "pin_commit_soll": "",
      "pin_commit_ist": "",
      "pin_version_soll": "",
      "pin_version_ist": "",
      "klassifikation": "modul",
      "sot_kennzeichnung": "aktiv",
      "adapter": ["system/hub/agent_launcher.py"],
      "abhaengigkeiten": [],
      "datenvertraege": [],
      "env_schalter": ["BACH_USE_EXTERNAL_AGENT_REGISTRY"],
      "rollback": "BACH_USE_EXTERNAL_AGENT_REGISTRY=0",
      "status": "doku",
      "abweichungen": [],
      "kommentar": "OC-B opt-in (BACH_USE_EXTERNAL_AGENT_REGISTRY=1); NICHT Teil der 8er-Zertifizierung, nur Hinweis."
    }
  ]
}
```

## §3 Validatorvertrag

Der Validator prüft eine Manifest-Instanz gegen dieses Dokument. Verbindliche Signatur: `validate_system_manifest(doc: dict) -> list[str]`. Die Regeln V1–V7 sind verbindlich; eine Implementierung ist **nicht** Teil von Task #1350 (siehe Hinweis am Ende).

### (V1) Maschinelle Stufe

Validierung gegen das JSON-Schema aus §1 mit **JSON Schema draft-07** (Python: `jsonschema`). Fehlende Pflichtfelder (`name`, `klassifikation`, `sot_kennzeichnung`, `status`) führen zur Ablehnung — je fehlendem Feld ein Fehlereintrag.

### (V2) Format-Regexe

- Commit-Pins (`pin_commit_ist`, `pin_commit_soll`): `^[0-9a-f]{7,8}$` — oder `""` (leerer String) bei checkout-basierten/unversionierten Komponenten. **`null` ist verboten** (Konvention: leerer String statt `null`).
- Versions-Pins (`pin_version_ist`, `pin_version_soll`): `^v\d+\.\d+\.\d+$` — oder `""`.

### (V3) Cross-Field-Pflichtregel (Ist/Soll-Abgleich)

1. **Abweichungspflicht:** `pin_commit_ist ≠ pin_commit_soll` **oder** `pin_version_ist ≠ pin_version_soll` ⇒ mindestens **ein** Eintrag in `abweichungen[]` mit `id`, `befund` und `klaerung_task`, **und** `status` muss `"offen"` sein.
2. **Gleichstand:** `pin_commit_ist == pin_commit_soll` **und** `pin_version_ist == pin_version_soll` ⇒ `abweichungen` muss **leer** sein. `"" == ""` gilt als Gleichstand (keine Abweichung).
3. **Taggleich-Ausnahme (nur Warnung, kein Fehler):** Weicht **nur** der Commit ab (`pin_commit_ist ≠ pin_commit_soll`) bei gleichzeitigem Versionsgleichstand (`pin_version_ist == pin_version_soll` und beide `≠ ""`), liegt **keine** Abweichung im Sinne von Regel 1 vor: `abweichungen` bleibt leer, `status` darf `"zertifiziert"` bleiben; der Validator kann die Commit-Differenz als Warnung protokollieren. *Begründung (accounts-core-Sonderfall):* `0166805` (Ist) ist der Tagsatz-Commit und referenziert denselben Tag `v0.1.1` wie `9e0d0e9` (Soll) — Versionsgleichstand, keine fachliche Abweichung (vgl. §2-Kommentar zu `accounts-core`). Ohne diese Ausnahme würde Regel 1 auf `accounts-core` fälschlich anschlagen.

### (V4) env_schalter-Whitelist

Jeder Eintrag in `env_schalter[]` muss exakt einem der 7 Whitelist-Werte entsprechen, sonst Ablehnung: die 6 Env-Schalter `BACH_USE_EXTERNAL_SCHEDULER`, `BACH_USE_EXTERNAL_EXPLORER`, `BACH_USE_EXTERNAL_MEMORYHOOKS`, `BACH_USE_EXTERNAL_WORKFLOWHOOKS`, `BACH_USE_EXTERNAL_TRANSITSYNC`, `BACH_USE_EXTERNAL_AGENT_REGISTRY` sowie `NATIVE_FLAG` (der `--native`-Umschaltpfad der ellmos-tests). Leere Liste ist erlaubt.

### (V5) klassifikation-Enum

`klassifikation` muss einem der 5 Werte entsprechen: `core`, `modul`, `adapter`, `daten`, `legacy`. Jeder andere Wert → Ablehnung.

### (V6) Unbekannte Felder / Schemaverletzungen

Verletzungen der `required`-Liste → Ablehnung (Pflicht). Felder, die im §1-Schema nicht definiert sind, sollen nicht stillschweigend akzeptiert werden; die Implementierung **darf** hierzu `additionalProperties: false` ergänzen (optional, empfohlen).

### (V7) Fehlerrückgabe

Rückgabetyp `list[str]` (menschlesbare Fehlertexte). **Leere Liste = Instanz gültig.** Der Validator **wirft keine Exceptions** für Validierungsfehler (kein `raise`), sondern sammelt alle Befunde und gibt sie als Liste zurück. Vorbild-Konvention: `tools/agents_export.py:791` `validate_agent_document`; zweites Muster: `tools/skill_header_gen.py:406` `validate_header`.

### Wiederverwendung (keine Parallelinstallation)

Schema-Konvention und Feldlehren (draft-07, `$id`-Benennung, `name`-Pattern `^[a-z][a-z0-9-]*$`) sind aus `system/agents/ati/export/manifest.schema.json` (`$id: bach-agent-manifest-v1`) übernommen — **keine Parallelinstallation** einer zweiten Manifest-Tradition. Bestehende Manifestflächen im Checkout bleiben eigenständig gültig: `agents/ati/export/manifest.json`, `agents/ati/manifest.json`, `system/exports/translations/manifest.release.json`, `system/hub/_services/mail/providers.schema.json`. Ausdrücklich **nicht** wiederverwendbar: `fs_manifest.json` (physisch nicht im Checkout, nur CHANGELOG-Erwähnung) sowie `distribution_manifest`/`dist_file_versions` (DB-Tabellen von `tools/upgrade.py`, keine Datei-Artefakte). Es existiert kein `system/validators/`-Verzeichnis: Dieser Vertrag definiert **nur die Regeln**; die Validator-Implementierung ist **nicht** Teil von Task #1350.

### Blocker-Vermerk

Die Abweichung **B1** (`assistant-core`) ist auf diesem Host (mac-studio) **seit 2026-09-17 gelöst**: Ist-Checkout wurde per Reflog von `ccadcf9`/`v0.1.0` auf den Soll-Pin `444a1fff`/`v0.2.0` gezogen; HEAD und Testnachweis (`test_notify_via_assistant_core.py` 4/4 grün) am **2026-09-27** verifiziert (MRP Stufe 8, #1382). Verbleibend offen in **#1341**: hostübergreifender Abschluss bzw. der Abschluss-Vermerk des zuständigen Owners (Windows-Gegenprobe 2026-09-21 bereits 4/4 grün).
