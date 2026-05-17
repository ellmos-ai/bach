#!/usr/bin/env python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Parallel-Chunks-Methode Stufe 3: LLM-Zusammenfassungen fuer Chunks
SQ047: Wissensindexierung

Zweck:
- Laedt alle Chunks aus document_chunks (ohne Summary)
- Generiert LLM-Zusammenfassungen via Claude API (Anthropic SDK)
- Speichert Summaries zurueck in DB
- Protokolliert Run in chunk_indexing_runs
- Token-Tracking fuer Kosten-Schaetzung

Usage:
    python summarize_chunks.py [--model haiku|sonnet] [--batch-size 10] [--dry-run]

Portiert: BACH v3.11.1 (system/tools/schwarm/)
"""

import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional

# Pfade
SCRIPT_DIR = Path(__file__).parent
SYSTEM_DIR = SCRIPT_DIR.parent.parent
DB_PATH = SYSTEM_DIR / "data" / "bach.db"

# API-Key Quellen (Fallback-Reihenfolge)
SECRETS_PATH = Path.home() / ".bach" / "bach_secrets.json"

MODELS = {
    "haiku": "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-20250514",
}

COST_PER_1M = {
    "haiku": {"input": 1.00, "output": 5.00},
    "sonnet": {"input": 3.00, "output": 15.00},
}

MAX_RETRIES = 3
RETRY_BASE_DELAY = 2.0

SYSTEM_PROMPT = (
    "Du bist ein Experte fuer Textzusammenfassungen in einem Wissensmanagement-System. "
    "Deine Aufgabe ist es, Text-Chunks praezise zusammenzufassen.\n\n"
    "REGELN:\n"
    "- Fasse den Text in 2-3 Saetzen zusammen\n"
    "- Fokus: Kernaussage, wichtigste Konzepte, technische Details\n"
    "- Behalte Fachbegriffe und technische Terme bei\n"
    "- Schreibe in der Sprache des Originals (meist Deutsch oder Englisch)\n"
    "- Keine Einleitungen wie 'Der Text handelt von...'\n"
    "- Direkt und informativ formulieren\n"
    "- Gib NUR die Zusammenfassung zurueck, keine Erklaerungen"
)


def get_api_key() -> str:
    """API-Key aus BACH Secrets oder Umgebungsvariable laden."""
    # 1. BACH Secrets
    if SECRETS_PATH.exists():
        try:
            secrets = json.loads(SECRETS_PATH.read_text(encoding="utf-8"))
            key = secrets.get("ANTHROPIC_API_KEY")
            if key:
                return key
        except (json.JSONDecodeError, OSError):
            pass

    # 2. Umgebungsvariable
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if api_key:
        return api_key

    raise ValueError(
        "ANTHROPIC_API_KEY nicht konfiguriert!\n\n"
        "Optionen:\n"
        "  1. ~/.bach/bach_secrets.json: {\"ANTHROPIC_API_KEY\": \"sk-ant-...\"}\n"
        "  2. Umgebungsvariable: set ANTHROPIC_API_KEY=sk-ant-..."
    )


class ChunkSummarizer:
    """LLM-basierte Chunk-Zusammenfassung via Claude API."""

    def __init__(self, model: str = "haiku", db_path: Path = DB_PATH):
        self.model = model
        self.model_id = MODELS.get(model, MODELS["haiku"])
        self.db_path = db_path
        self.client = None
        self.run_id = None
        self.stats = {
            'chunks_processed': 0,
            'chunks_summarized': 0,
            'errors': 0,
            'total_input_tokens': 0,
            'total_output_tokens': 0,
            'total_cost_usd': 0.0
        }

    def _get_db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _create_run(self) -> int:
        """Erstellt einen neuen chunk_indexing_runs Eintrag."""
        conn = self._get_db()
        cursor = conn.execute("""
            INSERT INTO chunk_indexing_runs (started_at, llm_model, status)
            VALUES (?, ?, 'running')
        """, (datetime.now().isoformat(), self.model_id))
        conn.commit()
        run_id = cursor.lastrowid
        conn.close()
        return run_id

    def _finish_run(self, status: str = "completed", log: str = ""):
        """Beendet den chunk_indexing_run."""
        conn = self._get_db()
        conn.execute("""
            UPDATE chunk_indexing_runs
            SET finished_at = ?,
                status = ?,
                chunks_summarized = ?,
                errors_count = ?,
                llm_cost_usd = ?,
                log = ?
            WHERE id = ?
        """, (
            datetime.now().isoformat(),
            status,
            self.stats['chunks_summarized'],
            self.stats['errors'],
            self.stats['total_cost_usd'],
            log,
            self.run_id
        ))
        conn.commit()
        conn.close()

    def get_unsummarized_chunks(self, limit: Optional[int] = None) -> List[Dict]:
        """Laedt alle Chunks ohne Summary aus DB."""
        conn = self._get_db()
        query = """
            SELECT id, search_index_id, chunk_number, chunk_text, chunk_tokens
            FROM document_chunks
            WHERE summary IS NULL
            ORDER BY search_index_id, chunk_number
        """
        if limit:
            query += f" LIMIT {limit}"

        cursor = conn.execute(query)
        chunks = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return chunks

    def _track_tokens(self, input_tokens: int, output_tokens: int):
        """Token-Verbrauch und Kosten tracken."""
        self.stats['total_input_tokens'] += input_tokens
        self.stats['total_output_tokens'] += output_tokens

        costs = COST_PER_1M.get(self.model, COST_PER_1M["haiku"])
        cost = (input_tokens * costs["input"] + output_tokens * costs["output"]) / 1_000_000
        self.stats['total_cost_usd'] += cost

    def summarize_chunk(self, chunk_text: str) -> Optional[str]:
        """Generiert LLM-Zusammenfassung fuer einen Chunk via Claude API."""
        user_prompt = (
            "Fasse den folgenden Text-Chunk zusammen:\n\n"
            f"---\n{chunk_text}\n---"
        )

        for attempt in range(MAX_RETRIES):
            try:
                message = self.client.messages.create(
                    model=self.model_id,
                    max_tokens=256,
                    system=SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": user_prompt}],
                )

                summary = message.content[0].text.strip()
                self._track_tokens(
                    message.usage.input_tokens,
                    message.usage.output_tokens
                )
                return summary

            except Exception as e:
                error_str = str(e)

                if "rate" in error_str.lower() or "429" in error_str:
                    delay = RETRY_BASE_DELAY * (2 ** attempt)
                    print(f"\n  [RATE-LIMIT] Warte {delay:.0f}s...", end=" ")
                    time.sleep(delay)
                    continue

                if "overloaded" in error_str.lower() or "529" in error_str:
                    delay = RETRY_BASE_DELAY * (attempt + 1)
                    print(f"\n  [OVERLOADED] Warte {delay:.0f}s...", end=" ")
                    time.sleep(delay)
                    continue

                if attempt >= MAX_RETRIES - 1:
                    print(f"\n  [API-FEHLER] {error_str[:100]}")
                    return None

                time.sleep(RETRY_BASE_DELAY)
                continue

        print(f"\n  [FEHLER] Max Retries ({MAX_RETRIES}) erreicht")
        return None

    def save_summary(self, chunk_id: int, summary: str):
        """Speichert Summary in DB."""
        conn = self._get_db()
        conn.execute("""
            UPDATE document_chunks
            SET summary = ?, summarized_at = ?
            WHERE id = ?
        """, (summary, datetime.now().isoformat(), chunk_id))
        conn.commit()
        conn.close()

    def run(self, batch_size: int = 10, dry_run: bool = False):
        """Hauptprozess: Alle Chunks laden, summarizen, speichern."""
        print("=== Parallel-Chunks Stufe 3: Chunk-Zusammenfassung ===\n")
        print(f"Modell: {self.model} ({self.model_id})")
        print(f"Batch-Size: {batch_size}")
        print(f"Dry-Run: {'Ja' if dry_run else 'Nein'}\n")

        if not dry_run:
            try:
                import anthropic
            except ImportError:
                print("[FEHLER] anthropic SDK nicht installiert: pip install anthropic")
                return

            api_key = get_api_key()
            self.client = anthropic.Anthropic(api_key=api_key)

        if not dry_run:
            self.run_id = self._create_run()
            print(f"Run-ID: {self.run_id}\n")

        chunks = self.get_unsummarized_chunks()
        total_chunks = len(chunks)

        if total_chunks == 0:
            print("[OK] Keine Chunks ohne Summary gefunden")
            if not dry_run:
                self._finish_run(status="completed", log="Keine Arbeit")
            return

        print(f"Gefunden: {total_chunks} Chunks ohne Summary\n")

        if dry_run:
            total_chars = sum(len(c['chunk_text']) for c in chunks)
            est_input_tokens = total_chars // 4 + total_chunks * 100
            est_output_tokens = total_chunks * 80
            costs = COST_PER_1M.get(self.model, COST_PER_1M["haiku"])
            est_cost = (est_input_tokens * costs["input"] + est_output_tokens * costs["output"]) / 1_000_000

            print("[DRY-RUN] Kosten-Schaetzung:")
            print(f"  Input-Tokens:  ~{est_input_tokens}")
            print(f"  Output-Tokens: ~{est_output_tokens}")
            print(f"  Gesamt-Zeichen: {total_chars}")
            print(f"  Geschaetzte Kosten: ${est_cost:.4f}")
            print(f"\n  Erste 5 Chunks:")
            for c in chunks[:5]:
                preview = c['chunk_text'][:60].replace('\n', ' ')
                print(f"    Chunk {c['id']}: {preview}...")
            return

        start_time = time.time()

        for i, chunk in enumerate(chunks, 1):
            chunk_id = chunk['id']
            chunk_text = chunk['chunk_text']
            chunk_tokens = chunk['chunk_tokens']

            print(f"[{i}/{total_chunks}] Chunk {chunk_id} ({chunk_tokens} Tokens)...", end=" ")

            try:
                summary = self.summarize_chunk(chunk_text)
                if summary:
                    self.save_summary(chunk_id, summary)
                    self.stats['chunks_summarized'] += 1
                    print("[OK]")
                else:
                    print("[FEHLER]")
                    self.stats['errors'] += 1

            except Exception as e:
                print(f"[FEHLER] ({e})")
                self.stats['errors'] += 1

            self.stats['chunks_processed'] += 1

            if i % batch_size == 0 and i < total_chunks:
                print(f"  -> Batch-Pause (5 Sekunden)...")
                time.sleep(5)

        elapsed = time.time() - start_time

        try:
            from .runner import log_schwarm_run
            log_schwarm_run(
                pattern="parallel_chunks_summarize",
                task=f"summarize {total_chunks} chunks",
                tokens_in=self.stats['total_input_tokens'],
                tokens_out=self.stats['total_output_tokens'],
                cost_usd=self.stats['total_cost_usd'],
                workers=1,
                duration_ms=int(elapsed * 1000),
                status="completed" if self.stats['errors'] == 0 else "completed_with_errors",
                result_summary=f"{self.stats['chunks_summarized']} summarized, {self.stats['errors']} errors",
            )
        except Exception:
            pass

        print(f"\n{'=' * 50}")
        print(f"  ZUSAMMENFASSUNG")
        print(f"{'=' * 50}")
        print(f"  Chunks verarbeitet:  {self.stats['chunks_processed']}")
        print(f"  Chunks summarisiert: {self.stats['chunks_summarized']}")
        print(f"  Fehler:              {self.stats['errors']}")
        print(f"  Input-Tokens:        {self.stats['total_input_tokens']}")
        print(f"  Output-Tokens:       {self.stats['total_output_tokens']}")
        print(f"  Kosten:              ${self.stats['total_cost_usd']:.4f}")
        print(f"{'=' * 50}")

        if not dry_run:
            status = "completed" if self.stats['errors'] == 0 else "completed_with_errors"
            self._finish_run(status=status, log=f"{self.stats['errors']} Fehler")
            print(f"\nRun-ID {self.run_id} abgeschlossen (Status: {status})")


def main():
    """CLI-Einstieg."""
    parser = argparse.ArgumentParser(
        description="Parallel-Chunks Stufe 3: LLM-Zusammenfassungen fuer Chunks"
    )
    parser.add_argument(
        '--model', choices=['haiku', 'sonnet'], default='haiku',
        help='LLM-Modell (haiku = schnell & guenstig, sonnet = praezise)'
    )
    parser.add_argument(
        '--batch-size', type=int, default=10,
        help='Chunks pro Batch (Rate-Limiting)'
    )
    parser.add_argument(
        '--dry-run', action='store_true',
        help='Simulation (keine DB-Aenderungen, keine API-Calls)'
    )

    args = parser.parse_args()

    summarizer = ChunkSummarizer(model=args.model)
    summarizer.run(batch_size=args.batch_size, dry_run=args.dry_run)


if __name__ == '__main__':
    main()
