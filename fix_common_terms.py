import sqlite3
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')

db_paths = [
    os.path.expanduser('~/.bach/bach.db'),
    r'C:\Users\User\OneDrive\.TOPICS\.AI\.OS\BACH\system\data\bach.db'
]

fixes = {
    'achtung': {
        'es': 'ATENCIÓN',
        'ru': 'ВНИМАНИЕ',
        'ja': '警告',
        'zh': '注意'
    },
    'hinweis': {
        'es': 'NOTA',
        'ru': 'ПРИМЕЧАНИЕ',
        'ja': '注記',
        'zh': '提示'
    },
    'beispiel': {
        'es': 'EJEMPLO',
        'ru': 'ПРИМЕР',
        'ja': '例',
        'zh': '示例'
    },
    'fehler': {
        'es': 'ERROR',
        'ru': 'ОШИБКА',
        'ja': 'エラー',
        'zh': '错误'
    }
}

for db_path in db_paths:
    if not os.path.exists(db_path):
        continue
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    
    updated = 0
    for key, lang_map in fixes.items():
        for lang, target_val in lang_map.items():
            cur.execute("""
                UPDATE languages_translations 
                SET value = ?, is_verified = 1, updated_at = datetime('now')
                WHERE key = ? AND language = ? AND value IN ('WARNING', 'NOTE', 'EXAMPLE', 'ERROR')
            """, (target_val, key, lang))
            updated += cur.rowcount
            
    conn.commit()
    conn.close()
    print(f"Database {db_path}: Updated {updated} term entries.")
