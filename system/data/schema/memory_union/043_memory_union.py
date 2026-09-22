# -*- coding: utf-8 -*-
"""BACH-Seite des gemeinsamen Gedaechtnisschemas BACH = OCEAN (S1).

Bringt die BACH-Gedaechtnistabellen auf den Vereinigungsvertrag, den USMC
und BACH teilen (``memory_union.py`` + ``memory_union.contract.json``,
byte-identisch aus ellmos-ai/usmc uebernommen).

Additiv, wo SQLite es erlaubt (ALTER ADD COLUMN: memory_sessions,
memory_lessons, memory_consolidation). Neu aufgebaut nur, wo ein Constraint
sich nicht nachtraeglich aendern laesst: memory_working (CHECK um handoff/task
erweitert), memory_facts und context_triggers (UNIQUE jetzt mit agent_id).
Alles in einer Transaktion mit Zeilenzahlpruefung und Vertragsvergleich am
Ende; jede Abweichung rollt komplett zurueck. Bestehende BACH-Schreibpfade
setzen kein agent_id und landen damit weiter auf demselben Schluessel
(agent_id = 'default'), OR REPLACE/OR IGNORE verhalten sich unveraendert.

STATUS: bewusst NICHT in migrations/. Der Runner fuehrt dort neue Dateien
beim naechsten Start jeder Bestands-DB automatisch aus; das waere eine
Live-Umstellung. Aktivierung (verschieben nach migrations/ und schema.sql-
Endstand angleichen) ist Teil von S2 des Tickets T-20260920-823767362.
"""

import importlib.util
import sqlite3
from pathlib import Path

_HERE = Path(__file__).resolve().parent


def _union_module():
    spec = importlib.util.spec_from_file_location("bach_memory_union", _HERE / "memory_union.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mu = _union_module()

ADDITIVE_TABLES = ("memory_sessions", "memory_lessons", "memory_consolidation")
REBUILD_TABLES = ("memory_working", "memory_facts", "context_triggers")


class MemoryUnionError(RuntimeError):
    """Migration abgebrochen; Datenbank unveraendert."""


def _exists(conn, name):
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
    ).fetchone() is not None


def _columns(conn, table):
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]


def _contract_columns(table):
    return [col[0] for col in mu.load_contract()["schema"][table]["columns"]]


def _column_ddl(table):
    """Spaltendefinitionen aus der kanonischen DDL (fuer ALTER ADD COLUMN)."""
    body = mu.TABLE_DDL[table]
    body = body[body.index("(") + 1:body.rindex(")")]
    result = {}
    for line in body.splitlines():
        line = line.strip().rstrip(",")
        if line and not line.upper().startswith(("UNIQUE", "CHECK", "PRIMARY")):
            result[line.split()[0]] = line
    return result


def _check_unknown(conn, table):
    extra = set(_columns(conn, table)) - set(_contract_columns(table))
    if extra:
        raise MemoryUnionError(f"unmapped-columns {table}: {', '.join(sorted(extra))}")


def _add_missing_columns(conn, table):
    have = set(_columns(conn, table))
    ddl = _column_ddl(table)
    for name in _contract_columns(table):
        if name not in have:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl[name]}")


def _is_union_shape(conn, table):
    return mu.describe_table(conn, table) == mu.load_contract()["schema"][table]


def _rebuild(conn, table):
    if _is_union_shape(conn, table):
        return
    temp = f"{table}__union"
    conn.execute(mu.TABLE_DDL[table].replace(f"EXISTS {table} (", f"EXISTS {temp} (", 1))
    shared = [c for c in _columns(conn, table) if c in _contract_columns(table)]
    cols = ", ".join(shared)
    conn.execute(f"INSERT INTO {temp} ({cols}) SELECT {cols} FROM {table}")
    before = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    after = conn.execute(f"SELECT COUNT(*) FROM {temp}").fetchone()[0]
    if before != after:
        raise MemoryUnionError(f"row-count {table}: {before} != {after}")
    seq = conn.execute(
        "SELECT seq FROM sqlite_sequence WHERE name = ?", (table,)
    ).fetchone() if _exists(conn, "sqlite_sequence") else None
    conn.execute(f"DROP TABLE {table}")
    conn.execute(f"ALTER TABLE {temp} RENAME TO {table}")
    if seq:
        # AUTOINCREMENT darf geloeschte IDs nicht wiederverwenden.
        conn.execute(
            "UPDATE sqlite_sequence SET seq = MAX(seq, ?) WHERE name = ?", (seq[0], table)
        )


def _copy_partner_config(conn):
    if not _exists(conn, "partner_memory_config"):
        return
    shared = [c for c in _columns(conn, "partner_memory_config") if c in _contract_columns("decay_config")]
    cols = ", ".join(shared)
    conn.execute(
        f"INSERT OR IGNORE INTO decay_config (agent_id, {cols}) "
        f"SELECT partner_id, {cols} FROM partner_memory_config WHERE partner_id IS NOT NULL"
    )


def _fk_problems(conn):
    """FK-Verstoesse nur der Gedaechtnistabellen (fremde Altlasten zaehlen nicht)."""
    tables = [t for t in mu.UNION_TABLES if _exists(conn, t)]
    return sum(len(conn.execute(f"PRAGMA foreign_key_check({t})").fetchall()) for t in tables)


def run_migration(conn=None):
    owns_connection = conn is None
    if owns_connection:
        from hub.bach_paths import BACH_DB

        conn = sqlite3.connect(BACH_DB)
    if conn.in_transaction:
        conn.commit()
    fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    legacy_alter = conn.execute("PRAGMA legacy_alter_table").fetchone()[0]
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("PRAGMA legacy_alter_table = ON")
    conn.execute("BEGIN IMMEDIATE")
    try:
        if not _exists(conn, "memory_sessions"):
            raise MemoryUnionError("memory_sessions fehlt")
        fk_before = _fk_problems(conn)
        for table in (*ADDITIVE_TABLES, *REBUILD_TABLES):
            if _exists(conn, table):
                _check_unknown(conn, table)
        for table in (*ADDITIVE_TABLES, *REBUILD_TABLES):
            if not _exists(conn, table):
                conn.execute(mu.TABLE_DDL[table])
        # Reihenfolge der Spalten muss dem Vertrag folgen: fehlende 039-Spalten
        # vor den Vereinigungsspalten nachziehen, dann neu aufbauen.
        for table in ADDITIVE_TABLES:
            _add_missing_columns(conn, table)
        for table in REBUILD_TABLES:
            _rebuild(conn, table)
        conn.execute(mu.TABLE_DDL["decay_config"])
        _copy_partner_config(conn)
        for statement in mu.INDEX_DDL:
            conn.execute(statement)
        mu.install_provenance_triggers(conn)
        actual = mu.describe_schema(conn)
        expected = mu.load_contract()["schema"]
        if actual != expected:
            diff = sorted(k for k in expected if actual.get(k) != expected.get(k))
            raise MemoryUnionError(f"contract-mismatch: {', '.join(diff)}")
        fk_after = _fk_problems(conn)
        if fk_after > fk_before:
            raise MemoryUnionError(f"foreign-key-check: {fk_before} -> {fk_after}")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.execute(f"PRAGMA legacy_alter_table = {int(legacy_alter)}")
        conn.execute(f"PRAGMA foreign_keys = {int(fk)}")
        if owns_connection:
            conn.close()
