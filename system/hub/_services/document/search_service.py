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

import sys
from pathlib import Path

# DocumentIndexer aus tools/ importieren
_TOOLS_DIR = Path(__file__).parent.parent.parent.parent / "tools"


def _get_indexer():
    """Lazy-Import des DocumentIndexer."""
    if str(_TOOLS_DIR) not in sys.path:
        sys.path.insert(0, str(_TOOLS_DIR))
    from document_indexer import DocumentIndexer
    try:
        from hub.bach_paths import BACH_DB
        db_path = BACH_DB
    except ImportError:
        db_path = Path(__file__).parent.parent.parent.parent / "data" / "bach.db"
    return DocumentIndexer(db_path)


class DocumentSearch:
    """
    Suche und Indizierung (SQLite FTS5).
    Delegiert an tools/document_indexer.py (DocumentIndexer).
    """

    @staticmethod
    def index_document(file_path: str, content: str = None):
        """
        Fuegt ein Dokument dem Suchindex hinzu.

        Args:
            file_path: Pfad zur Datei (wird vom Indexer gelesen)
            content: Optional - wird ignoriert, Indexer extrahiert selbst
        """
        indexer = _get_indexer()
        path = Path(file_path)
        if path.is_file():
            success, msg = indexer.index_file(path)
            return {"success": success, "message": msg}
        elif path.is_dir():
            success, msg = indexer.index_folder(path)
            return {"success": success, "message": msg}
        else:
            return {"success": False, "message": f"Pfad nicht gefunden: {file_path}"}

    @staticmethod
    def search(query: str, limit: int = 20) -> list:
        """
        Sucht im FTS5-Index.

        Args:
            query: Suchbegriff (FTS5-Syntax)
            limit: Maximale Ergebnisse

        Returns:
            list: Suchergebnisse als Dicts oder Fehlermeldung
        """
        indexer = _get_indexer()
        success, msg = indexer.search(query, limit=limit)
        if success:
            return {"success": True, "message": msg}
        else:
            return {"success": False, "message": msg}

    @staticmethod
    def status() -> dict:
        """Gibt Index-Status zurueck."""
        indexer = _get_indexer()
        success, msg = indexer.status()
        return {"success": success, "message": msg}
