# Trithon Phase 2: Review-, CI- und Release-Gates

Referenz: Trithon-Kette, Task #1381 (Phase 2: unabhängiges Review, CI, Release-Gates definieren/umsetzen)
Repo: `ellmos-ai/bach` · Default-Branch: `main` · HEAD: `29a6457`
Stand: 2026-09-27

> Hinweis zur Quelle: Der Trithon-Phasenplan (`TRITHON-MUSCHELGRUND-UMSETZUNGSPLAN-2026-09-16`) ist lokal nicht auffindbar (nur Verweis in `data/slots_config.json`; kein `trithon-*`-Branch; `sync_mirror` nicht verfügbar). Diese Gates wurden daher gegen das BACH-Repo definiert, in dem die Trithon-Umsetzung aktuell faktisch stattfindet.

---

## Gate 1: Unabhängiges Review

Prinzip: **PR-basiert** — kein direkter Push auf `main` (Präzedenz: #134–#137 wurden als PRs gemergt).

Vor jedem Merge prüfen (read-only):

```bash
gh pr view <n> --json mergeable,statusCheckRollup
```

Kriterien:

- `mergeable` == `MERGEABLE` (keine Konflikte)
- `statusCheckRollup`: **alle** Checks `SUCCESS` (tests + CodeQL)

Review-Präzedenzfälle (Sicherheits-Commits auf `main`, jeweils per PR gemergt):

| Commit | PR | Inhalt |
|---|---|---|
| `0bec4c8` | #137 | Shell-Härtung: `bach_command`-Allowlist, Telegram-Owner fail-closed |
| `3d25a00` | #134 | Seal/Release-Pfad-Absicherung |
| `83b745c` | #135 | Windows-Timeout-Kill |
| `6cc3503` | #136 | Härtung Folgecommit |

Externer Review-Punkt: **OCEAN-CI `T-20260913-283190451`** (Commit `8f47ad2` nachzertifiziert) ist als **WAITING** extern markiert — kein lokales Artefakt. Sobald verfügbar, als zusätzliche Review-Referenz für dieses Gate heranziehen.

**Gate-Regel:** Kein Merge ohne aktives Review am PR (mindestens: Mergeable-Status + Check-Rollup durch zweite Instanz geprüft).

## Gate 2: CI

Workflows im Repo (remote, lokal existiert kein `.github/`):

| Workflow | ID | Zweck |
|---|---|---|
| tests | 367915569 | pytest-Suite |
| CodeQL | 301777174 | Statische Analyse |
| Auto-assign PRs / Sync Labels / Stale Issues & PRs / Welcome New Contributors / Dependabot Updates / Dependency Graph | — | Repo-Hygiene |

**tests-Workflow (Detail):**

- Trigger: `pull_request` + `push` auf `main`
- Runner: `ubuntu-latest`, Python 3.12, `fetch-depth: 0`
- `conftest.py` isoliert `BACH_DB` ins Temp-Verzeichnis → läuft ohne Live-DB/Netz
- Installiert Requirements minus private Pakete (`assistant-core`, `accounts-core`), plus `doc-services` (public seit 2026-09-26)
- Läuft `pytest` auf explizite Liste von ~22 Tests in `system/tests/`, u. a.:
  `test_safe_exec`, `test_safe_shell_args`, `test_chat_runtime_security`, `test_telegram_owner_check`, `test_sandbox_handler`, `test_core`, `test_doc_extract_seam`

**main-Status:** letzte 4 Push-Runs (tests + CodeQL) = `success` (zuletzt Run `36315420927`, 2026-09-27T11:20).

**Bekannte Probleme (offene PRs, Stand 2026-09-27):**

- **#125** `ci: Testabdeckung 16→222` — `CONFLICTING`, pytest `FAILURE` (CodeQL `SUCCESS`). Vor Merge: Konflikt lösen + pytest-Fehler beheben.
- **#138** `fix(tasks): fail-closed deps` — `MERGEABLE`, alle Checks `SUCCESS` → mergebereit.
- **#16** `ellmos-chat wave2` — offen.

**Gate-Regel:** Kein Merge, solange nicht `tests` **und** `CodeQL` auf dem PR-Head `SUCCESS` sind.

## Gate 3: Release-Gates

Pipeline: **Tag + Push → CI grün → manuelle Release-Verifikation (`seal_release_check`) → Release.**

Werkzeug: `tests/seal_release_check.py` (SQ021 + SQ027)

- **Kein** pytest-CI-Test — bewusst manueller Schritt nach einem Release-Lauf
- Voraussetzung: befüllte Release-DB (≥ 200 CORE-Einträge in `distribution_manifest` / `dist_file_versions`)
- Öffnet `BACH_DB` **read-only** (`mode=ro`; Absicherung `T-20260927-807838815`, Commit `3d25a00`), kanonischer Pfad via `hub/bach_paths.BACH_DB`
- 4 Prüfungen: `kernel_scope`, `hash_calculation`, `file_versions_populated`, `startup_check_sampling`
- Exit-Code: `0` = bestanden, `1` = nicht bestanden

Ablauf:

```bash
git tag vX.Y.Z && git push origin vX.Y.Z
# 1. Warten, bis tests + CodeQL auf dem getaggten Commit SUCCESS sind
gh run watch
# 2. Auf einem System mit befüllter BACH_DB:
python tests/seal_release_check.py   # muss exit 0 liefern
```

**Gate-Regeln:**

- Kein Release ohne `seal_release_check` Exit `0`
- Kein Release ohne grüne CI auf dem getaggten Commit
- Kein Merge ohne SUCCESS-Checks (siehe Gate 2)

---

Erstellt im Rahmen von Task #1381 (Trithon Phase 2), 2026-09-27.
