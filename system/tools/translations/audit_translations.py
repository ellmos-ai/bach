import re
import sys
from collections import defaultdict
from datetime import datetime
from db_access import build_parser, connect

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

parser = build_parser("Auditiert fehlende und verdaechtige BACH-Uebersetzungen.")
parser.add_argument(
    "--no-tasks", action="store_true",
    help="Keine BACH-Tasks anlegen (nur Report).")
parser.add_argument(
    "--max-desc-keys", type=int, default=15,
    help="Max. Beispiel-Keys pro Task-Beschreibung (Default 15).")
args = parser.parse_args()
db_path, conn = connect(args.db)

target_langs = ['de', 'en', 'es', 'ru', 'ja', 'zh']

# 1. Fetch all rows from languages_translations
all_rows = conn.execute("SELECT key, namespace, language, value, source, is_verified FROM languages_translations").fetchall()

# Map: (namespace, key) -> { lang -> value }
key_map = defaultdict(dict)
source_map = defaultdict(dict)
verified_map = defaultdict(dict)

for r in all_rows:
    ns = r['namespace'] or 'common'
    k = r['key']
    lang = r['language']
    val = r['value']
    key_map[(ns, k)][lang] = val
    source_map[(ns, k)][lang] = r['source']
    verified_map[(ns, k)][lang] = r['is_verified']

print(f"Total unique (namespace, key) pairs: {len(key_map)}")

# 2. Find missing translations per language
missing_by_lang = defaultdict(list)

for (ns, k), lang_dict in key_map.items():
    # If key exists in at least one language
    for lang in target_langs:
        if lang not in lang_dict or lang_dict[lang] is None or str(lang_dict[lang]).strip() == '':
            missing_by_lang[lang].append((ns, k))

print("\n--- MISSING TRANSLATIONS PER LANGUAGE ---")
for lang in target_langs:
    print(f"{lang.upper()}: {len(missing_by_lang[lang])} missing keys")

if any(len(missing_by_lang[l]) > 0 for l in target_langs):
    print("\nSample missing keys:")
    for lang in target_langs:
        if missing_by_lang[lang]:
            print(f"  {lang}: {missing_by_lang[lang][:10]}")

# 3. Analyze namespaces of missing keys
ns_missing = defaultdict(lambda: defaultdict(int))
for lang in target_langs:
    for (ns, k) in missing_by_lang[lang]:
        ns_missing[ns][lang] += 1

print("\n--- MISSING KEYS BREAKDOWN BY NAMESPACE ---")
for ns in sorted(ns_missing.keys()):
    counts = ", ".join(f"{l}:{ns_missing[ns][l]}" for l in target_langs if ns_missing[ns][l] > 0)
    print(f"  Namespace '{ns}': {counts}")

# 4. Spot check existing translations (skills & help namespaces + general)
def is_technical(v):
    if not v:
        return True
    if v.startswith('--') or v.startswith('bach ') or v.startswith('http://') or v.startswith('https://'):
        return True
    if re.match(r'^[A-Z0-9_]+$', v):
        return True
    if re.match(r'^\s*[\{\}\[\]"\'\:\,\.\/\\]+\s*$', v):
        return True
    return False

print("\n--- SPOT CHECK: POTENTIAL ISSUES IN EXISTING TRANSLATIONS ---")

suspicious = []

# Broken placeholder: '{ ' and ' }' must form a pair in the SAME line.
# Multi-line JSON/YAML blocks in help docs (closing brace on its own line) are
# legitimate and must not trigger a false positive (v1.1 fix, Task #1296).
BROKEN_PLACEHOLDER_RE = re.compile(r'\{[^{}\n]*? \}|\{ [^{}\n]*\}')

def _has_broken_placeholder(v):
    """True, wenn ein echtes kaputtes Platzhalter-Muster wie '{ 0 }' vorliegt.
    Einzeilige JSON-Objekte ('{ "key": "value" }') werden ausgenommen:
    der Inhalt beginnt mit einem Anfuehrungszeichen, echte Platzhalter
    (Variablen-/Nummernnamen) tun das nie."""
    for m in BROKEN_PLACEHOLDER_RE.finditer(v):
        if re.match(r'\s*"', m.group(0)[1:]):
            continue
        return True
    return False

for (ns, k), lang_dict in key_map.items():
    # Check if German or English is available as base
    base_lang = 'de' if 'de' in lang_dict else ('en' if 'en' in lang_dict else list(lang_dict.keys())[0])
    base_val = lang_dict[base_lang]

    if is_technical(base_val):
        continue

    for lang in target_langs:
        if lang in lang_dict:
            # Skip entries already verified (manually or via OLLAMA confirmed as legitimate)
            if verified_map.get((ns, k), {}).get(lang):
                continue
            val = lang_dict[lang]
            # Check 1: Target equals German base in non-German language
            if lang != 'de' and val == lang_dict.get('de') and len(val) > 5 and not is_technical(val):
                suspicious.append((ns, k, lang, "Identical to German", val[:50]))

            # Check 2: Target equals English base in non-English language (and non-German)
            elif lang not in ['en', 'de'] and val == lang_dict.get('en') and len(val) > 5 and not is_technical(val):
                suspicious.append((ns, k, lang, "Identical to English", val[:50]))

            # Check 3: Check for glitchy automatic translations (e.g. broken html/markdown, weird placeholders like { 0 }, bad characters)
            # v1.1 (Task #1296): only same-line placeholder pairs trigger; multi-line
            # JSON blocks and one-line JSON objects are fine
            if _has_broken_placeholder(val) or '% s' in val or '% d' in val:
                suspicious.append((ns, k, lang, "Broken placeholder spaces", val[:50]))

            if 'http ' in val or 'https ' in val or 'www. ' in val:
                suspicious.append((ns, k, lang, "Broken URL spaces", val[:50]))

print(f"Total suspicious translation entries found: {len(suspicious)}")

# Break down suspicious by namespace
ns_susp = defaultdict(int)
for item in suspicious:
    ns_susp[item[0]] += 1

print("\nSuspicious entries by namespace:")
for ns, cnt in sorted(ns_susp.items(), key=lambda x: x[1], reverse=True):
    print(f"  {ns}: {cnt}")

print("\nSample suspicious entries:")
for item in suspicious[:15]:
    print(f"  [{item[0]}] key={item[1]} lang={item[2]} issue='{item[3]}' val='{item[4]}'")

# ═══════════════════════════════════════════════════════════════════════════
# 5. IDLE-TASKS FUER OLLAMA ERZEUGEN (Job-Zweck von 'translation_qa_missing')
#    Aggregiert und idempotent: pro Sprache / Issue-Kategorie max. 1 offener
#    Task (Dedup via Titel-Prefix), damit Scheduler-Laeufe keinen Task-Spam
#    erzeugen. Offene Tasks werden vom OLLAMA-/Idle-Worker abgearbeitet.
# ═══════════════════════════════════════════════════════════════════════════

def _task_open(title_prefix: str) -> bool:
    """True, wenn bereits ein offener Task mit diesem Titel-Prefix existiert."""
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM tasks "
            "WHERE status IN ('pending', 'open', 'in_progress') "
            "AND title LIKE ?",
            (title_prefix + '%',)
        ).fetchone()
        return row[0] > 0
    except Exception:
        return False

def _base_value(ns, k):
    """Besten Basiswert (de -> en -> erster) fuer einen Key liefern."""
    lang_dict = key_map.get((ns, k), {})
    for bl in ('de', 'en'):
        v = lang_dict.get(bl)
        if v and str(v).strip():
            return bl, str(v)
    for bl, v in lang_dict.items():
        if v and str(v).strip():
            return bl, str(v)
    return '', ''

def _create_task(title: str, description: str) -> bool:
    """Aggregierten QA-Task anlegen (P4, category 'ollama')."""
    try:
        conn.execute(
            "INSERT INTO tasks (title, description, priority, status, "
            "category, created_by, created_at) "
            "VALUES (?, ?, 'P4', 'pending', 'ollama', 'translation_qa_missing', ?)",
            (title, description, datetime.now().isoformat())
        )
        conn.commit()
        return True
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        print(f"  [WARN] Task-Anlage fehlgeschlagen: {e}")
        return False

tasks_created = 0
tasks_skipped = 0

if args.no_tasks:
    print("\n--- IDLE-TASKS: uebersprungen (--no-tasks) ---")
else:
    print("\n--- IDLE-TASKS FUER OLLAMA ---")

    # 5a. Fehlende Keys -> 1 Task pro betroffener Sprache
    for lang in target_langs:
        missing = missing_by_lang[lang]
        if not missing:
            continue
        prefix = f"Translation-QA: Fehlende Keys in {lang.upper()}"
        title = f"{prefix} [N={len(missing)}]"
        if _task_open(prefix):
            tasks_skipped += 1
            print(f"  [SKIP] offener Task existiert bereits: {prefix}")
            continue
        ns_counts = defaultdict(int)
        for ns, _k in missing:
            ns_counts[ns] += 1
        lines = [
            "Auto-Task vom Scheduler-Job 'translation_qa_missing' (audit_translations.py).",
            f"{len(missing)} fehlende Uebersetzungs-Keys in Sprache '{lang}'.",
            "",
            "Namespace-Breakdown: " + ", ".join(
                f"{ns}:{cnt}" for ns, cnt in
                sorted(ns_counts.items(), key=lambda x: -x[1])),
            "",
            f"Beispiele (max. {args.max_desc_keys}; Key -> Basiswert [Basis-Sprache]):",
        ]
        for ns, k in missing[:args.max_desc_keys]:
            bl, bv = _base_value(ns, k)
            lines.append(f"  - [{ns}] {k} [{bl}]: {bv[:120]}")
        lines += [
            "",
            "Auftrag (OLLAMA-Idle-Worker): Fehlende Sprachwerte via Ollama uebersetzen",
            "und eintragen, z.B.:",
            "  UPDATE languages_translations SET value=?, is_verified=1, source='ollama'",
            "  WHERE key=? AND namespace=? AND language=?",
            "(bzw. passende Zeile via INSERT anlegen, Schema siehe Tabelle).",
            "Vollstaendige Liste: python system/tools/translations/audit_translations.py --no-tasks",
        ]
        if _create_task(title, "\n".join(lines)):
            tasks_created += 1
            print(f"  [NEW ] {title}")

    # 5b. Suspicious Keys -> 1 Task pro Issue-Kategorie
    suspicious_groups = defaultdict(list)
    for item in suspicious:
        suspicious_groups[item[3]].append(item)

    for reason, items in sorted(suspicious_groups.items()):
        prefix = f"Translation-QA: {reason}"
        title = f"{prefix} [N={len(items)}]"
        if _task_open(prefix):
            tasks_skipped += 1
            print(f"  [SKIP] offener Task existiert bereits: {prefix}")
            continue
        lines = [
            "Auto-Task vom Scheduler-Job 'translation_qa_missing' (audit_translations.py).",
            f"{len(items)} potenziell problematische Uebersetzungen (Issue: '{reason}').",
            "",
            f"Beispiele (max. {args.max_desc_keys}; ns / key / lang / Wert):",
        ]
        for ns, k, lang, _r, val in items[:args.max_desc_keys]:
            lines.append(f"  - [{ns}] {k} ({lang}): {val}")
        lines += [
            "",
            "Auftrag (OLLAMA-Idle-Worker): Via Ollama pruefen, ob die Werte korrekt sind:",
            "- legitim (Eigennamen, Befehle, Akronyme, Codes, kurze Tokens):",
            "  UPDATE languages_translations SET is_verified=1 WHERE key=? AND namespace=? AND language=?;",
            "- fehlerhaft: korrekte Uebersetzung via Ollama erzeugen und value aktualisieren,",
            "  anschliessend is_verified=1 setzen.",
            "Vollstaendige Liste: python system/tools/translations/audit_translations.py --no-tasks",
        ]
        if _create_task(title, "\n".join(lines)):
            tasks_created += 1
            print(f"  [NEW ] {title}")

    print(f"\nTasks erstellt: {tasks_created}, bereits offen (skip): {tasks_skipped}")
