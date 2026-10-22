# BACH20-06 — Phase B: Schema-Erweiterung (Lizenz, Plattformen, Aktivierungsmodus, Provenienz)

> **Dokument-ID:** BACH20-06-PHASE-B-SCHEMA-ERWEITERUNG-2026-09-30
> **Quellen:** `LICENSE` (Repo-Root), `THIRD_PARTY_LICENSES.md` (192 Z., auto-generiert SQ034), BACH20-02-SYSTEMMANIFEST (Schema bach-system-manifest-v1, Validator V1–V7), BACH20-01 §4, ROADMAP BACH20-Kette
> **Task:** #1427 (BACH-2.0-Rückfluss, Phase B)
> **Bezug:** Erweiterungsvorschlag zu bach-system-manifest-v1; rückwärtskompatibel (nur optionale Felder + neue Validator-Regeln).

---

## 1. Lizenz-Befund (Ist-Stand, geprüft am Checkout task-1427)

| Befund | Stelle | Ergebnis |
|---|---|---|
| Projekt-Lizenz | `LICENSE` | **MIT**, © 2026 Lukas Geiger |
| Drittlizenzen | `THIRD_PARTY_LICENSES.md` (192 Zeilen, auto-generiert, SQ034) | Core-Dependencies aus **Apache-2.0 / BSD / MIT**; **PyMuPDF nur optional**; **keine AGPL-Infizierung** festgestellt |
| Konsequenz | Manifest | Neues Pflicht-fähiges Feld `lizenz` (Default `"MIT"` für monorepo-interne Einträge); Drittmodule verweisen auf `THIRD_PARTY_LICENSES.md` |

## 2. Plattformen

Ist-Stand: Entwicklung und Zertifizierung laufen auf **macOS** (mac-studio / WORKSTATION-LG);
Windows-Gegenproben sind teils offen (BACH20-01 §4).

**Vorschlag:** Feld `plattformen: ["macos"]` (Enum: `macos`, `windows`, `linux`) als
**verifizierte** Plattformliste — nicht als Lauffähigkeitsbehauptung. Erweiterung auf
`windows` erst nach Abschluss der offenen Gegenproben (#1340/#1341-Umfeld).

## 3. Aktivierungsmodus (neues Enum-Feld)

Befund: Die SoT-Umschaltung der 8 TRANSFER-Module läuft über Env-Schalter
(`BACH_USE_EXTERNAL_*`, 6-fach-Whitelist) mit internem Legacy-Fallback als Rollback-Ziel.
Ein deklarierter Betriebsmodus pro Manifest-Eintrag fehlt bisher.

**Vorschlag:** optionales Feld `aktivierungsmodus` mit Enum:

| Wert | Bedeutung |
|---|---|
| `read_only` | Eintrag wird nur gelesen/auditiert, keine Schreibwirkung (z. B. memoryhooker gegen BACH_DB) |
| `shadow` | Externer Pfad läuft mit, Interner bleibt führend (Schattenbetrieb/Vergleich) |
| `staged` | Externer Pfad scharf hinter Gate/Env-Schalter, Fallback jederzeit aktiv (Zustand der 6 Env-Schalter) |
| `aktiv` | Eintrag ist führender SoT-Pfad ohne Umschaltgate (Default für monorepo-interne core-Einträge) |

Default: `aktiv` (rückwärtskompatibel zu v1-Dokumenten ohne das Feld).
Ein `aktivierungsmodus` ungleich `aktiv` **erfordert** einen whitelisted `env_schalter`
(neue Validator-Regel V8) bzw. bei `read_only` eine Begründungsnotiz.

## 4. Provenienz (neues Feld)

Befund: `system/core/provenance.py` existiert, enthält aber Privacy/People-Heuristiken und
**kein** Schema-Provenienz-Konzept für Manifest-Einträge. Herkunft eines Eintrags
(Monorepo vs. TRANSFER-Modul vs. Inhaltsdaten) ist derzeit nur implizit über `pin`.

**Vorschlag:** optionales Feld `provenienz`:

```yaml
provenienz:
  herkunft: monorepo | transfer:<repo-name> | drittanbieter
  commit: "<7-8-hex>"      # optional; Pin-Regex ^[0-9a-f]{7,8}$ oder ""
  datum: "JJJJ-MM-TT"      # Aufnahmedatum in das Manifest
```

- `herkunft: transfer:<repo>` **erfordert** gleichzeitig `pin` oder `provenienz.commit`
  (Ist/Soll-Abgleich V3 bleibt maßgeblich; neue Regel V9).
- Monorepo-interne Einträge (BACH20-05, 13 Restflächen): `herkunft: monorepo`,
  `commit: ""`, `datum` = Aufnahmedatum.

## 5. Schema- und Validator-Delta (v1 → v1.1, rückwärtskompatibel)

| Änderung | Typ | Regel |
|---|---|---|
| `lizenz` | optional, Default `"MIT"` | V10: Wert `"MIT"` oder Verweis-String auf THIRD_PARTY_LICENSES-Eintrag |
| `plattformen` | optional, Default `["macos"]` | V11: Enum-Teilmenge {macos, windows, linux}, nicht leer |
| `aktivierungsmodus` | optional, Default `aktiv` | V8: Enum {read_only, shadow, staged, aktiv}; `shadow`/`staged` ⇒ `env_schalter` aus Whitelist; `read_only` ⇒ whitelisted `env_schalter` oder Begründungsnotiz gemäß §3 |
| `provenienz` | optional | V9: `herkunft`-Enum; `commit` gegen Pin-Regex ^[0-9a-f]{7,8}$\|^$ |

Alle vier Felder sind optional → bestehende v1-Manifeste bleiben valide (V1–V7 unverändert);
`validate_system_manifest(doc) -> list[str]` gibt zusätzlich V8–V11-Verstöße zurück.
Schema-Bezeichner: `bach-system-manifest-v1.1`.

## 6. Offene Verweise

| Punkt | Stand | Task |
|---|---|---|
| Validator-Implementierung V8–V11 | Vorschlag, noch nicht codiert | Folgetask (BACH20-Kette) |
| Windows-Plattform-Aufnahme | offene Gegenproben | #1340/#1341-Umfeld |
| SoT-Umschaltgate-Stufenplanung | Bezugsrahmen für `aktivierungsmodus` | BACH20-08 (Roadmap) |

---

*Erstellt: 2026-09-30 · Quellenstand: Checkout task-1427, LICENSE, THIRD_PARTY_LICENSES.md, BACH20-01/02 · Abschlussgrenze: verbindlicher Erweiterungsvorschlag Lizenz/Plattformen/Aktivierungsmodus/Provenienz mit Validator-Delta — erreicht.*
