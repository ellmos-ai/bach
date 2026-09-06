import sqlite3
import os
import sys
import re
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')

db_path = os.path.expanduser('~/.bach/bach.db')
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

rows = conn.execute("SELECT key, namespace, language, value, source, is_verified FROM languages_translations").fetchall()

key_map = defaultdict(dict)
for r in rows:
    ns = r['namespace'] or 'common'
    k = r['key']
    lang = r['language']
    val = r['value']
    key_map[(ns, k)][lang] = (val, r['source'])

def is_code_sql_or_technical(val):
    if not val or not isinstance(val, str):
        return True
    s = val.strip()
    if len(s) <= 3:
        return True
    # SQL
    if re.match(r'^\s*(SELECT|UPDATE|INSERT|DELETE|CREATE|ALTER|DROP|PRAGMA)\b', s, re.IGNORECASE):
        return True
    # Python code / expressions / formatting
    if s.startswith('bach ') or s.startswith('--') or s.startswith('http://') or s.startswith('https://'):
        return True
    if re.match(r'^[A-Za-z0-9_/\-\.:@]+\.py$', s):
        return True
    if re.match(r'^[A-Z0-9_\-\.\:\/]+$', s):
        return True
    if s.startswith('{') and s.endswith('}'):
        return True
    if s.startswith('[') and s.endswith(']'):
        return True
    # Variable format like {len(prompt)...}
    if '{' in s and '}' in s and ('len(' in s or 'json.' in s or 'get(' in s or 'set(' in s):
        return True
    return False

glitches = []
untranslated_copy = []
false_positives = []

for (ns, k), lang_dict in key_map.items():
    de_tuple = lang_dict.get('de')
    en_tuple = lang_dict.get('en')
    de_val = de_tuple[0] if de_tuple else ''
    en_val = en_tuple[0] if en_tuple else ''

    for lang, (val, src) in lang_dict.items():
        if not val or not isinstance(val, str):
            continue

        # 1. Glitches
        if re.search(r'\{\s+\d+\s+\}', val) or re.search(r'\{\s+[a-zA-Z0-9_]+\s+\}', val) or '% s' in val or '% d' in val:
            glitches.append((ns, k, lang, 'broken_placeholder', val))
        elif 'http ' in val or 'https ' in val or 'www. ' in val:
            glitches.append((ns, k, lang, 'broken_url', val))

        # 2. Untranslated text copy
        elif is_code_sql_or_technical(val):
            false_positives.append((ns, k, lang, 'technical', val))
        else:
            if lang not in ['de', 'en']:
                if de_val and val == de_val:
                    untranslated_copy.append((ns, k, lang, 'identical_to_de', val))
                elif en_val and val == en_val:
                    untranslated_copy.append((ns, k, lang, 'identical_to_en', val))
            elif lang == 'en':
                if de_val and val == de_val:
                    untranslated_copy.append((ns, k, lang, 'en_identical_to_de', val))

print(f"Total entries checked: {len(rows)}")
print(f"Detected Glitches (placeholder/URL formatting errors): {len(glitches)}")
print(f"Detected Genuine Untranslated Copy: {len(untranslated_copy)}")
print(f"Technical / Code / False Positives: {len(false_positives)}")

print("\n--- SAMPLE GLITCHES ---")
for item in glitches[:10]:
    print(f"[{item[0]}] key={item[1]} lang={item[2]} issue={item[3]}: '{item[4]}'")

print("\n--- SAMPLE UNTRANSLATED COPY BY NAMESPACE ---")
by_ns = defaultdict(list)
for item in untranslated_copy:
    by_ns[item[0]].append(item)

for ns, items in sorted(by_ns.items(), key=lambda x: len(x[1]), reverse=True):
    print(f"\nNamespace '{ns}': {len(items)} items")
    for item in items[:3]:
        print(f"  key={item[1]} lang={item[2]} issue={item[3]}: '{item[4][:80]}'")
