# BACH Adapter: report_runtime_identity
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Laufzeit-Identitaet der Berichtspipeline: laeuft der ausgefuehrte Code auf dem kanonischen Stand?

Anlass T-20261111-107529991: Ein gitloser OneDrive-Spiegel (``REPO.pointer.json``, Modus
tracked-files-no-git) hinkte dem Klon hinterher. Der Cloud-Weg lief dort ohne NER-/Identitaets-Sperre,
und niemand sah es, weil im Repo alles stimmte. Quellcode im Klon ist keine Laufzeitfreigabe.

Verglichen wird der Ordner ``system/hub/_services/document`` (dort liegen Pipeline, Anonymisierer und
Sperren) Datei fuer Datei als Git-Blob-ID (CRLF wie LF) gegen den kanonischen Stand:

- ``checkout``: Die Laufzeit ist selbst ein Git-Checkout (Entwicklung, Mac-Live). Verglichen wird mit
  HEAD; Abweichung ist Absicht und sperrt nicht.
- ``ok``/``stale``: Gitloser Spiegel; kanonisch ist ``origin/<default_branch>`` des Klons, gefunden ueber
  ``BACH_CANONICAL_CLONE`` oder den Pointer. ``stale`` sperrt den Cloud-Weg (siehe report_workflow_service).
- ``unverified``: Kein Klon auffindbar, Git oder ein Dateilesen schlaegt fehl. Mit ``REPO.pointer.json``
  (bekannter Spiegel, ``has_pointer``) sperrt das fail-closed (``runtime_unverified``); ohne Pointer
  (Release ohne Klon) bleibt es durchlaessig.

Ausgabe: ``python report_runtime_identity.py`` (Exit 1 nur bei ``stale``).

ponytail: Der Klon-Ref wird nicht per fetch aufgefrischt (offline), und ein Live-Checkout, der hinter
origin/main liegt, wird nie erkannt. ``ok``/``stale``/``checkout`` gelten je Prozess ab dem ersten Aufruf
(ein laufender Server prueft den beim ersten Aufruf geladenen Stand); ``unverified`` wird bewusst NICHT
zwischengespeichert, damit ein voruebergehender Git-/OneDrive-Fehler nicht die ganze Laufzeit sperrt.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parents[4]
_REL = "system/hub/_services/document"
_SUFFIXES = (".py", ".json", ".md", ".txt")


def _blob_id(data: bytes) -> str:
    data = data.replace(b"\r\n", b"\n")
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()  # Git-Blob-ID, kein Sicherheitshash


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, timeout=20, check=True)
    return done.stdout.decode("utf-8", "replace")


def _tree(repo: Path, ref: str) -> dict:
    out = _git(repo, "ls-tree", "-r", "-z", ref, "--", _REL)
    entries = (e.split("\t", 1) for e in out.split("\0") if e)
    return {path[len(_REL) + 1:]: meta.split()[2] for meta, path in entries if path.endswith(_SUFFIXES)}


def _runtime_files(root: Path) -> dict:
    base = root / _REL
    return {p.relative_to(base).as_posix(): p for p in base.rglob("*")
            if p.is_file() and "__pycache__" not in p.parts and p.suffix in _SUFFIXES}


def _pointer(root: Path) -> dict:
    try:
        return json.loads((root / "REPO.pointer.json").read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def _find_clone(pointer: dict) -> Optional[Path]:
    candidates = [os.environ.get("BACH_CANONICAL_CLONE", "")]
    if os.name == "nt":
        candidates.append(str(pointer.get("local_locator", {}).get("windows_default", "")))
    return next((Path(c) for c in candidates if c and (Path(c) / ".git").exists()), None)


def _importable(name: str) -> bool:
    """Zusatzdatei, die Python laden koennte; Konfliktkopien wie ``x-HOST.py`` sind nie importierbar."""
    return name.endswith(".py") and Path(name).stem.isidentifier()


def _is_checkout(root: Path) -> bool:
    """Echter Git-Checkout genau in ``root``; ein leeres/kaputtes ``.git`` (OneDrive-Reste) zaehlt nicht."""
    try:
        return Path(_git(root, "rev-parse", "--show-toplevel").strip()).resolve() == root.resolve()
    except (OSError, subprocess.SubprocessError):
        return False


def check_identity(root: Path = _ROOT) -> dict:
    """Prueft ``root`` gegen den kanonischen Stand; liefert Status und abweichende Dateinamen (nie Inhalte)."""
    root = Path(root)
    pointer = _pointer(root)
    result = {"status": "unverified", "root": str(root), "canonical_commit": "", "differing": [],
              "has_pointer": bool(pointer),
              "source_commit": pointer.get("onedrive_mirror", {}).get("source_commit", "")}
    if _is_checkout(root):
        repo, ref, is_checkout = root, "HEAD", True
    else:
        repo = _find_clone(pointer)
        if repo is None:
            return result
        ref, is_checkout = f"origin/{pointer.get('default_branch') or 'main'}", False
    try:
        try:
            result["canonical_commit"] = _git(repo, "rev-parse", "--verify", ref).strip()
        except subprocess.CalledProcessError:  # Klon ohne Remote-Ref: sein HEAD ist der beste Stand
            ref = "HEAD"
            result["canonical_commit"] = _git(repo, "rev-parse", "--verify", ref).strip()
        canonical, runtime = _tree(repo, ref), _runtime_files(root)
        diff = sorted({n for n, sha in canonical.items() if n not in runtime or _blob_id(runtime[n].read_bytes()) != sha}
                      | {n for n in runtime if n not in canonical and _importable(n)})
    except (OSError, subprocess.SubprocessError):
        return result  # Git nicht nutzbar: unverified, nie stale behaupten
    result["differing"] = diff
    result["status"] = "checkout" if is_checkout else "stale" if diff else "ok"
    return result


_cached: Optional[dict] = None


def runtime_identity() -> dict:
    global _cached
    if _cached is not None:
        return _cached
    result = check_identity()
    if result["status"] != "unverified":
        _cached = result
    return result


if __name__ == "__main__":
    ident = runtime_identity()
    print(json.dumps(ident, indent=2, ensure_ascii=False))
    raise SystemExit(1 if ident["status"] == "stale" else 0)
