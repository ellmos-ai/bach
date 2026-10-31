# SPDX-License-Identifier: MIT
"""Tests fuer hub.context_manifest.

Deckt ab:
  * make_planpunkt_kennung erzeugt f"{task_id}:{incarnation}" und prueft Segmente
  * ContextManifest .get/.kennungen/.to_dict
  * validate_manifest akzeptiert gueltiges Schema, verstoesst bei ungueltigen Daten
  * controlcenter_context_pack: gueltiges Manifest laedt, kein Manifest -> leeres
    gueltiges Manifest, Pfad ausserhalb root (Symlink/Entf.) -> leeres Manifest,
    ungueltiges JSON -> ValueError
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from hub.context_manifest import (
    MANIFEST_FILENAME,
    MANIFEST_VERSION,
    ContextManifest,
    controlcenter_context_pack,
    default_manifest_path,
    make_planpunkt_kennung,
    validate_manifest,
)


# --- Kennung -----------------------------------------------------------------

def test_kennung_form():
    assert make_planpunkt_kennung(2578, 3) == "2578:3"
    assert make_planpunkt_kennung("abc", "1378") == "abc:1378"


def test_kennung_ungueltig():
    with pytest.raises(ValueError):
        make_planpunkt_kennung("a b", 1)
    with pytest.raises(ValueError):
        make_planpunkt_kennung("", 1)


# --- Schema-Validierung ------------------------------------------------------

def _gueltiges_manifest(repo: str = "beispiel") -> dict:
    return {
        "repo": repo,
        "version": MANIFEST_VERSION,
        "planpunkte": [
            {
                "planpunkt_kennung": "2578:1",
                "task_id": 2578,
                "incarnation": 1,
                "titel": "Kontext-Manifest je Repo",
            }
        ],
    }


def test_validate_gueltig():
    data = _gueltiges_manifest()
    validate_manifest(data)  # darf keine Exception werfen
    assert data["planpunkte"][0]["planpunkt_kennung"] == "2578:1"


def test_validate_fehlendes_feld():
    data = _gueltiges_manifest()
    del data["version"]
    with pytest.raises(ValueError):
        validate_manifest(data)


def test_validate_kennung_unkonsistent():
    data = _gueltiges_manifest()
    # Kennung muss task_id:incarnation entsprechen
    data["planpunkte"][0]["task_id"] = 999
    with pytest.raises(ValueError):
        validate_manifest(data)


def test_validate_planpunkte_keine_liste():
    data = _gueltiges_manifest()
    data["planpunkte"] = {"oops": 1}
    with pytest.raises(ValueError):
        validate_manifest(data)


# --- In-Memory-Objekt --------------------------------------------------------

def test_contextmanifest_get_kennungen_to_dict():
    data = _gueltiges_manifest()
    manifest = validate_manifest(data)
    # validate_manifest gibt ein geprueftes ContextManifest zurueck
    assert isinstance(manifest, ContextManifest)
    obj = ContextManifest(
        repo=data["repo"],
        version=data["version"],
        planpunkte=data["planpunkte"],
    )
    assert obj.get(2578, 1) == data["planpunkte"][0]
    assert obj.get(2578, 2) is None
    assert "2578:1" in obj.kennungen()
    dump = obj.to_dict()
    assert dump["repo"] == "beispiel"
    assert dump["planpunkte"] == data["planpunkte"]


# --- Loader mit Lesezugriffspruefung ----------------------------------------

def test_loader_gueltiges_manifest(tmp_path: Path):
    (tmp_path / MANIFEST_FILENAME).write_text(
        json.dumps(_gueltiges_manifest()), encoding="utf-8"
    )
    pack = controlcenter_context_pack(tmp_path)
    assert pack.repo == "beispiel"
    assert 1 in {p["incarnation"] for p in pack.planpunkte}


def test_loader_kein_manifest_liefert_leer(tmp_path: Path):
    pack = controlcenter_context_pack(tmp_path)
    assert pack.planpunkte == []
    assert pack.kennungen() == []


def test_loader_pfad_ausserhalb_root(tmp_path: Path, monkeypatch):
    # Ziel zeigt ausserhalb des Roots -> wird sicher abgewiesen -> leeres Manifest
    outside = tmp_path / ".." / "andere" / MANIFEST_FILENAME
    pack = controlcenter_context_pack(tmp_path, manifest_path=str(outside))
    assert pack.planpunkte == []


def test_loader_ungueltiges_json(tmp_path: Path):
    (tmp_path / MANIFEST_FILENAME).write_text("{ nicht-json", encoding="utf-8")
    with pytest.raises(ValueError):
        controlcenter_context_pack(tmp_path)


def test_default_manifest_path():
    p = default_manifest_path(Path("/x/y"))
    assert p == Path("/x/y") / MANIFEST_FILENAME
