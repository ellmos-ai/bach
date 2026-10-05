#!/usr/bin/env python3
"""S8-Recherche: ALLE Treffer des Tickets in tasks.description (Volltext)."""
import sqlite3

DB = "file:/Users/lukas/.bach/bach.db?mode=ro"
TICKET = "T-20260920-823767362"

OUT_PATH = "/Users/lukas/services/bach/data/temp/s8_ticket_full_out.txt"
out = open(OUT_PATH, "w", encoding="utf-8")


def print(*args, **kwargs):
    kwargs.setdefault("sep", " ")
    line = kwargs["sep"].join(str(a) for a in args)
    out.write(line + "\n")

con = sqlite3.connect(DB, uri=True)
con.row_factory = sqlite3.Row
cur = con.cursor()

cols = [r[1] for r in cur.execute("PRAGMA table_info(tasks)").fetchall()]
print(f"tasks columns: {', '.join(cols)}")

rows = cur.execute(
    "SELECT * FROM tasks WHERE description LIKE ? ORDER BY id",
    (f"%{TICKET}%",),
).fetchall()
print(f"\n== {len(rows)} tasks rows matching ticket in description ==")
for r in rows:
    print(f"\n########## task id={r['id']} ##########")
    for k in r.keys():
        v = r[k]
        if k == "description":
            print(f"--- description (full, {len(v) if v else 0} chars) ---")
            print(v)
        else:
            print(f"{k} = {v!r}")

# Zusaetzlich: task_history fuer 1446/1447 (Provenienz des Ticket-Texts)
print("\n\n== task_history for 1446/1447 ==")
try:
    hist = cur.execute(
        "SELECT * FROM task_history WHERE task_id IN (1444, 1445, 1446, 1447) ORDER BY task_id, rowid"
    ).fetchall()
    for h in hist:
        d = {k: (str(h[k])[:200] if h[k] is not None else None) for k in h.keys()}
        print(d)
except Exception as e:
    print(f"ERROR: {e}")

con.close()
out.close()