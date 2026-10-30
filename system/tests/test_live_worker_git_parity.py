"""Diagnose: laeuft finish_task aus der Live-Installation oder aus dem Worktree?

Hintergrund (Task #2577): finish_task(is_wip=false) liefert im Live-Betrieb nur
"Worktree-Ergebnis oder Taskänderung nicht bestätigt" -- ohne den Typ-/Text-Suffix,
den der Catch-All in diesem Arbeitsbaum erzeugt. Das deutet darauf hin, dass der
Hub-Prozess die Live-Kopie unter services/bach/system/hub/worker_git.py laedt und
nicht den Arbeitsbaum-Code.

Der Test ist auf Fremdrechnern (CI) automatisch uebersprungen, weil dort keine
Live-Installation unter dem Home-Verzeichnis existiert. Er dient als Beleg-Werkzeug
und als Waechter gegen "Live laeuft alter Code".
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

import pytest

LIVE_ROOT = Path(os.path.expanduser("~/services/bach"))
LIVE_WORKER_GIT = LIVE_ROOT / "system" / "hub" / "worker_git.py"
WT_WORKER_GIT = Path(__file__).resolve().parents[1] / "hub" / "worker_git.py"

CATCH_ALL_SHORT = "Worktree-Ergebnis oder Taskänderung nicht bestätigt"
CATCH_ALL_NEW = re.compile(
    r"Worktree-Ergebnis oder Taskänderung nicht bestätigt: \{"
)
PR_GUARD = re.compile(
    r"Keine gültige PR-URL bestätigt"
)

pytestmark = pytest.mark.skipif(
    not LIVE_WORKER_GIT.is_file(),
    reason="keine Live-Installation vorhanden (erwartet auf Fremdrechnern/CI)",
)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _report() -> dict:
    live_text = LIVE_WORKER_GIT.read_text(encoding="utf-8", errors="replace")
    wt_text = WT_WORKER_GIT.read_text(encoding="utf-8", errors="replace")
    return {
        "live_path": str(LIVE_WORKER_GIT),
        "live_sha": _digest(LIVE_WORKER_GIT),
        "live_lines": live_text.count("\n") + 1,
        "live_has_short_catch_all": CATCH_ALL_SHORT in live_text,
        "live_catch_all_has_suffix": bool(CATCH_ALL_NEW.search(live_text)),
        "live_has_pr_guard": bool(PR_GUARD.search(live_text)),
        "worktree_sha": _digest(WT_WORKER_GIT),
        "worktree_catch_all_has_suffix": bool(CATCH_ALL_NEW.search(wt_text)),
        "worktree_has_pr_guard": bool(PR_GUARD.search(wt_text)),
    }


def test_live_and_worktree_worker_git_version_are_reported(capsys):
    """Gibt die Versionslage beider Dateien aus (immer gruen, reine Diagnose)."""
    info = _report()
    with capsys.disabled():
        print("\n[parity] Live:     ", info["live_path"])
        print("[parity] Live sha: ", info["live_sha"], "Zeilen:", info["live_lines"])
        print("[parity] Live  Catch-All kurz:      ", info["live_has_short_catch_all"])
        print("[parity] Live  Catch-All mit Suffix:", info["live_catch_all_has_suffix"])
        print("[parity] Live  PR-URL-Guard:        ", info["live_has_pr_guard"])
        print("[parity] Worktree sha:", info["worktree_sha"])
        print("[parity] Worktree Catch-All mit Suffix:", info["worktree_catch_all_has_suffix"])
        print("[parity] Worktree PR-URL-Guard:        ", info["worktree_has_pr_guard"])
    assert info["worktree_catch_all_has_suffix"], (
        "Der Arbeitsbaum muss den Catch-All mit Typ/Text-Suffix enthalten."
    )
    assert info["worktree_has_pr_guard"], (
        "Der Arbeitsbaum muss den PR-URL-Guard enthalten."
    )


@pytest.mark.xfail(
    reason=(
        "Erwartet: Live-Installation laeuft noch auf dem alten Catch-All; "
        "der Deploy des Arbeitsbaum-Codes steht aus (Task #2577)."
    ),
    strict=False,
)
def test_live_worker_git_contains_new_catch_all():
    info = _report()
    assert info["live_catch_all_has_suffix"], (
        "Live-Code enthaelt den Catch-All nicht mit Suffix -> "
        "finish_task kann keine Ursache melden. Live-Deploy ausstehend."
    )


@pytest.mark.xfail(
    reason="Erwartet: Live-Installation kennt den PR-URL-Guard noch nicht.",
    strict=False,
)
def test_live_worker_git_contains_pr_url_guard():
    info = _report()
    assert info["live_has_pr_guard"], (
        "Live-Code enthaelt keinen PR-URL-Guard."
    )
