#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
document_chunker.py — Dokumente in Token-Chunks aufteilen (SQ047)

Teil der Parallel-Chunks-Methode Wissensindexierung.
Zerteilt Dokumente in 400-Token-Chunks mit 80-Token Overlap.

Usage:
    from document_chunker import DocumentChunker

    chunker = DocumentChunker(chunk_size=400, overlap=80)
    chunks = chunker.chunk_text(text)

Author: Sonnet Worker (Runde 10)
Date: 2026-02-20
"""

import re
from typing import List, Dict


class DocumentChunker:
    """Zerteilt Dokumente in überlappende Token-Chunks."""

    def __init__(self, chunk_size: int = 400, overlap: int = 80):
        """
        Args:
            chunk_size: Maximale Anzahl Tokens pro Chunk (Standard: 400)
            overlap: Anzahl überlappende Tokens zwischen Chunks (Standard: 80)
        """
        self.chunk_size = chunk_size
        self.overlap = overlap

    def tokenize(self, text: str) -> List[str]:
        """
        Einfache Tokenisierung (Wort-basiert).

        Für echtes Token-Counting müsste man tiktoken verwenden,
        aber für den Parallel-Chunks-Ansatz reicht Wort-Approximation.

        Args:
            text: Zu tokenisierender Text

        Returns:
            Liste von Tokens (Wörter + Satzzeichen)
        """
        # Whitespace-basiertes Splitting
        # Approximation: 1 Wort ≈ 1.3 Tokens (durchschnittlich)
        # Für 400 Token-Chunks nehmen wir ~300 Wörter
        tokens = re.findall(r'\S+', text)
        return tokens

    def chunk_text(self, text: str, metadata: dict = None) -> List[Dict]:
        """
        Zerteilt Text in überlappende Chunks.

        Args:
            text: Zu zerteilender Text
            metadata: Optional, zusätzliche Metadaten (source, path, etc.)

        Returns:
            Liste von Chunk-Dicts mit {text, tokens, chunk_id, metadata}
        """
        tokens = self.tokenize(text)

        if len(tokens) <= self.chunk_size:
            # Text passt in einen Chunk
            return [{
                'text': text,
                'tokens': len(tokens),
                'chunk_id': 0,
                'total_chunks': 1,
                'metadata': metadata or {}
            }]

        chunks = []
        chunk_id = 0
        start = 0

        while start < len(tokens):
            # Chunk-Ende: start + chunk_size
            end = min(start + self.chunk_size, len(tokens))

            chunk_tokens = tokens[start:end]
            chunk_text = ' '.join(chunk_tokens)

            chunks.append({
                'text': chunk_text,
                'tokens': len(chunk_tokens),
                'chunk_id': chunk_id,
                'start_token': start,
                'end_token': end,
                'metadata': metadata or {}
            })

            chunk_id += 1

            # Nächster Start: aktuelles Ende - Overlap
            # (außer beim letzten Chunk)
            if end >= len(tokens):
                break

            start = end - self.overlap

        # Total_chunks ergänzen
        for chunk in chunks:
            chunk['total_chunks'] = len(chunks)

        return chunks

    def chunk_document(self, file_path: str, source: str = None) -> List[Dict]:
        """
        Zerteilt ein Dokument in Chunks.

        Args:
            file_path: Pfad zum Dokument
            source: Optional, Quell-Bezeichnung (z.B. "BACH Docs")

        Returns:
            Liste von Chunks mit Metadaten
        """
        from pathlib import Path

        path = Path(file_path)

        if not path.exists():
            raise FileNotFoundError(f"Datei nicht gefunden: {file_path}")

        # Text lesen (nur .txt, .md für jetzt)
        if path.suffix not in ['.txt', '.md', '.py', '.sh']:
            raise ValueError(f"Unsupported file type: {path.suffix}")

        text = path.read_text(encoding='utf-8')

        metadata = {
            'source': source or 'Unknown',
            'file_path': str(path),
            'file_name': path.name,
            'file_size': len(text)
        }

        return self.chunk_text(text, metadata=metadata)


def chunk_corpus(file_paths: List[str], source: str = "BACH") -> List[Dict]:
    """
    Zerteilt einen ganzen Corpus (mehrere Dateien) in Chunks.

    Args:
        file_paths: Liste von Dateipfaden
        source: Quell-Bezeichnung

    Returns:
        Alle Chunks aller Dateien kombiniert
    """
    chunker = DocumentChunker(chunk_size=400, overlap=80)
    all_chunks = []

    for file_path in file_paths:
        try:
            chunks = chunker.chunk_document(file_path, source=source)
            all_chunks.extend(chunks)
        except Exception as e:
            print(f"⚠ Fehler bei {file_path}: {e}")

    return all_chunks


# CLI Usage
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python document_chunker.py <file_or_dir>")
        print("  file: Zerteilt einzelne Datei")
        print("  dir: Zerteilt alle .md/.txt/.py Dateien im Verzeichnis")
        sys.exit(1)

    from pathlib import Path

    target = Path(sys.argv[1])

    if target.is_file():
        chunker = DocumentChunker()
        chunks = chunker.chunk_document(str(target))
        print(f"✓ {len(chunks)} Chunks erstellt:")
        for chunk in chunks:
            print(f"  Chunk {chunk['chunk_id']}/{chunk['total_chunks']}: {chunk['tokens']} tokens")
            print(f"    {chunk['text'][:80]}...")

    elif target.is_dir():
        files = list(target.rglob("*.md")) + list(target.rglob("*.txt")) + list(target.rglob("*.py"))
        chunks = chunk_corpus([str(f) for f in files], source=target.name)
        print(f"✓ {len(chunks)} Chunks aus {len(files)} Dateien:")
        print(f"  Chunk-Size: 400 tokens, Overlap: 80 tokens")
        print(f"  Gesamt-Text: {sum(c['tokens'] for c in chunks)} tokens")

    else:
        print(f"✗ Pfad nicht gefunden: {target}")
        sys.exit(1)
