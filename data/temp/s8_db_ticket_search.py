#!/usr/bin/env python3
"""S8-Recherche: gezielte Ticket-Suche in bach.db (lesend)."""
import sqlite3

DB = "file:/Users/lukas/.bach/bach.db?mode=ro"
TICKET = "T-20260920-823767362"

TARGETS = [
    "tasks", "task_history", "messages", "comm_messages", "prompt_board_items",
    "prompt_boards", "denkarium_entries", "document_index", "connector_messages",
    "session_context", "memory_working", "shared_memory_working",
]

con = sqlite3.connect(DB, uri=True)
cur = con.cursor()

print(f"== SEARCH '{TICKET}' in {len(TARGETS)} tables ==")
found = False
for t in TARGETS:
    cols = [r[1] for r in cur.execute(f"PRAGMA table_info({t})").fetchall()]
    for c in cols:
        try:
            cur.execute(f"SELECT COUNT(*) FROM {t} WHERE {c} LIKE ?", (f"%{TICKET}%",))
            n = cur.fetchone()[0]
        except Exception:
            continue
        if n:
            found = True
            rows = cur.execute(
                f"SELECT * FROM {t} WHERE {c} LIKE ? ORDER BY rowid DESC LIMIT 2",
                (f"%{TICKET}%",),
            ).fetchall()
            colnames = [d[0] for d in cur.description]
            print(f"\n-- MATCH {t}.{c} (count={n}) cols={colnames}")
            for r in rows:
                print(repr(r)[:4000])

if not found:
    print("no match in target tables")

print("\n== tasks table: S8 context ==")
cols = [r[1] for r in cur.execute("PRAGMA table_info(tasks)").fetchall()]
print("cols:", cols)
try:
    cur.execute("SELECT * FROM tasks WHERE id IN (1444,1446,1447,1368,1460)")
    colnames = [d[0] for d in cur.description]
    for r in cur.fetchall():
        row = dict(zip(colnames, r))
        print({k: (str(v)[:600] if v is not None else None) for k, v in row.items()})
except Exception as e:
    print("ERROR:", e)

con.close()