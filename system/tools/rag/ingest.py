#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
ingest.py - BACH RAG Ingestion Pipeline
========================================

Scannt BACH-Verzeichnisse, chunked Dokumente und speichert
Embeddings in ChromaDB via Ollama.

Usage:
    python tools/rag/ingest.py                    # Alles indexieren
    python tools/rag/ingest.py --source docs      # Nur docs/
    python tools/rag/ingest.py --source help      # Nur docs/help/
    python tools/rag/ingest.py --status            # Index-Status
    python tools/rag/ingest.py --reset             # Index loeschen

Voraussetzungen:
    pip install chromadb
    ollama pull nomic-embed-text
"""

import os
import sys
import json
import hashlib
import argparse
import re
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional

BASE_DIR = Path(__file__).parent.parent.parent
DATA_DIR = BASE_DIR / "data"
VECTOR_DIR = DATA_DIR / "vector_store"

# Quell-Verzeichnisse fuer Indexierung
SOURCE_DIRS = {
    "docs": BASE_DIR / "docs",
    "help": BASE_DIR / "help",
    "skills": BASE_DIR / "skills",
    "tools_help": BASE_DIR / "help" / "tools",
    "wiki": BASE_DIR / "help" / "wiki",
}

# Unterstuetzte Dateitypen
SUPPORTED_EXTENSIONS = {".md", ".txt", ".py"}

# Chunk-Konfiguration
CHUNK_SIZE = 500       # Zeichen pro Chunk
CHUNK_OVERLAP = 50     # Ueberlappung
EMBEDDING_MODEL = "nomic-embed-text"
COLLECTION_NAME = "bach_knowledge"


def check_dependencies():
    """Prueft ob ChromaDB und Ollama verfuegbar sind."""
    errors = []

    try:
        import chromadb
    except ImportError:
        errors.append("ChromaDB nicht installiert: pip install chromadb")

    try:
        import requests
        r = requests.get("http://localhost:11434/api/tags", timeout=3)
        if r.status_code != 200:
            errors.append("Ollama laeuft nicht: ollama serve")
    except Exception:
        errors.append("Ollama nicht erreichbar: ollama serve")

    return errors


def get_file_hash(filepath: Path) -> str:
    """MD5-Hash einer Datei fuer Change Detection."""
    hasher = hashlib.md5()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[str]:
    """Teilt Text in ueberlappende Chunks mit intelligentem Splitting."""
    if len(text) <= chunk_size:
        return [text] if text.strip() else []

    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size

        # Versuche am Satzende oder Absatz zu brechen
        if end < len(text):
            para_break = text.rfind("\n\n", start, end)
            if para_break > start + chunk_size / 2:
                end = para_break + 2
            else:
                sent_break = text.rfind(". ", start, end)
                if sent_break > start + chunk_size / 2:
                    end = sent_break + 2

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        start = end - overlap

    return chunks


def clean_markdown(text: str) -> str:
    """Bereinigt Markdown-Formatierung fuer bessere Embeddings."""
    text = re.sub(r"```[\s\S]*?```", "[CODE_BLOCK]", text)
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def scan_source(source_path: Path) -> List[Path]:
    """Scannt ein Verzeichnis nach indexierbaren Dateien."""
    files = []
    if not source_path.exists():
        return files

    for ext in SUPPORTED_EXTENSIONS:
        for filepath in source_path.rglob(f"*{ext}"):
            rel_path = filepath.relative_to(BASE_DIR)
            parts_lower = [p.lower() for p in rel_path.parts]
            if any(p.startswith("_archive") or p.startswith(".") for p in parts_lower):
                continue
            if any(p in ("node_modules", "__pycache__", ".git") for p in parts_lower):
                continue
            files.append(filepath)

    return sorted(files)


def get_embedding(text: str) -> Optional[List[float]]:
    """Holt Embedding via Ollama API."""
    import requests
    try:
        resp = requests.post(
            "http://localhost:11434/api/embed",
            json={"model": EMBEDDING_MODEL, "input": text},
            timeout=30
        )
        if resp.status_code == 200:
            return resp.json().get("embeddings", [[]])[0]
    except Exception as e:
        print(f"  [WARN] Ollama-Fehler: {e}")
    return None


def ingest_file(filepath: Path, collection) -> int:
    """Indexiert eine Datei in ChromaDB."""
    rel_path = str(filepath.relative_to(BASE_DIR)).replace("\\", "/")
    file_hash = get_file_hash(filepath)

    # Pruefen ob Datei bereits mit gleichem Hash indexiert ist
    existing = collection.get(where={"source": rel_path})
    if existing and existing["metadatas"]:
        if any(m.get("file_hash") == file_hash for m in existing["metadatas"]):
            return 0  # Keine Aenderung
        # Alte Eintraege loeschen (Datei geaendert)
        if existing["ids"]:
            collection.delete(ids=existing["ids"])

    # Datei lesen
    try:
        content = filepath.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        print(f"  [WARN] Kann {rel_path} nicht lesen: {e}")
        return 0

    if not content.strip():
        return 0

    # Bereinigen und chunken
    if filepath.suffix == ".md":
        content = clean_markdown(content)

    chunks = chunk_text(content)

    # Embeddings generieren und speichern
    ids = []
    documents = []
    metadatas = []
    embeddings = []

    for i, chunk in enumerate(chunks):
        chunk_id = f"{rel_path}::chunk_{i}"
        embedding = get_embedding(chunk)
        if embedding is None:
            continue

        ids.append(chunk_id)
        documents.append(chunk)
        metadatas.append({
            "source": rel_path,
            "chunk_index": i,
            "total_chunks": len(chunks),
            "file_hash": file_hash,
            "file_type": filepath.suffix,
            "indexed_at": datetime.now().isoformat(),
        })
        embeddings.append(embedding)

    if ids:
        collection.add(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
            embeddings=embeddings,
        )

    return len(ids)


def show_status():
    """Zeigt den aktuellen Index-Status."""
    try:
        import chromadb
    except ImportError:
        print("[FEHLER] ChromaDB nicht installiert: pip install chromadb")
        return

    if not VECTOR_DIR.exists():
        print("Kein Vector Store vorhanden.")
        print("Fuehre zuerst 'python tools/rag/ingest.py' aus.")
        return

    client = chromadb.PersistentClient(path=str(VECTOR_DIR))

    try:
        collection = client.get_collection(COLLECTION_NAME)
        count = collection.count()
        print(f"BACH RAG Index Status")
        print(f"=====================")
        print(f"  Chunks indexiert:  {count}")
        print(f"  Speicherort:       {VECTOR_DIR}")
        print(f"  Embedding Model:   {EMBEDDING_MODEL}")

        if count > 0:
            all_data = collection.get(include=["metadatas"])
            sources = set()
            for m in all_data["metadatas"]:
                sources.add(m.get("source", "unbekannt"))
            print(f"  Dateien indexiert:  {len(sources)}")

            by_dir = {}
            for s in sources:
                top_dir = s.split("/")[0]
                by_dir[top_dir] = by_dir.get(top_dir, 0) + 1
            print(f"\n  Nach Verzeichnis:")
            for d, c in sorted(by_dir.items()):
                print(f"    {d}/: {c} Dateien")

    except Exception:
        print("Keine Collection vorhanden.")
        print("Fuehre zuerst 'python tools/rag/ingest.py' aus.")


def reset_index():
    """Loescht den gesamten Index."""
    try:
        import chromadb
    except ImportError:
        print("[FEHLER] ChromaDB nicht installiert")
        return

    if not VECTOR_DIR.exists():
        print("Kein Vector Store vorhanden.")
        return

    client = chromadb.PersistentClient(path=str(VECTOR_DIR))
    try:
        client.delete_collection(COLLECTION_NAME)
        print("[OK] Index geloescht.")
    except Exception:
        print("Keine Collection zum Loeschen vorhanden.")


def main():
    parser = argparse.ArgumentParser(description="BACH RAG Ingestion Pipeline")
    parser.add_argument("--source", choices=list(SOURCE_DIRS.keys()) + ["all"],
                        default="all", help="Quell-Verzeichnis")
    parser.add_argument("--status", action="store_true", help="Index-Status anzeigen")
    parser.add_argument("--reset", action="store_true", help="Index loeschen")

    args = parser.parse_args()

    if args.status:
        show_status()
        return

    if args.reset:
        reset_index()
        return

    # Dependencies pruefen
    errors = check_dependencies()
    if errors:
        print("[FEHLER] Voraussetzungen nicht erfuellt:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)

    import chromadb

    # ChromaDB initialisieren
    VECTOR_DIR.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(VECTOR_DIR))
    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"embedding_model": EMBEDDING_MODEL}
    )

    # Quellen bestimmen
    if args.source == "all":
        sources = SOURCE_DIRS
    else:
        sources = {args.source: SOURCE_DIRS[args.source]}

    print(f"BACH RAG Indexierung")
    print(f"====================")
    print(f"Model: {EMBEDDING_MODEL}")
    print(f"Store: {VECTOR_DIR}")
    print()

    total_files = 0
    total_chunks = 0

    for name, path in sources.items():
        files = scan_source(path)
        print(f"[{name}] {len(files)} Dateien gefunden")

        for filepath in files:
            rel = filepath.relative_to(BASE_DIR)
            chunks_added = ingest_file(filepath, collection)
            if chunks_added > 0:
                print(f"  + {rel} ({chunks_added} Chunks)")
                total_chunks += chunks_added
            total_files += 1

    print()
    print(f"Fertig: {total_files} Dateien verarbeitet, {total_chunks} neue Chunks indexiert")
    print(f"Gesamt im Index: {collection.count()} Chunks")


if __name__ == "__main__":
    main()
