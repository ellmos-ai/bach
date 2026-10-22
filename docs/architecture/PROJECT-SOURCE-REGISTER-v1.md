# PROJECT-SOURCE-REGISTER-v1

Ergänzung zu TASKDB-SALT-LEASE-VERTRAG-v1.md, Task #2358.

## Kontext (§5.1)

Dieser Vertrag konkretisiert §5.1 des TASKDB-SALT-LEASE-VERTRAG-v1.md:
Jeder Task bindet seine Projektquelle nativ über einen Registereintrag
(`project_source_register`) und trägt den gebundenen `repo_key` in der
Task-DB (`tasks.repo_key`). Worktree-Pfad und Lease-Pfad lösen die Quelle
ausschließlich über das Register auf; lose Konventionen oder implizite
Live-Pfade entfallen.

## Register-Modul `hub/_services/project_source_register.py`

SQLite-Tabelle `project_source_register`:

| Spalte | Bedeutung |
|---|---|
| `repo_key` | Primärschlüssel, `^[a-z0-9][a-z0-9-]{0,63}$` |
| `checkout_path` | absoluter, realer Pfad des Projekt-Checkouts |
| `origin` | https-Origin des Checkouts |
| `approved_ref` | freigegebener Ref (z. B. 40-Zeichen-SHA) |
| `worktrees_root` | Wurzel für Worker-Worktrees |
| `revision` | INT, Startwert 1, je Registereintrag-Pflege +1 |
| `updated_at` / `updated_by` | Audit |

Guard: Registerpflege ist ausschließlich dem Actor `user` erlaubt
(`_require_user`); jeder andere Actor erhält
`RuntimeError: Registerpflege ist ausschließlich dem Actor 'user' erlaubt`.

fail-closed: `resolve_repo` klont oder fetched niemals; jede Abweichung
schlägt mit `RuntimeError` fehl.

Validierungen:

- `validate_repo_key`: Pattern `^[a-z0-9][a-z0-9-]{0,63}$`
- `validate_origin`: nur `https`, kein userinfo (`@`), keine Query, kein Fragment
- `validate_checkout_path`: absolut, kein Symlink, existierendes Verzeichnis,
  `.git` vorhanden und kein Symlink

Signaturen:

- `add_entry(*, actor, repo_key, checkout_path, origin=None, approved_ref=None, worktrees_root=None) -> dict`
  — INSERT mit `revision=1`; Doppel-Key → `RuntimeError: repo_key {r!r} ist bereits registriert`
- `update_entry(*, actor, repo_key, checkout_path, origin=None, approved_ref=None, worktrees_root=None) -> dict`
  — `revision+1`; `rowcount != 1` → RuntimeError
- `remove_entry(*, actor, repo_key) -> None` — `rowcount != 1` → RuntimeError
- `read_entry(repo_key) -> dict` — alle Spalten inklusive `revision`
- `register_revision(repo_key) -> int`
- `resolve_repo(repo_key, expected_revision, expected_origin=None) -> Path`

`resolve_repo` prüft in dieser Reihenfolge:

1. `expected_revision` erforderlich (None → RuntimeError)
2. Register-Revision: `Register-Revision divergiert: erwartet X, aktuell Y`
3. `validate_checkout_path` des registrierten `checkout_path`
4. live Origin des Checkouts gegen den Registereintrag; Abweichung →
   `origin des Projekt-Checkouts weicht vom Registereintrag ab`
5. Rückgabe des registrierten `checkout_path` als `Path` — kein Clone, kein Fetch

Tests lenken die DB über das Modulattribut `_DB_PATH_OVERRIDE` um.

## `tasks.repo_key`

- `hub/task_schema.py`: `ensure_task_repo_key_column()` legt die Spalte
  `tasks.repo_key` idempotent an.
- `gui/server.py` (`api_post_task`): schreibt 21 Spalten, inklusive `repo_key`.

## `worker_git`: Registerauflösung

`start_task_worktree(task_id, *, base_branch, repo_root=None, worker_task_binding=None, require_task_binding=False, task_code_capability=False)`

- `worker_task_binding` → `repo_key` + `register_revision`; Auflösung über
  `project_source_register.resolve_repo(repo_key, register_revision)`
  (erwartete Revision positional).
- `worker_task_binding=None` trotz Anforderung → RuntimeError.
- Registereintrag fehlt → RuntimeError `Taskbindung ohne Projektquellen-Registereintrag`.
- `repo_root` weicht vom registrierten `checkout_path` ab → RuntimeError.
- `task_code_capability=True` nur für `repo_key == "bach"`.

## `worker_lease_binding._project_binding_for`

`_project_binding_for(task_id, snapshot)`:

- Snapshot ohne `repo_key` → `RuntimeError: Task {id} ohne Projektquellen-Bindung (repo_key fehlt)`.
- `revision = psr.register_revision(repo_key)`;
  `checkout = psr.resolve_repo(repo_key, expected_revision=revision)`.
- `pinned_sha` via `git rev-parse HEAD` im Checkout; Fehler →
  `RuntimeError: Task {id}: pinned SHA für {r!r} nicht ermittelbar`.
- Rückgabe: `{"repo_key", "register_revision", "pinned_sha"}`.

## Lease-Acquire

- `LeaseAcquireRequest` (extra=forbid) mit Alias-Feld `_project_binding`.
- `_validated_project_binding` prüft die Bindung; Fehler → HTTP 422.
- Register-Revision-Mismatch beim Acquire → HTTP 422 mit Fehlercode
  `project_register_revision_mismatch`.
- `hub/task_lease.py`: `LEASE_COLUMNS` um `repo_key` erweitert; die Bindung wird
  mit dem Lease persistiert.
- `hub/task_lease_client.py`: Client übernimmt `_project_binding`.

## Status

- Tests geschrieben: `system/tests/test_project_source_register.py` (#2400a),
  `system/tests/test_worker_git_register_binding.py` (#2400b).
- pytest-Probe am 2025-Lauf im Task-Worktree ausgeführt:
  `python -m pytest system/tests/test_project_source_register.py system/tests/test_worker_git_register_binding.py -q`
  → **41 passed** (Exitcode 0, ca. 2,1 s; 1 PytestConfigWarning wegen unbekannter
  Option `confcutdir`, funktional irrelevant). Beide Testdateien decken das
  Register-Modul und die worker_git-Registerbindung grün ab; formale Abnahme der
  Teil-Tasks #2396–#2400 bleibt ausstehend.