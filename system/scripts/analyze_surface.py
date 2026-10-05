#!/usr/bin/env python3
"""
analyze_surface.py
==================
Baut aus work_surface.json die translate_jobs.json fuer Task #1317.

Eingabe: /Users/lukas/.bach/backups/task_1316/work_surface.json
Ausgabe: /Users/lukas/.bach/backups/task_1316/translate_jobs.json

Logik:
- Liest work_surface.json (items + wrong_verified_ids).
- Gruppiert die 212 Surface-Items nach (namespace, key).
- Pro Item wird ein Uebersetzungsjob angelegt (target_language = requested_language),
  AUSSER die ID des Zielsprachen-Eintrags ist in wrong_verified_ids.
- Referenz: DE bevorzugt, sonsten die "beste" vorhandene Nicht-DE-Sprache
  (verifiziert vor unverifiziert, dann en > es > ja > ru > zh).
- Kategorie: nach raw_de_len pro Key: short (<100), medium (100-250), long (>=250).
- Schreibt translate_jobs.json mit 212 Jobs.
"""

import json
from pathlib import Path
from collections import defaultdict, Counter

INPUT_PATH = Path("/Users/lukas/.bach/backups/task_1316/work_surface.json")
OUTPUT_PATH = Path("/Users/lukas/.bach/backups/task_1316/translate_jobs.json")

ALL_LANGUAGES = ["de", "en", "es", "ja", "ru", "zh"]
NON_DE_LANGS = ["en", "es", "ja", "ru", "zh"]


def categorize(de_len: int) -> str:
    if de_len < 100:
        return "short"
    if de_len < 250:
        return "medium"
    return "long"


def score_reference(lang: str, entry: dict) -> tuple:
    """
    Bestimmt die Qualitaet eines Referenz-Eintrags.
    Hoeherer Tuple-Wert = besser.
    """
    is_verified = bool(entry.get("is_verified", 0))
    has_value = bool(entry.get("value", "").strip())
    # Verifiziert + Wert vorhanden ist am besten
    return (is_verified, has_value, NON_DE_LANGS.index(lang) if lang in NON_DE_LANGS else 99)


def pick_reference(db: dict):
    """Waehlt Referenzsprache und -text. DE bevorzugt, sonst beste Nicht-DE."""
    de_entry = db.get("de", {})
    de_text = de_entry.get("value", "")
    if de_text.strip():
        return "de", de_text

    candidates = []
    for lang in NON_DE_LANGS:
        entry = db.get(lang, {})
        value = entry.get("value", "")
        if value.strip():
            candidates.append((score_reference(lang, entry), lang, value))

    if candidates:
        candidates.sort(reverse=True)
        return candidates[0][1], candidates[0][2]

    # Fallback: irgendeinen vorhandenen Wert nehmen
    for lang in ALL_LANGUAGES:
        entry = db.get(lang, {})
        value = entry.get("value", "")
        if value.strip():
            return lang, value

    return "de", ""


def main():
    with open(INPUT_PATH, "r", encoding="utf-8") as f:
        surface = json.load(f)

    items = surface.get("items", [])
    wrong_verified = surface.get("wrong_verified_ids", [])
    ignore_ids = {w["id"] for w in wrong_verified}

    # Gruppieren nach (namespace, key)
    grouped = defaultdict(list)
    for item in items:
        grouped[(item["namespace"], item["key"])].append(item)

    jobs = []
    job_id = 1
    key_categories = Counter()
    job_categories = Counter()
    ignored_jobs = []

    for (namespace, key), key_items in sorted(grouped.items()):
        # db ist fuer alle Items desselben Keys identisch; erstes nehmen
        db = key_items[0]["db"]
        de_entry = db.get("de", {})
        de_text = de_entry.get("value", "")
        de_len = len(de_text)
        category = categorize(de_len)
        key_categories[category] += 1

        ref_lang, ref_text = pick_reference(db)

        # Pro Surface-Item fuer diesen Key einen Job erzeugen
        for item in key_items:
            target_lang = item.get("requested_language", "")
            if target_lang not in db:
                continue
            target_entry = db[target_lang]
            target_id = target_entry.get("id")

            if target_id in ignore_ids:
                ignored_jobs.append({
                    "id": target_id,
                    "namespace": namespace,
                    "key": key,
                    "target_language": target_lang,
                    "reason": "wrong_verified_id"
                })
                continue

            job = {
                "id": job_id,
                "namespace": namespace,
                "key": key,
                "target_language": target_lang,
                "reference_language": ref_lang,
                "reference_text": ref_text,
                "target_text_existing": target_entry.get("value", ""),
                "category": category,
                "de_len": de_len,
                "source": "manual_qa_1317",
                "existing_verified": bool(target_entry.get("is_verified", 0)),
                "translation_id": target_id,
            }
            jobs.append(job)
            job_categories[category] += 1
            job_id += 1

    result = {
        "input": str(INPUT_PATH),
        "output": str(OUTPUT_PATH),
        "total_jobs": len(jobs),
        "ignored_count": len(ignored_jobs),
        "ignored_jobs": ignored_jobs,
        "key_category_counts": dict(key_categories),
        "job_category_counts": dict(job_categories),
        "jobs": jobs,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"analyze_surface.py: {len(jobs)} jobs written to {OUTPUT_PATH}")
    print(f"Ignored wrong-verified jobs: {len(ignored_jobs)}")
    print(f"Key category counts: {dict(key_categories)}")
    print(f"Job category counts: {dict(job_categories)}")


if __name__ == "__main__":
    main()
