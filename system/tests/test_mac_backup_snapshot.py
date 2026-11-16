"""Tests fuer MAC-DATENSICHERUNG: system/tools/mac_backup_snapshot.py (Task #2635).

Eigenstaendig lauffaehig: nur tmp_path, kein Netz. git wird ausschliesslich
via subprocess benutzt; Tests skippen, wenn git fehlt.
"""

import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

_SYSTEM_DIR = Path(__file__).resolve().parents[1]
if str(_SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(_SYSTEM_DIR))

from tools.mac_backup_snapshot import (  # noqa: E402
    GATE_LIMITS,
    NAMED_REPOS,
    RESTORE_CONTRACT,
    UNNAMED_REPOS,
    create_git_bundle,
    create_zip_backup,
    gates_report,
    run_backup,
    sha256_file,
    verify_manifest,
    write_manifest,
)

GIT = shutil.which("git")
requires_git = pytest.mark.skipif(GIT is None, reason="git nicht verfuegbar")


@pytest.fixture
def git_repo(tmp_path):
    """Repo mit initialem Commit plus un-committeter Aenderung (dirty)."""
    if GIT is None:
        pytest.skip("git nicht verfuegbar")
    repo = tmp_path / NAMED_REPOS[0]
    repo.mkdir()

    def run(*args):
        proc = subprocess.run([GIT, *args], cwd=str(repo), capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr
        return proc

    run("init")
    run("config", "user.email", "mac-backup-test@example.invalid")
    run("config", "user.name", "Mac Backup Test")
    (repo / "README.md").write_text("mac backup snapshot test\n", encoding="utf-8")
    run("add", ".")
    run("commit", "-m", "initial")
    (repo / "worklog.md").write_text("dirty change\n", encoding="utf-8")
    return repo


def test_cli_gates_und_contract_ausgabe(capsys):
    """CLI-Smoke: --gates und --print-contract liefern benannte Infos."""
    from tools.mac_backup_snapshot import main

    assert main(["--print-contract"]) == 0
    out = capsys.readouterr().out
    assert "File Restore Handler" in out

    assert main(["--gates"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["task"] == 2635
    assert data["open_gates"] == ["G1", "G2", "G3", "G4", "G5"]


def test_named_repos_liste_exakt():
    assert len(NAMED_REPOS) == 4
    assert len(set(NAMED_REPOS)) == 4
    assert NAMED_REPOS == [
        "awesome-phone-call-agents",
        "call-e-integrations",
        "cockroachdb-skills",
        "OpenMontage",
    ]


def test_unnamed_repros_status_pending_identification():
    assert set(UNNAMED_REPOS) == {"R5", "R6", "R7"}
    for key in ("R5", "R6", "R7"):
        info = UNNAMED_REPOS[key]
        assert info["status"] == "PENDING_IDENTIFICATION"
        assert "host-abhaengig" in info["note"]


def test_restore_contract_zitiert_hub_vertrag():
    assert "File Restore Handler (SQ020/HQ6)" in RESTORE_CONTRACT
    assert "Stellt einzelne Dateien aus dist_file_versions wieder her." in RESTORE_CONTRACT
    assert "distribution.db/manifest" in RESTORE_CONTRACT
    assert "file (mit --version=X)" in RESTORE_CONTRACT
    assert "(success, message)" in RESTORE_CONTRACT
    assert "system/hub/restore.py" in RESTORE_CONTRACT


@requires_git
def test_deep_verify_roundtrip_ueber_manifest(tmp_path, git_repo):
    """Deep-Verify: SHA + ZIP-CRC + Bundle-Refs je gesichertem Gegenstand."""
    result = run_backup({NAMED_REPOS[0]: str(git_repo)}, tmp_path / "out", "td")

    # Standard (ohne deep): Artefakt-Eintraege ok, weil SHA stimmt.
    results = [i for i in verify_manifest(result["manifest_path"]) if i["kind"] in ("zip", "bundle")]
    assert results and all(item["ok"] for item in results)
    assert all(item["reason"] == "SHA256 stimmt" for item in results)

    # Deep: ZIP-CRC/Mitglieder und Bundle-Refs zusaetzlich geprueft.
    deep = verify_manifest(result["manifest_path"], deep=True)
    by_kind = {}
    for item in deep:
        by_kind.setdefault(item["kind"], []).append(item)
    assert all(item["ok"] for item in by_kind["zip"] + by_kind["bundle"])
    assert "ZIP-Inhalt intakt" in by_kind["zip"][0]["reason"]
    assert "Bundle enthaelt alle Refs" in by_kind["bundle"][0]["reason"]


def test_deep_verify_erkennt_beschaedigtes_zip(tmp_path):
    """Deep-Verify faellt auf FAIL, wenn ZIP nach Manifest CRC-Fehler hat."""
    target = tmp_path / "demo.zip"
    original = b"PK\x03\x04" + b"0" * 64  # gueltiger ZIP-Kopf, aber kein Zentralverzeichnis
    target.write_bytes(original)
    sha = hashlib.sha256(original).hexdigest()
    entry = {
        "repo": "demo", "kind": "zip", "path": str(target),
        "bytes": len(original), "sha256": sha, "note": "",
    }
    manifest = tmp_path / "manifest-deep.json"
    manifest.write_text(json.dumps({"entries": [entry]}), encoding="utf-8")

    # Ohne deep: SHA stimmt -> ok (alter Stand).
    assert verify_manifest(manifest)[0]["ok"] is True
    # Deep: ZIP ist unlesbar -> ok=False mit Restore-Beleg-Begruendung.
    deep = verify_manifest(manifest, deep=True)[0]
    assert deep["ok"] is False
    assert "Restore-Beleg unzulaenglich" in deep["reason"]
    assert "ZIP nicht lesbar" in deep["reason"]


def test_gates_report_listet_alle_gates_und_repos():
    report = gates_report()
    assert report["task"] == 2635
    assert report["named_repos"] == NAMED_REPOS
    assert set(report["unnamed_repos"]) == {"R5", "R6", "R7"}
    assert all(v == "PENDING_IDENTIFICATION" for v in report["unnamed_repos"].values())
    # Jeder Gate ist mit Status/Topic/Owner benannt und als OFFEN gekennzeichnet.
    ids = [g["id"] for g in report["gates"]]
    assert ids == ["G1", "G2", "G3", "G4", "G5"]
    for gate in report["gates"]:
        assert gate["status"] == "OFFEN"
        assert gate["topic"] and gate["owner"]
        assert gate["blockiert"]
    assert report["open_gates"] == ids
    assert report["restore_contract_ref"] == RESTORE_CONTRACT
    # Gesamtzahl GATE_LIMITS == gemsensen Report-Gates.
    assert len(GATE_LIMITS) == len(report["gates"])


def test_unnamed_repos_werden_nicht_gesichert(tmp_path, git_repo):
    result = run_backup({"R5": str(git_repo)}, tmp_path / "out", "t6")
    r5 = [e for e in result["entries"] if e["repo"] == "R5"]
    assert len(r5) == 1
    assert r5[0]["kind"] == "skipped"
    assert r5[0]["path"] is None
    assert r5[0]["sha256"] is None
    assert "unidentifiziert" in r5[0]["note"]


@requires_git
def test_backup_erzeugt_und_zip(tmp_path, git_repo):
    out = tmp_path / "out"
    result = run_backup({NAMED_REPOS[0]: str(git_repo)}, out, "t1")

    manifest_path = Path(result["manifest_path"])
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["tag"] == "t1"
    assert len(manifest["entries"]) == len(result["entries"])

    zip_entry = next(e for e in result["entries"] if e["kind"] == "zip")
    bundle_entry = next(e for e in result["entries"] if e["kind"] == "bundle")
    assert zip_entry["repo"] == NAMED_REPOS[0]
    assert bundle_entry["repo"] == NAMED_REPOS[0]

    zip_path = Path(zip_entry["path"])
    bundle_path = Path(bundle_entry["path"])
    assert zip_path.exists() and zip_path.stat().st_size > 0
    assert bundle_path.exists() and bundle_path.stat().st_size > 0

    # .git ist im ZIP enthalten und dirty-Status erkannt
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        assert any(".git/HEAD" in name for name in names)
    assert zip_entry["dirty"] is True
    assert zip_entry["git_head"] is not None
    assert len(zip_entry["git_head"]) == 40

    # Gesamtbild: 1 benanntes gesichert (2 Artefakte) + 3 benannte skipped + 3 unname
    assert len(result["entries"]) == 2 + (len(NAMED_REPOS) - 1) + len(UNNAMED_REPOS)


@requires_git
def test_manifest_sha256_stimmt(tmp_path, git_repo):
    result = run_backup({NAMED_REPOS[0]: str(git_repo)}, tmp_path / "out", "t2")
    artifacts = [e for e in result["entries"] if e["kind"] in ("zip", "bundle")]
    assert len(artifacts) == 2
    for entry in artifacts:
        path = Path(entry["path"])
        assert entry["bytes"] == path.stat().st_size
        assert entry["sha256"] == sha256_file(path)
        assert entry["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()


def test_verify_manifest_erkennt_tamper(tmp_path):
    # Manipulierter Eintrag ohne echtes Backup-Setup: Datei + falsch gepflegtes target
    target = tmp_path / "demo.zip"
    original = b"PAKET-INHALT-v1"

    def build(manifest_path, sha):
        entry = {
            "repo": "demo", "kind": "zip", "path": str(target),
            "bytes": len(original), "sha256": sha, "note": "",
        }
        Path(manifest_path).write_text(
            json.dumps({"entries": [entry]}), encoding="utf-8"
        )

    target.write_bytes(original)
    build(tmp_path / "manifest-ok.json", hashlib.sha256(original).hexdigest())
    results = verify_manifest(tmp_path / "manifest-ok.json")
    assert results[0]["ok"] is True
    assert results[0]["reason"] == "SHA256 stimmt"

    # TAMPER: Inhalt wird veraendert, Manifest bleibt unveraendert
    target.write_bytes(original + b"TAMPER")
    results = verify_manifest(tmp_path / "manifest-ok.json")
    assert results[0]["ok"] is False
    assert "TAMPER" in results[0]["reason"].upper()
    assert "SHA256" in results[0]["reason"].upper()


def test_verify_manifest_erkenn_t_ftlende_datei(tmp_path):
    entry = {
        "repo": "demo", "kind": "zip",
        "path": str(tmp_path / "fehlt.zip"), "bytes": 1, "sha256": "0" * 64,
        "note": "",
    }
    results = verify_manifest([entry])
    assert results[0]["ok"] is False
    assert "fehlt" in results[0]["reason"]


def test_fehlendes_inventar_alles_skipped_ohne_dateien(tmp_path):
    out = tmp_path / "out"
    result = run_backup({}, out, "t4")
    assert len(result["entries"]) == len(NAMED_REPOS) + len(UNNAMED_REPOS)
    assert all(e["kind"] == "skipped" for e in result["entries"])
    assert list(out.glob("*.zip")) == []
    assert list(out.glob("*.bundle")) == []
    for entry in result["entries"]:
        if entry["repo"] in NAMED_REPOS:
            assert entry["path"] is None
            assert "nicht gesichert" in entry["note"]
            assert "Auto-Annahme" in entry["note"]
        else:
            assert entry["repo"] in UNNAMED_REPOS
            assert "unidentifiziert" in entry["note"]
    # Verify meldet skipped-Eintraege als nicht-geeignet (fail mit Grund)
    results = verify_manifest(result["manifest_path"])
    assert len(results) == len(result["entries"])
    assert all(item["ok"] is False for item in results)


def test_unbekannter_und_fehler_Host_pfad(tmp_path):
    out = tmp_path / "out"
    inventory = {
        NAMED_REPOS[0]: "UNBEKANNT",
        NAMED_REPOS[1]: str(tmp_path / "existiert-nicht"),
    }
    result = run_backup(inventory, out, "t5")
    by_repo = {}
    for entry in result["entries"]:
        by_repo.setdefault(entry["repo"], []).append(entry)
    for repo in (NAMED_REPOS[0], NAMED_REPOS[1]):
        assert len(by_repo[repo]) == 1
        assert by_repo[repo][0]["kind"] == "skipped"
        assert by_repo[repo][0]["sha256"] is None
    assert "UNBEKANNT" in by_repo[NAMED_REPOS[0]][0]["note"]
    assert "nicht erreichbar" in by_repo[NAMED_REPOS[1]][0]["note"]
    assert list(out.glob("*.zip")) == []


def test_write_manifest_und_artefakt_funktionen(tmp_path):
    entries = [{
        "repo": "demo", "kind": "zip", "path": str(tmp_path / "a.zip"),
        "bytes": None, "sha256": None, "timestamp": "x",
        "git_head": None, "dirty": None, "note": "Direkttest", "restore_ref": None,
    }]
    out = write_manifest(entries, tmp_path / "sub" / "manifest.json", "dx")
    data = json.loads(Path(out).read_text(encoding="utf-8"))
    assert data["tag"] == "dx"
    assert data["entries"][0]["note"] == "Direkttest"
    assert "sha256" in data["entries"][0]

    # Skript-Funktionen direkt: zip + bundle gegen git-losem Ordner (tolerantes bundle)
    demo = tmp_path / "demo-repo"
    demo.mkdir()
    (demo / "f.txt").write_text("x", encoding="utf-8")
    zip_entry = create_zip_backup(demo, tmp_path, "dz")
    assert zip_entry["kind"] == "zip" and zip_entry["sha256"] == sha256_file(zip_entry["path"])
    assert zip_entry["git_head"] is None  # kein git-Repo
    bundle_entry = create_git_bundle(demo, tmp_path, "dz")
    assert bundle_entry["kind"] == "bundle-failed"  # Fehler toleriert, notiert
    assert "fehlgeschlagen" in bundle_entry["note"]
