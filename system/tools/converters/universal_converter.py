#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Copyright (c) 2026 BACH Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

"""
Tool: c_universal_converter
Version: 1.0.0
Author: BACH Team
Created: 2026-02-04
Updated: 2026-02-04
Anthropic-Compatible: True

VERSIONS-HINWEIS: Prüfe auf neuere Versionen mit: bach tools version c_universal_converter

Description:
    [Beschreibung hinzufügen]

Usage:
    python c_universal_converter.py [args]
"""

__version__ = "1.0.0"
__author__ = "BACH Team"

"""
Universal Data Converter
========================
Konvertiert zwischen JSON, YAML, TOML, XML und TOON Formaten.

Nutzung:
  GUI:  python c_universal_converter.py
  CLI:  python c_universal_converter.py file1.json file2.yaml --to yaml

Unterstützte Formate:
  - JSON (.json)
  - YAML (.yaml, .yml)
  - TOML (.toml)
  - XML (.xml)
  - TOON (.toon) - Token-Oriented Object Notation (offizielle toons Library)

Abhängigkeiten:
  pip install pyyaml toml xmltodict toons tkinterdnd2

TOON Spezifikation: https://github.com/toon-format/toon

Autor: Claude für _BATCH System
Version: 2.0.0
Datum: 2026-01-06
"""

import sys
import os
import json
import re
import argparse
import threading
from tkinter import *
from tkinter import ttk, messagebox

# Windows Console Encoding Fix
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, OSError):
        pass

# Optionale Imports
try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

try:
    import toml
    HAS_TOML = True
except ImportError:
    HAS_TOML = False

try:
    import xmltodict
    HAS_XML = True
except ImportError:
    HAS_XML = False

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    HAS_DND = True
except ImportError:
    HAS_DND = False

try:
    import toons
    HAS_TOON = True
except ImportError:
    HAS_TOON = False


# --- 2. UNIVERSAL CONVERTER ---

class UniversalConverter:
    """Zentrale Konvertierungslogik"""
    
    SUPPORTED_FORMATS = {
        'json': True,  # Immer verfügbar
        'yaml': HAS_YAML,
        'yml': HAS_YAML,
        'toml': HAS_TOML,
        'xml': HAS_XML,
        'toon': HAS_TOON,  # Offizielle toons Library (pip install toons)
    }
    
    @classmethod
    def get_available_formats(cls):
        """Gibt Liste verfügbarer Formate zurück"""
        return [fmt for fmt, available in cls.SUPPORTED_FORMATS.items() if available]
    
    @staticmethod
    def load_file(filepath):
        """Lädt eine Datei und gibt Python-Dict zurück"""
        ext = os.path.splitext(filepath)[1].lower().lstrip('.')
        
        if ext not in UniversalConverter.SUPPORTED_FORMATS:
            raise ValueError(f"Format .{ext} nicht unterstützt.")
        
        if not UniversalConverter.SUPPORTED_FORMATS.get(ext, False):
            raise ImportError(f"Bibliothek für .{ext} nicht installiert.")
        
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        if ext == 'json':
            return json.loads(content)
        elif ext in ['yaml', 'yml']:
            return yaml.safe_load(content)
        elif ext == 'toml':
            return toml.loads(content)
        elif ext == 'xml':
            return xmltodict.parse(content)
        elif ext == 'toon':
            return toons.loads(content)
        else:
            raise ValueError(f"Format .{ext} nicht implementiert.")

    @staticmethod
    def save_file(data, filepath, target_format):
        """Speichert Dict in Zielformat"""
        target_format = target_format.lower().lstrip('.')
        
        if target_format == 'yml':
            target_format = 'yaml'
        
        if not UniversalConverter.SUPPORTED_FORMATS.get(target_format, False):
            raise ImportError(f"Bibliothek für .{target_format} nicht installiert.")
        
        target_path = os.path.splitext(filepath)[0] + "." + target_format
        
        with open(target_path, 'w', encoding='utf-8') as f:
            if target_format == 'json':
                json.dump(data, f, indent=2, ensure_ascii=False)
            elif target_format == 'yaml':
                yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
            elif target_format == 'toml':
                # TOML erfordert spezielle Behandlung für verschachtelte Strukturen
                toml.dump(data, f)
            elif target_format == 'xml':
                # XML braucht Root-Element wenn mehrere Top-Level Keys
                if isinstance(data, dict) and len(data.keys()) > 1:
                    data = {'root': data}
                elif isinstance(data, list):
                    data = {'root': {'item': data}}
                xmltodict.unparse(data, output=f, pretty=True)
            elif target_format == 'toon':
                toons.dump(data, f)
            else:
                raise ValueError(f"Zielformat .{target_format} nicht implementiert.")
        
        return target_path
    
    @staticmethod
    def convert(source_path, target_format):
        """Convenience-Methode: Lädt und speichert in einem Schritt"""
        data = UniversalConverter.load_file(source_path)
        return UniversalConverter.save_file(data, source_path, target_format)


# --- 3. GUI IMPLEMENTATION ---

def create_gui():
    """Erstellt GUI mit oder ohne Drag&Drop"""
    
    if HAS_DND:
        root = TkinterDnD.Tk()
    else:
        root = Tk()
    
    root.title("Universal Converter v2.0 (JSON/XML/YAML/TOML/TOON)")
    root.geometry("650x550")
    root.configure(bg="#f0f0f0")

    files_to_process = []
    available_formats = UniversalConverter.get_available_formats()
    # Entferne 'yml' Duplikat
    available_formats = [f for f in available_formats if f != 'yml']
    target_format = StringVar(value="json")

    # Header
    header_text = "Dateien hier hineinziehen" if HAS_DND else "Dateien über Button hinzufügen"
    lbl_instruct = Label(root, text=header_text, bg="#f0f0f0", font=("Arial", 12, "bold"))
    lbl_instruct.pack(pady=15)
    
    # Verfügbarkeits-Info
    missing = [k for k, v in UniversalConverter.SUPPORTED_FORMATS.items() if not v and k != 'yml']
    if missing:
        info_text = f"⚠️ Fehlende Bibliotheken für: {', '.join(missing)}"
        lbl_missing = Label(root, text=info_text, bg="#f0f0f0", fg="#cc0000", font=("Arial", 9))
        lbl_missing.pack()

    # Format Selection
    frame_ctrl = Frame(root, bg="#f0f0f0")
    frame_ctrl.pack(pady=10)
    
    Label(frame_ctrl, text="Zielformat:", bg="#f0f0f0").pack(side=LEFT, padx=5)
    combo = ttk.Combobox(frame_ctrl, textvariable=target_format, values=available_formats, state="readonly", width=10)
    combo.pack(side=LEFT, padx=5)

    # File List
    frame_list = Frame(root)
    frame_list.pack(fill=BOTH, expand=True, padx=20, pady=10)
    
    listbox = Listbox(frame_list, font=("Consolas", 10), selectmode=EXTENDED)
    listbox.pack(side=LEFT, fill=BOTH, expand=True)
    
    scrollbar = Scrollbar(frame_list, orient="vertical", command=listbox.yview)
    scrollbar.pack(side=RIGHT, fill=Y)
    listbox.config(yscrollcommand=scrollbar.set)

    # Log Area
    frame_log = Frame(root)
    frame_log.pack(fill=X, padx=20)
    Label(frame_log, text="Log:", anchor="w").pack(fill=X)
    log_text = Text(frame_log, height=5, font=("Consolas", 9), state="disabled")
    log_text.pack(fill=X)

    def log(msg):
        log_text.config(state="normal")
        log_text.insert(END, msg + "\n")
        log_text.see(END)
        log_text.config(state="disabled")

    def drop_files(event):
        raw_files = root.tk.splitlist(event.data)
        for f in raw_files:
            if os.path.isfile(f):
                files_to_process.append(f)
                listbox.insert(END, f"⏳ {os.path.basename(f)}")

    def add_files():
        from tkinter import filedialog
        filetypes = [
            ("Alle unterstützten", "*.json *.yaml *.yml *.toml *.xml *.toon"),
            ("JSON", "*.json"), ("YAML", "*.yaml *.yml"), 
            ("TOML", "*.toml"), ("XML", "*.xml"), ("TOON", "*.toon")
        ]
        selected = filedialog.askopenfilenames(filetypes=filetypes)
        for f in selected:
            files_to_process.append(f)
            listbox.insert(END, f"⏳ {os.path.basename(f)}")

    def clear_list():
        files_to_process.clear()
        listbox.delete(0, END)
        log_text.config(state="normal")
        log_text.delete(1.0, END)
        log_text.config(state="disabled")

    def update_list_item(index, text):
        listbox.delete(index)
        listbox.insert(index, text)
        if "✅" in text:
            listbox.itemconfig(index, {'fg': 'green'})
        elif "❌" in text:
            listbox.itemconfig(index, {'fg': 'red'})

    def process_thread(tgt):
        success = 0
        for idx, file_path in enumerate(files_to_process):
            try:
                update_list_item(idx, f"⚙️ {os.path.basename(file_path)}")
                new_path = UniversalConverter.convert(file_path, tgt)
                update_list_item(idx, f"✅ {os.path.basename(file_path)} → .{tgt}")
                log(f"✅ {file_path} → {new_path}")
                success += 1
            except Exception as e:
                update_list_item(idx, f"❌ {os.path.basename(file_path)}")
                log(f"❌ {os.path.basename(file_path)}: {e}")
        
        messagebox.showinfo("Fertig", f"{success}/{len(files_to_process)} erfolgreich konvertiert.")

    def start_processing():
        if not files_to_process:
            messagebox.showwarning("Info", "Keine Dateien ausgewählt.")
            return
        threading.Thread(target=process_thread, args=(target_format.get(),), daemon=True).start()

    # Drag & Drop
    if HAS_DND:
        root.drop_target_register(DND_FILES)
        root.dnd_bind('<<Drop>>', drop_files)

    # Buttons
    frame_btn = Frame(root, bg="#f0f0f0")
    frame_btn.pack(pady=15, fill=X, padx=20)

    btn_add = Button(frame_btn, text="📂 Dateien hinzufügen", command=add_files)
    btn_add.pack(side=LEFT, padx=5)

    btn_clear = Button(frame_btn, text="🗑️ Liste leeren", command=clear_list)
    btn_clear.pack(side=LEFT)

    btn_start = Button(frame_btn, text="▶️ Konvertieren", bg="#4CAF50", fg="white", 
                       font=("Arial", 11, "bold"), command=start_processing)
    btn_start.pack(side=RIGHT)

    return root


# --- 4. MAIN ---

if __name__ == "__main__":
    if len(sys.argv) > 1:
        # CLI Mode
        parser = argparse.ArgumentParser(
            description="Universal Converter v2.0 - JSON/YAML/TOML/XML/TOON",
            epilog="Beispiel: python c_universal_converter.py data.json --to yaml"
        )
        parser.add_argument("files", nargs='+', help="Eingabedateien")
        parser.add_argument("--to", required=True, 
                           choices=UniversalConverter.get_available_formats(),
                           help="Zielformat")
        parser.add_argument("--verbose", "-v", action="store_true", help="Ausführliche Ausgabe")
        
        args = parser.parse_args()
        
        print(f"Konvertiere nach: {args.to.upper()}")
        print("-" * 40)
        
        success = 0
        for f in args.files:
            try:
                if args.verbose:
                    data = UniversalConverter.load_file(f)
                    print(f"  Geladen: {f} ({len(str(data))} chars)")
                new_path = UniversalConverter.convert(f, args.to)
                print(f"✅ {f} → {new_path}")
                success += 1
            except Exception as e:
                print(f"❌ {f}: {e}")
        
        print("-" * 40)
        print(f"Ergebnis: {success}/{len(args.files)} erfolgreich")
    else:
        # GUI Mode
        app = create_gui()
        app.mainloop()
