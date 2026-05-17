#!/usr/bin/env python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Parallel-Chunks-Methode Stufe 3: LLM-Zusammenfassungen fuer Chunks
SQ047: Wissensindexierung

Zweck:
- Laedt alle Chunks aus document_chunks (ohne Summary)
- Generiert LLM-Zusammenfassungen via Claude API
- Speichert Summaries zurueck in DB
- Protokolliert Run in chunk_indexing_runs

Usage:
    python summarize_chunks.py [--model haiku|sonnet] [--batch-size 10] [--dry-run]

Portiert: BACH v3.8.0-SUGAR (system/tools/schwarm/)
"""

import argparse
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


class ChunkSummarizer:
    """LLM-basierte Chunk-Zusammenfassung."""

    def __init__(self, model: str = "haiku", db_path: Path = DB_PATH):
        """
        Initialisiert den ChunkSummarizer.

        Args:
            model: LLM-Modell ("haiku" oder "sonnet")
            db_path: Pfad zur bach.db
        """
        self.model = model
        self.db_path = db_path
        self.run_id = None
        self.stats = {
            'chunks_processed': 0,
            'chunks_summarized': 0,
            'errors': 0,
            'total_cost_usd': 0.0
        }

    def _get_db(self) -> sqlite3.Connection:
        """Oeffnet Datenbankverbindung."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _create_run(self) -> int:
        """
        Erstellt einen neuen chunk_indexing_runs Eintrag.

        Returns:
            run_id
        """
        conn = self._get_db()
        cursor = conn.execute("""
            INSERT INTO chunk_indexing_runs (started_at, llm_model, status)
            VALUES (?, ?, 'running')
        """, (datetime.now().isoformat(), self.model))
        conn.commit()
        run_id = cursor.lastrowid
        conn.close()
        return run_id

    def _finish_run(self, status: str = "completed", log: str = ""):
        """
        Beendet den chunk_indexing_run.

        Args:
            status: "completed" oder "failed"
            log: Fehler-Log
        """
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
        """
        Laedt alle Chunks ohne Summary aus DB.

        Args:
            limit: Maximale Anzahl Chunks (None = alle)

        Returns:
            Liste von Chunks (id, chunk_text, chunk_tokens, ...)
        """
        conn = self._get_db()
        query = """
            SELECT
                id,
                search_index_id,
                chunk_number,
                chunk_text,
                chunk_tokens
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

    def summarize_chunk(self, chunk_text: str) -> Optional[str]:
        """
        Generiert LLM-Zusammenfassung fuer einen Chunk.

        Args:
            chunk_text: Text des Chunks

        Returns:
            Summary-Text oder None bei Fehler

        TODO: LLM-API Integration
        """
        prompt = f"""Fasse den folgenden Text-Chunk in 2-3 Saetzen zusammen.
Fokus: Kernaussage, wichtigste Konzepte, technische Details.

---
{chunk_text}
---

Zusammenfassung:"""

        # TODO: API-Call an Claude
        # try:
        #     response = anthropic.messages.create(
        #         model=f"claude-{self.model}-3.5",
        #         max_tokens=150,
        #         messages=[{"role": "user", "content": prompt}]
        #     )
        #     summary = response.content[0].text.strip()
        #     return summary
        # except Exception as e:
        #     print(f"Fehler bei LLM-API: {e}")
        #     return None

        # MOCK fuer Entwicklung (entfernen wenn API verfuegbar):
        print(f"[MOCK] Wuerde jetzt Zusammenfassung generieren fuer {len(chunk_text)} Zeichen")
        return f"[MOCK-SUMMARY] Zusammenfassung fuer Chunk mit {len(chunk_text)} Zeichen"

    def save_summary(self, chunk_id: int, summary: str):
        """
        Speichert Summary in DB.

        Args:
            chunk_id: Chunk-ID
            summary: Zusammenfassungs-Text
        """
        conn = self._get_db()
        conn.execute("""
            UPDATE document_chunks
            SET summary = ?,
                summarized_at = ?
            WHERE id = ?
        """, (summary, datetime.now().isoformat(), chunk_id))
        conn.commit()
        conn.close()

    def run(self, batch_size: int = 10, dry_run: bool = False):
        """
        Hauptprozess: Alle Chunks laden, summarizen, speichern.

        Args:
            batch_size: Wie viele Chunks pro Batch? (Rate-Limiting)
            dry_run: Wenn True, nur Simulation (keine DB-Schreibzugriffe)
        """
        print("=== Parallel-Chunks Stufe 3: Chunk-Zusammenfassung ===\n")
        print(f"Modell: {self.model}")
        print(f"Batch-Size: {batch_size}")
        print(f"Dry-Run: {'Ja' if dry_run else 'Nein'}\n")

        # Run starten
        if not dry_run:
            self.run_id = self._create_run()
            print(f"Run-ID: {self.run_id}\n")

        # Chunks laden
        chunks = self.get_unsummarized_chunks()
        total_chunks = len(chunks)

        if total_chunks == 0:
            print("[OK] Keine Chunks ohne Summary gefunden")
            if not dry_run:
                self._finish_run(status="completed", log="Keine Arbeit")
            return

        print(f"Gefunden: {total_chunks} Chunks ohne Summary\n")

        # Kosten-Tracking
        start_time = time.time()

        # Chunks durchgehen
        for i, chunk in enumerate(chunks, 1):
            chunk_id = chunk['id']
            chunk_text = chunk['chunk_text']
            chunk_tokens = chunk['chunk_tokens']

            print(f"[{i}/{total_chunks}] Chunk {chunk_id} ({chunk_tokens} Tokens)...", end=" ")

            # Zusammenfassung generieren
            try:
                summary = self.summarize_chunk(chunk_text)
                if summary:
                    # In DB speichern
                    if not dry_run:
                        self.save_summary(chunk_id, summary)
                    self.stats['chunks_summarized'] += 1
                    print("[OK]")
                else:
                    print("[FEHLER] (Fehler bei LLM-API)")
                    self.stats['errors'] += 1

            except Exception as e:
                print(f"[FEHLER] (Exception: {e})")
                self.stats['errors'] += 1

            self.stats['chunks_processed'] += 1

            # Batch-Pause (Rate-Limiting)
            if i % batch_size == 0 and i < total_chunks:
                print(f"  -> Batch-Pause (5 Sekunden)...")
                time.sleep(5)

        elapsed = time.time() - start_time

        # Kosten-Tracking in DB
        try:
            from .runner import log_schwarm_run
            log_schwarm_run(
                pattern="parallel_chunks_summarize",
                task=f"summarize {total_chunks} chunks",
                tokens_in=sum(c.get('chunk_tokens', 0) for c in chunks),
                tokens_out=self.stats['chunks_summarized'] * 50,
                cost_usd=self.stats['total_cost_usd'],
                workers=1,
                duration_ms=int(elapsed * 1000),
                status="completed" if self.stats['errors'] == 0 else "completed_with_errors",
                result_summary=f"{self.stats['chunks_summarized']} summarized, {self.stats['errors']} errors",
            )
        except Exception:
            pass

        # Run beenden
        print("\n=== ZUSAMMENFASSUNG ===")
        print(f"Chunks verarbeitet: {self.stats['chunks_processed']}")
        print(f"Chunks summarisiert: {self.stats['chunks_summarized']}")
        print(f"Fehler: {self.stats['errors']}")
        print(f"Geschaetzte Kosten: ${self.stats['total_cost_usd']:.4f}")

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
        '--model',
        choices=['haiku', 'sonnet'],
        default='haiku',
        help='LLM-Modell (haiku = schnell & guenstig, sonnet = praezise)'
    )
    parser.add_argument(
        '--batch-size',
        type=int,
        default=10,
        help='Wie viele Chunks pro Batch? (Rate-Limiting)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Simulation (keine DB-Aenderungen)'
    )

    args = parser.parse_args()

    summarizer = ChunkSummarizer(model=args.model)
    summarizer.run(batch_size=args.batch_size, dry_run=args.dry_run)


if __name__ == '__main__':
    main()
