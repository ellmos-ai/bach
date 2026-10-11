"""Synthetischer Fixture-Test fuer index_gardener() (Task 1675, M3).

Legt zwei minimale Gardener-SQLite-DBs (user.db, gardener.db) mit einer
`everything`-Tabelle in einem Fixture-Verzeichnis an und prueft, dass
UnifiedSearch.index_gardener() strikt read-only indiziert:
- Checksummen der Quell-DBs bleiben unveraendert (read-only-Beweis)
- Provenance gardener_user / gardener_system getrennt (2 + 2 Eintraege)
- Tags (kommagetrennt) + 'pinned' landen in search_tags
- meta-JSON wird als Content-Anhang indiziert ('observed_at' findbar)
- Idempotenz (2. Lauf) und fail-soft bei fehlendem/leerem Datenverzeichnis
"""

from pathlib import Path
import sys
import os
import sqlite3
import hashlib
import shutil

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "system" / "tools"))
import unified_search

DATA = HERE / "fixture_data"
DB_USER = DATA / "user.db"
DB_SYS = DATA / "gardener.db"
BACH_DB = DATA / "bach.db"
EMPTY = HERE / "leeres_verzeichnis"

EXPECTED_MSG = "[Gardener] 2 User- + 2 System-Eintraege indexiert"

RESULTS = []


def check(name, passed, detail=""):
    RESULTS.append((name, bool(passed), str(detail)))


def build_fixture():
    shutil.rmtree(DATA, ignore_errors=True)
    DATA.mkdir()
    schema = (
        "CREATE TABLE everything ("
        "id INTEGER PRIMARY KEY, "
        "type TEXT, "
        "name TEXT UNIQUE, "
        "content TEXT, "
        "tags TEXT, "
        "meta TEXT, "
        "pinned INTEGER, "
        "created TEXT, "
        "updated TEXT)"
    )
    user_rows = [
        (1, "note", "user-note-1",
         "Erste User-Notiz mit Stichwort Apfel", "a,b", None, 0,
         "2026-10-01T09:00:00", "2026-10-01T09:00:00"),
        (2, "note", "user-note-2",
         "Zweite User-Notiz mit Stichwort Birne", "a, obst",
         '{"source":"fixture"}', 1,
         "2026-10-02T09:00:00", "2026-10-02T09:00:00"),
    ]
    sys_rows = [
        (1, "system", "system-entry-1",
         "Systemeintrag mit Stichwort Cherry", "sys", None, 0,
         "2026-10-05T10:00:00", "2026-10-05T10:00:00"),
        (2, "observed", "observed/src-1/test.md",
         "Beobachteter Inhalt der Datei test.md", None,
         '{"path":"src-1/test.md","observed_at":"2026-10-05T10:00:00","observed":true}', 0,
         "2026-10-05T10:00:00", "2026-10-05T10:00:00"),
    ]
    for db_path, rows in ((DB_USER, user_rows), (DB_SYS, sys_rows)):
        conn = sqlite3.connect(db_path)
        conn.execute(schema)
        for row in rows:
            conn.execute(
                "INSERT INTO everything "
                "(id, type, name, content, tags, meta, pinned, created, updated) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                row,
            )
        conn.commit()
        conn.close()


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def index_counts():
    conn = sqlite3.connect(BACH_DB)
    out = {}
    for src in ("gardener_user", "gardener_system"):
        out[src] = conn.execute(
            "SELECT COUNT(*) FROM search_index WHERE source = ?", (src,)
        ).fetchone()[0]
    conn.close()
    return out


def tags_of(source, source_id):
    conn = sqlite3.connect(BACH_DB)
    row = conn.execute(
        "SELECT id FROM search_index WHERE source = ? AND source_id = ?",
        (source, source_id),
    ).fetchone()
    tags = set()
    if row is not None:
        for r in conn.execute(
            "SELECT tag FROM search_tags WHERE search_id = ?", (row[0],)
        ):
            tags.add(r[0])
    conn.close()
    return tags


def meta_hits():
    conn = sqlite3.connect(BACH_DB)
    n = conn.execute(
        "SELECT COUNT(*) FROM search_index "
        "WHERE source = 'gardener_system' AND content LIKE '%observed_at%'"
    ).fetchone()[0]
    conn.close()
    return n


def run():
    build_fixture()
    hash_user = sha256(DB_USER)
    hash_sys = sha256(DB_SYS)

    unified_search.DB_PATH = BACH_DB
    os.environ["BACH_GARDENER_DATA"] = str(DATA)
    us = unified_search.UnifiedSearch(db_path=BACH_DB)
    us.ensure_schema()

    # --- Lauf 1: frischer Index ---
    ok, msg = us.index_gardener()
    check("Lauf1: ok == True", ok is True, f"ok={ok!r}, msg={msg!r}")
    check("Lauf1: Meldung '2 User- + 2 System-Eintraege indexiert'",
          msg == EXPECTED_MSG, f"msg={msg!r}")
    check("Lauf1 (a): Checksumme user.db unveraendert (read-only)",
          sha256(DB_USER) == hash_user,
          f"erwartet={hash_user}, ist={sha256(DB_USER)}")
    check("Lauf1 (a): Checksumme gardener.db unveraendert (read-only)",
          sha256(DB_SYS) == hash_sys,
          f"erwartet={hash_sys}, ist={sha256(DB_SYS)}")
    c1 = index_counts()
    check("Lauf1 (b): 2 Eintraege source='gardener_user'",
          c1.get("gardener_user") == 2, f"counts={c1}")
    check("Lauf1 (b): 2 Eintraege source='gardener_system'",
          c1.get("gardener_system") == 2, f"counts={c1}")

    tags = tags_of("gardener_user", "user-note-2")
    check("Lauf1 (c): Tags user-note-2 == {'a','obst','pinned'}",
          tags == {"a", "obst", "pinned"}, f"tags={sorted(tags)}")

    n_meta = meta_hits()
    check("Lauf1 (d): 1 gardener_system-Zeile mit observed_at im meta-Anhang",
          n_meta == 1, f"count={n_meta}")
    s_ok, hits = us.search("observed_at")
    hit_ok = False
    hit_detail = f"ok={s_ok!r}, typ={type(hits).__name__}"
    if s_ok is True and isinstance(hits, list) and len(hits) == 1:
        h = hits[0]
        hit_ok = (
            h.get("source") == "gardener_system"
            and h.get("source_id") == "observed/src-1/test.md"
            and h.get("source_path") == str(DB_SYS)
            and h.get("category") == "observed"
        )
        hit_detail = (
            f"source={h.get('source')!r}, source_id={h.get('source_id')!r}, "
            f"source_path={h.get('source_path')!r}, category={h.get('category')!r}, "
            f"erwartet path={str(DB_SYS)!r}"
        )
    elif isinstance(hits, list):
        hit_detail = f"ok={s_ok!r}, n={len(hits)}"
    check("Lauf1 (d): search('observed_at') -> genau 1 Treffer gardener_system",
          hit_ok, hit_detail)

    # --- Lauf 2: Idempotenz (existing_count > 0, Loeschblock laeuft) ---
    ok2, msg2 = us.index_gardener()
    check("Lauf2: ok == True (Idempotenz)", ok2 is True,
          f"ok={ok2!r}, msg={msg2!r}")
    check("Lauf2: Meldung wieder 2 + 2", msg2 == EXPECTED_MSG, f"msg={msg2!r}")
    c2 = index_counts()
    check("Lauf2: counts wieder 2 + 2",
          c2.get("gardener_user") == 2 and c2.get("gardener_system") == 2,
          f"counts={c2}")
    check("Lauf2: Checksummen unveraendert",
          sha256(DB_USER) == hash_user and sha256(DB_SYS) == hash_sys,
          f"user_unchanged={sha256(DB_USER) == hash_user}, "
          f"sys_unchanged={sha256(DB_SYS) == hash_sys}")

    # --- fail-soft 1: nicht existierendes Datenverzeichnis ---
    ok3, msg3 = us.index_gardener(data_dir=HERE / "gibt_es_nicht")
    check("fail-soft1: ok == True und 'uebersprungen' in Meldung",
          ok3 is True and "uebersprungen" in msg3,
          f"ok={ok3!r}, msg={msg3!r}")
    c3 = index_counts()
    check("fail-soft1 (Bonus): Index bleibt 2 + 2",
          c3.get("gardener_user") == 2 and c3.get("gardener_system") == 2,
          f"counts={c3}")

    # --- fail-soft 2: leeres Datenverzeichnis (DBs fehlen, Loeschblock laeuft) ---
    os.makedirs(EMPTY, exist_ok=True)
    ok4, msg4 = us.index_gardener(data_dir=EMPTY)
    check("fail-soft2: ok == True und 'nicht gefunden' in Meldung",
          ok4 is True and "nicht gefunden" in msg4,
          f"ok={ok4!r}, msg={msg4!r}")
    c4 = index_counts()
    check("fail-soft2: Loeschblock lief, Index danach 0 + 0",
          c4.get("gardener_user") == 0 and c4.get("gardener_system") == 0,
          f"counts={c4}")

    # --- Lauf 3: ENV unveraendert, Index wird wieder aufgebaut ---
    ok5, msg5 = us.index_gardener()
    check("Lauf3: ok == True nach fail-soft2", ok5 is True,
          f"ok={ok5!r}, msg={msg5!r}")
    check("Lauf3: Meldung wieder 2 + 2", msg5 == EXPECTED_MSG, f"msg={msg5!r}")
    c5 = index_counts()
    check("Lauf3: counts wieder 2 + 2",
          c5.get("gardener_user") == 2 and c5.get("gardener_system") == 2,
          f"counts={c5}")
    check("Lauf3: Checksummen unveraendert",
          sha256(DB_USER) == hash_user and sha256(DB_SYS) == hash_sys,
          f"user_unchanged={sha256(DB_USER) == hash_user}, "
          f"sys_unchanged={sha256(DB_SYS) == hash_sys}")


def cleanup():
    shutil.rmtree(DATA, ignore_errors=True)
    shutil.rmtree(EMPTY, ignore_errors=True)
    shutil.rmtree(HERE / "__pycache__", ignore_errors=True)
    shutil.rmtree(HERE.parent / "system" / "tools" / "__pycache__",
                  ignore_errors=True)


if __name__ == "__main__":
    crash = None
    try:
        run()
    except Exception as exc:
        crash = f"{type(exc).__name__}: {exc}"
    cleanup()
    if crash is not None:
        check("Ablauf ohne Exception", False, crash)

    passed = sum(1 for _, p, _ in RESULTS if p)
    failed = len(RESULTS) - passed
    overall = "PASSED" if (RESULTS and failed == 0) else "FAILED"

    lines = ["=== test_gardener_adapter.py (Task 1675, M3 gardener-Adapter) ==="]
    for name, p, detail in RESULTS:
        lines.append("[{}] {}{}".format("PASS" if p else "FAIL", name,
                                        f" | {detail}" if detail else ""))
    lines.append("Gesamt: {}/{} Checks bestanden, {} fehlgeschlagen".format(
        passed, len(RESULTS), failed))
    lines.append("ERGEBNIS: " + overall)
    report = "\n".join(lines)

    out_path = HERE / "test_gardener_adapter_output.txt"
    out_path.write_text(report + "\n", encoding="utf-8")
    print(report)
    sys.exit(0 if overall == "PASSED" else 1)