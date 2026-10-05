#!/usr/bin/env python3
"""
Analysiert den Stand der 1317.3-Übersetzungen.
Vergleicht translate_jobs.json mit translation_results.json,
berücksichtigt wrong_verified_ids und berechnet fehlende Übersetzungen.
"""
import json
from pathlib import Path
from collections import Counter, defaultdict

ROOT = Path('/Users/lukas/.bach/backups/task_1316')
JOBS_FILE = ROOT / 'translate_jobs.json'
RESULTS_FILE = ROOT / 'translation_results.json'
WORK_FILE = ROOT / 'work_surface.json'

WRONG_VERIFIED_IDS = {6691, 6840, 6841, 12471}

def load_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def main():
    jobs_data = load_json(JOBS_FILE)
    results_data = load_json(RESULTS_FILE)
    work_data = load_json(WORK_FILE)

    jobs = jobs_data['jobs']
    results = results_data.get('results', [])

    print('=== translate_jobs.json ===')
    print(f"total_jobs: {jobs_data['total_jobs']}")
    print(f"key_category_counts: {jobs_data['key_category_counts']}")
    print(f"job_category_counts: {jobs_data['job_category_counts']}")

    print('\n=== translation_results.json ===')
    print(f"jobs_total (meta): {results_data.get('jobs_total')}")
    print(f"stats: {results_data.get('stats')}")
    print(f"results count: {len(results)}")

    success_results = [r for r in results if r.get('success')]
    failed_results = [r for r in results if not r.get('success')]
    print(f"success: {len(success_results)}, failed: {len(failed_results)}")

    if results:
        success_ids = sorted({r['job_id'] for r in success_results if 'job_id' in r})
        print(f"successful job IDs: {success_ids[:10]}...{success_ids[-10:] if len(success_ids)>20 else ''}")
        print(f"min id: {min(success_ids)}, max id: {max(success_ids)}, unique: {len(set(success_ids))}")

    # Jobs ohne Ergebnis
    result_job_ids = {r.get('job_id') for r in results if 'job_id' in r}
    missing_jobs = [j for j in jobs if j['id'] not in result_job_ids]
    print(f"\n=== Fehlende Übersetzungen ===")
    print(f"Jobs ohne Ergebnis: {len(missing_jobs)} / {len(jobs)}")

    by_cat = Counter(j['category'] for j in missing_jobs)
    print(f"fehlend nach Kategorie: {dict(by_cat)}")

    # Detaillierte fehlende Pro Key/Sprache
    missing_by_key = defaultdict(list)
    for j in missing_jobs:
        missing_by_key[(j['namespace'], j['key'])].append(j['target_language'])

    print(f"fehlende Keys: {len(missing_by_key)}")
    for (ns, key), langs in sorted(missing_by_key.items())[:20]:
        print(f"  {ns}.{key}: {langs}")
    if len(missing_by_key) > 20:
        print(f"  ... und {len(missing_by_key)-20} weitere")

    # Prüfe, ob existing_verified = true bei allen, und ob das stimmt
    print("\n=== existing_verified Analyse ===")
    ev_true = sum(1 for j in jobs if j.get('existing_verified'))
    ev_false = len(jobs) - ev_true
    print(f"existing_verified=true: {ev_true}, false: {ev_false}")

    # wrong_verified_ids aus work_surface
    items = work_data.get('items', work_data if isinstance(work_data, list) else [])
    wrong_in_work = []
    for item in items:
        if item.get('id') in WRONG_VERIFIED_IDS:
            wrong_in_work.append(item)
    print(f"\nwrong_verified_ids in work_surface: {len(wrong_in_work)}")
    for item in wrong_in_work:
        print(f"  id={item.get('id')} key={item.get('key')} lang={item.get('language')} verified={item.get('is_verified')} source={item.get('source')}")

    # Jobs, deren existing_verified widersprüchlich ist
    jobs_with_wrong_id = [j for j in jobs if j.get('translation_id') in WRONG_VERIFIED_IDS]
    print(f"\nJobs mit translation_id in WRONG_VERIFIED_IDS: {len(jobs_with_wrong_id)}")
    for j in jobs_with_wrong_id:
        print(f"  job_id={j['id']} key={j['key']} lang={j['target_language']} translation_id={j.get('translation_id')} existing_verified={j.get('existing_verified')}")

    # Jobs die tatsächlich übersetzt werden müssen:
    # - Ergebnis fehlt ODER existing_verified ist falsch/widersprüchlich
    needs_translation = []
    for j in jobs:
        needs = False
        if j['id'] not in result_job_ids:
            needs = True
        if j.get('translation_id') in WRONG_VERIFIED_IDS:
            needs = True
        if not j.get('existing_verified'):
            needs = True
        if needs:
            needs_translation.append(j)

    print(f"\n=== Übersetzungsbedarf gesamt ===")
    print(f"Jobs, die (neu) übersetzt/validiert werden müssen: {len(needs_translation)}")
    by_cat2 = Counter(j['category'] for j in needs_translation)
    print(f"nach Kategorie: {dict(by_cat2)}")

    # Für Task-Text '110 medium/lange': prüfe medium+long fehlend
    medium_long_missing = [j for j in missing_jobs if j['category'] in ('medium','long')]
    print(f"\nFehlende medium+long Jobs: {len(medium_long_missing)}")
    print(f"  medium: {sum(1 for j in medium_long_missing if j['category']=='medium')}")
    print(f"  long:   {sum(1 for j in medium_long_missing if j['category']=='long')}")

if __name__ == '__main__':
    main()
