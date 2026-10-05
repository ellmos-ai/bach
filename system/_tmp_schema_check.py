import sqlite3, os
for p in ['data/bach.db','data/bach-ASUS-GEI.db']:
    if os.path.exists(p):
        print('===',p)
        c=sqlite3.connect(p)
        for r in c.execute("PRAGMA table_info(bach_agents)").fetchall():
            print(r)
        print('---CREATE SQL---')
        row=c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='bach_agents'").fetchone()
        print(row[0] if row else 'NONE')
        print()
