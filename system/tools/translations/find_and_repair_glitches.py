import sqlite3
import os
import sys
import re

sys.stdout.reconfigure(encoding='utf-8')

db_paths = [
    os.path.expanduser('~/.bach/bach.db'),
    r'C:\Users\User\OneDrive\.TOPICS\.AI\.OS\BACH\system\data\bach.db'
]

def fix_glitches(text):
    if not text or not isinstance(text, str):
        return text
    
    # 1. Broken braces around numbers or words: { 0 } -> {0}, { name } -> {name}
    new_text = re.sub(r'\{\s+([a-zA-Z0-9_]+)\s+\}', r'{\1}', text)
    new_text = re.sub(r'\{\s+([a-zA-Z0-9_]+)\}', r'{\1}', new_text)
    new_text = re.sub(r'\{([a-zA-Z0-9_]+)\s+\}', r'{\1}', new_text)

    # 2. Broken printf specifiers: % s -> %s, % d -> %d
    new_text = re.sub(r'%\s+([sd])', r'%\1', new_text)

    # 3. Broken URLs: http : // -> http://, https : // -> https://, http // -> http://
    new_text = re.sub(r'https?\s*:\s*/\s*/', r'http://' if 'http:' in text else 'https://', new_text)
    new_text = re.sub(r'https?\s+://', r'https://' if 'https' in text else 'http://', new_text)
    
    return new_text

total_repaired = 0

for db_path in db_paths:
    if not os.path.exists(db_path):
        continue
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT id, key, namespace, language, value FROM languages_translations").fetchall()
    
    repaired_in_db = 0
    cur = conn.cursor()
    
    for r in rows:
        val = r['value']
        fixed_val = fix_glitches(val)
        if fixed_val != val:
            cur.execute("UPDATE languages_translations SET value = ?, updated_at = datetime('now') WHERE id = ?", (fixed_val, r['id']))
            repaired_in_db += 1
            if repaired_in_db <= 5:
                print(f"[{r['namespace']}] {r['key']} ({r['language']}) FIXED:\n  BEFORE: {repr(val[:60])}\n  AFTER:  {repr(fixed_val[:60])}")
    
    conn.commit()
    conn.close()
    print(f"Database {db_path}: Repaired {repaired_in_db} glitch entries.")
    total_repaired += repaired_in_db

print(f"Total entries repaired across databases: {total_repaired}")
