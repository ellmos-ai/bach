#!/usr/bin/env python3
"""
Modul-Gate Prüf-Skript

Prüft, ob Änderungen am BACH-System den modularen Grenzen entsprechen.
Wird als einziger Required Check im CI betrieben.

Prüfkriterien (aus MODUL-ZUORDNUNG.md Abschnitt 5):
1. CI-Workflow module-gate als einziger Required Check
2. Zeilen-Ratsche je Kerndatei (keine Netto-Zunahme in system/core/*.py)
3. Neue _services-Dateien nur mit Adapter-Kopfzeile
4. Pfadverbot: system/gui/web/** (keine Netto-Zunahme in Ressourcendateien)
5. Ausnahme nur mit Label plus Task-ID
"""

import os
import sys
import re
import argparse
import subprocess

# Pfad-Definitionen
def find_repo_root():
    ws = os.getenv("GITHUB_WORKSPACE")
    if ws and os.path.isdir(ws):
        return os.path.abspath(ws)
    candidate = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    if os.path.isdir(candidate):
        return candidate
    return os.getcwd()

REPO_ROOT = find_repo_root()

CONFIG = {
    "forbidden_paths": ["system/gui/web/**"],
    "required_header": "# BACH Adapter: ",
    "module_id_pattern": r"bauort:([a-zA-Z0-9_-]+)",
    "core_dir": "system/core",
    "resource_extensions": [".jpg", ".png", ".svg", ".ico", ".woff", ".woff2", ".ttf", ".eot"],
}


def load_task_metadata(repo_root=None):
    """Lädt Task-Metadaten aus der TaskDB/Task-Datei."""
    if repo_root is None:
        repo_root = REPO_ROOT
    task_file = os.path.join(repo_root, "task_result.md")
    if os.path.exists(task_file):
        with open(task_file, "r", encoding="utf-8") as f:
            content = f.read()
        task_id_match = re.search(r"Task #(\d+)", content)
        bauort_match = re.search(r"bauort:([a-zA-Z0-9_-]+)", content)
        return {
            "task_id": task_id_match.group(1) if task_id_match else None,
            "bauort": bauort_match.group(1) if bauort_match else None,
        }
    return {"task_id": None, "bauort": None}


def check_path_compliance(filepath, forbidden_patterns):
    """Prüft, ob ein Pfad den Verbotsmustern entspricht."""
    norm_path = filepath.replace("\\", "/")
    for pattern in forbidden_patterns:
        regex_pattern = pattern.replace("**", ".*")
        if re.search(regex_pattern, norm_path):
            return False, f"Verbotener Pfad: {filepath} passt zu {pattern}"
    return True, "OK"


def check_header_compliance(filepath, base_ref=None, repo_root=None):
    """Prüft, ob eine neue _services-Datei die Adapter-Kopfzeile hat."""
    norm_path = filepath.replace("\\", "/")
    if "_services" not in norm_path:
        return True, "Keine Services-Datei, Prüfung entfällt"
    
    if not norm_path.endswith(".py"):
        return True, "Keine Python-Datei, Prüfung entfällt"
    
    if repo_root is None:
        repo_root = REPO_ROOT

    # Prüfe ob Datei neu ist (Bestandsschutz für existierende Dateien)
    if not base_ref:
        base_ref = os.getenv("BACH_MODULE_GATE_BASE") or os.getenv("GITHUB_BASE_REF")

    if base_ref:
        base_ref = base_ref.strip()
        existed = False
        for ref in [f"origin/{base_ref}", base_ref]:
            res = subprocess.run(
                ["git", "cat-file", "-e", f"{ref}:{norm_path}"],
                capture_output=True, cwd=repo_root
            )
            if res.returncode == 0:
                existed = True
                break
        if existed:
            return True, "Existierende Datei (Bestandsschutz)"

    full_path = os.path.join(repo_root, filepath)
    if not os.path.exists(full_path):
        return True, "Datei gelöscht, Prüfung entfällt"

    try:
        with open(full_path, "r", encoding="utf-8") as f:
            first_line = f.readline().strip()
        if first_line.startswith("# BACH Adapter:"):
            return True, "Kopfzeile gefunden"
        else:
            return False, f"Fehlende Kopfzeile in {filepath}: erste Zeile ist '{first_line}'"
    except Exception as e:
        return False, f"Fehler beim Lesen von {filepath}: {e}"


def get_changed_files(base_ref=None, repo_root=None):
    """
    Ermittelt geänderte Dateien via git diff.
    1. Uncommitted changes gegen HEAD (`git diff --name-only HEAD`).
    2. Falls base_ref gesetzt ist (oder via BACH_MODULE_GATE_BASE / GITHUB_BASE_REF):
       diff origin/<base>...HEAD (Fallback: <base>...HEAD, Fallback: HEAD~1...HEAD).
    """
    if repo_root is None:
        repo_root = REPO_ROOT

    changed = []

    # 1. Uncommitted changes gegen HEAD
    try:
        res = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            capture_output=True, text=True, cwd=repo_root
        )
        if res.returncode == 0 and res.stdout.strip():
            for line in res.stdout.splitlines():
                f = line.strip().replace("\\", "/")
                if f and f not in changed:
                    changed.append(f)
    except Exception:
        pass

    # 2. Base-Ref ermitteln
    if not base_ref:
        base_ref = os.getenv("BACH_MODULE_GATE_BASE") or os.getenv("GITHUB_BASE_REF")

    if base_ref:
        base_ref = base_ref.strip()
        candidates = [
            f"origin/{base_ref}...HEAD",
            f"{base_ref}...HEAD",
            "HEAD~1...HEAD",
        ]
        for target in candidates:
            try:
                res = subprocess.run(
                    ["git", "diff", "--name-only", target],
                    capture_output=True, text=True, cwd=repo_root
                )
                if res.returncode == 0:
                    for line in res.stdout.splitlines():
                        f = line.strip().replace("\\", "/")
                        if f and f not in changed:
                            changed.append(f)
                    break
            except Exception:
                continue

    return changed


get_git_changed_files = get_changed_files


def get_git_base_head():
    """Ermittelt base und head commit für PR."""
    try:
        base = os.getenv("BACH_MODULE_GATE_BASE") or os.getenv("GITHUB_BASE_REF")
        head = os.getenv("GITHUB_HEAD_REF")
        if base and head:
            return base, head
    except Exception:
        pass
    return None, None


def check_line_ratchet(filepath, changed_files, base_ref=None, repo_root=None):
    """
    Prüft Zeilen-Ratsche: Keine Netto-Zunahme an Zeilen in Kern-Dateien (system/core/*.py).
    Vergleicht aktuelle Zeilen mit BASE-Commit.
    """
    norm_path = filepath.replace("\\", "/")
    if not norm_path.startswith(CONFIG["core_dir"]):
        return True, "Nicht Kern-Datei"
    
    if not norm_path.endswith(".py"):
        return True, "Keine Python-Datei"
    
    if filepath not in changed_files and norm_path not in changed_files:
        return True, "Nicht geändert"
    
    if repo_root is None:
        repo_root = REPO_ROOT

    try:
        full_path = os.path.join(repo_root, filepath)
        if not os.path.exists(full_path):
            return True, "Datei gelöscht"

        with open(full_path, "r", encoding="utf-8") as f:
            current_lines = len(f.readlines())
        
        if not base_ref:
            base_ref = os.getenv("BACH_MODULE_GATE_BASE") or os.getenv("GITHUB_BASE_REF")

        if base_ref:
            base_ref = base_ref.strip()
            result = subprocess.run(
                ["git", "show", f"origin/{base_ref}:{norm_path}"],
                capture_output=True, text=True, cwd=repo_root
            )
            if result.returncode != 0:
                result = subprocess.run(
                    ["git", "show", f"{base_ref}:{norm_path}"],
                    capture_output=True, text=True, cwd=repo_root
                )
            if result.returncode == 0:
                base_lines = len(result.stdout.splitlines())
                if current_lines > base_lines:
                    return False, f"Zeilen-Ratsche verletzt: {filepath} hat {current_lines} Zeilen (Base: {base_lines})"
                return True, f"Zeilen-Ratsche OK: {filepath} {current_lines} Zeilen (Base: {base_lines})"
        
        return True, f"Kein Base-Vergleich möglich, aktuelle Zeilen: {current_lines}"
    except Exception as e:
        return False, f"Fehler bei Zeilen-Ratsche-Prüfung für {filepath}: {e}"


def check_resource_net_increase(filepath, changed_files, base_ref=None, repo_root=None):
    """
    Prüft: Keine Netto-Zunahme in Ressourcendateien (Bilder, Fonts, etc.).
    """
    norm_path = filepath.replace("\\", "/")
    if filepath not in changed_files and norm_path not in changed_files:
        return True, "Nicht geändert"
    
    _, ext = os.path.splitext(filepath)
    if ext.lower() not in CONFIG["resource_extensions"]:
        return True, "Keine Ressourcen-Datei"
    
    if repo_root is None:
        repo_root = REPO_ROOT

    try:
        full_path = os.path.join(repo_root, filepath)
        if not os.path.exists(full_path):
            return True, "Datei gelöscht"

        if not base_ref:
            base_ref = os.getenv("BACH_MODULE_GATE_BASE") or os.getenv("GITHUB_BASE_REF")

        if base_ref:
            base_ref = base_ref.strip()
            result = subprocess.run(
                ["git", "show", f"origin/{base_ref}:{norm_path}"],
                capture_output=True, text=True, cwd=repo_root
            )
            if result.returncode != 0:
                result = subprocess.run(
                    ["git", "show", f"{base_ref}:{norm_path}"],
                    capture_output=True, text=True, cwd=repo_root
                )
            if result.returncode == 0:
                base_size = len(result.stdout.encode())
                current_size = os.path.getsize(full_path)
                if current_size > base_size:
                    return False, f"Ressourcen-Zunahme: {filepath} {current_size} Bytes (Base: {base_size})"
                return True, f"Ressourcen OK: {filepath} {current_size} Bytes (Base: {base_size})"
    except Exception as e:
        return False, f"Fehler bei Ressourcen-Prüfung für {filepath}: {e}"
    
    return True, "Kein Base-Vergleich möglich"


def check_exception_label(task_id, bauort):
    """
    Prüft: Ausnahme nur mit Label plus Task-ID.
    Prüft GitHub PR Labels auf 'ausnahme:<task-id>'.
    """
    if not bauort or not bauort.startswith("ausnahme:"):
        return True, "Keine Ausnahme"
    
    if not task_id:
        return False, "Ausnahme ohne Task-ID nicht erlaubt"
    
    pr_number = os.getenv("GITHUB_EVENT_NUMBER")
    if pr_number:
        if f"ausnahme:{task_id}" == bauort:
            return True, f"Ausnahme mit Task-ID {task_id} erlaubt"
        return False, f"Ausnahme-Label {bauort} passt nicht zu Task {task_id}"
    
    return True, "Kein PR-Kontext, Ausnahme-Prüfung übersprungen"


def extract_bauort_from_pr(repo_root=None):
    """Extrahiert Bauort aus PR-Titel, -Beschreibung oder Commits."""
    if repo_root is None:
        repo_root = REPO_ROOT

    pr_title = os.getenv("GITHUB_EVENT_PULL_REQUEST_TITLE", "")
    pr_body = os.getenv("GITHUB_EVENT_PULL_REQUEST_BODY", "")
    
    for text in [pr_title, pr_body]:
        match = re.search(r"bauort:([a-zA-Z0-9_:-]+)", text)
        if match:
            return match.group(1)
    
    try:
        result = subprocess.run(
            ["git", "log", "-5", "--pretty=format:%s"],
            capture_output=True, text=True, cwd=repo_root
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                match = re.search(r"bauort:([a-zA-Z0-9_:-]+)", line)
                if match:
                    return match.group(1)
    except Exception:
        pass
    
    return None


def main(argv=None):
    parser = argparse.ArgumentParser(description="Modul-Gate CI-Check")
    parser.add_argument("--base", dest="base_ref", default=None, help="Base Git-Ref für Diff (z.B. main)")
    parser.add_argument("--repo", dest="repo_root", default=None, help="Repository Root Pfad")
    args, unknown = parser.parse_known_args(argv)

    repo_root = os.path.abspath(args.repo_root) if args.repo_root else REPO_ROOT
    base_ref = args.base_ref or os.getenv("BACH_MODULE_GATE_BASE") or os.getenv("GITHUB_BASE_REF")

    print("=== Modul-Gate CI-Check ===")
    
    meta = load_task_metadata(repo_root=repo_root)
    task_id = meta.get("task_id")
    bauort = meta.get("bauort")
    
    if not bauort:
        bauort = extract_bauort_from_pr(repo_root=repo_root)
    
    print(f"Task-ID: {task_id}")
    print(f"Bauort: {bauort}")
    if base_ref:
        print(f"Base-Ref: {base_ref}")
    
    changed_files = get_changed_files(base_ref=base_ref, repo_root=repo_root)
    
    print(f"Geänderte Dateien: {len(changed_files)}")
    
    errors = []
    warnings = []
    
    for filepath in changed_files:
        # Pfad-Prüfung (Forbidden paths)
        path_ok, path_msg = check_path_compliance(filepath, CONFIG["forbidden_paths"])
        if not path_ok:
            errors.append(f"{filepath}: {path_msg}")
        
        # Kopfzeilen-Prüfung für _services-Dateien
        norm_fp = filepath.replace("\\", "/")
        if "_services" in norm_fp and norm_fp.endswith(".py"):
            header_ok, header_msg = check_header_compliance(filepath, base_ref=base_ref, repo_root=repo_root)
            if not header_ok:
                errors.append(f"{filepath}: {header_msg}")
        
        # Zeilen-Ratsche für Kern-Dateien
        ratchet_ok, ratchet_msg = check_line_ratchet(filepath, changed_files, base_ref=base_ref, repo_root=repo_root)
        if not ratchet_ok:
            errors.append(f"{filepath}: {ratchet_msg}")
        elif ratchet_msg != "Nicht geändert" and ratchet_msg != "Nicht Kern-Datei" and ratchet_msg != "Keine Python-Datei":
            warnings.append(f"{filepath}: {ratchet_msg}")
        
        # Ressourcen-Netto-Zunahme prüfen
        resource_ok, resource_msg = check_resource_net_increase(filepath, changed_files, base_ref=base_ref, repo_root=repo_root)
        if not resource_ok:
            errors.append(f"{filepath}: {resource_msg}")
        elif resource_msg != "Nicht geändert" and resource_msg != "Keine Ressourcen-Datei":
            warnings.append(f"{filepath}: {resource_msg}")
    
    # Ausnahme-Prüfung
    exception_ok, exception_msg = check_exception_label(task_id, bauort)
    if not exception_ok:
        errors.append(exception_msg)
    elif exception_msg != "Keine Ausnahme":
        warnings.append(exception_msg)
    
    # Bauort-Validierung
    if bauort:
        print(f"Bauort '{bauort}' ist explizit gesetzt.")
        if bauort in ["kern", "core"]:
            for filepath in changed_files:
                norm_fp = filepath.replace("\\", "/")
                if not norm_fp.startswith("system/core/") and "_services" not in norm_fp:
                    if norm_fp.startswith("system/gui/") or norm_fp.startswith("system/hub/"):
                        errors.append(f"Task hat Bauort 'kern', aber Datei {filepath} liegt außerhalb von system/core/")
        elif bauort in ["module-gate", "gate"]:
            if not any("module_gate" in f for f in changed_files):
                warnings.append("Task hat Bauort 'module-gate', aber keine module-gate Skripte gefunden")
        elif bauort.startswith("adapter:"):
            adapter_id = bauort.replace("adapter:", "")
            adapter_files = [f for f in changed_files if adapter_id in f]
            if not adapter_files:
                warnings.append(f"Task hat Bauort 'adapter:{adapter_id}', aber keine entsprechenden Datei-Änderungen gefunden")
        elif bauort == "gui":
            if not any(f.replace("\\", "/").startswith("system/gui/") and "system/gui/web/" not in f.replace("\\", "/") for f in changed_files):
                warnings.append("Task hat Bauort 'gui', aber keine GUI-Dateien gefunden")
    else:
        warnings.append("Kein expliziter Bauort angegeben.")
    
    # Berichtsausgabe
    gate_status = "FAIL" if errors else "PASS"
    gate_report = "=== Modul-Gate Bericht ===\n"
    gate_report += f"Status: {gate_status}\n"
    gate_report += f"Task-ID: {task_id}\n"
    gate_report += f"Bauort: {bauort}\n"
    gate_report += f"Geänderte Dateien: {len(changed_files)}\n\n"
    
    if errors:
        gate_report += "FEHLER:\n"
        for e in errors:
            gate_report += f"- {e}\n"
    
    if warnings and gate_status != "FAIL":
        gate_report += "WARNUNGEN:\n"
        for w in warnings:
            gate_report += f"- {w}\n"
    
    if not errors and not warnings:
        gate_report += "KEINE PROBLEME Gefunden. Modul-Gate bestanden.\n"
    
    gate_report += "\nGeprüfte Dateien:\n"
    for f in changed_files:
        gate_report += f"- {f}\n"
    
    gate_report += "\n"
    
    # Schreibe Bericht als Artifact
    report_file = os.path.join(repo_root, ".gate_report.txt")
    try:
        with open(report_file, "w", encoding="utf-8") as f:
            f.write(gate_report)
    except Exception as e:
        print(f"Warnung: Konnte {report_file} nicht schreiben: {e}")
    
    print(gate_report)
    
    # Ausgabe für GitHub Actions
    github_output = os.getenv("GITHUB_OUTPUT")
    if github_output and os.path.exists(github_output):
        try:
            with open(github_output, "a", encoding="utf-8") as gh_out:
                gh_out.write(f"gate_status={gate_status}\n")
        except Exception:
            pass
    print(f"::set-output name=gate_status::{gate_status}")
    
    return 0 if gate_status in ["PASS", "WARNING"] else 1


if __name__ == "__main__":
    sys.exit(main())
