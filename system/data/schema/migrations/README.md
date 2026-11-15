# DB-Migrationsstufen — Ticket-/Planabgleich 25.10.2026 (Task #3722)

Ticket **T-20260920-823767362**, Aufgabe laut Ticket-/Planabgleich 25.10.2026 (Tasktext #2461).
Suchstand: 25.10.2026 (Worktree task-3722, Haupt-`CHANGELOG.md`, `system/CHANGELOG.md`,
`system/ROADMAP.md`, `docs/` ohne weitere `T-20260920`-Treffer).

## Stufenbild

| Stufe | Migration(en) | Beleg |
| --- | --- | --- |
| S1/S2/S2a | `043_memory_union.py` | Header Zeile 20: `STATUS: aktiv (S2 …)` mit T-20260920-823767362; Vertragsordner `system/data/schema/memory_union/` |
| S3 | `044_strategy_triggers.sql`, `045_context_triggers_sichtung.sql`, `046_tool_warn_triggers.sql`, `047_between_triggers.sql` | alle vier Header `(S3 von T-20260920-823767362)` |
| S4 | **keine Migration** | nur PR #178 „S4 Policy & neutrale Context-Hints“ (Haupt-`CHANGELOG.md`, PR-Zeile) |
| S6 | **kein Migrationsanteil gefunden** | weder `system/CHANGELOG.md` (Suche `S[46]`: 0 Treffer) noch Header von `048`–`054`, `migrate_unify_distribution.py`, ROADMAP/docs; im Ticket-/Planabgleich nachziehen, falls S6 migrationsrelevant ist |
| S7 | **keine Migration** | nur PR #176 „lokale S7-Fencing-Zustände“ (Haupt-`CHANGELOG.md`) |

Damit sind die Stufen S4 und S7 rein im Code (PRs #178/#176) gelandet und brauchen keinen
Migrationsnachsatz; S6 ist im Migrationsschatz nicht belegt.

## Schema-Vertrag memory_union (S1/S2)

- `system/ARCHITECTURE.md` (USMC-Abschnitt): USMC-Bridge entfernt; BACH + USMC schreiben
  nach dem gemeinsamen Vertrag `system/data/schema/memory_union/` (T-20260920-823767362).
- `043_memory_union.py`: bucht den Vertragsstand; danach bucht
  „init_schema + baseline_migrations … nur“ den Inkrementstand (Runner-Buchung, Zeile 23).
- CLI-Pfad: `system/bach.py` `_cli_memory_hook` (S3-Seam für memoryhooker, fail-soft;
  Rueckweg `BACH_LEGACY_INJECTORS` bzw. `BACH_USE_EXTERNAL_MEMORYHOOKS=0`).

## S3-Inhalt (Trigger-Migrationen 044–047)

- `044`: Strategy-Injektor als Trigger-Zeilen in `context_triggers` (`source='strategy'`),
  `INSERT OR IGNORE` (idempotent, BACH-SEED).
- `045`: Sichtung/Buchung der bestehenden Laptop-Zeilen (292 aktive Zeilen Stand 2026-09-26,
  nichts gelöscht), Schalter `BACH_CONTEXT_TRIGGERS_DB=1`.
- `046`: `ToolInjector.check_before_create` als `context_triggers`-Zeilen (`source='tool_warn'`).
- `047`: Between-Trigger (analoge idempotente Kopfzeile, `(S3 von T-20260920-823767362)`).

## Prüfverfahren (reproduzierbar, Stand 15.11.2026)

1. Stufenmarker in Migrationsköpfen:
   `grep -rn "S[0-9] von T-20260920-823767362" system/data/schema/migrations/`
   → nur `044`–`047` (S3) sowie `043_memory_union.py` (S2-Statuszeile).
2. Stufenreferenzen in Doku/CI:
   `grep -rn "S[0-9]" CHANGELOG.md ROADMAP.md system/CHANGELOG.md system/ROADMAP.md .github/workflows/tests.yml`
   → `CHANGELOG.md:38` (S2), `:63` (S1), `:64` (S2a), `:92` (PR #176 S7, PR #178 S4),
   `ROADMAP.md:155` (dito), `.github/workflows/tests.yml:3` („S2/S3 von T-20260920-823767362“).
3. Abgleich Ticket-/Planreferenzen: `grep -rn "T-20260920-823767362" .` → 4 Treffer (CI-Kommentar,
   `CHANGELOG.md` ×2, `043`/`044`-Headerbereich). Kein Treffer nennt S4/S6/S7 als Migrationsstufe.
4. Volltextsuche bewusst nur in `system/`, `docs/`, `*.md`: eine Repo-weite Suche bricht in
   Binärassets (`assets/*.png`) ab und liefert dort keine Stufenmarker.

## Entscheidung

Es werden **keine** neuen Migrationsdateien angelegt: S3 ist vollständig vorhanden, S4 und S7 sind
Code-/Policy-Änderungen ohne Schemafolge, und für S6 existiert keine Spezifikation, die eine
Migration definieren würde. Diese Datei dokumentiert den Ist-Stand und die Belegstellen; eine
Erweiterung erfolgt erst, wenn der Ticket-/Planabgleich einen konkreten Schemaanteil für S4/S6/S7
benennt.

## Nicht dem Planabgleich zugeordnet

Migrationen mit eigenen Tickets/Namensräumen, keine S-Stufenmarker:
`048_harden_session_provenance.py`, `049_migration_002_dist_type_catchup.py`,
`050_task_model_slot_routing.py` bzw. `050_task_slot_routing.py`, `051_task_model_binding.sql`,
`052_blueprint_template_provider.py`, `053_resource_leases.py` (Polarstern, BACH #2121),
`054_task_result_service_scopes.py`, `migrate_unify_distribution.py` (T-20260926-357988320 /
T-20260926-598278998, bach#93), `migrate_prompts.py`, `migration_002_user_dist_type.sql`
und die Namespacedateien `doc_*`, `fin_*`, `steuer_*`.

Diese Datei ist reine Doku (`.md`) und wird vom Migrations-Runner nicht gebucht.
