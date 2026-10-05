#!/usr/bin/env python3
"""S8-Recherche: ControlCenter-Registry-Tabellen in bach.db lesend inspizieren.

Schemata + je 3 Beispielzeilen fuer:
tool_registry, ati_tool_registry, skills, toolchain_runs, tool_patterns, agents.
Fokus: Feldnamen fuer trigger_phrases, Zaehlung, Provenienz.
"""
import sqlite3
import json

DB = "file:/Users/lukas/.bach/bach.db?mode=ro"
TABLES = [
    "tool_registry",
    "ati_tool_registry",
    "skills",
    "toolchain_runs",
    "tool_patterns",
    "agents",
]


def trunc(value, maxlen=400):
    if isinstance(value, str) and len(value) > maxlen:
        return value[:maxlen] + f"...[+{len(value)-maxlen} chars]"
    return value


OUT_PATH = "/Users/lukas/services/bach/data/temp/s8_registry_probe_out.txt"
out = open(OUT_PATH, "w", encoding="utf-8")


def print(*args, **kwargs):
    kwargs.setdefault("sep", " ")
    line = kwargs["sep"].join(str(a) for a in args)
    out.write(line + "\n")


con = sqlite3.connect(DB, uri=True)
con.row_factory = sqlite3.Row
cur = con.cursor()

for t in TABLES:
    print(f"\n===== TABLE {t} =====")
    try:
        cols = [r[1] for r in cur.execute(f"PRAGMA table_info({t})").fetchall()]
        print(f"COLUMNS ({len(cols)}): {', '.join(cols)}")
        n = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"ROW COUNT: {n}")
        rows = cur.execute(f"SELECT * FROM {t} LIMIT 3").fetchall()
        for i, r in enumerate(rows, 1):
            print(f"--- row {i} ---")
            for k in r.keys():
                print(f"  {k} = {trunc(r[k])!r}")
    except Exception as e:
        print(f"ERROR: {e}")

# Zusaetzlich: Distribution/Provenienz-feldbezogene Aggregationen
print("\n===== AGGREGATES =====")
for t in ["tool_registry", "skills", "toolchain_runs", "tool_patterns", "agents"]:
    try:
        cols = [r[1] for r in cur.execute(f"PRAGMA table_info({t})").fetchall()]
        print(f"\n-- {t}: {', '.join(cols)}")
        # Distinct-Werte fuer likely-kategoriale Spalten (klein halten)
        for c in cols:
            try:
                distinct = cur.execute(
                    f"SELECT COUNT(DISTINCT {c}) FROM {t}"
                ).fetchone()[0]
                total = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                if distinct <= 12:
                    vals = [trunc(r[0], 60) for r in cur.execute(
                        f"SELECT DISTINCT {c} FROM {t} LIMIT 12"
                    ).fetchall()]
                    print(f"  {c}: distinct={distinct}/{total} -> {vals}")
                else:
                    print(f"  {c}: distinct={distinct}/{total}")
            except Exception:
                pass
    except Exception as e:
        print(f"ERROR: {e}")

con.close()
out.close()