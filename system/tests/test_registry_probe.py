"""Probe-Diagnose Task #2373: Registry-Eintrag worker_external_results.

Rein lesende Diagnose (keine Manipulation, keine DB-Schreiboperationen):
 1) Existenz der Live-/Worktree-Pfade
 2) hub.bach_paths (Live-Mount) -> BACH_ROOT / BACH_DB
 3) tool_registry.json (Live system/data + system/tools/data) -> Eintrag worker_external_results
 4) Live bach.db read-only via sqlite-URI (mode=ro) -> tools-Zeilen %worker_external%
 5) registry_watcher.RegistryWatcher (unterstuetzter Registry/API-Weg) -> check_tools/check_all

Ergebnis wird als JSON nach <worktree>/probe_results/task2373_registry_probe.json
geschrieben. Der Test schlaegt bewusst nicht fehl (Befund-Sammlung); erzeugte
Datei ist der Ruecklese-Nachweis.
"""
import importlib.util
import inspect
import json
import os
import sqlite3
import sys
from pathlib import Path

WORKTREE = Path(__file__).resolve().parents[2]
LIVE_ROOT = Path("/Users/lukas/services")
LIVE_SYSTEM = LIVE_ROOT / "system"
WATCHER = WORKTREE / "system" / "tools" / "maintenance" / "registry_watcher.py"
OUT_DIR = WORKTREE / "probe_results"
OUT_PATH = OUT_DIR / "task2373_registry_probe.json"

R = {
    "meta": {
        "task": 2373,
        "cwd": os.getcwd(),
        "worktree": str(WORKTREE),
        "live_root_candidate": str(LIVE_ROOT),
        "watcher_source": str(WATCHER),
    }
}


def section(key, fn):
    try:
        R[key] = fn()
    except Exception as exc:
        R[key] = {"error": repr(exc)}


def _paths_exist(pairs):
    out = {}
    for label, p in pairs:
        p = Path(p)
        info = {"path": str(p)}
        try:
            info["exists"] = p.exists()
            info["is_file"] = p.is_file()
            info["size"] = p.stat().st_size if p.is_file() else None
        except OSError as exc:
            info["error"] = repr(exc)
        out[label] = info
    return out


def probe_path_existence():
    return _paths_exist([
        ("live_system", LIVE_SYSTEM),
        ("live_data_bach_db", LIVE_SYSTEM / "data" / "bach.db"),
        ("live_data_registries_tool_registry_json",
         LIVE_SYSTEM / "data" / "registries" / "tool_registry.json"),
        ("live_tools_data_registries_tool_registry_json",
         LIVE_SYSTEM / "tools" / "data" / "registries" / "tool_registry.json"),
        ("live_tools_data_bach_db", LIVE_SYSTEM / "tools" / "data" / "bach.db"),
        ("live_tools_worker_external_results_py",
         LIVE_SYSTEM / "tools" / "worker_external_results.py"),
        ("live_hub_bach_paths_py", LIVE_SYSTEM / "hub" / "bach_paths.py"),
        ("wt_data_bach_db", WORKTREE / "system" / "data" / "bach.db"),
        ("wt_data_registries_tool_registry_json",
         WORKTREE / "system" / "data" / "registries" / "tool_registry.json"),
        ("wt_tools_worker_external_results_py",
         WORKTREE / "system" / "tools" / "worker_external_results.py"),
        ("wt_maintenance_registry_watcher_py", WATCHER),
    ])


def probe_hub_paths():
    """Kanonische Pfade der Handler (registry_watcher nutzt genau diesen Weg)."""
    sys.path.insert(0, str(LIVE_SYSTEM))
    try:
        from hub import bach_paths as bp  # noqa
        return {
            "BACH_ROOT": str(getattr(bp, "BACH_ROOT", None)),
            "BACH_DB": str(getattr(bp, "BACH_DB", None)),
            "public_attrs": sorted(
                a for a in dir(bp)
                if not a.startswith("_") and "BACH" in a.upper()
            ),
        }
    finally:
        try:
            sys.path.remove(str(LIVE_SYSTEM))
        except ValueError:
            pass


def _load_json_registry(path):
    p = Path(path)
    if not p.is_file():
        return {"missing": True, "path": str(p)}
    data = json.loads(p.read_text(encoding="utf-8"))
    tools = data.get("tools", {}) if isinstance(data, dict) else {}
    return {
        "path": str(p),
        "top_keys": sorted(data.keys())[:12] if isinstance(data, dict) else None,
        "tool_count": len(tools),
        "worker_external_results": tools.get("worker_external_results"),
    }


def probe_json_registry_live_data():
    return _load_json_registry(
        LIVE_SYSTEM / "data" / "registries" / "tool_registry.json")


def probe_json_registry_live_tools_data():
    return _load_json_registry(
        LIVE_SYSTEM / "tools" / "data" / "registries" / "tool_registry.json")


def probe_sqlite_readonly():
    db = LIVE_SYSTEM / "data" / "bach.db"
    if not db.is_file():
        return {"missing_db": True, "path": str(db)}
    uri = "file:%s?mode=ro" % db.resolve().as_posix()
    conn = sqlite3.connect(uri, uri=True)
    try:
        cur = conn.cursor()
        cur.execute("PRAGMA database_list")
        dblist = [
            {"seq": r[0], "name": r[1], "file": r[2]} for r in cur.fetchall()
        ]
        cur.execute("SELECT COUNT(*) FROM tools")
        tools_total = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM tools WHERE is_available = 1")
        tools_avail = cur.fetchone()[0]
        cur.execute(
            "SELECT name, path, type, category, command, dist_type, is_available "
            "FROM tools WHERE name LIKE '%worker_external%'"
        )
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        return {
            "uri": uri,
            "databases": dblist,
            "tools_total": tools_total,
            "tools_available": tools_avail,
            "rows_worker_external": rows,
        }
    finally:
        conn.close()


def _find_entry(report, name_sub="worker_external"):
    hits = {}
    for cat in ("valid", "relocated_entries", "stale_db_entries", "orphan_files",
                "historical_entries", "external_entries"):
        items = report.get(cat)
        if items is None:
            continue
        sel = []
        for it in items:
            blob = it if isinstance(it, str) else json.dumps(it, default=str)
            if name_sub in blob:
                sel.append(it)
        if sel:
            hits[cat] = sel
    return hits


def probe_watcher():
    spec = importlib.util.spec_from_file_location("probe_registry_watcher", WATCHER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    out = {
        "module_VERSION": str(getattr(mod, "VERSION", None)),
        "module_BACH_ROOT_original": str(getattr(mod, "BACH_ROOT", None)),
    }
    cls = getattr(mod, "RegistryWatcher", None)
    if cls is None:
        out["error"] = "RegistryWatcher-Klasse nicht gefunden"
        return out
    out["init_signature"] = str(inspect.signature(cls.__init__))

    # Watcher auf Live-Root schalten (root==BACH_ROOT -> hub.bach_paths.BACH_DB).
    mod.BACH_ROOT = LIVE_SYSTEM
    try:
        inst = cls(base_path=str(LIVE_SYSTEM))
    except TypeError:
        inst = cls(str(LIVE_SYSTEM))
    for attr in ("root", "tools_dir", "db_path"):
        val = getattr(inst, attr, None)
        out["instance_" + attr] = str(val)
        if attr == "db_path" and val is not None:
            out["instance_db_path_exists"] = Path(val).exists()

    report = inst.check_tools()
    out["check_tools"] = {
        "summary": report.get("summary"),
        "db_count": report.get("db_count"),
        "fs_count": report.get("fs_count"),
        "managed_db_count": report.get("managed_db_count"),
        "valid_count": len(report.get("valid", []) or []),
        "orphan_files_count": len(report.get("orphan_files", []) or []),
        "orphan_contains_worker_external_results": any(
            "worker_external_results" in (it if isinstance(it, str) else json.dumps(it, default=str))
            for it in (report.get("orphan_files") or [])
        ),
        "hits_worker_external": _find_entry(report),
    }
    try:
        fs_paths, _fs_names = inst._scan_tools()
        out["scan_tools"] = {
            "fs_count": len(fs_paths),
            "worker_external_results_in_fs": "tools/worker_external_results.py" in fs_paths,
            "fs_entry": str(fs_paths.get("tools/worker_external_results.py")),
        }
    except Exception as exc:
        out["scan_tools"] = {"error": repr(exc)}
    try:
        full = inst.check_all()
        tools_report = (full.get("checks") or {}).get("tools", {})
        out["check_all"] = {
            "timestamp": full.get("timestamp"),
            "version": full.get("version"),
            "summary": full.get("summary"),
            "tools_summary": tools_report.get("summary"),
        }
        out["check_all_tools_report"] = tools_report
    except Exception as exc:
        out["check_all"] = {"error": repr(exc)}
    return out


def test_probe_2373_write_findings():
    section("path_existence", probe_path_existence)
    section("hub_paths_live_mount", probe_hub_paths)
    section("json_registry_live_data", probe_json_registry_live_data)
    section("json_registry_live_tools_data", probe_json_registry_live_tools_data)
    section("sqlite_readonly_live", probe_sqlite_readonly)
    section("registry_watcher", probe_watcher)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps(R, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    R["meta"]["result_file"] = str(OUT_PATH)
    assert OUT_PATH.is_file()