import sqlite3
import os
import re
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')

db_path = os.path.expanduser('~/.bach/bach.db')
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

print("=== 1. HELP_DOC NAMESPACE ANALYSIS ===")
rows = conn.execute("SELECT key, language, value FROM languages_translations WHERE namespace = 'help_doc' ORDER BY key, language").fetchall()
help_doc_matrix = defaultdict(dict)
for r in rows:
    help_doc_matrix[r['key']][r['language']] = r['value']

for k, langs in help_doc_matrix.items():
    print(f"\nKey: {k}")
    print("  Languages present:", list(langs.keys()))
    for l, val in langs.items():
        snippet = val.replace('\n', ' ')[:100]
        print(f"    [{l}] (len={len(val)}): {snippet}...")

print("\n\n=== 2. DETAILED SUSPICIOUS ENTRIES AUDIT ===")
all_rows = conn.execute("SELECT key, namespace, language, value, source, is_verified FROM languages_translations").fetchall()
key_map = defaultdict(dict)
for r in all_rows:
    ns = r['namespace'] or 'common'
    k = r['key']
    lang = r['language']
    val = r['value']
    key_map[(ns, k)][lang] = val

def is_code_or_sql(val):
    if not val:
        return True
    val_strip = val.strip()
    if val_strip.startswith('SELECT ') or val_strip.startswith('UPDATE ') or val_strip.startswith('INSERT ') or val_strip.startswith('DELETE '):
        return True
    if val_strip.startswith('bach ') or val_strip.startswith('--') or val_strip.startswith('http://') or val_strip.startswith('https://'):
        return True
    if val_strip.startswith('{') and val_strip.endswith('}'):
        return True
    if val_strip.startswith('[') and val_strip.endswith(']'):
        return True
    if re.match(r'^[A-Z0-9_]+$', val_strip):
        return True
    return False

categories = defaultdict(list)

for (ns, k), lang_dict in key_map.items():
    de_val = lang_dict.get('de')
    en_val = lang_dict.get('en')
    
    for lang, val in lang_dict.items():
        if not val or not isinstance(val, str):
            continue
        
        # Check broken placeholders
        if re.search(r'\{\s+\d+\s+\}', val) or re.search(r'\{\s+[a-zA-Z0-9_]+\s+\}', val):
            categories['broken_placeholder'].append((ns, k, lang, val))
        
        # Check broken formatting / percent spaces
        if '% s' in val or '% d' in val:
            categories['broken_format_specifier'].append((ns, k, lang, val))
            
        # Check broken URLs
        if 'http ' in val or 'https ' in val or 'www. ' in val:
            categories['broken_url'].append((ns, k, lang, val))
            
        # Check identical to base when non-base language and not code/SQL
        if lang not in ['de', 'en']:
            if de_val and val == de_val and not is_code_or_sql(val) and len(val) > 5:
                categories['untranslated_identical_to_de'].append((ns, k, lang, val))
            elif en_val and val == en_val and not is_code_or_sql(val) and len(val) > 5:
                categories['untranslated_identical_to_en'].append((ns, k, lang, val))
        elif lang == 'en':
            if de_val and val == de_val and not is_code_or_sql(val) and len(val) > 5:
                categories['untranslated_en_identical_to_de'].append((ns, k, lang, val))

print("\nCategory breakdown of quality issues:")
for cat, items in categories.items():
    print(f"  {cat}: {len(items)} items")

for cat, items in categories.items():
    print(f"\n--- Category: {cat} (showing first 5) ---")
    for item in items[:5]:
        ns, k, lang, val = item
        snippet = val.replace('\n', ' ')[:100]
        print(f"  [{ns}] {k} ({lang}): {snippet}")
