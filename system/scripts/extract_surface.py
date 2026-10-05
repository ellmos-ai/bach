import sqlite3, json, os
from collections import defaultdict

DB_PATH = '/Users/lukas/services/bach/system/data/bach.db'
REST_PATH = '/Users/lukas/.bach/backups/task_1316/rest_surface.json'
OUT_PATH = '/Users/lukas/.bach/backups/task_1316/work_surface.json'

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

rest = json.load(open(REST_PATH, encoding='utf-8'))
print('rest rows', len(rest))

# build set of (ns,key,lang) and just keys
items = []
for r in rest:
    ns = r['namespace']
    key = r['key']
    lang = r['language']
    # fetch all languages for this key from DB
    rows = conn.execute(
        "SELECT id, namespace, key, language, value, is_verified, source FROM languages_translations WHERE namespace=? AND key=?",
        (ns, key)
    ).fetchall()
    db_by_lang = {}
    for row in rows:
        db_by_lang[row['language']] = {
            'id': row['id'],
            'value': row['value'],
            'is_verified': row['is_verified'],
            'source': row['source'],
        }
    items.append({
        'namespace': ns,
        'key': key,
        'len': r['len'],
        'requested_language': lang,
        'db': db_by_lang,
    })

# Also inspect wrong-verified IDs
ids = [6691,6840,6841,12471]
wrong = []
for id_ in ids:
    row = conn.execute("SELECT * FROM languages_translations WHERE id=?", (id_,)).fetchone()
    if row:
        wrong.append(dict(row))
    else:
        wrong.append({'id': id_, 'missing': True})

# Scan is_verified=1 total
verified_counts = conn.execute("SELECT language, COUNT(*) FROM languages_translations WHERE is_verified=1 GROUP BY language").fetchall()
verified_total = conn.execute("SELECT COUNT(*) FROM languages_translations WHERE is_verified=1").fetchone()[0]

# Scan all verified rows for potential false positives? Maybe list by source
verified_sources = conn.execute("SELECT source, COUNT(*) FROM languages_translations WHERE is_verified=1 GROUP BY source").fetchall()

conn.close()

out = {
    'db_path': DB_PATH,
    'rest_path': REST_PATH,
    'items': items,
    'wrong_verified_ids': wrong,
    'verified_counts': [dict(r) for r in verified_counts],
    'verified_total': verified_total,
    'verified_sources': [dict(r) for r in verified_sources],
}
with open(OUT_PATH, 'w', encoding='utf-8') as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print('wrote', OUT_PATH)
print('verified total', verified_total)
print('verified counts', verified_counts)
print('verified sources', verified_sources)
print('wrong rows', len(wrong))
