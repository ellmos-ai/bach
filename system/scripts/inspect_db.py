import sqlite3, os
paths = [
    '/Users/lukas/services/bach/system/data/bach.db',
    '/Users/lukas/services/bach/data/bach.db',
    '/Users/lukas/services/bach/bach.db',
    '/Users/lukas/services/bach/system/system/data/bach.db',
    '/Users/lukas/services/bach/system/data/bach-ASUS-GEI.db',
]
for p in paths:
    if not os.path.exists(p):
        print(f'MISSING {p}')
        continue
    try:
        c = sqlite3.connect(p)
        cur = c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='languages_translations'")
        exists = cur.fetchone()
        if not exists:
            print(f'NO_LT {p}')
            continue
        rows = c.execute("SELECT language, COUNT(*) FROM languages_translations GROUP BY language").fetchall()
        print(f'OK {p} -> {rows}')
        c.close()
    except Exception as e:
        print(f'ERR {p}: {e}')
