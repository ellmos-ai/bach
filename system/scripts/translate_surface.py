#!/usr/bin/env python3
"""
translate_surface.py
====================
Uebersetzt die Surface-Jobs aus translate_jobs.json mit Ollama.

Eingabe: /Users/lukas/.bach/backups/task_1316/translate_jobs.json
Ausgabe: /Users/lukas/.bach/backups/task_1316/translation_results.json

Logik:
- Liest translate_jobs.json.
- Nutzt OllamaClient (tools.ollama.ollama_client).
- Primaeres Modell: qwen3.8:27b-mlx
- Fallback-Modell: gemma4:26b-mlx
- Pro Job bis zu 3 Versuche mit dem Primaermodell, danach bis zu 3 Versuche
  mit dem Fallback-Modell.
- Prompt bewahrt Format, Markup, Zeilenumbrueche und Platzhalter wie
  <name>, [--mode MODE], Variablen, Befehlsnamen.
- Das Modell soll nur die reine Uebersetzung zurueckgeben.
- Fortschritt wird laufend in translation_results.json geschrieben.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parents[1]
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from tools.ollama.ollama_client import OllamaClient

INPUT_PATH = Path("/Users/lukas/.bach/backups/task_1316/translate_jobs.json")
OUTPUT_PATH = Path("/Users/lukas/.bach/backups/task_1316/translation_results.json")

PRIMARY_MODEL = "qwen3.8:27b-mlx"
FALLBACK_MODEL = "gemma4:26b-mlx"
MAX_TRIES_PRIMARY = 3
MAX_TRIES_FALLBACK = 3
SLEEP_BETWEEN_JOBS = 0.2
SLEEP_BETWEEN_RETRIES = 0.5

LANGUAGE_NAMES = {
    "de": "German",
    "en": "English",
    "es": "Spanish",
    "ja": "Japanese",
    "ru": "Russian",
    "zh": "Chinese",
}


def build_prompt(ref_lang: str, target_lang: str, ref_text: str) -> str:
    """Baut den Uebersetzungsprompt."""
    source_name = LANGUAGE_NAMES.get(ref_lang, ref_lang)
    target_name = LANGUAGE_NAMES.get(target_lang, target_lang)
    return (
        f"Translate the following {source_name} text into {target_name}.\n"
        f"Preserve all formatting, line breaks, markup, placeholders like <name>, "
        f"[--mode MODE], variables, and command names exactly as they appear.\n"
        f"Do not add explanations, notes, or markdown code fences. "
        f"Return only the translation.\n\n"
        f"Text:\n{ref_text}\n"
    )


def clean_response(text: str) -> str:
    """
    Bereinigt die Modellantwort.
    Entfernt umgebende Leerzeichen und umschliessende Markdown-Codefences,
    aber erhaelt den eigentlichen Inhalt.
    """
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def translate_one(
    client: OllamaClient,
    job: dict,
    model: str,
    max_tries: int,
) -> dict:
    """Versucht, einen Job mit einem bestimmten Modell zu uebersetzen."""
    prompt = build_prompt(
        job["reference_language"],
        job["target_language"],
        job["reference_text"],
    )
    last_error = ""
    for attempt in range(1, max_tries + 1):
        resp = client.generate(
            prompt=prompt,
            model=model,
            temperature=0.2,
            num_predict=None,
        )
        last_error = resp.error or ""
        if resp.success:
            cleaned = clean_response(resp.text)
            if cleaned:
                return {
                    "success": True,
                    "translation": cleaned,
                    "model_used": resp.model or model,
                    "attempt": attempt,
                    "duration_seconds": resp.duration_seconds,
                    "prompt_tokens": resp.prompt_tokens,
                    "completion_tokens": resp.completion_tokens,
                    "error": "",
                }
        # Bei Leerantwort oder Fehler kurz warten und wiederholen
        time.sleep(SLEEP_BETWEEN_RETRIES)

    return {
        "success": False,
        "translation": "",
        "model_used": model,
        "attempt": max_tries,
        "duration_seconds": 0.0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "error": last_error or "empty/no response",
    }


def _dedupe_by_job_id(results: list[dict]) -> list[dict]:
    """Behält nur den jeweils letzten Eintrag pro job_id."""
    seen: dict[int, dict] = {}
    for r in results:
        seen[r.get("job_id", -1)] = r
    return list(seen.values())


def save_progress(results: list[dict], stats: dict, jobs_total: int) -> None:
    """Schreibt den aktuellen Stand als JSON."""
    payload = {
        "primary_model": PRIMARY_MODEL,
        "fallback_model": FALLBACK_MODEL,
        "jobs_total": jobs_total,
        "stats": stats,
        "results": _dedupe_by_job_id(results),
    }
    with open(OUTPUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)


def main() -> int:
    client = OllamaClient(timeout=300)
    if not client.is_available():
        print("Fehler: Ollama-Server ist nicht erreichbar.", file=sys.stderr)
        return 1

    # Modelle pruefen
    available_models = {m.name for m in client.list_models()}
    missing_primary = PRIMARY_MODEL not in available_models
    missing_fallback = FALLBACK_MODEL not in available_models
    if missing_primary:
        print(
            f"Warnung: Primaermodell {PRIMARY_MODEL} nicht in Ollama-Liste. "
            f"Verfuegbare Modelle: {sorted(available_models)}",
            file=sys.stderr,
        )
    if missing_fallback:
        print(
            f"Warnung: Fallback-Modell {FALLBACK_MODEL} nicht in Ollama-Liste.",
            file=sys.stderr,
        )
    if missing_primary and missing_fallback:
        print(
            "Fehler: Weder Primaer- noch Fallback-Modell verfuegbar.",
            file=sys.stderr,
        )
        return 1

    with open(INPUT_PATH, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    jobs = data.get("jobs", [])
    jobs_total = len(jobs)
    if jobs_total == 0:
        print("Keine Jobs in translate_jobs.json gefunden.")
        return 0

    # Vorhandene Ergebnisse laden, um nach Abbruch fortsetzen zu koennen
    results: list[dict] = []
    existing_ids: set[int] = set()
    if OUTPUT_PATH.exists():
        try:
            with open(OUTPUT_PATH, "r", encoding="utf-8") as fh:
                old = json.load(fh)
            results = old.get("results", [])
            # Deduplizieren: falls ein frueherer Durchlauf fehlgeschlagen ist,
            # nur den jeweils letzten Eintrag pro job_id behalten.
            results = _dedupe_by_job_id(results)
            existing_ids = {r["job_id"] for r in results if r.get("success")}
            print(
                f"Resume-Modus: {len(existing_ids)} von {jobs_total} "
                f"uebersetzte Jobs bereits vorhanden."
            )
        except Exception as exc:
            print(
                f"Warnung: Vorhandene Ergebnisse konnten nicht geladen werden: {exc}",
                file=sys.stderr,
            )
            results = []
            existing_ids = set()

    stats = {"success": len(existing_ids), "fail": len(results) - len(existing_ids)}

    for i, job in enumerate(jobs, start=1):
        job_id = job["id"]
        if job_id in existing_ids:
            print(
                f"[{i}/{jobs_total}] Job {job_id} bereits uebersetzt – ueberspringe."
            )
            continue

        print(
            f"[{i}/{jobs_total}] Job {job_id}: {job['namespace']}.{job['key']} "
            f"({job['reference_language']} -> {job['target_language']}, "
            f"{job['category']})"
        )

        # Primaermodell
        result = translate_one(client, job, PRIMARY_MODEL, MAX_TRIES_PRIMARY)

        # Fallback, falls noetig
        if not result["success"]:
            print(
                f"  Primaermodell {PRIMARY_MODEL} fehlgeschlagen, "
                f"versuche Fallback {FALLBACK_MODEL}..."
            )
            result = translate_one(client, job, FALLBACK_MODEL, MAX_TRIES_FALLBACK)

        result.update(
            {
                "job_id": job_id,
                "namespace": job["namespace"],
                "key": job["key"],
                "target_language": job["target_language"],
                "reference_language": job["reference_language"],
                "category": job["category"],
            }
        )
        results.append(result)

        if result["success"]:
            stats["success"] += 1
            print(
                f"  OK ({result['model_used']}, "
                f"{result['duration_seconds']:.1f}s, "
                f"{result['prompt_tokens']}+{result['completion_tokens']} tokens)"
            )
        else:
            stats["fail"] += 1
            print(f"  FEHLER: {result['error']}")

        save_progress(results, stats, jobs_total)
        time.sleep(SLEEP_BETWEEN_JOBS)

    print(
        f"\nFertig. Erfolgreich: {stats['success']}/{jobs_total}, "
        f"Fehler: {stats['fail']}/{jobs_total}."
    )
    print(f"Ergebnisse gespeichert unter: {OUTPUT_PATH}")
    return 0 if stats["fail"] == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
