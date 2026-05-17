import os
import glob
from pathlib import Path
from deep_translator import GoogleTranslator
import concurrent.futures
import time
import re

HELP_DIR = Path('C:/Users/User/OneDrive/.TOPICS/.AI/.OS/BACH/system/docs/help')
LANGS = ['en', 'es', 'ru', 'zh', 'ja']
LANG_MAP = {
    'en': 'en',
    'es': 'es',
    'ru': 'ru',
    'zh': 'zh-CN',
    'ja': 'ja'
}

def split_text_into_chunks(text, max_len=4500):
    chunks = []
    current_chunk = []
    current_len = 0
    for line in text.split('\n'):
        line_len = len(line) + 1 # +1 for \n
        if current_len + line_len > max_len:
            chunks.append('\n'.join(current_chunk))
            current_chunk = [line]
            current_len = line_len
        else:
            current_chunk.append(line)
            current_len += line_len
    if current_chunk:
        chunks.append('\n'.join(current_chunk))
    return chunks

def process_file_content(content, target_lang):
    lines = content.split('\n')
    out_lines = []
    header_idx = -1
    portability_val = 'UNIVERSAL'
    
    # 1. Parse lines
    blocks_to_translate = []
    current_block = []
    
    def flush_block():
        if current_block:
            blocks_to_translate.append('\n'.join(current_block))
            current_block.clear()

    for i, line in enumerate(lines):
        # Handle Portability headers
        if line.startswith('# Portabilitaet:') or line.startswith('# Portability:'):
            portability_val = line.split(':', 1)[1].strip()
            flush_block()
            blocks_to_translate.append(f"__HEADER_PORTABILITY__")
            continue
        if line.startswith('# Version:') or line.startswith('# Zuletzt validiert:') or line.startswith('# Naechste Pruefung:'):
            flush_block()
            continue
            
        # Keep empty lines
        if not line.strip():
            flush_block()
            blocks_to_translate.append("")
            continue
            
        # Keep separator lines
        if re.match(r'^={3,}\s*$', line) or re.match(r'^-{3,}\s*$', line):
            flush_block()
            blocks_to_translate.append(line)
            continue
            
        # Keep technical CLI lines: start with 'bach ' or '  bach '
        if re.match(r'^\s*bach\s+.*$', line):
            flush_block()
            # If it has a description after multiple spaces, try to translate description only
            m = re.match(r'^(\s*bach\s+.*?\s{2,})(.+)$', line)
            if m:
                blocks_to_translate.append((m.group(1), m.group(2))) # Tuple means: keep part 1, translate part 2
            else:
                blocks_to_translate.append(line)
            continue
            
        # Keep file paths
        if re.match(r'^\s*(/?\w+/)+\w+(\.\w+)?\s*$', line):
            flush_block()
            blocks_to_translate.append(line)
            continue
            
        # Table names like: '  abo_subscriptions - Description'
        m = re.match(r'^(\s*[a-z0-9_]+\s+-\s+)(.+)$', line)
        if m:
            flush_block()
            blocks_to_translate.append((m.group(1), m.group(2)))
            continue
            
        current_block.append(line)
        
    flush_block()
    
    # 2. Batch translation preparation
    texts_to_translate = []
    for item in blocks_to_translate:
        if isinstance(item, tuple):
            texts_to_translate.append(item[1])
        elif isinstance(item, str) and item not in ["", "__HEADER_PORTABILITY__"] and not re.match(r'^[=\-]+$', item) and not item.strip().startswith('bach '):
            texts_to_translate.append(item)
            
    # Combine texts into < 4500 chunks
    combined_chunks = []
    current_chunk = []
    current_len = 0
    for t in texts_to_translate:
        t_len = len(t) + 3 # separator length
        if current_len + t_len > 4500:
            combined_chunks.append("|||".join(current_chunk))
            current_chunk = [t]
            current_len = t_len
        else:
            current_chunk.append(t)
            current_len += t_len
    if current_chunk:
        combined_chunks.append("|||".join(current_chunk))
        
    # Translate chunks
    translator = GoogleTranslator(source='de', target=LANG_MAP[target_lang])
    translated_texts = []
    for chunk in combined_chunks:
        try:
            res = translator.translate(chunk)
            translated_texts.extend(res.split("|||"))
        except Exception as e:
            print(f"[{target_lang}] Trans error: {e}")
            translated_texts.extend(chunk.split("|||"))
            time.sleep(1)
            
    # 3. Reconstruct
    t_idx = 0
    final_lines = []
    for item in blocks_to_translate:
        if item == "__HEADER_PORTABILITY__":
            final_lines.append(f"# Portability: {portability_val}")
            final_lines.append(f"# Last validated: 2026-05-17")
            final_lines.append(f"# Next review: 2027-05-17")
        elif isinstance(item, tuple):
            trans_desc = translated_texts[t_idx].strip() if t_idx < len(translated_texts) else item[1]
            final_lines.append(f"{item[0]}{trans_desc}")
            t_idx += 1
        elif isinstance(item, str):
            if item in [""] or re.match(r'^[=\-]+$', item) or item.strip().startswith('bach '):
                final_lines.append(item)
            else:
                # Text block
                trans_block = translated_texts[t_idx] if t_idx < len(translated_texts) else item
                t_idx += 1
                # Format block keeping newlines and approximate indentation
                final_lines.append(trans_block)
                
    return '\n'.join(final_lines)

def translate_file_for_lang(args):
    file_path, target_lang = args
    stem = file_path.stem
    out_name = f"{stem}_{target_lang}.txt"
    out_path = file_path.parent / out_name
    
    if out_path.exists():
        return f"Skipped (exists): {out_name}"
        
    try:
        content = file_path.read_text(encoding='utf-8')
        translated = process_file_content(content, target_lang)
        out_path.write_text(translated, encoding='utf-8')
        return f"Translated: {out_name}"
    except Exception as e:
        return f"Failed: {out_name} - {e}"

def main():
    files = []
    for f in HELP_DIR.rglob('*.txt'):
        if f.name.startswith('_'): continue
        if any(f.name.endswith(f'_{l}.txt') for l in LANGS): continue
        files.append(f)
        
    print(f"Found {len(files)} original files.")
    
    tasks = []
    for f in files:
        for l in LANGS:
            out_path = f.parent / f"{f.stem}_{l}.txt"
            if not out_path.exists():
                tasks.append((f, l))
                
    print(f"Created {len(tasks)} translation tasks.")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        for result in executor.map(translate_file_for_lang, tasks):
            print(result)

if __name__ == "__main__":
    main()
