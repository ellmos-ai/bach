import sqlite3
import os
import re
from collections import defaultdict

db_path = os.path.expanduser('~/.bach/bach.db')
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

target_langs = ['de', 'en', 'es', 'ru', 'ja', 'zh']

# 1. Fetch all rows from languages_translations
all_rows = conn.execute("SELECT key, namespace, language, value, source, is_verified FROM languages_translations").fetchall()

# Map: (namespace, key) -> { lang -> value }
key_map = defaultdict(dict)
source_map = defaultdict(dict)
verified_map = defaultdict(dict)

for r in all_rows:
    ns = r['namespace'] or 'common'
    k = r['key']
    lang = r['language']
    val = r['value']
    key_map[(ns, k)][lang] = val
    source_map[(ns, k)][lang] = r['source']
    verified_map[(ns, k)][lang] = r['is_verified']

print(f"Total unique (namespace, key) pairs: {len(key_map)}")

# 2. Find missing translations per language
missing_by_lang = defaultdict(list)

for (ns, k), lang_dict in key_map.items():
    # If key exists in at least one language
    for lang in target_langs:
        if lang not in lang_dict or lang_dict[lang] is None or str(lang_dict[lang]).strip() == '':
            missing_by_lang[lang].append((ns, k))

print("\n--- MISSING TRANSLATIONS PER LANGUAGE ---")
for lang in target_langs:
    print(f"{lang.upper()}: {len(missing_by_lang[lang])} missing keys")

if any(len(missing_by_lang[l]) > 0 for l in target_langs):
    print("\nSample missing keys:")
    for lang in target_langs:
        if missing_by_lang[lang]:
            print(f"  {lang}: {missing_by_lang[lang][:10]}")

# 3. Analyze namespaces of missing keys
ns_missing = defaultdict(lambda: defaultdict(int))
for lang in target_langs:
    for (ns, k) in missing_by_lang[lang]:
        ns_missing[ns][lang] += 1

print("\n--- MISSING KEYS BREAKDOWN BY NAMESPACE ---")
for ns in sorted(ns_missing.keys()):
    counts = ", ".join(f"{l}:{ns_missing[ns][l]}" for l in target_langs if ns_missing[ns][l] > 0)
    print(f"  Namespace '{ns}': {counts}")

# 4. Spot check existing translations (skills & help namespaces + general)
def is_technical(v):
    if not v:
        return True
    if v.startswith('--') or v.startswith('bach ') or v.startswith('http://') or v.startswith('https://'):
        return True
    if re.match(r'^[A-Z0-9_]+$', v):
        return True
    if re.match(r'^\s*[\{\}\[\]"\'\:\,\.\/\\]+\s*$', v):
        return True
    return False

print("\n--- SPOT CHECK: POTENTIAL ISSUES IN EXISTING TRANSLATIONS ---")

suspicious = []

for (ns, k), lang_dict in key_map.items():
    # Check if German or English is available as base
    base_lang = 'de' if 'de' in lang_dict else ('en' if 'en' in lang_dict else list(lang_dict.keys())[0])
    base_val = lang_dict[base_lang]
    
    if is_technical(base_val):
        continue
        
    for lang in target_langs:
        if lang in lang_dict:
            val = lang_dict[lang]
            # Check 1: Target equals German base in non-German language
            if lang != 'de' and val == lang_dict.get('de') and len(val) > 5 and not is_technical(val):
                suspicious.append((ns, k, lang, "Identical to German", val[:50]))
            
            # Check 2: Target equals English base in non-English language (and non-German)
            elif lang not in ['en', 'de'] and val == lang_dict.get('en') and len(val) > 5 and not is_technical(val):
                suspicious.append((ns, k, lang, "Identical to English", val[:50]))

            # Check 3: Check for glitchy automatic translations (e.g. broken html/markdown, weird placeholders like { 0 }, bad characters)
            if '{ ' in val or ' }' in val or '% s' in val or '% d' in val:
                suspicious.append((ns, k, lang, "Broken placeholder spaces", val[:50]))
            
            if 'http ' in val or 'https ' in val or 'www. ' in val:
                suspicious.append((ns, k, lang, "Broken URL spaces", val[:50]))

print(f"Total suspicious translation entries found: {len(suspicious)}")

# Break down suspicious by namespace
ns_susp = defaultdict(int)
for item in suspicious:
    ns_susp[item[0]] += 1

print("\nSuspicious entries by namespace:")
for ns, cnt in sorted(ns_susp.items(), key=lambda x: x[1], reverse=True):
    print(f"  {ns}: {cnt}")

print("\nSample suspicious entries:")
for item in suspicious[:15]:
    print(f"  [{item[0]}] key={item[1]} lang={item[2]} issue='{item[3]}' val='{item[4]}'")

