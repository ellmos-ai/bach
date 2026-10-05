# BACH20-03 — Referenzieller Registry-ID-Vertrag

| Feld | Wert |
|---|---|
| dokument_id | BACH20-03-ID-VERTRAG-2026-09-29 |
| Version | 1.0 |
| Status | doku |
| Datum | 2026-09-29 |
| Task | #1351 |
| Vorgänger-Dokumente | BACH20-01-INVENTAR.md; BACH20-02-SYSTEMMANIFEST.md (dokument_id BACH20-02-SYSTEMMANIFEST-2026-09-27) |
| Änderungsregel | append-only (siehe §10) |

## §0 Zweck und Abschlussgrenze

Dieser Vertrag definiert den referenziellen Umgang mit Modul-, Skill-, Policy- und Learning-IDs in BACH: welche Namensräume und ID-Patterns gelten, wie eine Referenz formal aussieht und wie eine ID aufgelöst wird, ohne den referenzierten Inhalt zu kopieren.

Abschlussgrenze (Task #1351):

1. IDs sind auflösbar, ohne dass Inhalte der Quell-Registries kopiert werden (dokumentiert in §4 und Anhang A).
2. Der Vertrag ist dokumentiert (vorliegendes Dokument).

Offene Blocker (OC-B, BACH-AGENT-PID-01, probe_running()) sind in §7 benannt und bleiben bewusst offen; sie verhindern die Dokumentation des Vertrags nicht.

## §1 Grundsatz: Referenzierung statt Kopie

Wortlaut ../ROADMAP.md (~Z. 560–562):

> „Die Registry-Kopplung referenziert die Ergebnisse von T-20260728-04 (PolicyRegistry) und T-20260728-09 (Skill-/Learning-Control-Registry), statt deren Inhalte zu duplizieren."

Abgeleitete Grundsätze:

- **G1:** Eine Referenz besteht aus ID + Quell-Registry-Typ (§3), niemals aus einer Feldkopie des Zieleintrags.
- **G2:** Inhalte fremder Registries (Policy-, Skill-/Learning-Registry) werden nicht in andere Dokumente, Manifeste oder DB-Tabellen dupliziert, um sie „aufzulösen".
- **G3:** Auflösung erfolgt immer gegen die lebende Quell-Registry (sot_kennzeichnung=aktiv), nicht gegen Snapshots oder Kopien.
- **G4:** Pin-Felder (pin_commit/pin_version) sind Referenzattribute, keine Inhalte; ihre Mitführung verletzt G1/G2 nicht.

## §2 Namensräume und ID-Patterns

### §2.1 Modul-ID (Systemmanifest, bach-system-manifest-v1)

- ID = Feld `name`, Pattern `^[a-z][a-z0-9-]*$` (draft-07-Schema bach-system-manifest-v1, vgl. BACH20-02 §1).
- Pflichtfelder je Modul: `name`, `klassifikation`, `sot_kennzeichnung`, `status`.
- `klassifikation` (enum): `core` | `modul` | `adapter` | `daten` | `legacy`.
- `sot_kennzeichnung` (enum): `aktiv` = lebender Pfad; `fallback` = Rollback-Ziel (per Env-Schalter); `legacy` = Prä-Transfer-Altlast.
- Pin-Attribute gemäß V2: `pin_commit` ∈ `^[0-9a-f]{7,8}$` oder `""`; `pin_version` ∈ `^v\d+\.\d+\.\d+$` oder `""`; `null` ist verboten.
- Abhängigkeiten: `abhaengigkeiten[]` mit `{von, nach, art}`; Kanten sind `name → name`, d. h. Abhängigkeiten werden bereits im Manifest per Modul-ID referenziert, nicht kopiert.

### §2.2 Agent-/Dienst-ID (Export-Manifeste, bach-agent-manifest-v1)

- Schema-Beleg: `system/agents/ati/export/manifest.schema.json`.
- ID = Feld `name`, gleiches Pattern `^[a-z][a-z0-9-]*$`.
- `version` ∈ `^\d+\.\d+(\.\d+)?$`; `type` ∈ `agent` | `skill` | `service`; `includes.core` ist Pflicht.

### §2.3 Skill-ID (Skill-Registry)

- Quelle: `skills.json` (Skill-Registry); Discovery/Verifikation über die Tool-/Skill-Registry-Auto-Discovery in `system/core/registry.py`.
- ID = Registry-Schlüssel des Skill-Eintrags in der Skill-Registry.
- Ein Skill kann zusätzlich einen Export-Eintrag nach §2.2 besitzen; beide Namensräume bleiben getrennt und werden jeweils mit ihrem Quell-Registry-Typ referenziert (§3).

### §2.4 Policy-ID (reserviert; T-20260728-04)

- Namensraum reserviert für die zukünftige PolicyRegistry (T-20260728-04).
- Zum Vertragszeitpunkt existiert KEIN Code-Modul im Repo (Beleglage: nur ../ROADMAP.md sowie bach.db-Notizen).
- Referenzen mit Quell-Registry-Typ `policy-registry` sind zulässig, bis zum Vorliegen der Registry aber nicht dereferenzierbar (§4.4) — ausdrücklich vertragskonform, kein Fehler.

### §2.5 Learning-ID (reserviert; T-20260728-09)

- Namensraum reserviert für die Skill-/Learning-Control-Registry (T-20260728-09).
- Beleglage wie §2.4: kein Code-Modul im Repo; nur ROADMAP- und bach.db-Notizen.
- Referenzen mit Quell-Registry-Typ `learning-registry` zulässig, bis Registry vorliegt nicht dereferenzierbar.

## §3 Referenzformat

Eine Registry-Referenz ist das minimale Tupel:

```
(registry_typ, id)
```

Zulässige `registry_typ`-Werte:

| registry_typ | Auflösungsquelle | Status |
|---|---|---|
| `system-manifest` | Systemmanifest-Eintrag (BACH20-02, sot_kennzeichnung) | aktiv |
| `agent-manifest` | Export-Manifest nach bach-agent-manifest-v1 | aktiv |
| `skill-registry` | skills.json / core/registry.py-Discovery | aktiv |
| `policy-registry` | PolicyRegistry (T-20260728-04) | reserviert |
| `learning-registry` | Skill-/Learning-Control-Registry (T-20260728-09) | reserviert |

Optionaler Pin-Kontext bei Modul-Referenzen: `pin_commit` / `pin_version` gemäß §2.1 (V2-Patterns).

Verboten: Felder des Zieleintrags in den referenzierenden Kontext zu kopieren (G1/G2). Wer Inhalte der Zielregistry benötigt, löst die Referenz zur Laufzeit auf (§4).

## §4 Auflösungsregeln (IDs auflösbar ohne Kopie)

- **§4.1 Modul-ID** → Eintrag im lebenden Systemmanifestpfad (sot_kennzeichnung=`aktiv`). `fallback`-/`legacy`-Einträge werden über ihren `env_schalter` bzw. ihre Kennzeichnung aufgelöst, niemals über Kopien des aktiv-Eintrags.
- **§4.2 Agent-/Dienst-ID** → Export-Manifest-Instanzen nach bach-agent-manifest-v1 (`agents/*/export/`).
- **§4.3 Skill-ID** → `skills.json`; Discovery/Verifikation via `system/core/registry.py`.
- **§4.4 Reservierte IDs** (`policy-registry`, `learning-registry`) → Dereferenzierung erst nach Bereitstellung durch T-20260728-04 / T-20260728-09; bis dahin referenzierbar, nicht auflösbar.
- **§4.5 Auflösbarkeitskriterium:** Eine Referenz gilt als „auflösbar ohne Kopie", wenn Quell-Registry-Typ + ID genügen, den Zieleintrag in der lebenden Registry eindeutig zu finden. Snapshot-/Exportkopien dürfen höchstens Cache sein, nie Quelle.

## §5 Validator-Vertrag (Wiederverwendung per Referenz)

Der Validatorvertrag V1–V7 steht in BACH20-02-SYSTEMMANIFEST §3 und wird von diesem Vertrag referenziert, nicht kopiert. Für ID-Felder dieses Vertrags bindend:

- **V1:** draft-07-jsonschema-Validierung.
- **V2:** Pin-Formate `^[0-9a-f]{7,8}$` bzw. `^v\d+\.\d+\.\d+$` oder `""`; `null` verboten.
- **V3:** Ist/Soll-Abgleich mit Abweichungspflicht + Taggleich-Ausnahme (gilt für manifestierte Referenzlisten).
- **V4:** env_schalter-Whitelist (7 Werte): `BACH_USE_EXTERNAL_SCHEDULER`, `BACH_USE_EXTERNAL_EXPLORER`, `BACH_USE_EXTERNAL_MEMORYHOOKS`, `BACH_USE_EXTERNAL_WORKFLOWHOOKS`, `BACH_USE_EXTERNAL_TRANSITSYNC`, `BACH_USE_EXTERNAL_AGENT_REGISTRY`, `NATIVE_FLAG`.
- **V5:** `klassifikation`-Enum (§2.1).
- **V7:** Rückgabe `list[str]`; leere Liste = gültig; keine Exceptions (Vorbilder `tools/agents_export.py:791`, `tools/skill_header_gen.py:406`).

## §6 Kopplung an T-20260728-04 und T-20260728-09 (per Referenz)

- Dieser Vertrag kopplet an die Ergebnisse von T-20260728-04 (PolicyRegistry) und T-20260728-09 (Skill-/Learning-Control-Registry) per Referenz (ROADMAP-Wortlaut §1).
- Konkret: §2.4/§2.5 reservieren die Namensräume und Quell-Registry-Typen; die tatsächlichen Registry-Inhalte werden von den genannten T-Tasks geliefert und hier NICHT dupliziert.
- Umgekehrt gilt: Sobald die Registries vorliegen, referenzieren sie IDs nach §3 dieses Vertrags; eine Rück-Kopie ihrer Inhalte in BACH20-Dokumente findet nicht statt.

## §7 Nicht-grün-Fall OC-B (agent launcher)

OC-B ist der von diesem Vertrag abgedeckte, ausdrücklich NICHT grüne Fall:

- Quelle: `OC-B-OWNED-SPAWN-STOP-GATE.md` (2026-09-15). Fehlerpfad `agent_launcher.py::_start_agent` (Popen, danach create_time, PID-Datei null möglich); die 4 Invarianten sind dort dokumentiert und gelten hier per Referenz.
- Beleglage: nur isolierte Tests; KEIN echter Agent-Lifecycle belegt; kein Release-Gate; NICHT Teil der 8er-Zertifizierung.
- Aktivierung nur als Opt-in über env_schalter `BACH_USE_EXTERNAL_AGENT_REGISTRY` (V4-Whitelist); rollback `""` (vgl. Beispiel-Komponente in BACH20-02 §2, status doku).
- `docs/BACH-AGENT-PID-01.md` existiert NICHT (nur historische bach.db-Notiz sowie Referenz in MODULRUECKTRANSFER-PLAN.md:46); das PID-Doku-Defizit bleibt offen.
- `probe_running()`: per Taskbeschreibung #1351 vorgesehen; Code-Beleg im Repo ausstehend (kein Treffer); externer PR `ellmos-ai/agent-launcher#2`.
- Konsequenz: OC-B-bezogene IDs dürfen referenziert werden, müssen aber als nicht-grün gekennzeichnet bleiben; aus einer erfolgreichen Referenzauflösung darf kein Zertifizierungs- oder Release-Status abgeleitet werden.

## §8 Namenskollision BACH20-03-KANDIDATENREGISTER

Im selben Verzeichnis existiert `BACH20-03-KANDIDATENREGISTER.md`. Dieses Dokument gehört zu den Folgetasks #1352/#1427 und ist vom vorliegenden ID-VERTRAG strikt zu unterscheiden: keine Umwidmung, keine gegenseitige Inhaltsübernahme. Die BACH20-03-Präfix-Kollision ist bekannt und wird mit diesem Vermerk dokumentiert, nicht aufgelöst.

## §9 IDs für Folgetasks

Die hier definierten IDs und Referenztypen stehen den Folgetasks #1352 und #1427 zur Verfügung. Diese Tasks nutzen das Referenzformat nach §3; Inhalte dieses Vertrags oder der Quell-Registries werden nicht in deren Artefakte kopiert. (Verfügbarkeits-Hinweis an #1352/#1427 erfolgt als Kommentar, ohne deren Status zu ändern.)

## §10 Änderungsregeln (append-only)

- Dieses Dokument ist append-only: Nachträge werden unten angehängt; bestehende §§ werden nicht umgeschrieben.
- ID-Patterns und Referenzformat sind stabil; Änderungen nur als neue Vertragsversion (neue dokument_id) mit Rückwärtskompatibilitäts-Nachweis.
- Reservierte Namensräume (§2.4/§2.5) werden ausschließlich durch T-20260728-04 / T-20260728-09 aktiviert.

## Anhang A: Auflösbarkeits-Matrix (Abschlussnachweis)

| ID-Typ | registry_typ | Auflösung ohne Kopie |
|---|---|---|
| Modul | `system-manifest` | ja — §4.1 |
| Agent/Dienst | `agent-manifest` | ja — §4.2 |
| Skill | `skill-registry` | ja — §4.3 |
| Policy | `policy-registry` | reserviert — §4.4 (T-20260728-04) |
| Learning | `learning-registry` | reserviert — §4.4 (T-20260728-09) |
| OC-B-Komponenten | `system-manifest` (env_schalter-Opt-in) | ja, aber nicht-grün — §7 |

Ergebnis: Abschlussgrenze #1351 erreicht — das Referenzmodell ist dokumentiert; alle aktiven ID-Typen sind ohne Kopie auflösbar; reservierte Namensräume und die OC-B-Defizite sind benannt und bleiben offen.
