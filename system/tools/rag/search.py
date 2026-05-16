#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
search.py - BACH RAG Semantic Search
=====================================

Semantische Suche ueber den BACH Knowledge Index.

Usage:
    python tools/rag/search.py "Wie funktioniert das Memory-System?"
    python tools/rag/search.py "OCR Tools" --top 5
    python tools/rag/search.py "Steuer-Workflow" --sources

Voraussetzungen:
    pip install chromadb
    ollama pull nomic-embed-text
    Vorher: python tools/rag/ingest.py
"""

import sys
import argparse
from pathlib import Path
from typing import List, Dict, Optional

BASE_DIR = Path(__file__).parent.parent.parent
DATA_DIR = BASE_DIR / "data"
VECTOR_DIR = DATA_DIR / "vector_store"

EMBEDDING_MODEL = "nomic-embed-text"
COLLECTION_NAME = "bach_knowledge"


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
        print(f"[FEHLER] Ollama nicht erreichbar: {e}")
    return None


def search(query: str, top_k: int = 3, show_sources: bool = False) -> List[Dict]:
    """Fuehrt semantische Suche durch."""
    try:
        import chromadb
    except ImportError:
        print("[FEHLER] ChromaDB nicht installiert: pip install chromadb")
        return []

    if not VECTOR_DIR.exists():
        print("[FEHLER] Kein Index vorhanden. Erst: python tools/rag/ingest.py")
        return []

    # Embedding fuer die Anfrage
    query_embedding = get_embedding(query)
    if query_embedding is None:
        return []

    # ChromaDB abfragen
    client = chromadb.PersistentClient(path=str(VECTOR_DIR))
    try:
        collection = client.get_collection(COLLECTION_NAME)
    except Exception:
        print("[FEHLER] Collection nicht vorhanden. Erst: python tools/rag/ingest.py")
        return []

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        include=["documents", "metadatas", "distances"]
    )

    # Ergebnisse formatieren
    output = []
    if results and results["documents"] and results["documents"][0]:
        print(f"\nSuche: \"{query}\"")
        print(f"{'=' * 60}")

        for i, (doc, meta, dist) in enumerate(zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0]
        )):
            source = meta.get("source", "unbekannt")
            similarity = max(0, 1 - dist)  # Cosine distance -> similarity

            print(f"\n--- Ergebnis {i+1} (Relevanz: {similarity:.1%}) ---")
            print(f"Quelle: {source}")

            if show_sources:
                print(f"Chunk:  {meta.get('chunk_index', '?')}/{meta.get('total_chunks', '?')}")

            # Text-Preview (max 300 Zeichen)
            preview = doc[:300]
            if len(doc) > 300:
                preview += "..."
            print(f"\n{preview}")

            output.append({
                "source": source,
                "text": doc,
                "similarity": similarity,
                "metadata": meta
            })

    else:
        print("Keine Ergebnisse gefunden.")

    return output


def main():
    parser = argparse.ArgumentParser(description="BACH RAG Semantic Search")
    parser.add_argument("query", nargs="?", help="Suchanfrage")
    parser.add_argument("--top", type=int, default=3, help="Anzahl Ergebnisse (default: 3)")
    parser.add_argument("--sources", action="store_true", help="Quell-Details anzeigen")

    args = parser.parse_args()

    if not args.query:
        print("Usage: python tools/rag/search.py \"Suchanfrage\"")
        print("       python tools/rag/search.py \"Suchanfrage\" --top 5 --sources")
        return

    search(args.query, top_k=args.top, show_sources=args.sources)


if __name__ == "__main__":
    main()
