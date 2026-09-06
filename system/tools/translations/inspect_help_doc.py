import sqlite3
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')

db_path = os.path.expanduser('~/.bach/bach.db')
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

rows = conn.execute("SELECT key, language, value, source FROM languages_translations WHERE namespace = 'help_doc' ORDER BY key, language").fetchall()
print(f"Total rows in help_doc: {len(rows)}")

keys = sorted(list(set(r['key'] for r in rows)))
for k in keys:
    print(f"\n=== Key: {k} ===")
    k_rows = [r for r in rows if r['key'] == k]
    langs = [r['language'] for r in k_rows]
    print(f"Languages present: {langs}")
    for r in k_rows:
        val_snippet = r['value'].replace('\n', ' ')[:100]
        print(f"  [{r['language']}] (src: {r['source']}): {val_snippet}...")
