#!/usr/bin/env python3
"""
Lock Scanner - Identifiziert Locks und Scan-Depth-Status für Verzeichnisbaumüberprüfungen.
Kanonische Quelle: ellmos-ai/lock-master (pure-locking/lock_scan.py)
Rootdatei ist nur ein Kompatibilitätsshim.
"""
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict


MAX_SYMLINK_DEPTH = 20
_MACOS_SYSTEM_SYMLINKS = {Path("/var"), Path("/tmp"), Path("/etc")}


def _safe_target(path: Path) -> str | None:
    try:
        return str(path.resolve(strict=False))
    except (OSError, RuntimeError):
        try:
            return os.readlink(path)
        except OSError:
            return None


def classify_symlink(path: Path) -> str | None:
    if not path.is_symlink():
        return None
    try:
        st = path.lstat()
    except OSError:
        return "symlink_broken"

    from stat import S_ISDIR, S_ISREG, S_ISLNK

    if S_ISLNK(st.st_mode):
        try:
            target_st = path.stat()
        except OSError:
            return "symlink_broken"
        if S_ISREG(target_st.st_mode):
            return "symlink_to_file"
        if S_ISDIR(target_st.st_mode):
            return "symlink_to_directory"
        return "symlink_other"
    return None


def _has_path_redirect(raw_root: Path) -> str | None:
    cur = raw_root
    while cur != cur.parent:
        if cur not in _MACOS_SYSTEM_SYMLINKS and cur.is_symlink():
            return str(cur)
        cur = cur.parent
    return None


def scan_directory(root_path: Path) -> Dict[str, Any]:
    raw_root = Path(root_path)
    redirect = _has_path_redirect(raw_root)
    try:
        root = raw_root.resolve(strict=False)
    except (OSError, RuntimeError):
        return {
            "checked": str(raw_root),
            "twin_status": "not-applicable",
            "path_redirect": str(raw_root),
        }

    result: Dict[str, Any] = {
        "checked": str(root),
        "twin_status": "not-applicable" if redirect else "ok",
        "locks": [],
        "hookguards": [],
        "symlinks": [],
        "regular_files": [],
        "regular_dirs": [],
    }
    if redirect:
        result["path_redirect"] = redirect

    try:
        for entry in root.rglob("*"):
            rel = entry.relative_to(root)
            link_type = classify_symlink(entry)

            try:
                parent = entry.parent
                while parent != root and parent != root.parent:
                    if classify_symlink(parent):
                        result["twin_status"] = "not-applicable"
                        result["path_redirect"] = str(parent.relative_to(root))
                        break
                    parent = parent.parent
            except Exception:
                pass

            if link_type == "symlink_to_file":
                target_str = _safe_target(entry)
                try:
                    size = entry.stat().st_size if entry.exists() else 0
                except OSError:
                    size = 0
                result["symlinks"].append({
                    "path": str(rel),
                    "type": "symlink_to_file",
                    "target": target_str,
                })
                result["regular_files"].append({
                    "path": str(rel),
                    "is_symlink": True,
                    "target": target_str,
                    "size": size,
                })
                continue

            if link_type in ("symlink_to_directory", "symlink_broken", "symlink_other"):
                result["symlinks"].append({
                    "path": str(rel),
                    "type": link_type,
                    "target": _safe_target(entry) if entry.is_symlink() else None,
                })
                result["twin_status"] = "not-applicable"
                continue

            if entry.is_file():
                result["regular_files"].append({
                    "path": str(rel),
                    "is_symlink": False,
                    "size": entry.stat().st_size,
                })
            elif entry.is_dir():
                result["regular_dirs"].append({
                    "path": str(rel),
                })
    except Exception as e:
        result["twin_status"] = "unknown"
        result["error"] = str(e)

    result = {k: v for k, v in result.items() if v}
    return result


def main() -> None:
    if len(sys.argv) < 2:
        print(json.dumps({"error": "No path provided", "twin_status": "unknown"}), file=sys.stderr)
        sys.exit(2)
    target = Path(sys.argv[1])
    if not target.exists() and not target.is_symlink():
        print(json.dumps({"error": f"Path does not exist: {target}", "twin_status": "unknown"}))
        sys.exit(1)
    payload = scan_directory(target)
    print(json.dumps(payload, indent=2))
    sys.exit(0 if payload.get("twin_status") == "ok" else 1)


if __name__ == "__main__":
    main()
