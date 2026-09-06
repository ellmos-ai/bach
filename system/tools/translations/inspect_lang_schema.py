import sqlite3
import os

db_path = os.path.expanduser('~/.bach/bach.db')
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

# Get schema of languages_translations
cols = conn.execute("PRAGMA table_info(languages_translations)").fetchall()
print("Columns in languages_translations:")
for c in cols:
    print(dict(c))

# Get language counts
lang_counts = conn.execute("SELECT language, COUNT(*) FROM languages_translations GROUP BY language").fetchall()
print("\nLanguage Counts:")
for r in lang_counts:
    print(r[0], ":", r[1])

# Get namespace breakdown
ns_counts = conn.execute("SELECT namespace, language, COUNT(*) FROM languages_translations GROUP BY namespace, language ORDER BY namespace, language").fetchall()
print("\nNamespace breakdown:")
for r in ns_counts:
    print(r[0], r[1], ":", r[2])
