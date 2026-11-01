"""Abbruchpfad-Tests fuer den fail-closed Installer (#3715).

Geprueft werden ausschliesslich Verweigerungspfade, die vor jeder Mutation
greifen muessen:

(a) Abweichung zwischen Manifest- und Profilkomponentenmenge
(b) fehlender bzw. falsch signierter Capability-Grant
(c) unvollstaendige Protokollierung beim Rollback (kein Loeschplan)
(d) Gegenprobe: gueltiges Manifest + Profil + Grant ergibt ``verify() == True``
(e) doppelte Komponentennamen in Manifest bzw. Profil
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from setup import BACHSetup  # noqa: E402
from system.tools.installer_manifest import (  # noqa: E402
    GRANT_SCHEMA,
    MANIFEST_SCHEMA,
    PRODUCT_PROFILE_SCHEMA,
    InstallerVerificationError,
    MutationJournal,
    component_names,
    compute_grant_signature,
    file_digest,
    load_manifest,
    payload_digest,
    plan_rollback,
)

KEY = "test-key-3715"
PROFILE_ID = "test-profile"


def _write_json(path: Path, data: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _manifest(components: list[str]) -> dict:
    return {
        "schema": MANIFEST_SCHEMA,
        "manifest_version": 1,
        "manifest_id": "test.v1",
        "components": [{"name": name} for name in components],
    }


def _profile(components: list[str]) -> dict:
    return {
        "schema": PRODUCT_PROFILE_SCHEMA,
        "profile_id": PROFILE_ID,
        "profile_version": 1,
        "components": list(components),
    }


def _grant(manifest: dict, key: str = KEY) -> dict:
    body = {
        "schema": GRANT_SCHEMA,
        "grant_id": "test-grant",
        "manifest_digest": payload_digest(manifest),
        "profile_id": PROFILE_ID,
    }
    body["signature"] = compute_grant_signature(body, key)
    return body


def _setup(
    tmp_path: Path,
    manifest_components: list[str],
    profile_components: list[str],
    *,
    sign_key: str = KEY,
    write_grant: bool = True,
) -> BACHSetup:
    manifest = _manifest(manifest_components)
    manifest_path = _write_json(tmp_path / "manifest.json", manifest)
    profile_path = _write_json(tmp_path / "profile.json", _profile(profile_components))
    grant_path = tmp_path / "grant.json"
    if write_grant:
        _write_json(grant_path, _grant(manifest, sign_key))
    return BACHSetup(
        bach_root=tmp_path,
        manifest_path=manifest_path,
        grant_path=grant_path,
        product_profile_path=profile_path,
        grant_key=KEY,
    )


def test_komponentenmengen_abweichung_bricht_ab(tmp_path: Path) -> None:
    """(a) Profil fordert mehr Komponenten als das Manifest liefert."""
    installer = _setup(
        tmp_path,
        manifest_components=["alpha", "beta"],
        profile_components=["alpha", "beta", "gamma"],
    )

    with pytest.raises(InstallerVerificationError) as excinfo:
        installer.verify()

    message = str(excinfo.value)
    assert "Komponentenmenge weicht ab" in message
    assert "gamma" in message
    # Fail-closed: keine Journaldatei, also keine protokollierte Mutation.
    assert not installer.journal_path.exists()


def test_ueberzaehlige_manifestkomponenten_brechen_ab(tmp_path: Path) -> None:
    """(a) Umgekehrte Richtung: Manifest liefert zu viel."""
    installer = _setup(
        tmp_path,
        manifest_components=["alpha", "beta", "gamma"],
        profile_components=["alpha", "beta"],
    )

    with pytest.raises(InstallerVerificationError) as excinfo:
        installer.verify()

    assert "ueberzaehlig" in str(excinfo.value)
    assert not installer.journal_path.exists()


def test_fehlender_grant_bricht_ab(tmp_path: Path) -> None:
    """(b) Ohne Grantdatei darf verify() nie wahr werden."""
    installer = _setup(
        tmp_path,
        manifest_components=["alpha", "beta"],
        profile_components=["alpha", "beta"],
        write_grant=False,
    )

    with pytest.raises(InstallerVerificationError):
        installer.verify()


def test_falsch_signierter_grant_bricht_ab(tmp_path: Path) -> None:
    """(b) Signatur mit fremdem Schluessel wird abgewiesen."""
    installer = _setup(
        tmp_path,
        manifest_components=["alpha", "beta"],
        profile_components=["alpha", "beta"],
        sign_key="fremder-schluessel",
    )

    with pytest.raises(InstallerVerificationError):
        installer.verify()

    assert not installer.journal_path.exists()


def test_plan_rollback_ohne_vollstaendige_protokollierung(tmp_path: Path) -> None:
    """(c) Fehlt eine erwartete Komponente im Journal, gibt es keinen Loeschplan."""
    target = tmp_path / "installiert" / "alpha.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("alpha", encoding="utf-8")

    journal_path = tmp_path / "journal.jsonl"
    journal = MutationJournal(journal_path)
    journal.record("install", target, digest=file_digest(target), component="alpha")

    with pytest.raises(InstallerVerificationError) as excinfo:
        plan_rollback(journal_path, expected_components=["alpha", "beta"])

    assert "unvollstaendige Protokollierung" in str(excinfo.value)
    # Kein Loeschplan bedeutet auch: nichts wurde angefasst.
    assert target.is_file()


def test_plan_rollback_umgekehrte_reihenfolge_nach_vollpruefung(tmp_path: Path) -> None:
    """Gegenprobe zu (c): vollstaendige Protokollierung ergibt einen Plan."""
    first = tmp_path / "installiert" / "alpha.txt"
    second = tmp_path / "installiert" / "beta.txt"
    first.parent.mkdir(parents=True, exist_ok=True)
    first.write_text("alpha", encoding="utf-8")
    second.write_text("beta", encoding="utf-8")

    journal_path = tmp_path / "journal.jsonl"
    journal = MutationJournal(journal_path)
    journal.record("install", first, digest=file_digest(first), component="alpha")
    journal.record("write", second, digest=file_digest(second), component="beta")

    plan = plan_rollback(journal_path, expected_components=["alpha", "beta"])

    assert [str(item) for item in plan] == [str(second), str(first)]


def test_gueltige_konfiguration_ergibt_verify_true(tmp_path: Path) -> None:
    """(d) Korrektes Manifest, passendes Profil und gueltiger Grant."""
    components = ["alpha", "beta", "gamma"]
    installer = _setup(
        tmp_path,
        manifest_components=components,
        profile_components=components,
    )

    assert installer.verify() is True

    # Die Verifikation selbst ist protokolliert, aber nicht als Mutation.
    journal_path = installer.journal_path
    assert journal_path.is_file()
    entries = [json.loads(line) for line in journal_path.read_text("utf-8").splitlines() if line.strip()]
    assert [entry["op"] for entry in entries] == ["verify"]
    with pytest.raises(InstallerVerificationError):
        plan_rollback(journal_path)
    assert component_names(load_manifest(installer.manifest_path)["components"]) == components


def test_doppelte_manifestkomponente_bricht_ab(tmp_path: Path) -> None:
    """(e) Ein doppelter Manifestname ist ein Manifestfehler, keine Mengengleichheit."""
    installer = _setup(
        tmp_path,
        manifest_components=["alpha", "alpha", "beta"],
        profile_components=["alpha", "beta"],
    )

    with pytest.raises(InstallerVerificationError) as excinfo:
        installer.verify()

    assert "doppelt im Manifest" in str(excinfo.value)
    assert "alpha" in str(excinfo.value)
    # Fail-closed: die Pruefung bricht vor jeder Mutation ab.
    assert not installer.journal_path.exists()


def test_doppelte_profilkomponente_bricht_ab(tmp_path: Path) -> None:
    """(e) Eine doppelte Sollkomponente im Profil darf die Mengenpruefung nicht verwaessern."""
    installer = _setup(
        tmp_path,
        manifest_components=["alpha", "beta"],
        profile_components=["alpha", "beta", "beta"],
    )

    with pytest.raises(InstallerVerificationError) as excinfo:
        installer.verify()

    assert "Soll-Menge enthaelt Duplikate" in str(excinfo.value)
    assert "beta" in str(excinfo.value)
    assert not installer.journal_path.exists()
