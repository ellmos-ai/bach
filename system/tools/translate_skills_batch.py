import sqlite3
import os
import re
import time
from pathlib import Path
from datetime import datetime
import concurrent.futures
from deep_translator import GoogleTranslator

BACH_DB = Path(os.path.expanduser('~/.bach/bach.db'))

def _make_key(text: str) -> str:
    key = text[:50].lower()
    key = re.sub(r'[^a-z0-9_]', '_', key)
    key = re.sub(r'_+', '_', key)
    return key.strip('_')

def translate_skills_batch():
    if not BACH_DB.exists():
        print(f"Database not found at {BACH_DB}")
        return

    conn = sqlite3.connect(BACH_DB, timeout=30.0)
    conn.row_factory = sqlite3.Row
    
    # Get top 50 active skills
    skills = conn.execute("SELECT name, description FROM skills WHERE is_active=1 ORDER BY priority DESC LIMIT 50").fetchall()
    
    target_langs = ['en', 'es', 'ru', 'ja', 'zh']
    
    for target_lang in target_langs:
        gt_target = 'zh-CN' if target_lang == 'zh' else target_lang
        
        to_translate = []
        # Find which skills need translation for this language
        for skill in skills:
            desc = skill['description']
            if not desc or str(desc).strip() == "":
                continue
            
            key = _make_key(desc)
            
            # Check if it already exists
            existing = conn.execute("SELECT 1 FROM languages_translations WHERE key=? AND namespace='skills' AND language=?", (key, target_lang)).fetchone()
            if not existing:
                to_translate.append((key, desc))
                
        if not to_translate:
            print(f"[{target_lang.upper()}] No missing skill descriptions to translate.")
            continue
            
        print(f"[{target_lang.upper()}] Found {len(to_translate)} skill descriptions to translate.")
        
        translated_items = []
        
        def do_translate(item):
            key, text = item
            try:
                t = GoogleTranslator(source='de', target=gt_target)
                res = t.translate(text)
                print(".", end="", flush=True)
                return (key, text, res)
            except Exception as e:
                print("E", end="", flush=True)
                time.sleep(1)
                return (key, text, text)  # Fallback to original
                
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            translated_items = list(executor.map(do_translate, to_translate))
            
        print(" Translations complete.")
        
        # Insert translations
        now = datetime.now().isoformat()
        batch_inserts = []
        
        for key, original, translated in translated_items:
            # Also ensure the original 'de' entry exists so it acts as the source
            # wait, 'de' might not exist, but let's just insert the target language
            
            batch_inserts.append((
                key, 
                'skills', 
                target_lang, 
                translated, 
                0, 
                'google_auto', 
                now, 
                now
            ))
            
        try:
            conn.executemany("""
                INSERT OR REPLACE INTO languages_translations
                (key, namespace, language, value, is_verified, source, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, batch_inserts)
            
            # Also insert 'de' if not exists
            de_inserts = []
            for key, original, _ in translated_items:
                existing_de = conn.execute("SELECT 1 FROM languages_translations WHERE key=? AND namespace='skills' AND language='de'", (key,)).fetchone()
                if not existing_de:
                    de_inserts.append((key, 'skills', 'de', original, 1, 'manual', now, now))
                    
            if de_inserts:
                conn.executemany("""
                    INSERT OR IGNORE INTO languages_translations
                    (key, namespace, language, value, is_verified, source, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, de_inserts)
                
            conn.commit()
            print(f"[{target_lang.upper()}] Successfully saved {len(batch_inserts)} translations to DB.")
        except Exception as e:
            print(f"[{target_lang.upper()}] Failed to write to DB: {e}")

    conn.close()
    print("\nAll skill translations completed.")

if __name__ == '__main__':
    translate_skills_batch()
