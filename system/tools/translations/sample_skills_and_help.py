import sqlite3
import os
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')

db_path = os.path.expanduser('~/.bach/bach.db')
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

for ns in ['skills', 'help']:
    rows = conn.execute("SELECT key, language, value, is_verified, source FROM languages_translations WHERE namespace = ? ORDER BY key, language", (ns,)).fetchall()
    key_dict = defaultdict(dict)
    for r in rows:
        key_dict[r['key']][r['language']] = r['value']
    
    print(f"\n==========================================")
    print(f"SAMPLE AUDIT FOR NAMESPACE: '{ns}' (Total keys: {len(key_dict)})")
    print(f"==========================================")
    
    # Take a sample of 15 keys
    sample_keys = sorted(list(key_dict.keys()))[:15]
    for k in sample_keys:
        print(f"\n--- KEY: {k} ---")
        for lang in ['de', 'en', 'es', 'ru', 'ja', 'zh']:
            val = key_dict[k].get(lang, '<MISSING>')
            print(f"  [{lang}]: {val}")

conn.close()
