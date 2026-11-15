#!/usr/bin/env python3
"""MAC-DATENSICHERUNG: mac_backup_snapshot.py

Erzeugt je benanntem Lokal-Repo eine ZIP-Sicherung (kompletter Ordner,
inkl. .git, fs_protection-Stil: keine Symlink-Verfolgung) und ein git
bundle (git bundle create <file>.bundle --all), notiert beide Artefakte
zusammen mit SHA256/Bytes/Timestamp/HEAD/Dirty im JSON-Manifest und
prueft Manifeste wieder (Restore-Verify: SHA-Neuberechnung, Tamper- und
Missing-Erkennung).

Regeln (Taskanalyse #2635):
- KEINE Auto-Annahme von Host-Pfaden. Der Windows-Host ist von hier nicht
  erreichbar; alle lokalen Repo-Ordner kommen ausschliesslich aus dem
  Inventar-JSON (--inventory). Fehlt ein Repo dort oder ist sein Pfad
  UNBEKANNT/nicht erreichbar, entsteht nur ein skipped-Eintrag mit Grund.
- Unbenannte Repos (R5/R6/R7) tragen status PENDING_IDENTIFICATION und
  werden absichtlich NICHT gesichert; ihre Identifizierung ist
  host-abhaengig und beim Nutzer zu erfragen (Gate G1).
- Der Restore-Vertrag der Hub-Seite wird als RESTORE_CONTRACT zitiert.

CLI:
  python system/tools/mac_backup_snapshot.py --inventory inventar.json --out backups --tag TAG
  python system/tools/mac_backup_snapshot.py --verify backups/manifest-TAG.json
  python system/tools/mac_backup_snapshot.py --print-contract

Inventar-Format (JSON-Objekt): {"<repo-name>": "<host-pfad oder UNBEKANNT>"}
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

# --- Konstanten -------------------------------------------------------------

# Von der Task festgelegte, benannte Repos (exakte Liste).
NAMED_REPOS = [
    "awesome-phone-call-agents",
    "call-e-integrations",
    "cockroachdb-skills",
    "OpenMontage",
]

# Unbenannte Repos: Identifizierung host-abhaengig, erst nach Nutzer-Klarstellung.
PENDING_STATUS = "PENDING_IDENTIFICATION"

UNNAMED_REPOS = {
    "R5": {
        "status": PENDING_STATUS,
        "note": "Repo unidentifiziert; Identifizierung host-abhaengig (Gate G1). Nicht gesichert.",
        "restore_ref": "blockiert bis Identifikation (Nutzer-Gate G1)",
    },
    "R6": {
        "status": PENDING_STATUS,
        "note": "Repo unidentifiziert; Identifizierung host-abhaengig (Gate G1). Nicht gesichert.",
        "restore_ref": "blockiert bis Identifikation (Nutzer-Gate G1)",
    },
    "R7": {
        "status": PENDING_STATUS,
        "note": "Repo unidentifiziert; Identifizierung host-abhaengig (Gate G1). Nicht gesichert.",
        "restore_ref": "blockiert bis Identifikation (Nutzer-Gate G1)",
    },
}

# Zitierfahebner Restore-Vertrag aus dem Hub (Quelle im Kopf jeder Zeile).
RESTORE_CONTRACT = (
    "RESTORE-VERTRAG (Quelle: system/hub/restore.py, Zeilen 4-16 sowie 54-59)\n"
    'Wortlaut: "File Restore Handler (SQ020/HQ6)"\n'
    'Wortlaut: "Stellt einzelne Dateien aus dist_file_versions wieder her. '
    'Nutzt gespeicherte Hashes + TEMPLATE-Dateien aus distribution.db/manifest."\n'
    "Operations: file (mit --version=X), list, category (mit --dry-run), info\n"
    "Returns: (success, message)\n"
    "Hinweis: Dieses Playbook sichert Repos (ZIP/bundle) und verifiziert "
    "SHA256-Manifeste vor Restore; einzelner Datei-Restore laeuft ueber den "
    "oben zitierten Hub-Handler."
)

# --- Hilfsfunktionen --------------------------------------------------------


def _utc_now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _default_tag():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def sha256_file(path):
    """SHA256 einer Datei (Hexdigest)."""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_state(repo_path):
    """(head_sha | None, dirty | None). None bedeutet: kein/beschaedigtes git-Repo."""
    # GIT_CEILING_DIRECTORIES verhindert versehentliche Discovery eines
    # uebergeordneten Repos (z. B. wenn tmp_path im Worktree-Repo liegt).
    env = {**os.environ, "GIT_CEILING_DIRECTORIES": str(Path(repo_path).resolve().parent)}
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(repo_path), capture_output=True, text=True, env=env,
    )
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(repo_path), capture_output=True, text=True, env=env,
    )
    dirty = bool(status.stdout.strip()) if status.returncode == 0 else None
    return (head.stdout.strip() if head.returncode == 0 else None), dirty


def _base_entry(repo, kind, path, note, restore_ref=None):
    return {
        "repo": repo,
        "kind": kind,
        "path": str(path) if path else None,
        "bytes": None,
        "sha256": None,
        "timestamp": _utc_now_iso(),
        "git_head": None,
        "dirty": None,
        "note": note or "",
        "restore_ref": restore_ref,
    }


# --- Backup-Artefakte -------------------------------------------------------


def create_zip_backup(repo_path, out_dir, tag):
    """ZIP des kompletten Repo-Ordners inkl. .git (fs_protection-Stil:
    Symlinks werden weder als Ordner noch als Datei verfolgt)."""
    repo_path = Path(repo_path).resolve()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = out_dir / "{}-{}.zip".format(repo_path.name, tag)
    file_count = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(str(repo_path)):
            dirs[:] = sorted(
                d for d in dirs if not os.path.islink(os.path.join(root, d))
            )
            for name in sorted(
                f for f in files if not os.path.islink(os.path.join(root, f))
            ):
                full = os.path.join(root, name)
                arc = os.path.join(
                    repo_path.name, os.path.relpath(full, str(repo_path))
                )
                zf.write(full, arcname=arc)
                file_count += 1
    entry = _base_entry(
        repo_path.name,
        "zip",
        zip_path,
        "Vollbackup des Repo-Ordners inkl. .git ({} Dateien, kein Symlink-Follow)".format(
            file_count
        ),
        restore_ref="zip: Ordner am Zielort entpacken (Verzeichnis {}/)".format(
            repo_path.name
        ),
    )
    entry["bytes"] = zip_path.stat().st_size
    entry["sha256"] = sha256_file(zip_path)
    entry["git_head"], entry["dirty"] = _git_state(repo_path)
    return entry


def create_git_bundle(repo_path, out_dir, tag):
    """git bundle create <file>.bundle --all.

    Fehler werden toleriert: Bei Misserfolg entsteht ein Eintrag kind
    "bundle-failed" mit Grund in "note", statt dass der Backup-Lauf bricht.
    """
    repo_path = Path(repo_path).resolve()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = out_dir / "{}-{}.bundle".format(repo_path.name, tag)
    # GIT_CEILING_DIRECTORIES verhindert versehentliche Discovery eines
    # uebergeordneten Repos (z. B. wenn tmp_path im Worktree-Repo liegt).
    proc = subprocess.run(
        ["git", "bundle", "create", str(bundle_path), "--all"],
        cwd=str(repo_path), capture_output=True, text=True,
        env={**os.environ, "GIT_CEILING_DIRECTORIES": str(Path(repo_path).parent)},
    )
    head, dirty = _git_state(repo_path)
    if proc.returncode != 0 or not bundle_path.exists():
        lines = (proc.stderr or proc.stdout or "").strip().splitlines()
        reason = lines[0] if lines else "rc={}".format(proc.returncode)
        entry = _base_entry(
            repo_path.name,
            "bundle-failed",
            bundle_path,
            "git bundle create fehlgeschlagen (toleriert): {}".format(reason),
        )
        entry["git_head"], entry["dirty"] = head, dirty
        return entry
    entry = _base_entry(
        repo_path.name,
        "bundle",
        bundle_path,
        "git bundle --all (alle Refs, klonbar)",
        restore_ref="bundle: git clone <bundle-datei> zielverzeichnis",
    )
    entry["bytes"] = bundle_path.stat().st_size
    entry["sha256"] = sha256_file(bundle_path)
    entry["git_head"], entry["dirty"] = head, dirty
    return entry


# --- Manifest ---------------------------------------------------------------


def write_manifest(entries, out_path, tag):
    """Manifest als JSON schreiben. Pro Eintrag: repo, kind, path, bytes,
    sha256, timestamp, git_head, dirty, note, restore_ref."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "tool": "mac_backup_snapshot",
        "tag": tag,
        "created": _utc_now_iso(),
        "restore_contract_ref": "RESTORE_CONTRACT in diesem Modul (system/hub/restore.py:4-16/54-59)",
        "entries": list(entries),
    }
    out_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=True), encoding="utf-8"
    )
    return str(out_path)


def run_backup(inventory, out_dir, tag):
    """Backup-Lauf ueber das Inventar (dict repo->host-pfad).

    - Benannte Repos ohne/UNBEKANNT/unerreichbarem Pfad -> skipped-Eintrag.
    - R5/R6/R7 bleiben unangetastet (PENDING_IDENTIFICATION, skip).
    Rueckgabe: dict mit manifest_path, tag, entries.
    """
    if not isinstance(inventory, dict):
        raise ValueError("inventory muss ein JSON-Objekt repo->host-pfad sein")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    entries = []
    for repo in NAMED_REPOS:
        host_path = inventory.get(repo)
        if host_path is None:
            entries.append(
                _base_entry(
                    repo, "skipped", None,
                    "kein Host-Pfad im Inventar -> nicht gesichert "
                    "(keine Auto-Annahme von Pfaden)",
                )
            )
            continue
        if str(host_path).strip().upper() == "UNBEKANNT":
            entries.append(
                _base_entry(
                    repo, "skipped", None,
                    "Host-Pfad UNBEKANNT -> nicht gesichert",
                )
            )
            continue
        repo_dir = Path(str(host_path))
        if not repo_dir.exists():
            entries.append(
                _base_entry(
                    repo, "skipped", str(repo_dir),
                    "Host-Pfad nicht erreichbar/nicht vorhanden -> nicht gesichert",
                )
            )
            continue
        if not repo_dir.is_dir():
            entries.append(
                _base_entry(
                    repo, "skipped", str(repo_dir),
                    "Host-Pfad ist kein Ordner -> nicht gesichert",
                )
            )
            continue
        entries.append(create_zip_backup(repo_dir, out_dir, tag))
        entries.append(create_git_bundle(repo_dir, out_dir, tag))
    for key in sorted(UNNAMED_REPOS):
        info = UNNAMED_REPOS[key]
        entries.append(
            _base_entry(key, "skipped", None, info["note"], info["restore_ref"])
        )
    manifest_path = write_manifest(entries, out_dir / "manifest-{}.json".format(tag), tag)
    return {"manifest_path": manifest_path, "tag": tag, "entries": entries}


def _load_entries(manifest):
    """Akzeptiert Pfad, Manifest-Dict oder entries-Liste."""
    if isinstance(manifest, (str, os.PathLike)):
        data = json.loads(Path(manifest).read_text(encoding="utf-8"))
    elif isinstance(manifest, dict):
        data = manifest
    elif isinstance(manifest, list):
        data = {"entries": manifest}
    else:
        raise TypeError("manifest muss Pfad, Dict oder Liste sein")
    if isinstance(data, dict):
        return list(data.get("entries", []))
    return list(data)


def verify_manifest(manifest):
    """Restore-Verify: pro Eintrag SHA256 neu berechnen und vergleichen.

    Rueckgabe: Liste von {"repo", "kind", "ok", "reason"}.
    - ok=False mit "SHA256-Abweichung (TAMPER)" bei Veraenderung,
    - ok=False bei fehlender Datei (Missing),
    - ok=False fuer skipped/failed-Eintraege ohne Pruefwert (Grund in reason).
    """
    results = []
    for entry in _load_entries(manifest):
        result = {
            "repo": entry.get("repo"),
            "kind": entry.get("kind"),
            "path": entry.get("path"),
            "ok": False,
            "reason": "",
        }
        if entry.get("kind") in ("skipped", "bundle-failed") or not entry.get("sha256"):
            result["reason"] = entry.get("note") or "kein Pruefwert (skipped/failed)"
            results.append(result)
            continue
        path = entry.get("path")
        if not path or not os.path.exists(path):
            result["reason"] = "Datei fehlt: Manifest und Artefakt widerspruechig"
            results.append(result)
            continue
        actual = sha256_file(path)
        if actual != entry.get("sha256"):
            result["reason"] = "SHA256-Abweichung (TAMPER): erwartet {}..., ist {}...".format(
                str(entry.get("sha256"))[:12], actual[:12]
            )
        else:
            result["ok"] = True
            result["reason"] = "SHA256 stimmt"
        results.append(result)
    return results


# --- CLI --------------------------------------------------------------------


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="MAC-DATENSICHERUNG: ZIP+BUNDLE+SHA256-Manifest mit Restore-Verify"
    )
    parser.add_argument(
        "--inventory",
        help="JSON-Datei (Objekt): repo -> Host-Pfad. Pflicht fuer Backup (keine Auto-Annahme).",
    )
    parser.add_argument("--out", default="backups", help="Ausgabeordner fuer ZIP/Bundles/Manifest")
    parser.add_argument("--tag", default=None, help="Sicherungstag (Standard: UTC-Zeitstempel)")
    parser.add_argument("--verify", help="Manifest-JSON pruefen (Restore-Verify) und Ergebnis melden")
    parser.add_argument("--print-contract", action="store_true", help="RESTORE_CONTRACT ausgeben")
    args = parser.parse_args(argv)

    if args.print_contract:
        print(RESTORE_CONTRACT)
        return 0

    if args.verify:
        results = verify_manifest(args.verify)
        for item in results:
            print("{} {} [{}]: {}".format(
                "OK  " if item["ok"] else "FAIL",
                item["repo"],
                item["kind"],
                item["reason"],
            ))
        ok = bool(results) and all(item["ok"] for item in results)
        return 0 if ok else 1

    if not args.inventory:
        parser.error(
            "--inventory ist fuer Backup erforderlich (keine Auto-Annahme von Host-Pfaden); "
            "alternativ --verify oder --print-contract."
        )
    with open(args.inventory, encoding="utf-8") as fh:
        inventory = json.load(fh)
    tag = args.tag or _default_tag()
    backup = run_backup(inventory, args.out, tag)
    print(json.dumps(
        {"manifest": backup["manifest_path"], "entries": len(backup["entries"])},
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    sys.exit(main())
