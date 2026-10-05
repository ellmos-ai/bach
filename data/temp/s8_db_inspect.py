#!/usr/bin/env python3
"""S8-Recherche: bach.db lesend inspizieren (Tabellen + Ticket-Volltext)."""
import sqlite3

DB = "file:/Users/lukas/.bach/bach.db?mode=ro"
TICKET = "T-20260920-823767362"

con = sqlite3.connect(DB, uri=True)
cur = con.cursor()

print("== TABLES ==")
tables = [r[0] for r in cur.execute(
    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
).fetchall()]
print(", ".join(tables))

print("\n== COLUMNS of relevant tables ==")
for t in tables:
    try:
        cols = [r[1] for r in cur.execute(f"PRAGMA table_info({t})").fetchall()]
        print(f"{t}: {', '.join(cols)}")
    except Exception as e:
        print(f"{t}: ERROR {e}")

print(f"\n== SEARCH for {TICKET} ==")
for t in tables:
    cols = [r[1] for r in cur.execute(f"PRAGMA table_info({t})").fetchall()]
    if not cols:
        continue
    textcols = []
    for c in cols:
        try:
            # Test-Spalte: nur wenn LIKE funktioniert (TEXT-artig)
            cur.execute(
                f"SELECT COUNT(*) FROM {t} WHERE {c} LIKE ?", (f"%{TICKET}%",)
            )
            n = cur.fetchone()[0]
            if n:
                rows = cur.execute(
                    f"SELECT * FROM {t} WHERE {c} LIKE ? LIMIT 3", (f"%{TICKET}%",)
                ).fetchall()
                print(f"\n-- MATCH table={t} col={c} count={n}")
                for r in rows:
                    print(r)
        except Exception:
            pass

con.close()