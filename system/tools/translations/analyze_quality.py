import sys
import re
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from db_access import build_parser, connect

sys.stdout.reconfigure(encoding='utf-8')

parser = build_parser("Analysiert die Qualitaet der BACH-Uebersetzungen.")
parser.add_argument(
    "--no-llm", action="store_true",
    help="Ollama-Plausibilitaetscheck deaktivieren.")
parser.add_argument(
    "--llm", action="store_true",
    help="Ollama-Check erzwingen (Fehler, wenn Server nicht erreichbar).")
parser.add_argument(
    "--llm-limit", type=int, default=10,
    help="Max. Stichproben fuer den LLM-Check (Default 10).")
parser.add_argument(
    "--llm-model", default=None,
    help="Ollama-Modell (Default: llama3.2).")
parser.add_argument(
    "--json-out", default=None,
    help="JSON-Report-Pfad (Default: exports/translations/analyze_quality_<ts>.json; '-' = stdout).")
args = parser.parse_args()
db_path, conn = connect(args.db)

rows = conn.execute("SELECT key, namespace, language, value, source, is_verified FROM languages_translations").fetchall()

key_map = defaultdict(dict)
for r in rows:
    ns = r['namespace'] or 'common'
    k = r['key']
    lang = r['language']
    val = r['value']
    key_map[(ns, k)][lang] = (val, r['source'])

def is_code_sql_or_technical(val):
    if not val or not isinstance(val, str):
        return True
    s = val.strip()
    if len(s) <= 3:
        return True
    # SQL
    if re.match(r'^\s*(SELECT|UPDATE|INSERT|DELETE|CREATE|ALTER|DROP|PRAGMA)\b', s, re.IGNORECASE):
        return True
    # Python code / expressions / formatting
    if s.startswith('bach ') or s.startswith('--') or s.startswith('http://') or s.startswith('https://'):
        return True
    if re.match(r'^[A-Za-z0-9_/\-\.:@]+\.py$', s):
        return True
    if re.match(r'^[A-Z0-9_\-\.\:\/]+$', s):
        return True
    if s.startswith('{') and s.endswith('}'):
        return True
    if s.startswith('[') and s.endswith(']'):
        return True
    # Variable format like {len(prompt)...}
    if '{' in s and '}' in s and ('len(' in s or 'json.' in s or 'get(' in s or 'set(' in s):
        return True
    return False

glitches = []
untranslated_copy = []
false_positives = []

for (ns, k), lang_dict in key_map.items():
    de_tuple = lang_dict.get('de')
    en_tuple = lang_dict.get('en')
    de_val = de_tuple[0] if de_tuple else ''
    en_val = en_tuple[0] if en_tuple else ''

    for lang, (val, src) in lang_dict.items():
        if not val or not isinstance(val, str):
            continue

        # 1. Glitches
        if re.search(r'\{\s+\d+\s+\}', val) or re.search(r'\{\s+[a-zA-Z0-9_]+\s+\}', val) or '% s' in val or '% d' in val:
            glitches.append((ns, k, lang, 'broken_placeholder', val))
        elif 'http ' in val or 'https ' in val or 'www. ' in val:
            glitches.append((ns, k, lang, 'broken_url', val))

        # 2. Untranslated text copy
        elif is_code_sql_or_technical(val):
            false_positives.append((ns, k, lang, 'technical', val))
        else:
            if lang not in ['de', 'en']:
                if de_val and val == de_val:
                    untranslated_copy.append((ns, k, lang, 'identical_to_de', val))
                elif en_val and val == en_val:
                    untranslated_copy.append((ns, k, lang, 'identical_to_en', val))
            elif lang == 'en':
                if de_val and val == de_val:
                    untranslated_copy.append((ns, k, lang, 'en_identical_to_de', val))

print(f"Total entries checked: {len(rows)}")
print(f"Detected Glitches (placeholder/URL formatting errors): {len(glitches)}")
print(f"Detected Genuine Untranslated Copy: {len(untranslated_copy)}")
print(f"Technical / Code / False Positives: {len(false_positives)}")

print("\n--- SAMPLE GLITCHES ---")
for item in glitches[:10]:
    print(f"[{item[0]}] key={item[1]} lang={item[2]} issue={item[3]}: '{item[4]}'")

print("\n--- SAMPLE UNTRANSLATED COPY BY NAMESPACE ---")
by_ns = defaultdict(list)
for item in untranslated_copy:
    by_ns[item[0]].append(item)

for ns, items in sorted(by_ns.items(), key=lambda x: len(x[1]), reverse=True):
    print(f"\nNamespace '{ns}': {len(items)} items")
    for item in items[:3]:
        print(f"  key={item[1]} lang={item[2]} issue={item[3]}: '{item[4][:80]}'")

# ═══════════════════════════════════════════════════════════════════════════
# LLM-PLAUSIBILITAETSCHECK VIA OLLAMA (Job-Zweck von 'translation_qa_verify')
# Stichproben aus: 1) identischen Kopien (identical_to_de/en), 2) unverifizierten
# Eintraegen (is_verified=0). Läuft nur, wenn Ollama erreichbar ist; andernfalls
# sauberer Skip (Exit-Code bleibt 0, damit der Scheduler-Job nicht crash't).
# ═══════════════════════════════════════════════════════════════════════════

llm_checks = []
llm_meta = {
    "attempted": False,
    "available": False,
    "model": None,
    "candidates": 0,
    "checked": 0,
    "errors": 0,
}

def _base_of(ns, k, lang):
    """Basiswert (de -> en) fuer einen Key liefern, language 'lang' ausgenommen."""
    lang_dict = key_map.get((ns, k), {})
    for bl in ('de', 'en'):
        if bl != lang and bl in lang_dict:
            val = lang_dict[bl][0]
            if val and str(val).strip():
                return bl, str(val)
    return '', ''

def _llm_candidates(limit):
    """Stichproben-Kandidaten: 1) identische Kopien, 2) unverifizierte Rest-Eintraege."""
    out = []
    seen = set()
    for ns, k, lang, issue, val in untranslated_copy:
        if len(out) >= limit:
            break
        if (ns, k, lang) in seen:
            continue
        seen.add((ns, k, lang))
        base_lang = 'de' if issue.endswith('_to_de') else 'en'
        out.append({
            "namespace": ns, "key": k, "language": lang, "issue": issue,
            "value": val[:300], "base_lang": base_lang, "base_value": val[:300],
        })
    if len(out) < limit:
        for r in rows:
            if len(out) >= limit:
                break
            ns = r['namespace'] or 'common'
            k, lang, val = r['key'], r['language'], r['value']
            if (ns, k, lang) in seen or lang in ('de', 'en'):
                continue
            if r['is_verified']:
                continue
            if not val or not isinstance(val, str) or is_code_sql_or_technical(val):
                continue
            bl, bv = _base_of(ns, k, lang)
            if not bv:
                continue
            seen.add((ns, k, lang))
            out.append({
                "namespace": ns, "key": k, "language": lang, "issue": "unverified",
                "value": val[:300], "base_lang": bl, "base_value": bv[:300],
            })
    return out

def _parse_verdict(text):
    """LLM-Antwort robust parsen -> (verdict, reason)."""
    m = re.search(r'\{.*\}', text, re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group(0))
            v = str(obj.get("verdict", "")).lower()
            if v in ("ok", "suspicious"):
                return v, str(obj.get("reason", ""))[:200]
        except Exception:
            pass
    low = text.lower()
    if "suspicious" in low:
        return "suspicious", text.strip()[:200]
    if '"ok"' in low or "'ok'" in low or low.strip() == "ok":
        return "ok", text.strip()[:200]
    return "unparsed", text.strip()[:200]

def _pick_model(client, requested):
    """Robuste Modell-Auswahl: explizit > bevorzugte Kandidaten > erstes verfuegbares."""
    if requested:
        return requested
    preferred = [
        OllamaClient.DEFAULT_MODEL,       # llama3.2
        "qwen3.5:4b",                     # klein & schnell
        "gemma4:e2b",
        "qwen3.8:27b-mlx",
    ]
    try:
        models = [m.name for m in client.list_models()]
    except Exception:
        models = []
    for name in preferred:
        if name in models:
            return name
    for name in models:
        low = name.lower()
        if "embed" in low or "ocr" in low:
            continue
        return name
    return OllamaClient.DEFAULT_MODEL

if args.no_llm:
    print("\n--- LLM-CHECK: uebersprungen (--no-llm) ---")
else:
    llm_meta["attempted"] = True
    try:
        _tools_ollama = Path(__file__).resolve().parents[1] / "ollama"
        sys.path.insert(0, str(_tools_ollama))
        from ollama_client import OllamaClient

        client = OllamaClient()
        llm_meta["available"] = client.is_available()
        if not llm_meta["available"]:
            if args.llm:
                raise SystemExit(
                    "[FEHLER] --llm gefordert, aber Ollama ist nicht erreichbar.")
            print("\n--- LLM-CHECK: Ollama nicht erreichbar -> uebersprungen ---")
        else:
            llm_meta["model"] = _pick_model(client, args.llm_model)
            cands = _llm_candidates(max(0, args.llm_limit))
            llm_meta["candidates"] = len(cands)
            print(f"\n--- LLM-PLAUSIBILITAETSCHECK "
                  f"(Ollama, Modell: {llm_meta['model']}, Stichprobe: {len(cands)}) ---")
            for cand in cands:
                prompt = (
                    "Pruefe, ob der Zielwert eine plausible "
                    f"{cand['language']}-Uebersetzung des Basiswerts ist.\n"
                    "Identische Werte sind akzeptabel bei Eigennamen, Befehlen, "
                    "Akronymen, Codes oder kurzen Tokens.\n"
                    f"Basis ({cand['base_lang']}): {cand['base_value']}\n"
                    f"Ziel ({cand['language']}): {cand['value']}\n"
                    'Antworte AUSSCHLIESSLICH mit JSON: '
                    '{"verdict": "ok" oder "suspicious", "reason": "kurze Begruendung"}'
                )
                resp = client.generate(
                    prompt,
                    model=llm_meta["model"],
                    system=("Du bist ein Uebersetzungs-QA-Pruefer fuer das Projekt BACH. "
                            "Antworte nur mit dem geforderten JSON."),
                    temperature=0,
                    num_predict=200,
                    think=False,
                )
                if not resp.success:
                    llm_meta["errors"] += 1
                    print(f"  [ERR ] [{cand['namespace']}] {cand['key']} "
                          f"({cand['language']}): {resp.error} "
                          f"(Modell: {llm_meta['model']} installiert?)")
                    llm_checks.append({**cand, "verdict": "error",
                                       "reason": resp.error, "model": resp.model})
                    continue
                if not resp.text.strip():
                    llm_meta["errors"] += 1
                    print(f"  [ERR ] [{cand['namespace']}] {cand['key']} "
                          f"({cand['language']}): leere Antwort "
                          f"(Modell: {llm_meta['model']})")
                    llm_checks.append({**cand, "verdict": "error",
                                       "reason": "empty response", "model": resp.model})
                    continue
                verdict, reason = _parse_verdict(resp.text)
                llm_meta["checked"] += 1
                flag = "OK  " if verdict == "ok" else (
                    "SUSP" if verdict == "suspicious" else "?   ")
                print(f"  [{flag}] [{cand['namespace']}] {cand['key']} "
                      f"({cand['language']}): {reason[:80]}")
                llm_checks.append({**cand, "verdict": verdict,
                                   "reason": reason, "model": resp.model})
    except ImportError:
        print("\n--- LLM-CHECK: ollama_client nicht verfuegbar -> uebersprungen ---")
    except SystemExit:
        raise
    except Exception as e:
        print(f"\n--- LLM-CHECK: abgebrochen ({e}) ---")

# ═══════════════════════════════════════════════════════════════════════════
# JSON-REPORT (maschinenlesbarer Output neben dem Print-Report)
# ═══════════════════════════════════════════════════════════════════════════

report = {
    "generated_at": datetime.now().isoformat(),
    "script": "analyze_quality.py",
    "db": str(db_path),
    "total_entries": len(rows),
    "summary": {
        "glitches": len(glitches),
        "untranslated_copy": len(untranslated_copy),
        "technical_false_positives": len(false_positives),
    },
    "glitches": [
        {"namespace": g[0], "key": g[1], "language": g[2],
         "issue": g[3], "value": g[4]}
        for g in glitches
    ],
    "untranslated_copy_by_ns": {
        ns: len(items) for ns, items in by_ns.items()
    },
    "llm": llm_meta,
    "llm_checks": llm_checks,
}

json_out = args.json_out
if json_out is None:
    out_dir = Path(__file__).resolve().parents[2] / "exports" / "translations"
    out_dir.mkdir(parents=True, exist_ok=True)
    json_out = str(out_dir / (
        f"analyze_quality_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"))
if json_out == "-":
    print("\n" + json.dumps(report, ensure_ascii=False, indent=2))
else:
    Path(json_out).write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nJSON-Report: {json_out}")
