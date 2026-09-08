import sys
from collections import defaultdict
from db_access import build_parser, connect

sys.stdout.reconfigure(encoding='utf-8')

args = build_parser("Erstellt Stichproben fuer Skill- und Help-Uebersetzungen.").parse_args()
db_path, conn = connect(args.db)

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
