# SPDX-License-Identifier: MIT
"""
Kontext-Manifest je Repo (Governance)
======================================

Schema mit Planpunkt-Kennungen und ein Loader, der ein Kontext-Manifest
eines Repos liest. Planpunkt-Kennung = f"{task_id}:{incarnation}".

Design-Grundsatz (analog hub.context_hints.neutral_manual_hint):
Alle Manifest-Pfade werden gegen den Root des Repos gecheckt. Ein Ziel
ist nur gueltig, wenn der geloste Pfad innerhalb des Roots liegt
(``is_relative_to(root)``) und eine echte Datei ist (``is_file()``).
Symlinks, die aus dem Repo heraus zeigen, werden so erkannt und
abgewiesen. Fehler beim Loesen (OSError/ValueError) fuhren nie zu
Ausnahmen, sondern zu einem sicheren, leerem Ergebnis.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional


# --- Schema-Definition ------------------------------------------------------

MANIFEST_FILENAME = "CONTEXT_MANIFEST.json"
MANIFEST_VERSION = 1

# Erforderte Felder des Manifests und der Planpunkte.
_REQUIRED_MANIFEST_KEYS = ("repo", "version", "planpunkte")
_REQUIRED_PLANPUNKT_KEYS = ("planpunkt_kennung", "task_id", "incarnation")

# Planpunkt-Kennung darf nur aus erlaubten Zeichen bestehen.
import re
_PLANPUNKT_KENNUNG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def make_planpunkt_kennung(task_id, incarnation) -> str:
    """Bildet die stabile Planpunkt-Kennung f"{task_id}:{incarnation}".

    task_id und incarnation muessen als Zahl/textuelle Id darstellbar sein.
    Die Kennung enthaelt keinen Trenner-Pfad, damit sie sich sicher als
    Manifest-Schluessel und Dateiname verwenden laesst.
    """
    return f"{_canonical_segment(task_id)}:{_canonical_segment(incarnation)}"


def _canonical_segment(value: Any) -> str:
    text = str(value).strip()
    if not text or not _PLANPUNKT_KENNUNG_RE.match(text):
        raise ValueError(f"Ungueltiger Kennungs-Teil: {value!r}")
    return text


class ContextManifest:
    """In-Memory-Repraesentation eines Kontext-Manifests je Repo.

    Felder:
      repo:      Name/Bezeichner des Repos (frei textlich).
      version:   Schema-Version (int).
      planpunkte: Liste von Planpunkt-Dicts. Jeder Planpunkt hat zwingend
                  die Felder ``planpunkt_kennung``, ``task_id`` und
                  ``incarnation``.
    """

    __slots__ = ("repo", "version", "planpunkte", "source_path")

    def __init__(self, repo: str, version: int,
                 planpunkte: List[Dict[str, Any]],
                 source_path: Optional[Path] = None):
        self.repo = repo
        self.version = version
        self.planpunkte = list(planpunkte)
        self.source_path = source_path

    # -- Zugriff --------------------------------------------------------

    def get(self, task_id, incarnation) -> Optional[Dict[str, Any]]:
        """Gibt den Planpunkt zur Kennung zurueck oder None."""
        key = make_planpunkt_kennung(task_id, incarnation)
        for plan in self.planpunkte:
            if plan.get("planpunkt_kennung") == key:
                return plan
        return None

    def kennungen(self) -> List[str]:
        return [p["planpunkt_kennung"] for p in self.planpunkte]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "repo": self.repo,
            "version": self.version,
            "planpunkte": [dict(p) for p in self.planpunkte],
        }


# --- Validierung ------------------------------------------------------------

def validate_manifest(data: Dict[str, Any]) -> ContextManifest:
    """Validiert rohes Manifest-JSON und liefert eine ContextManifest.

    Wirft ValueError bei strukturell ungultigem Inhalt.
    """
    if not isinstance(data, dict):
        raise ValueError("Manifest muss ein JSON-Objekt sein")
    for key in _REQUIRED_MANIFEST_KEYS:
        if key not in data:
            raise ValueError(f"Manifest fehlt Feld '{key}'")

    if not isinstance(data["planpunkte"], list):
        raise ValueError("'planpunkte' muss eine Liste sein")

    if data.get("version") in (None, "1", 1):
        version = int(MANIFEST_VERSION)
    else:
        try:
            version = int(data["version"])
        except (TypeError, ValueError):
            raise ValueError("'version' muss eine Zahl sein")

    planpunkte: List[Dict[str, Any]] = []
    for plan in data["planpunkte"]:
        if not isinstance(plan, dict):
            raise ValueError("Jeder Planpunkt muss ein JSON-Objekt sein")
        for key in _REQUIRED_PLANPUNKT_KEYS:
            if key not in plan:
                raise ValueError(f"Planpunkt fehlt Feld '{key}'")
        task_id = plan["task_id"]
        incarnation = plan["incarnation"]
        # Kennung muss zu task_id:incarnation passen.
        expected = make_planpunkt_kennung(task_id, incarnation)
        if str(plan["planpunkt_kennung"]) != expected:
            raise ValueError(
                f"Planpunkt-Kennung {plan['planpunkt_kennung']!r} "
                f"passt nicht zu task_id:incarnation {expected!r}"
            )
        planpunkte.append(dict(plan))

    return ContextManifest(str(data["repo"]), version, planpunkte)


# --- Lesezugriffspruefung ---------------------------------------------------

def _safe_read_manifest_file(root: Path, manifest_path: Path) -> Optional[Path]:
    """Loest manifest_path innerhalb von root auf.

    Gibt den gelosten Pfad zurueck, wenn er eine Datei innerhalb von root
    ist (analog hub.context_hints Zeilen 50-56). Bei Symlinks nach aussen,
    fehlenden Dateien oder Loesefehlern wird None zurueckgegeben.
    """
    try:
        candidate = (root / manifest_path).resolve()
        valid = candidate.is_relative_to(root) and candidate.is_file()
    except (OSError, ValueError):
        return None
    if not valid:
        return None
    return candidate


# --- Loader -----------------------------------------------------------------

def controlcenter_context_pack(repo, manifest_path: Optional[Any] = None,
                               *, default_name: str = MANIFEST_FILENAME
                               ) -> ContextManifest:
    """Laedt das Kontext-Manifest eines Repos (Governance-Loader).

    Parameter:
      repo:          Pfad oder Name des Repos. Wenn es ein existierender
                     Verzeichnispfad ist, dient er als Root und Default-Pfad
                     fuer das Manifest. Ist es nur ein Name, wird ein
                     virtuelles Manifest aus manifest_path gelesen.
      manifest_path: Optionaler Pfad zur Manifest-Datei. Muss innerhalb des
                     Repo-Roots liegen (Lesezugriffspruefung).
      default_name:  Dateiname, wenn kein manifest_path gegeben ist
                     (standardmaessig CONTEXT_MANIFEST.json).

    Verhalten:
      - Lesezugriffspruefung: Der Manifest-Pfad muss eine Datei innerhalb
        des Repo-Roots sein. Andernfalls wird ein leeres Manifest zurueck-
        gegeben (keine Ausnahme).
      - Bei leerer/gueltiger Datei wird das Manifest validiert. Ein
        ungultiges Manifest fuehrt zu einem ValueError.

    Rueckgabe:
      ContextManifest (evtl. leer, wenn kein Manifest existiert).
    """
    repo_path = Path(repo)
    repo_is_dir = repo_path.is_dir()

    if manifest_path is None:
        manifest_path = default_name

    # Root fuer die Lesezugriffspruefung.
    root = repo_path.resolve() if repo_is_dir else Path.cwd().resolve()

    resolved = _safe_read_manifest_file(root, Path(manifest_path))
    if resolved is None:
        # Kein zugreifbares Manifest: leeres, aber gueltiges Manifest.
        return ContextManifest(
            repo=str(repo) if not repo_is_dir else repo_path.name,
            version=MANIFEST_VERSION,
            planpunkte=[],
        )

    try:
        raw = json.loads(resolved.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Manifest ist kein gueltiges JSON: {exc}") from exc

    manifest = validate_manifest(raw)
    manifest.source_path = resolved
    if not repo_is_dir:
        manifest.repo = str(repo)
    return manifest


def default_manifest_path(repo: Path) -> Path:
    """Standard-Pfad eines Kontext-Manifests in einem Repo."""
    return Path(repo) / MANIFEST_FILENAME
