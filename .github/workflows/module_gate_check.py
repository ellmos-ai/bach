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
import json
import subprocess

# Pfad-Definitionen
REPO_ROOT = os.getenv("GITHUB_WORKSPACE", os.path.dirname(os.path.abspath(__file__)) + "/../../..")
# Normalisiere auf das Worktree-Verzeichnis
if not os.path.isdir(REPO_ROOT):
    REPO_ROOT = "/Users/lukas/services/bach-worktrees/task-2445"

CONFIG = {
    "forbidden_paths": ["system/gui/web/**"],
    "required_header": "# BACH Adapter: ",
    "module_id_pattern": r"bauort:([a-zA-Z0-9_-]+)",
    "core_dir": "system/core",
    "resource_extensions": [".jpg", ".png", ".svg", ".ico", ".woff", ".woff2", ".ttf", ".eot"],
}


def load_task_metadata():
    """Lädt Task-Metadaten aus der TaskDB/Task-Datei."""
    task_file = os.path.join(REPO_ROOT, "task_result.md")
    if os.path.exists(task_file):
        with open(task_file, "r", encoding="utf-8") as f:
            content = f.read()
        # Versuche Task-ID und Bauort zu extrahieren
        task_id_match = re.search(r"Task #(\d+)", content)
        bauort_match = re.search(r"bauort:([a-zA-Z0-9_-]+)", content)
        return {
            "task_id": task_id_match.group(1) if task_id_match else None,
            "bauort": bauort_match.group(1) if bauort_match else None,
        }
    return {"task_id": None, "bauort": None}


def check_path_compliance(filepath, forbidden_patterns):
    """Prüft, ob ein Pfad den Verbotsmustern entspricht."""
    abs_path = os.path.relpath(filepath, REPO_ROOT)
    for pattern in forbidden_patterns:
        # Konvertiere ** zu beliebigen Unterverzeichnissen
        regex_pattern = pattern.replace("**", ".*")
        if re.search(regex_pattern, abs_path):
            return False, f"Verbotener Pfad: {filepath} passt zu {pattern}"
    return True, "OK"


def check_header_compliance(filepath):
    """Prüft, ob eine _services-Datei den Adapter-Kopfzeilen hat."""
    if "_services" not in filepath:
        return True, "Keine Services-Datei, Prüfung entfällt"
    
    if not filepath.endswith(".py"):
        return True, "Keine Python-Datei, Prüfung entfällt"
    
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            first_line = f.readline().strip()
        if first_line.startswith("# BACH Adapter:"):
            return True, "Kopfzeile gefunden"
        else:
            return False, f"Fehlende Kopfzeile in {filepath}: erste Zeile ist '{first_line}'"
    except Exception as e:
        return False, f"Fehler beim Lesen von {filepath}: {e}"


def get_git_changed_files():
    """Ermittelt geänderte Dateien via git diff."""
    try:
        # Für PR: diff gegen base branch
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            capture_output=True, text=True, cwd=REPO_ROOT
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip().split("\n")
    except Exception:
        pass
    return []


def get_git_base_head():
    """Ermittelt base und head commit für PR."""
    try:
        # GitHub Actions setzt GITHUB_BASE_REF und GITHUB_HEAD_REF
        base = os.getenv("GITHUB_BASE_REF")
        head = os.getenv("GITHUB_HEAD_REF")
        if base and head:
            return base, head
    except Exception:
        pass
    return None, None


def check_line_ratchet(filepath, changed_files):
    """
    Prüft Zeilen-Ratsche: Keine Netto-Zunahme an Zeilen in Kern-Dateien (system/core/*.py).
    Vergleicht aktuelle Zeilen mit BASE-Commit.
    """
    if not filepath.startswith(CONFIG["core_dir"]):
        return True, "Nicht Kern-Datei"
    
    if not filepath.endswith(".py"):
        return True, "Keine Python-Datei"
    
    # Prüfe ob in changed_files
    if filepath not in changed_files:
        return True, "Nicht geändert"
    
    try:
        # Zeilen im aktuellen Stand zählen
        with open(os.path.join(REPO_ROOT, filepath), "r", encoding="utf-8") as f:
            current_lines = len(f.readlines())
        
        # Zeilen im Base-Commit zählen (falls PR)
        base_ref = os.getenv("GITHUB_BASE_REF")
        if base_ref:
            result = subprocess.run(
                ["git", "show", f"origin/{base_ref}:{filepath}"],
                capture_output=True, text=True, cwd=REPO_ROOT
            )
            if result.returncode == 0:
                base_lines = len(result.stdout.splitlines())
                if current_lines > base_lines:
                    return False, f"Zeilen-Ratsche verletzt: {filepath} hat {current_lines} Zeilen (Base: {base_lines})"
                return True, f"Zeilen-Ratsche OK: {filepath} {current_lines} Zeilen (Base: {base_lines})"
        
        return True, f"Kein Base-Vergleich möglich, aktuelle Zeilen: {current_lines}"
    except Exception as e:
        return False, f"Fehler bei Zeilen-Ratsche-Prüfung für {filepath}: {e}"


def check_resource_net_increase(filepath, changed_files):
    """
    Prüft: Keine Netto-Zunahme in Ressourcendateien (Bilder, Fonts, etc.).
    """
    if filepath not in changed_files:
        return True, "Nicht geändert"
    
    _, ext = os.path.splitext(filepath)
    if ext.lower() not in CONFIG["resource_extensions"]:
        return True, "Keine Ressourcen-Datei"
    
    try:
        base_ref = os.getenv("GITHUB_BASE_REF")
        if base_ref:
            result = subprocess.run(
                ["git", "show", f"origin/{base_ref}:{filepath}"],
                capture_output=True, text=True, cwd=REPO_ROOT
            )
            if result.returncode == 0:
                base_size = len(result.stdout.encode())
                current_size = os.path.getsize(os.path.join(REPO_ROOT, filepath))
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
    
    # Prüfe auf Label im PR
    pr_number = os.getenv("GITHUB_EVENT_NUMBER")
    if pr_number:
        # In GitHub Actions: Labels über API prüfen
        # Hier vereinfacht: Prüfen ob bauort Task-ID enthält
        if f"ausnahme:{task_id}" == bauort:
            return True, f"Ausnahme mit Task-ID {task_id} erlaubt"
        return False, f"Ausnahme-Label {bauort} passt nicht zu Task {task_id}"
    
    return True, "Kein PR-Kontext, Ausnahme-Prüfung übersprungen"


def extract_bauort_from_pr():
    """Extrahiert Bauort aus PR-Titel, -Beschreibung oder Commits."""
    # 1. Aus PR-Titel (GITHUB_EVENT_PULL_REQUEST_TITLE)
    pr_title = os.getenv("GITHUB_EVENT_PULL_REQUEST_TITLE", "")
    pr_body = os.getenv("GITHUB_EVENT_PULL_REQUEST_BODY", "")
    
    for text in [pr_title, pr_body]:
        match = re.search(r"bauort:([a-zA-Z0-9_:-]+)", text)
        if match:
            return match.group(1)
    
    # 2. Aus Commits (letzte 5 Commits)
    try:
        result = subprocess.run(
            ["git", "log", "-5", "--pretty=format:%s"],
            capture_output=True, text=True, cwd=REPO_ROOT
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                match = re.search(r"bauort:([a-zA-Z0-9_:-]+)", line)
                if match:
                    return match.group(1)
    except Exception:
        pass
    
    return None


def main():
    print("=== Modul-Gate CI-Check ===")
    
    meta = load_task_metadata()
    task_id = meta.get("task_id")
    bauort = meta.get("bauort")
    
    # Versuche Bauort aus PR zu extrahieren falls nicht in task_result.md
    if not bauort:
        bauort = extract_bauort_from_pr()
    
    print(f"Task-ID: {task_id}")
    print(f"Bauort: {bauort}")
    
    # Sammle alle geänderten Dateien
    changed_files = get_git_changed_files()
    
    if not changed_files:
        changed_files = []
    
    print(f"Geänderte Dateien: {len(changed_files)}")
    
    errors = []
    warnings = []
    
    for filepath in changed_files:
        # Pfad-Prüfung (Forbidden paths)
        path_ok, path_msg = check_path_compliance(filepath, CONFIG["forbidden_paths"])
        if not path_ok:
            errors.append(f"{filepath}: {path_msg}")
        
        # Kopfzeilen-Prüfung für _services-Dateien
        if "_services" in filepath and filepath.endswith(".py"):
            header_ok, header_msg = check_header_compliance(filepath)
            if not header_ok:
                errors.append(f"{filepath}: {header_msg}")
        
        # Zeilen-Ratsche für Kern-Dateien
        ratchet_ok, ratchet_msg = check_line_ratchet(filepath, changed_files)
        if not ratchet_ok:
            errors.append(f"{filepath}: {ratchet_msg}")
        elif ratchet_msg != "Nicht geändert" and ratchet_msg != "Nicht Kern-Datei" and ratchet_msg != "Keine Python-Datei":
            warnings.append(f"{filepath}: {ratchet_msg}")
        
        # Ressourcen-Netto-Zunahme prüfen
        resource_ok, resource_msg = check_resource_net_increase(filepath, changed_files)
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
        # Wenn Bauort 'kern' oder 'core' gesetzt ist, prüfe auf Kern-Dateien
        if bauort in ["kern", "core"]:
            for filepath in changed_files:
                if not filepath.startswith("system/core/") and "_services" not in filepath:
                    if filepath.startswith("system/gui/") or filepath.startswith("system/hub/"):
                        errors.append(f"Task hat Bauort 'kern', aber Datei {filepath} liegt außerhalb von system/core/")
        # Wenn Bauort 'module-gate' gesetzt ist
        elif bauort in ["module-gate", "gate"]:
            if not any("module_gate" in f for f in changed_files):
                warnings.append("Task hat Bauort 'module-gate', aber keine module-gate Skripte gefunden")
        # Wenn Bauort 'adapter:' gesetzt ist
        elif bauort and bauort.startswith("adapter:"):
            adapter_id = bauort.replace("adapter:", "")
            adapter_files = [f for f in changed_files if adapter_id in f]
            if not adapter_files:
                warnings.append(f"Task hat Bauort 'adapter:{adapter_id}', aber keine entsprechenden Datei-Änderungen gefunden")
        # Wenn Bauort 'gui' gesetzt ist
        elif bauort == "gui":
            if not any(f.startswith("system/gui/") and not "system/gui/web/" in f for f in changed_files):
                warnings.append("Task hat Bauort 'gui', aber keine GUI-Dateien gefunden")
    else:
        warnings.append("Kein expliziter Bauort angegeben.")
    
    # Berichtsausgabe
    gate_status = "PASS"
    gate_report = f"=== Modul-Gate Bericht ===\n"
    gate_report += f"Task-ID: {task_id}\n"
    gate_report += f"Bauort: {bauort}\n"
    gate_report += f"Geänderte Dateien: {len(changed_files)}\n\n"
    
    if errors:
        gate_status = "FAIL"
        gate_report += "FEHLER:\n"
        for e in errors:
            gate_report += f"- {e}\n"
    
    if warnings and gate_status != "FAIL":
        gate_report += "WARNUNGEN:\n"
        for w in warnings:
            gate_report += f"- {w}\n"
    
    if not errors and not warnings:
        gate_report += "KEINE PROBLEME Gefunden. Modul-Gate bestanden.\n"
    
    gate_report += f"\nGeprüfte Dateien:\n"
    for f in changed_files:
        gate_report += f"- {os.path.relpath(f, REPO_ROOT)}\n"
    
    gate_report += "\n"
    
    # Schreibe Bericht als Artifact
    with open(os.path.join(REPO_ROOT, ".gate_report.txt"), "w", encoding="utf-8") as f:
        f.write(gate_report)
    
    print(gate_report)
    
    # Ausgabe für GitHub Actions
    print(f"::set-output name=gate_status::{gate_status}")
    print(f"::set-output name=gate_report::{gate_report}")
    
    sys.exit(0 if gate_status in ["PASS", "WARNING"] else 1)


if __name__ == "__main__":
    main()