import sqlite3
c = sqlite3.connect('data/bach.db')
row = c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='bach_agents'").fetchone()
print(row[0] if row else 'NONE')
print('---columns---')
for r in c.execute("PRAGMA table_info(bach_agents)").fetchall():
    print(r)
