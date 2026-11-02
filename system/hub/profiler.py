#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
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
ProfilerHandler - CLI-Wrapper fuer ProFiler Extension
======================================================

Operationen:
  search <keyword>        Dateien nach Keyword durchsuchen
  profile <path>          Datei/Ordner analysieren
  hash <path>             SHA256-Hash berechnen
  categorize <path>       Dateikategorie bestimmen
  status                  ProFiler-Status anzeigen

Nutzt: extensions/ProFiler/ + Dateisystem
"""

import os
import hashlib
from pathlib import Path
from typing import List, Tuple
from hub.base import BaseHandler


from hub._services.ocean_stack_bridge import deprecated_legacy_bach
@deprecated_legacy_bach("system-explorer")
class ProfilerHandler(BaseHandler):

    # Datei-Kategorien nach Endung
    CATEGORIES = {
        "Dokumente": {".pdf", ".doc", ".docx", ".txt", ".odt", ".rtf", ".xls", ".xlsx", ".pptx", ".csv"},
        "Bilder": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".svg", ".webp", ".tiff", ".ico"},
        "Audio": {".mp3", ".wav", ".flac", ".ogg", ".aac", ".wma", ".m4a"},
        "Video": {".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm"},
        "Archive": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2"},
        "Code": {".py", ".js", ".ts", ".html", ".css", ".java", ".c", ".cpp", ".rs", ".go", ".sql"},
        "Daten": {".json", ".xml", ".yaml", ".yml", ".toml", ".ini", ".cfg"},
        "Ausfuehrbar": {".exe", ".msi", ".bat", ".cmd", ".ps1", ".sh"},
    }

    def __init__(self, base_path_or_app):
        super().__init__(base_path_or_app)
        self.extensions_dir = self.base_path.parent / "extensions" / "ProFiler"

    @property
    def profile_name(self) -> str:
        return "profiler"

    @property
    def target_file(self) -> Path:
        return self.extensions_dir

    def get_operations(self) -> dict:
        return {
            "search": "Dateien suchen: search <keyword> [--path=DIR]",
            "profile": "Datei/Ordner analysieren: profile <path>",
            "hash": "SHA256-Hash: hash <path>",
            "categorize": "Dateikategorie: categorize <path>",
            "status": "ProFiler-Status",
            "stats": "Ordner-Statistiken: stats <path>",
        }

    def handle(self, operation: str, args: List[str], dry_run: bool = False) -> Tuple[bool, str]:
        ops = {
            "search": self._search,
            "profile": self._profile,
            "hash": self._hash,
            "categorize": self._categorize,
            "status": self._status,
            "stats": self._stats,
        }

        fn = ops.get(operation)
        if not fn:
            avail = ", ".join(ops.keys())
            return False, f"Unbekannte Operation: {operation}\nVerfuegbar: {avail}"

        return fn(args, dry_run)

    # ------------------------------------------------------------------
    # Operations
    # ------------------------------------------------------------------

    def _search(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        if not args:
            return False, "Verwendung: profiler search <keyword> [--path=DIR] [--type=ext]"

        keyword = args[0].lower()
        search_path = Path(".")
        file_type = None

        for a in args[1:]:
            if a.startswith("--path="):
                search_path = Path(a.split("=", 1)[1])
            elif a.startswith("--type="):
                file_type = a.split("=", 1)[1]

        if not search_path.exists():
            return False, f"Pfad existiert nicht: {search_path}"

        results = []
        for root, dirs, files in os.walk(str(search_path)):
            for f in files:
                if keyword in f.lower():
                    if file_type and not f.endswith(f".{file_type}"):
                        continue
                    fp = Path(root) / f
                    size = fp.stat().st_size
                    results.append((str(fp), size))
                    if len(results) >= 50:
                        break
            if len(results) >= 50:
                break

        if not results:
            return True, f"Keine Dateien gefunden fuer '{keyword}'"

        lines = [f"Suchergebnisse: '{keyword}' ({len(results)} Treffer)", "=" * 50]
        for path, size in results:
            size_str = self._format_size(size)
            lines.append(f"  {size_str:>10}  {path}")
        return True, "\n".join(lines)

    def _profile(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        if not args:
            return False, "Verwendung: profiler profile <path>"

        target = Path(args[0])
        if not target.exists():
            return False, f"Pfad existiert nicht: {target}"

        if target.is_file():
            return self._profile_file(target)
        else:
            return self._profile_dir(target)

    def _hash(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        if not args:
            return False, "Verwendung: profiler hash <path>"

        target = Path(args[0])
        if not target.is_file():
            return False, f"Datei nicht gefunden: {target}"

        sha = hashlib.sha256()
        with open(target, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha.update(chunk)

        return True, f"SHA256: {sha.hexdigest()}\nDatei:  {target}\nGroesse: {self._format_size(target.stat().st_size)}"

    def _categorize(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        if not args:
            return False, "Verwendung: profiler categorize <path>"

        target = Path(args[0])
        ext = target.suffix.lower()
        category = self._get_category(ext)
        return True, f"{target.name}: {category} ({ext})"

    def _status(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        lines = ["ProFiler Status", "=" * 40]
        if self.extensions_dir.exists():
            files = list(self.extensions_dir.glob("*.py"))
            lines.append(f"  Extension: {self.extensions_dir}")
            lines.append(f"  Python-Dateien: {len(files)}")
            lines.append(f"  Status: verfuegbar")
        else:
            lines.append(f"  Extension nicht installiert")
            lines.append(f"  Erwartet: {self.extensions_dir}")

        lines.append(f"\n  Kategorien: {len(self.CATEGORIES)}")
        for cat, exts in self.CATEGORIES.items():
            lines.append(f"    {cat}: {', '.join(sorted(exts)[:5])}...")
        return True, "\n".join(lines)

    def _stats(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        if not args:
            return False, "Verwendung: profiler stats <path>"

        target = Path(args[0])
        if not target.is_dir():
            return False, f"Kein Ordner: {target}"

        categories = {}
        total_size = 0
        total_files = 0

        for root, dirs, files in os.walk(str(target)):
            for f in files:
                fp = Path(root) / f
                try:
                    size = fp.stat().st_size
                    total_size += size
                    total_files += 1
                    cat = self._get_category(fp.suffix.lower())
                    if cat not in categories:
                        categories[cat] = {"count": 0, "size": 0}
                    categories[cat]["count"] += 1
                    categories[cat]["size"] += size
                except Exception:
                    pass

        lines = [f"Ordner-Statistiken: {target}", "=" * 50]
        lines.append(f"  Dateien gesamt: {total_files}")
        lines.append(f"  Groesse gesamt: {self._format_size(total_size)}")
        lines.append("\n  Nach Kategorie:")
        for cat in sorted(categories, key=lambda c: categories[c]["size"], reverse=True):
            d = categories[cat]
            lines.append(f"    {cat:15} {d['count']:>5} Dateien  {self._format_size(d['size']):>10}")

        return True, "\n".join(lines)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _profile_file(self, fp: Path) -> Tuple[bool, str]:
        stat = fp.stat()
        ext = fp.suffix.lower()
        cat = self._get_category(ext)

        lines = [
            f"Datei-Profil: {fp.name}",
            "=" * 40,
            f"  Pfad:      {fp}",
            f"  Groesse:   {self._format_size(stat.st_size)}",
            f"  Kategorie: {cat}",
            f"  Endung:    {ext}",
            f"  Geaendert: {stat.st_mtime}",
        ]
        return True, "\n".join(lines)

    def _profile_dir(self, dp: Path) -> Tuple[bool, str]:
        files = list(dp.rglob("*"))
        file_count = sum(1 for f in files if f.is_file())
        dir_count = sum(1 for f in files if f.is_dir())
        total_size = sum(f.stat().st_size for f in files if f.is_file())

        lines = [
            f"Ordner-Profil: {dp.name}",
            "=" * 40,
            f"  Pfad:      {dp}",
            f"  Dateien:   {file_count}",
            f"  Ordner:    {dir_count}",
            f"  Groesse:   {self._format_size(total_size)}",
        ]
        return True, "\n".join(lines)

    def _get_category(self, ext: str) -> str:
        for cat, exts in self.CATEGORIES.items():
            if ext in exts:
                return cat
        return "Sonstige"

    @staticmethod
    def _format_size(size: int) -> str:
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} PB"
