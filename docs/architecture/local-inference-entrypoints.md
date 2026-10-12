# Local inference reserve entrypoints

session: 01a117e2-1767-77a3-9d51-cd1e0c9fac28 | codex@ASUS-GEI | 2026-10-12

## Canonical path authority

Local resource checks resolve the task database directory through
`hub.bach_paths.BACH_DB`. This is BACH's existing path registry, including the
explicit `BACH_DB` environment override. The reserve check only inspects paths;
it does not open a database, run migrations or grant an inference reservation.

BACH supports both the root editable-install `bach_api.py` shim and the
`system/bach_api.py` entrypoint. The root shim exports the public API contract,
not its internal `_resolve_db_path` helper. Resource checks must not depend on
that private helper being exported by whichever entrypoint Python loads.

## Regression evidence and limits

The entrypoint tests run fresh Python processes with each real API module and
an explicitly selected isolated database path. They cover both an absent
database and an existing sentinel file, reject any SQLite connection, verify
unchanged file hashes and modification times, and reject newly created WAL/SHM
files. The root shim's private exports remain unchanged.

These tests demonstrate path inspection and import compatibility. They do not
prove model capacity, production deployment, a restarted Buddha worker or a
successful task result. The large configured model remains a separate resource
and runtime acceptance requirement; a working small-model fallback does not
replace it.
