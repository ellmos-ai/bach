# Paketgelieferte Systemvorlagen (Providerweg v1)

Stand: 2026-10-11, GithubBot-OCEAN P05 Schritt 3a + 3e (Mac-BACH #2060).

## Zweck und Grenzen

Ein installiertes Paket kann eine Agentenvorlage mitliefern. BACH übernimmt sie als
Systemvorlage (`agent_blueprints.is_template = 1`) neben den BACH-eigenen Seeds. Es gibt
keine zweite Vorlagen-Registry: Vorlagen bleiben in `agent_blueprints`, Normen in
`policy-registry`, Modellbindung in Slots/`model_sockets`. Nutzer-Saves mit `is_template`
bleiben verboten. Felder wie `provider` in einem Nutzer-Payload werden nicht gespeichert.

Nicht Teil dieses Schritts: `policy_refs`/`inherits_from` (3b), Laufbeleg-Erweiterung (3c),
Modellkette (3d), GUI-Tab „Installiert“ und Ocean-Adapter.

## Konfiguration

`BACH_TEMPLATE_PROVIDERS_FILE`, Standard `<BACH_LOCAL_DIR>/template_providers.json`
(hostlokal, nicht im Repo):

```json
{"providers": [{"id": "githubbot-core",
                "command": ["/pfad/zum/venv/bin/githubbot-core", "--json", "system-agent"]}]}
```

Unbekannte Schlüssel, doppelte IDs oder ein `command`, der kein String-Array ist, führen zu
`provider_config_invalid`. BACH führt den Befehl ohne Shell, ohne stdin, ohne Konsolenfenster
und mit einem Timeout von 20 s aus.

## Providerausgabe und Prüfung

Akzeptiert wird der Deskriptor direkt oder im Umschlag `<provider>.result/v1` mit
`ok: true` und leerem `errors`. Der Deskriptor:

| Feld | Regel |
|---|---|
| `schema` | genau `<provider>.system-agent/v1` |
| `id` | Vorlagen-ID (`[A-Za-z0-9][A-Za-z0-9._-]*`) |
| `version` | SemVer `X.Y.Z[-pre]`, gleich `capability.version` |
| `capability` | `package` = Provider-ID, `version`, optional `spi_version`, `source_commit` (40 hex, nur deklariert) |
| `blueprint` | nur Agent-Studio-Felder: name, title, kind, description, persona_role, persona_prompt, skills, animus_type, modus, contractus, governance; dieselbe Feldprüfung wie beim Nutzer-Save |
| `permissions` | erlaubt, wird weder gespeichert noch ausgegeben (Instanzkonfiguration) |
| `sha256` | sha256 über kanonisches JSON (`sort_keys`, Trenner `,`/`:`, UTF-8, `ensure_ascii=False`) von `{"schema", "id", "blueprint"}` |

Unbekannte Felder auf jeder Ebene werden abgewiesen (`unknown_fields`). Gründe für
`unavailable`: `provider_missing`, `provider_not_executable`, `provider_timeout`,
`provider_exit_nonzero`, `provider_output_too_large`, `provider_output_invalid_json`,
`provider_result_not_ok`, `schema_mismatch`, `version_invalid`, `hash_mismatch`,
`blueprint_invalid`.

## Speicherung, Status und Migration

Additive Spalten (Migration `052_blueprint_template_provider.py`, Helfer
`ensure_blueprint_schema`): `provider`, `provider_template_id`, `provider_version`,
`template_sha256`, `template_status`, `template_status_reason`. Eindeutiger Teilindex auf
(provider, provider_template_id, provider_version). Der Zeilenname ist
`<provider>.<id>.v<version>`. Gehört dieser Name schon einer Nutzerzeile, wird nichts
geschrieben (`name_conflict`).

`POST /api/agent-studio/template-providers/sync` (Gerätetoken) probt alle Provider:

- Erstregistrierung: neue Zeile, Status `available`.
- Gleiche Version und gleicher Hash: bestätigt.
- Gleiche Version mit anderem Hash: `unavailable` / `template_changed_without_version`, Inhalt bleibt.
- Andere Version: `migration_required`, Inhalt bleibt.
- Provider fehlt, schlägt fehl oder ist nicht mehr konfiguriert: `unavailable`.

`POST /api/agent-studio/template-providers/migrate` mit `provider`, `template_id`,
`to_version`, `expected_sha256` probt erneut und übernimmt nur genau dieses Angebot. Die alte
Zeile wird `superseded` und bleibt bestehen.

Materialisieren verlangt bei Providerzeilen `template_status = available`
(`template_unavailable` sonst). Bereits materialisierte Steckplätze ändern sich nicht und
bleiben startbar, auch nach einer Migration, weil sie auf ihre alte Zeile und Revision zeigen.

## Capability-Status (3e)

`/api/gui/capabilities` ergänzt je konfiguriertem Provider `modules["template-provider:<id>"]`
mit `adapter_registered: true`, `available` aus der letzten echten Probe (Exitcode, Schema,
Version und Hash; `null` vor der ersten Probe), `runtime_verified: false`, `reason_code`,
`observed_at` und `version`. `module_sources` erhält ID, Version, deklarierten
`source_commit` sowie die Vorlage (id, version, sha256). Weil die Paketprovenienz nicht
geprüft wird, bleibt `verified: false`; `descriptor_verified` weist die bestandene
Deskriptorprüfung aus. Die öffentliche GET-Route startet keine Prozesse und gibt keine Befehle
oder Pfade aus. Der Probenstand ist prozesslokal; nach einem Neustart gilt
`provider_not_probed` bis zum nächsten Sync. Der deklarierte „running“-Status des
Domain-Katalogs wird nicht als Probe verwendet.

## Bekannter Providerstand

githubbot-core v0.2.0 hasht seine ganze Paketdatei einschließlich `_meta.description`, die
in der Ausgabe fehlt. Der Hash ist damit nicht nachrechenbar, und BACH meldet
`hash_mismatch`. Mit einer auf `{schema, id, blueprint}` umgestellten Hash-Eingabe
registriert die echte CLI die Vorlage (gemessen mit einer lokal angepassten Scratch-Kopie,
sha256 `2e72c000…46c8`).
