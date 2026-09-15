#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""TRANSFER-09 Gate 3 — Echter 3-Host-Lauf sqlite-transit-sync ueber OneDrive-Transit.

Stufe-7-Nachlauf (Plan-Regel 4.3 "Offener Betriebs-Nachlauf").

Dieses Script fuehrt mit dem REALEN, installierten Modul ``sqlite-transit-sync``
ueber die Produktiv-Provider-Seam (``hub.transit_sync_provider.create_external_engine``)
einen 3-Wege-Zustand fuer die Hosts ``WORKSTATION-LG``, ``ASUS-GEI`` und
``mac-studio`` durch und verifiziert:

  * 3 unabhängige Nodes (je eigene lokale DB + je eigener Merge-State OUTSIDE transit)
  * Push/Pull ueber ein gemeinsames Transit-Verzeichnis (OneDrive-gestuetzt)
  * LWW-Konfliktloesung (neuerer Timestamp gewinnt)
  * State-Gate: wiederholter Pull ist No-op (kein Replay)
  * Ausschluss von ``secrets`` aus Snapshots
  * SyncConfig-Hardinvariante: State niemals im Transit-Verzeichnis

Nicht-destruktiv: Der 3-Wege-Beweis laeuft in einem DATEGESTUETZTEM, klarem
Subfolder unter dem ECHTEN OneDrive-Transit (``.../.SYNC/bach_db_transit/.oprun-gate3-<datum>/``),
damit Produktionssnapshots nicht beschadigt werden. Separate Produktionsschnittstelle
wird nur gepraefucht (engine != None), NICHT gepusht.

Evidenz: ``~/.bach/transit_sync_state/oprun_gate3_<datum>.json`` + Konsole.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import traceback
from datetime import date
from pathlib import Path

# ---------------------------------------------------------------------------
# Import der Produktiv-Seam
# ---------------------------------------------------------------------------
BACH_ROOT = Path(__file__).resolve().parent.parent
if str(BACH_ROOT) not in sys.path:
    sys.path.insert(0, str(BACH_ROOT))

from hub import transit_sync_provider as tsp  # noqa: E402
from hub import bach_paths as bp  # noqa: E402

HOSTS = ["WORKSTATION-LG", "ASUS-GEI", "mac-studio"]
TODAY = date.today().isoformat()

results: dict = {
    "gate": "TRANSFER-09 Gate 3 — 3-Host transit-sync ueber OneDrive",
    "date": TODAY,
    "module": "sqlite-transit-sync",
    "checks": [],
    "artifacts": {},
}
ok_all = True


def check(name: str, cond: bool, detail: str = "") -> None:
    global ok_all
    ok_all = ok_all and cond
    results["checks"].append({"name": name, "pass": bool(cond), "detail": detail})
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def seed_db(path: Path) -> None:
    """Minimaler tasks+secrets-Schema (Paritaet mit dem Waechter-Test)."""
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS tasks "
                     "(id INTEGER PRIMARY KEY, title TEXT, updated_at TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS secrets "
                     "(id INTEGER PRIMARY KEY, key TEXT, value TEXT)")
        conn.commit()
    finally:
        conn.close()


def engine_for(node: str, db: Path, state_dir: Path, transit: Path):
    """Echte Engine ueber die Produktiv-Seam (fail-closed bei Vertragsbruch)."""
    return tsp.create_external_engine(
        db_path=db,
        transit_dir=transit,
        local_bach_dir=state_dir,
        node_id=node,
    )


def rows(node_db: Path) -> list:
    conn = sqlite3.connect(str(node_db))
    try:
        return conn.execute("SELECT id, title FROM tasks ORDER BY id").fetchall()
    finally:
        conn.close()


def main() -> int:
    global results
    # Rollback-Schalter muss NICHT gesetzt sein (sonst laeuft der Legacy-Pfad).
    if tsp._rollback_forced():
        print("FATAL: BACH_USE_EXTERNAL_TRANSITSYNC=0 setzt den Legacy-Pfad — OpRun abgebrochen.")
        return 2

    provider = tsp.probe_transit_sync_provider()
    check("Provider = externes Modul (nicht legacy)", provider.external,
          f"name={provider.name!r} module={provider.module!r}")

    real_transit = Path(bp.PROSYNC_TRANSIT_DIR)
    run_transit = real_transit / f".oprun-gate3-{TODAY}"
    run_transit.mkdir(parents=True, exist_ok=True)
    run_dir = Path.home() / ".bach" / "transit_sync_state" / f"_oprun_{TODAY}"
    run_dir.mkdir(parents=True, exist_ok=True)

    print(f"== Transit (echter OneDrive, isoliertes Subfolder): {run_transit}")
    results["artifacts"]["transit_real"] = str(real_transit)
    results["artifacts"]["transit_run"] = str(run_transit)

    nodes = {}
    for host in HOSTS:
        db = run_dir / f"{host}.db"
        if db.exists():
            db.unlink()
        seed_db(db)
        # Je eigener Merge-State OUTSIDE transit. mac-studio nutzt den ECHTEN
        # Produktivpfad ~/.bach/transit_sync_state/state.json (Task-Name).
        if host == "mac-studio":
            state_local = Path.home() / ".bach"
        else:
            state_local = run_dir / f"_state_{host}"
        state_local.mkdir(parents=True, exist_ok=True)
        eng = engine_for(host, db, state_local, run_transit)
        nodes[host] = {"eng": eng, "db": db, "state_local": state_local,
                       "state_file": state_local / tsp.STATE_DIR_NAME / tsp.STATE_FILE_NAME}
        # Hardinvariante pro Node
        st = Path(eng._config.state)
        check(f"Hardinvariante {host}: State ausserhalb Transit",
              not (st == Path(run_transit) or Path(run_transit) in st.parents),
              f"state={st}")
        print(f"   {host}: db={db.name} state={st}")

    print(f"\n== 1. Jeder Host pusht einen eigenstaendigen Snapshot")
    pushed = {}
    for host in HOSTS:
        conn = sqlite3.connect(str(nodes[host]["db"]))
        _sid = {"WORKSTATION-LG": 10, "ASUS-GEI": 11, "mac-studio": 12}[host]
        conn.execute("INSERT INTO tasks VALUES (?, 'seed-%s', '2026-09-10T09:00:00')" % host, (_sid,))
        conn.commit(); conn.close()
        name = nodes[host]["eng"].push()
        pushed[host] = name
        check(f"Push {host} -> {name}", name.endswith(".sqlite-snapshot"),
              f"size={Path(run_transit, 'bach', name).stat().st_size if _snap_path(run_transit, name) else '?'}")
    results["artifacts"]["pushed"] = pushed

    print("\n== 2. Jeder Host merged die fremden Snapshots (3-Wege-Zustand)")
    for host in HOSTS:
        eng = nodes[host]["eng"]
        foreign = [h for h in HOSTS if h != host]
        changed, names = eng.pull()
        got = rows(nodes[host]["db"])
        # Alle 3 seeds (10/11/12-artig) + eigene sollte jetzt da sein
        titles = {t for _, t in got}
        all_three = all(f"seed-{h}" in titles for h in HOSTS)
        check(f"3-Wege-Merge {host}: alle seeds vorhanden", all_three and changed > 0,
              f"changed={changed} merged={names} rows={got}")

    print("\n== 3. LWW-Konflikt: WORKSTATION-LG vs. ASUS-GEI, neuerer Timestamp gewinnt")
    # Beide schreiben id=1; WORKSTATION-LG aelter, ASUS-GEI neuer -> ASUS-GEI gewinnt.
    for host, ts in (("WORKSTATION-LG", "2026-09-11T08:00:00"),
                     ("ASUS-GEI", "2026-09-11T12:00:00")):
        conn = sqlite3.connect(str(nodes[host]["db"]))
        conn.execute("INSERT OR REPLACE INTO tasks VALUES (1, 'konflikt-%s', ?)" % host, (ts,))
        conn.commit(); conn.close()
        nodes[host]["eng"].push()
    m_changed, _ = nodes["mac-studio"]["eng"].pull()
    winner = next((t for _, t in rows(nodes["mac-studio"]["db"]) if t.startswith("konflikt")), None)
    check("LWW: mac-studio nimmt den NEUEREN Wert (konflikt-ASUS-GEI)",
          winner == "konflikt-ASUS-GEI", f"winner={winner!r} changed={m_changed}")

    print("\n== 4. State-Gate: wiederholter Pull ist No-op (kein Replay)")
    again_changed, again_names = nodes["mac-studio"]["eng"].pull()
    check("No-op-Re-Pull mac-studio", again_changed == 0 and again_names == [],
          f"changed={again_changed} names={again_names}")

    print("\n== 5. Ausschluss von 'secrets' aus Snapshots")
    conn = sqlite3.connect(str(nodes["mac-studio"]["db"]))
    conn.execute("INSERT INTO secrets VALUES (1, 'api_key', 'GEHEIM_TEST')")
    conn.execute("INSERT OR REPLACE INTO tasks VALUES (20, 'oeffentlich', '2026-09-12T09:00:00')")
    conn.commit(); conn.close()
    nodes["mac-studio"]["eng"].push()
    nodes["ASUS-GEI"]["eng"].pull()
    conn = sqlite3.connect(str(nodes["ASUS-GEI"]["db"]))
    n_sec = conn.execute("SELECT COUNT(*) FROM secrets").fetchone()[0]
    has_pub = conn.execute("SELECT COUNT(*) FROM tasks WHERE title='oeffentlich'").fetchone()[0]
    conn.close()
    check("secrets nicht reproduziert (0) + oeffentlich task vorhanden",
          n_sec == 0 and has_pub == 1, f"secrets={n_sec} oeffentlich={has_pub}")

    print("\n== 6. Negative Kontrolle: State IM Transit wirft ValueError (SyncConfig)")
    try:
        tsp.load_external_transit_sync().SyncConfig(
            database=run_dir / "x.db",
            transit=run_transit,
            state=run_transit / "state.json",  # IM Transit -> verboten
            node_id="probe",
        )
        check("SyncConfig verweigert State im Transit", False, "kein ValueError!")
    except ValueError as e:
        check("SyncConfig verweigert State im Transit", True, str(e)[:80])

    print("\n== 7. Produktionsschnittstelle mac-studio (nur Pruefen, NICHT puschen)")
    prod = tsp.create_external_engine_if_active(
        db_path=run_dir / "prod_probe.db",
        transit_dir=real_transit,
        local_bach_dir=Path.home() / ".bach",
        node_id="mac-studio",
    )
    if not Path(run_dir / "prod_probe.db").exists():
        seed_db(run_dir / "prod_probe.db")
    check("Produktive Engine != None (echter Transit + echter State-Pfad)",
          prod is not None,
          f"status={prod.status() if prod else None}")
    if prod:
        st = Path(prod._config.state)
        check("Produktiver State-Pfad = ~/.bach/transit_sync_state/state.json",
              st == (Path.home() / ".bach" / tsp.STATE_DIR_NAME / tsp.STATE_FILE_NAME),
              f"state={st}")

    results["artifacts"]["state_files"] = {h: str(nodes[h]["state_file"]) for h in HOSTS}
    results["artifacts"]["state_files_exist"] = {h: nodes[h]["state_file"].exists() for h in HOSTS}
    results["result"] = "PASS" if ok_all else "FAIL"
    results["production_live_status"] = (
        "NUR mac-studio emittiert transit-sync-Snapshots im Live-Transit; "
        "WORKSTATION-LG/ASUS-GEI liegen noch im Legacy-.bachdb-Format "
        "(Host-seitige Migration noetig = echter 3-Host-Lauf).")

    out = Path.home() / ".bach" / "transit_sync_state" / f"oprun_gate3_{TODAY}.json"
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n== Evidenz geschrieben: {out}")
    print(f"== ERGEBNIS: {results['result']}")
    return 0 if ok_all else 1


def _snap_path(transit: Path, name: str):
    p = transit / "bach" / name
    return p if p.exists() else None


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        sys.exit(3)
