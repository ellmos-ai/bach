#!/usr/bin/env python3
"""Review /tmp/german_verified_candidates.json für Task #1565.

Ziel: echte deutsche Text-Tokens isolieren; Code/SQL/Identifier/Englisch-Mischtreffer entfernen.
"""
import json
import re
from pathlib import Path

INPUT = Path("/Users/lukas/.bach/backups/task_1316/german_verified_candidates.json")
OUTPUT = Path("/Users/lukas/.bach/backups/task_1316/german_verified_candidates_reviewed.json")

# deutsche Wortmarker: häufige deutsche Wörter oder Wortteile
GERMAN_WORDS = re.compile(
    r"\b("
    r"[Aa]ber|[Aa]lle|[Aa]ls|[Aa]uch|[Aa]uf|[Aa]us|[Bb]ei|[Bb]eim|[Bb]ereits|[Bb]esser|"
    r"[Bb]evor|[Dd]a|[Dd]as|[Dd]ass|[Dd]eine?|[Dd]em|[Dd]en|[Dd]er|[Dd]es|[Dd]ich|"
    r"[Dd]iese?n?|[Dd]u|[Dd]urch|[Ee]in(?:e|en|em|er)?|[Ee]s|[Ff]ür|[Gg]eht|[Gg]ibt|"
    r"[Hh]aben|[Hh]ast|[Hh]att(?:e|est)|[Hh]ier|[Hh]och|[Ii]ch|[Ii]hm|[Ii]hn|[Ii]hre?|"
    r"[Ii]m|[Ii]n|[Ii]st|[Jj]a|[Kk]ann|[Kk]eine?|[Mm]al|[Mm]an|[Mm]ehr|[Mm]ein(?:e|en|em|er)?|"
    r"[Mm]it|[Mm]öchte|[Mm]uss|[Nn]ach|[Nn]icht|[Nn]och|[Nn]ur|[Oo]der|[Ss]chon|[Ss]ehr|"
    r"[Ss]ein(?:e|en|em|er)?|[Ss]ich|[Ss]ind|[Ss]oll(?:te)?|[Ss]ondern|[Ss]tatt|[Uu]m|"
    r"[Uu]nd|[Uu]nter|[Vv]om|[Vv]on|[Vv]or|[Vv]orher|[Ww]ar|[Ww]as|[Ww]egen|[Ww]eitere?|"
    r"[Ww]enn|[Ww]er|[Ww]erde|[Ww]erden|[Ww]ie|[Ww]ieder|[Ww]ill|[Ww]ir|[Ww]ird|[Ww]o|"
    r"[Ww]ohl|[Zz]u|[Zz]um|[Zz]ur|[Zz]urück|[Zz]wischen"
    r")\b",
    re.UNICODE,
)

# Technische/englische Stopmarker, die einen Eintrag als eher Code/SQL/Identifier einstufen
TECH_MARKERS = re.compile(
    r"\b(SELECT|FROM|WHERE|INSERT|UPDATE|DELETE|JOIN|CREATE|TABLE|DROP|ALTER|"
    r"VALUES|INTO|SET|INDEX|REFERENCES|PRIMARY|KEY|FOREIGN|NOT\s+NULL|UNIQUE|"
    r"DEFAULT|AUTOINCREMENT|CASCADE|sqlite_|INTEGER|TEXT|REAL|BLOB|DATETIME|BOOLEAN|"
    r"handler|connector|namespace|is_verified|JSON|SQL|API|CLI|URL|URI|UUID|SHA256|"
    r"dist_|manifest|version|template|core|hub/|tools/|tests/|\.py|\.md|\.json|"
    r"bach_|_id|__pycache__|pytest|ollama|qwen|mlx|homebrew)"
    r"\b",
    re.IGNORECASE,
)


def has_umlaut_or_sz(text: str) -> bool:
    return bool(re.search(r"[äöüÄÖÜß]", text))


def looks_like_german_sentence(text: str) -> bool:
    """Echte deutsche Sätze erkennen: mindestens ein Umlaut/ß und deutsche Funktionswörter."""
    if not has_umlaut_or_sz(text):
        return False
    german_word_hits = len(GERMAN_WORDS.findall(text))
    # Mindestens 2 deutsche Wörter und ein Umlaut
    return german_word_hits >= 2


def score_candidate(item: dict) -> dict:
    value = item.get("value", "")
    text = f"{item.get('namespace', '')} {item.get('key', '')} {value}"
    umlaut = has_umlaut_or_sz(text)
    german_words = len(GERMAN_WORDS.findall(text))
    tech_hits = len(TECH_MARKERS.findall(text))
    # Heuristik: je mehr deutsche Wörter und Umlaute, desto wahrscheinlicher echter deutscher Text.
    # Je mehr Tech-Marker, desto wahrscheinlicher False Positive.
    score = german_words * 2 + int(umlaut) * 3 - tech_hits * 2
    return {
        **item,
        "_umlaut": umlaut,
        "_german_words": german_words,
        "_tech_hits": tech_hits,
        "_score": score,
    }


def main():
    data = json.loads(INPUT.read_text(encoding="utf-8"))
    print(f"Eingelesen: {len(data)} Kandidaten")

    scored = [score_candidate(i) for i in data]

    # Hochkonfidente echte deutsche Treffer
    high_confidence = [s for s in scored if s["_score"] >= 4 and s["_german_words"] >= 2 and s["_umlaut"]]
    # Mittlere Konfidenz: deutsche Wörter + Umlaut, aber auch Tech-Marker
    medium = [s for s in scored if 0 < s["_score"] < 4 and s["_umlaut"]]
    # Wahrscheinliche False Positives
    low = [s for s in scored if s["_score"] <= 0 or not s["_umlaut"]]

    print(f"high_confidence={len(high_confidence)}, medium={len(medium)}, low={len(low)}")

    # Sortiert ausgeben
    for label, subset in [("HIGH", high_confidence), ("MEDIUM", medium), ("LOW", low)]:
        print(f"\n=== {label} ({len(subset)}) ===")
        for item in subset[:10]:
            snippet = item["value"].replace("\n", " ")[:120]
            print(
                f"  id={item['id']} ns={item['namespace']} key={item['key']} lang={item['language']} "
                f"score={item['_score']} gw={item['_german_words']} tech={item['_tech_hits']} | {snippet}"
            )
        if len(subset) > 10:
            print(f"  ... und {len(subset)-10} weitere")

    # Review-Datei mit Scores für spätere manuelle Filterung speichern
    OUTPUT.write_text(json.dumps(scored, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nReview-Datei geschrieben: {OUTPUT}")


if __name__ == "__main__":
    main()
