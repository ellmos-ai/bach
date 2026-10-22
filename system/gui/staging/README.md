# Staging: Governance-API-Client für ellmos-system-gui

Dieser Ordner ist die **Staging-Fassung** des Moduls `src/lib/governance-client.mjs` für das
externe Repository [ellmos-ai/ellmos-system-gui](https://github.com/ellmos-ai/ellmos-system-gui).
Bis zur Überführung per Pull Request liegt der Code hier vor; nach Merge und Release wird der
GUI-Kit-Pin in `system/gui/kit_manifest.json` aktualisiert und dieses Staging obsolet.

## Dateien

| Datei | Inhalt |
| --- | --- |
| `governance-client.mjs` | API-Client-Modul (reines ESM, keine DOM-Abhängigkeit außer `window.BOARD_CONFIG` und `localStorage`) |
| `governance-client.test.mjs` | Testsuite (12 Tests, `node:test`, Fetch-Mock) |

## Funktionen

| Export | Methode + Pfad | Verhalten |
| --- | --- | --- |
| `getPolicyRegistry({scope, consumer, query, kind}, fetcher?)` | GET `/api/governance/policy-registry` | Validiert `scope`/`consumer` (≤ 256), `query` (≤ 512) und `kind` (`policy\|rule\|decision\|evidence\|decision-candidate`); Query wird mit `encodeURIComponent` kodiert. Fehler: „Der Abfrageparameter ist zu lang.“ bzw. „Die Art muss policy, rule, decision, evidence oder decision-candidate sein.“ |
| `getEffectivePolicy({scope, consumer}, fetcher?)` | GET `/api/governance/effective-policy` | `scope` ist Pflicht: „Für die wirksame Richtlinie ist ein Geltungsbereich erforderlich.“ |
| `getCapabilities(fetcher?)` | GET `/api/gui/capabilities` | Liefert `{data, kit_status, policyRegistry, registrySource, matches, summary}` (siehe unten). |
| `requestJson(url, options?, fetcher?)` | — | Low-Level-Helfer; Fehlerverhalten: nicht lesbares JSON → „Die Quelle liefert keine lesbare Antwort.“, 409 → „Die Quelle wurde inzwischen geändert. Lade die aktuelle Fassung vor dem Speichern.“, 503 → „Richtlinien-Anbieter ist gerade nicht erreichbar.“ (ggf. mit `detail`/`public_unavailable_reason`), sonst `data.detail` oder „Die Anfrage konnte nicht bestätigt werden.“; `error.status` wird gesetzt. |
| `baseUrl()`, `deviceHeaders()`, `_headers()` | — | Basis-URL aus `window.BOARD_CONFIG.apiBase`; Auth via `BOARD_CONFIG.token`, `tokenStorageKey` oder Device-Token aus `localStorage` (`bach_device_token`). |

## Erwartete Pins (Konstanten im Modul)

| Konstante | Wert | Bedeutung |
| --- | --- | --- |
| `EXPECTED_DIST_VERSION` | `0.2.24` | Erwartete GUI-Distribution-Version |
| `EXPECTED_DIST_COMMIT` | `ff13cccde77a997ab4d0a0173db43ff88ee3c2be` | Erwarteter Source-Commit des GUI-Kits |
| `EXPECTED_REGISTRY_VERSION` | `0.2.4` | Erwartete Version des Richtlinien-Registry |
| `EXPECTED_REGISTRY_COMMIT_PREFIX` | `2c4896b70cb3` | Erwarteter Commit-Präfix des Registry |

## getCapabilities-Rückgabe

```
{
  data,           // Antworten der Capabilities-Route (defensiv geprüft, sonst null)
  kit_status,     // Status zum GUI-Kit
  policyRegistry, // Registry-Status aus der Antwort
  registrySource, // Provider-Information (version/source_commit, offen gehalten)
  matches: {      // Abgleich gegen die Pins (true/false je Prüfung)
    dist_commit_ok, dist_version_ok, registry_registered,
    registry_available, registry_version_ok, registry_commit_ok
  },
  summary: { ok, passed, total }  // ok = alle Prüfungen bestanden
}
```

## Tests

Ausführen mit:

```
node --test governance-client.test.mjs
```

Die Suite enthält 12 Tests (Query-Kodierung, Parameter-Validierung ohne Fetch, Fehlermeldungen
409/503/404/400, unlesbares JSON, `matches`/`summary` für positive, negative und `null`-Payloads)
und nutzt nur einen Fetch-Mock, kein DOM.

**Testlauf-Status (Stand dieses Staging):** Der Testlauf konnte in der BACH-Worktree-Umgebung
*bisher nicht bestätigt* werden (`execute_command` lieferte keine bestätigte Ausführung).
Die Tests sind deshalb als **nicht ausgeführt** zu behandeln; der Lauf ist erste Pflicht der
Überführung (siehe Teilaufgabe).

## Überführung ins externe Repo (nicht Teil des Stagings)

1. Clone `ellmos-ai/ellmos-system-gui` am Pin **0.2.24** (`ff13cccde77a997ab4d0a0173db43ff88ee3c2be`).
2. `governance-client.mjs` nach `src/lib/governance-client.mjs` übernehmen.
3. `governance-client.test.mjs` nach `tests/` übernehmen und den Import-Pfad auf das neue
   Modul anpassen.
4. Branch anlegen, Tests (`node --test`) ausführen, Commit mit Secrets-Scan und
   `git diff --check`, Pull Request öffnen.
5. Review/Merge und Release abwarten.
6. Neu-Pin in `system/gui/kit_manifest.json` des BACH-Repo setzen: neue `version` und
   `source_commit` des gemergten Releases.