#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
translate_swarm.py - Schwarm-Uebersetzung mit Parallel-Chunks-Methode (SQ062)
=====================================================================

Uebersetzt fehlende DE->EN Texte in languages_translations via Claude Haiku.
"Parallel-Chunks-Methode": Texte in kleine Chunks buendeln, 5-10 parallele Haiku-Instanzen.

Usage:
    python translate_swarm.py                       # Alle fehlenden uebersetzen
    python translate_swarm.py --dry-run              # Nur anzeigen, kein API-Call
    python translate_swarm.py --namespace help        # Nur einen Namespace
    python translate_swarm.py --chunk-size 5          # Chunk-Groesse anpassen
    python translate_swarm.py --workers 5             # Thread-Anzahl anpassen
    python translate_swarm.py --limit 20              # Max. Texte uebersetzen
    python translate_swarm.py --inventory             # Status-Uebersicht

Author: BACH Development Team (SQ062)
Created: 2026-02-22
Portiert: BACH v3.8.0-SUGAR (system/tools/schwarm/)
"""

import argparse
import json
import os
import sqlite3
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

try:
    import anthropic
except ImportError:
    print("[FEHLER] anthropic SDK nicht installiert: pip install anthropic")
    sys.exit(1)

# --- Konstanten ---

MODEL = "claude-haiku-4-5-20251001"
DEFAULT_CHUNK_SIZE = 10
DEFAULT_WORKERS = 0  # 0 = dynamisch (auto-berechnet aus Chunk-Anzahl)
MAX_RETRIES = 3
RETRY_BASE_DELAY = 2.0

TABLE = "languages_translations"
SOURCE_TAG = "llm_auto_swarm"

SYSTEM_PROMPT = (
    "You are a professional translator for BACH, a text-based operating "
    "system for LLMs. Translate German UI/help texts to English.\n\n"
    "RULES:\n"
    "- Keep markdown formatting, code blocks, headings (===, ---) unchanged\n"
    "- Keep placeholders like {variable}, {count}, {name} unchanged\n"
    "- Keep CLI commands (bach ..., python ..., --flags) unchanged\n"
    "- Keep technical terms: Skill, Agent, Handler, Hub, Kernel, Daemon, Workflow, Task, Wiki, Memory\n"
    "- Keep SQL statements unchanged\n"
    "- Maintain the same tone (professional but friendly)\n"
    "- If text contains ONLY code/commands/variables, return it unchanged\n"
    "- Output ONLY valid JSON, nothing else"
)


# --- Hilfsfunktionen ---


def get_api_key():
    """API-Key laden: 1. BACH Secrets, 2. Env-Variable."""
    # 1. BACH Secrets
    try:
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "hub" / "_services"))
        from secrets_service import SecretsService

        secrets_file = Path.home() / ".bach" / "bach_secrets.json"
        if secrets_file.exists():
            service = SecretsService(str(secrets_file))
            api_key = service.get_secret("ANTHROPIC_API_KEY")
            if api_key:
                print("[INFO] API-Key aus BACH Secrets-System geladen")
                return api_key
    except (ImportError, FileNotFoundError, KeyError):
        pass

    # 2. Env
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if api_key:
        print("[INFO] API-Key aus Umgebungsvariable geladen")
        return api_key

    raise ValueError(
        "ANTHROPIC_API_KEY nicht konfiguriert!\n\n"
        "Methode 1 (EMPFOHLEN): BACH Secrets-System\n"
        "  bach secrets set ANTHROPIC_API_KEY sk-ant-api03-...\n\n"
        "Methode 2: Umgebungsvariable\n"
        "  export ANTHROPIC_API_KEY=sk-ant-api03-...\n\n"
        "Weitere Infos: BACH_Dev/docs/SQ062_API_KEY_KONFIGURATION.md"
    )


def get_db_path():
    """Ermittelt bach.db Pfad."""
    try:
        from hub.bach_paths import BACH_DB
        if BACH_DB.exists():
            return BACH_DB
    except ImportError:
        pass
    db_path = Path(__file__).parent.parent.parent / "data" / "bach.db"
    if not db_path.exists():
        print(f"[FEHLER] bach.db nicht gefunden: {db_path}")
        sys.exit(1)
    return db_path


def get_missing_translations(db_path, namespace=None, limit=0):
    """
    Holt alle DE-Texte ohne EN-Uebersetzung.

    Returns:
        Liste von Dicts: {id, key, namespace, value}
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    query = f"""
        SELECT t1.id, t1.key, t1.namespace, t1.value
        FROM {TABLE} t1
        WHERE t1.language = 'de'
        AND NOT EXISTS (
            SELECT 1 FROM {TABLE} t2
            WHERE t2.key = t1.key
            AND t2.namespace = t1.namespace
            AND t2.language = 'en'
            AND t2.value != ''
        )
    """
    params = []

    if namespace:
        query += " AND t1.namespace = ?"
        params.append(namespace)

    query += " ORDER BY t1.namespace, t1.key"

    if limit > 0:
        query += " LIMIT ?"
        params.append(limit)

    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def chunk_texts(texts, chunk_size):
    """Teilt Texte in Chunks der Groesse chunk_size."""
    return [texts[i:i + chunk_size] for i in range(0, len(texts), chunk_size)]


# --- Kern: API-Call pro Chunk ---


def translate_chunk(client, chunk, chunk_index, total_chunks):
    """
    Uebersetzt einen Chunk von Texten via Haiku API.

    Returns:
        (chunk_index, results_list, error_or_none)
    """
    texts_for_api = [
        {"key": item["key"], "namespace": item["namespace"], "de": item["value"]}
        for item in chunk
    ]

    user_prompt = (
        f"Translate these {len(chunk)} German texts to English.\n\n"
        f"INPUT (JSON array):\n"
        f"{json.dumps(texts_for_api, ensure_ascii=False, indent=2)}\n\n"
        f"OUTPUT FORMAT (JSON array, same order, same keys + \"en\" field):\n"
        f'[{{"key": "...", "namespace": "...", "en": "translated text"}}, ...]\n\n'
        f"Return ONLY the JSON array, no explanation."
    )

    for attempt in range(MAX_RETRIES):
        try:
            message = client.messages.create(
                model=MODEL,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )

            response_text = message.content[0].text.strip()

            # Robuste JSON-Extraktion
            start = response_text.find("[")
            end = response_text.rfind("]") + 1
            if start == -1 or end == 0:
                raise ValueError(f"Kein JSON-Array in Antwort: {response_text[:200]}")

            results = json.loads(response_text[start:end])

            if len(results) != len(chunk):
                raise ValueError(
                    f"Erwartet {len(chunk)} Ergebnisse, bekommen {len(results)}"
                )

            mapped = []
            for orig, translated in zip(chunk, results):
                en_text = translated.get("en", "") or translated.get("translation", "")
                mapped.append({
                    "key": orig["key"],
                    "namespace": orig["namespace"],
                    "translation": en_text,
                })

            return (chunk_index, mapped, None)

        except Exception as e:
            error_str = str(e)

            if "rate" in error_str.lower() or "429" in error_str:
                delay = RETRY_BASE_DELAY * (2 ** attempt)
                time.sleep(delay)
                continue

            if "overloaded" in error_str.lower() or "529" in error_str:
                time.sleep(RETRY_BASE_DELAY * (attempt + 1))
                continue

            if "json" in error_str.lower() and attempt < MAX_RETRIES - 1:
                continue

            return (chunk_index, [], f"Chunk {chunk_index + 1}: {error_str}")

    return (chunk_index, [], f"Chunk {chunk_index + 1}: Max retries ({MAX_RETRIES}) erreicht")


# --- DB-Writer ---


def write_results_to_db(db_path, all_results):
    """
    Schreibt Uebersetzungs-Ergebnisse gesammelt in die DB.
    Single-threaded, wird NACH allen API-Calls aufgerufen.
    """
    conn = sqlite3.connect(str(db_path))
    now = datetime.now().isoformat()
    success = 0
    errors = 0

    for item in all_results:
        try:
            conn.execute(
                f"INSERT INTO {TABLE} "
                "(key, namespace, language, value, is_verified, source, created_at, updated_at) "
                "VALUES (?, ?, 'en', ?, 0, ?, ?, ?)",
                (item["key"], item["namespace"], item["translation"],
                 SOURCE_TAG, now, now),
            )
            success += 1
        except sqlite3.IntegrityError:
            errors += 1
        except Exception as e:
            print(f"  [DB-ERROR] {item['key']}: {e}")
            errors += 1

    conn.commit()
    conn.close()
    return (success, errors)


# --- Haupt-Orchestrierung ---


def run_swarm(source_lang="de", target_lang="en", namespace=None,
              chunk_size=DEFAULT_CHUNK_SIZE, workers=DEFAULT_WORKERS,
              max_workers=0, limit=0, dry_run=False):
    """Schwarm-Uebersetzung mit Parallel-Chunks-Methode."""
    db_path = get_db_path()

    # 1. Fehlende laden
    missing = get_missing_translations(db_path, namespace, limit)

    if not missing:
        print("[OK] Alle Texte sind bereits uebersetzt!")
        return True

    # Namespace-Verteilung anzeigen
    by_ns = {}
    for txt in missing:
        ns = txt["namespace"] or "general"
        by_ns.setdefault(ns, []).append(txt)

    print(f"[SWARM] {len(missing)} Texte zu uebersetzen ({source_lang} -> {target_lang})")
    for ns, texts in sorted(by_ns.items()):
        print(f"         {ns}: {len(texts)}")

    # 2. Chunken
    chunks = chunk_texts(missing, chunk_size)

    # Dynamische Worker-Berechnung wenn nicht explizit gesetzt
    if workers <= 0:
        try:
            from .runner import calculate_dynamic_workers
            workers = calculate_dynamic_workers(len(chunks), max_workers=max_workers)
        except ImportError:
            cap = max_workers if max_workers > 0 else 8
            workers = min(max(2, len(chunks) // 2), cap)  # Fallback
        print(f"[SWARM] Worker-Anzahl automatisch berechnet: {workers} (basierend auf {len(chunks)} Chunks)")
    print(f"[SWARM] {len(chunks)} Chunks a {chunk_size} Texte, {workers} parallele Worker")

    if dry_run:
        print("\n[DRY-RUN] Wuerde folgende Chunks senden:")
        for i, chunk in enumerate(chunks):
            keys = [txt["key"][:30] for txt in chunk[:3]]
            print(f"  Chunk {i + 1}/{len(chunks)}: {len(chunk)} Texte - {', '.join(keys)}...")

        total_chars = sum(len(txt["value"]) for txt in missing)
        est_input_tokens = total_chars // 4 + len(chunks) * 200
        est_output_tokens = total_chars // 4
        cost = (est_input_tokens * 1 + est_output_tokens * 5) / 1_000_000
        print(f"\n[DRY-RUN] Geschaetzte Kosten: ${cost:.4f}")
        print(f"           Input-Tokens:  ~{est_input_tokens}")
        print(f"           Output-Tokens: ~{est_output_tokens}")
        print(f"           Gesamt-Zeichen: {total_chars}")
        return True

    # 3. API-Key + Client
    api_key = get_api_key()
    client = anthropic.Anthropic(api_key=api_key)

    # 4. Parallel uebersetzen
    all_results = []
    all_errors = []
    completed = 0
    lock = threading.Lock()
    start_time = time.time()

    print(f"\n[SWARM] Starte Uebersetzung mit {workers} Workern...")

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(translate_chunk, client, chunk, i, len(chunks)): i
            for i, chunk in enumerate(chunks)
        }

        for future in as_completed(futures):
            chunk_idx, results, error = future.result()

            with lock:
                completed += 1
                if error:
                    all_errors.append(error)
                    print(f"  [{completed}/{len(chunks)}] Chunk {chunk_idx + 1} FEHLER: {error}")
                else:
                    all_results.extend(results)
                    print(f"  [{completed}/{len(chunks)}] Chunk {chunk_idx + 1} OK ({len(results)} Texte)")

    elapsed = time.time() - start_time
    print(f"\n[SWARM] API-Phase abgeschlossen in {elapsed:.1f}s")
    print(f"         Erfolgreich: {len(all_results)} Texte")
    print(f"         Fehler: {len(all_errors)} Chunks")

    # 4b. Kosten-Tracking in DB
    try:
        from .runner import log_schwarm_run
        total_chars = sum(len(txt["value"]) for txt in missing)
        tokens_in = total_chars // 4 + len(chunks) * 200
        tokens_out = total_chars // 4
        cost = (tokens_in * 1 + tokens_out * 5) / 1_000_000
        log_schwarm_run(
            pattern="parallel_chunks_translate",
            task=f"translate {source_lang}->{target_lang}, {len(missing)} texts",
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost,
            workers=workers,
            duration_ms=int(elapsed * 1000),
            status="completed" if not all_errors else "completed_with_errors",
            result_summary=f"{len(all_results)} uebersetzt, {len(all_errors)} Fehler",
        )
    except Exception:
        pass  # Tracking-Fehler nicht kritisch

    # 5. In DB schreiben
    if all_results:
        print(f"\n[SWARM] Schreibe {len(all_results)} Uebersetzungen in DB...")
        db_success, db_errors = write_results_to_db(db_path, all_results)
        print(f"         Geschrieben: {db_success}")
        if db_errors > 0:
            print(f"         Uebersprungen (Duplikate): {db_errors}")

    # 6. Zusammenfassung
    print(f"\n{'=' * 60}")
    print(f"  ERGEBNIS")
    print(f"{'=' * 60}")
    print(f"  Gesamt zu uebersetzen:  {len(missing)}")
    print(f"  Erfolgreich uebersetzt: {len(all_results)}")
    print(f"  Fehler (API):           {len(all_errors)}")
    print(f"  Dauer:                  {elapsed:.1f}s")
    print(f"  Chunks:                 {len(chunks)} (a {chunk_size} Texte)")
    print(f"  Parallele Worker:       {workers}")
    print(f"{'=' * 60}")

    if all_errors:
        print("\n[FEHLER-DETAILS]:")
        for err in all_errors:
            print(f"  - {err}")

    return len(all_errors) == 0


def show_inventory(namespace=None):
    """Zeigt Inventar der fehlenden Uebersetzungen."""
    db_path = get_db_path()
    missing = get_missing_translations(db_path, namespace)

    if not missing:
        print("[OK] Alle Texte sind bereits uebersetzt!")
        return

    print(f"[INVENTAR] {len(missing)} fehlende EN-Uebersetzungen\n")

    by_ns = {}
    for txt in missing:
        ns = txt["namespace"] or "general"
        by_ns.setdefault(ns, []).append(txt)

    for ns, texts in sorted(by_ns.items()):
        print(f"  [{ns.upper()}] {len(texts)} Texte")
        for txt in texts[:3]:
            val_short = txt["value"][:60].replace("\n", " ")
            print(f"    {txt['key'][:30]:<32} {val_short}")
        if len(texts) > 3:
            print(f"    ... und {len(texts) - 3} weitere")
        print()

    # Gesamtstatistik
    total_chars = sum(len(txt["value"]) for txt in missing)
    avg_len = total_chars // len(missing) if missing else 0
    print(f"  Gesamt: {len(missing)} Texte, {total_chars} Zeichen, avg {avg_len} Zeichen/Text")


# --- CLI ---


def main():
    parser = argparse.ArgumentParser(
        description="Schwarm-Uebersetzung mit Parallel-Chunks-Methode (SQ062)"
    )
    parser.add_argument(
        "--namespace", "-n",
        help="Nur einen Namespace uebersetzen (cli/docs/help/gui/skills)",
    )
    parser.add_argument(
        "--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE,
        help=f"Texte pro API-Call (default: {DEFAULT_CHUNK_SIZE})",
    )
    parser.add_argument(
        "--workers", "-w", type=int, default=DEFAULT_WORKERS,
        help="Parallele Threads (default: auto, basierend auf Chunk-Anzahl)",
    )
    parser.add_argument(
        "--max-workers", type=int, default=0,
        help="Obere Schranke fuer dynamische Worker-Anzahl (default: min(CPU, 8))",
    )
    parser.add_argument(
        "--limit", type=int, default=0,
        help="Max. Texte uebersetzen (0 = alle)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Nur anzeigen, kein API-Call")
    parser.add_argument("--inventory", action="store_true", help="Inventar anzeigen")
    parser.add_argument("--source", default="de", help="Quellsprache (default: de)")
    parser.add_argument("--target", default="en", help="Zielsprache (default: en)")

    args = parser.parse_args()

    if args.inventory:
        show_inventory(args.namespace)
        return

    success = run_swarm(
        source_lang=args.source,
        target_lang=args.target,
        namespace=args.namespace,
        chunk_size=args.chunk_size,
        workers=args.workers,
        max_workers=args.max_workers,
        limit=args.limit,
        dry_run=args.dry_run,
    )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
