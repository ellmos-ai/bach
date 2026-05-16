#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
policy_control.py - Zentrale Code-Snippet Injection

Injiziert standardisierte Code-Policies in Python-Projekte.
Unterstuetzt inline-Injection (kleine Snippets) und externe Dateien (grosse).

Usage:
    python policy_control.py <datei.py> --inject emoji_safe
    python policy_control.py <datei.py> --set standardfixer
    python policy_control.py <datei.py> --check emoji_safe
    python policy_control.py <ordner> --set standardfixer --recursive
    python policy_control.py --list
    python policy_control.py --list-sets

Autor: Claude
Version: 1.0
"""

import sys
import re
import json
import shutil
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any

# Windows Console Encoding Fix
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, OSError):
        pass

# ============================================================================
# KONFIGURATION
# ============================================================================

SCRIPT_DIR = Path(__file__).parent
POLICY_SETS_FILE = SCRIPT_DIR / "policy_sets.json"
POLICIES_DIR = SCRIPT_DIR / "policies"

# ============================================================================
# POLICY MANAGER
# ============================================================================

class PolicyManager:
    """Verwaltet Policies und deren Injection."""
    
    def __init__(self):
        self.config = self._load_config()
        self.policies = self.config.get("policies", {})
        self.sets = self.config.get("sets", {})
    
    def _load_config(self) -> Dict:
        """Laedt policy_sets.json"""
        if POLICY_SETS_FILE.exists():
            try:
                with open(POLICY_SETS_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        return {"policies": {}, "sets": {}}
    
    def _load_policy_content(self, policy_name: str) -> Optional[str]:
        """Laedt den Code einer Policy."""
        if policy_name not in self.policies:
            return None
        
        policy = self.policies[policy_name]
        policy_file = SCRIPT_DIR / policy["file"]
        
        if not policy_file.exists():
            return None
        
        try:
            content = policy_file.read_text(encoding='utf-8')
            
            # Extrahiere nur den Code zwischen Markern
            marker_start = policy.get("marker_start", f"# === POLICY:{policy_name}:")
            marker_end = policy.get("marker_end", f"# === END:{policy_name} ===")
            
            start_idx = content.find(marker_start)
            end_idx = content.find(marker_end)
            
            if start_idx != -1 and end_idx != -1:
                # Finde das Ende der Start-Zeile
                start_line_end = content.find('\n', start_idx)
                if start_line_end != -1:
                    return content[start_idx:end_idx + len(marker_end)]
            
            return None
        except OSError:
            return None

    def _is_policy_present(self, filepath: Path, policy_name: str) -> Tuple[bool, Optional[str]]:
        """Prueft ob Policy bereits vorhanden ist. Returns (present, version)"""
        try:
            content = filepath.read_text(encoding='utf-8')
        except OSError:
            return False, None
        
        policy = self.policies.get(policy_name, {})
        marker_start = policy.get("marker_start", f"# === POLICY:{policy_name}:")
        
        if marker_start in content:
            # Version extrahieren
            match = re.search(rf'{re.escape(marker_start)}(\d+\.\d+)', content)
            if match:
                return True, match.group(1)
            return True, "unknown"
        
        # Fuer encoding_header: Pruefe auf UTF-8 Marker
        if policy_name == "encoding_header":
            if "# -*- coding: utf-8 -*-" in content:
                return True, "1.0"
        
        return False, None
    
    def check_policy(self, filepath: Path, policy_name: str) -> Dict[str, Any]:
        """Prueft Status einer Policy in einer Datei."""
        result = {
            "file": str(filepath),
            "policy": policy_name,
            "present": False,
            "version": None,
            "current_version": self.policies.get(policy_name, {}).get("version"),
            "needs_update": False
        }
        
        present, version = self._is_policy_present(filepath, policy_name)
        result["present"] = present
        result["version"] = version
        
        if present and version and result["current_version"]:
            result["needs_update"] = version != result["current_version"]
        
        return result
    
    def inject_policy(self, filepath: Path, policy_name: str, 
                      dry_run: bool = False, force: bool = False) -> Dict[str, Any]:
        """Injiziert eine Policy in eine Datei."""
        result = {
            "file": str(filepath),
            "policy": policy_name,
            "success": False,
            "action": None,
            "message": ""
        }
        
        if policy_name not in self.policies:
            result["message"] = f"Policy '{policy_name}' nicht gefunden"
            return result
        
        policy = self.policies[policy_name]
        inject_mode = policy.get("inject_mode", "inline")
        
        # Pruefe ob bereits vorhanden
        present, existing_version = self._is_policy_present(filepath, policy_name)
        
        if present and not force:
            result["action"] = "skipped"
            result["message"] = f"Bereits vorhanden (v{existing_version})"
            result["success"] = True
            return result
        
        # Policy-Content laden
        policy_content = self._load_policy_content(policy_name)
        if not policy_content:
            result["message"] = "Policy-Content konnte nicht geladen werden"
            return result
        
        try:
            content = filepath.read_text(encoding='utf-8')
        except Exception as e:
            result["message"] = f"Datei nicht lesbar: {e}"
            return result
        
        # Je nach Modus injizieren
        if inject_mode == "header":
            new_content = self._inject_header(content, policy_name, policy)
            result["action"] = "header_injected"
        elif inject_mode == "inline":
            new_content = self._inject_inline(content, policy_content, policy)
            result["action"] = "inline_injected"
        elif inject_mode == "external":
            new_content, external_file = self._inject_external(
                filepath, content, policy_name, policy, policy_content, dry_run
            )
            result["action"] = f"external_created ({external_file})"
        else:
            result["message"] = f"Unbekannter inject_mode: {inject_mode}"
            return result
        
        if new_content == content:
            result["action"] = "no_change"
            result["message"] = "Keine Aenderung noetig"
            result["success"] = True
            return result
        
        if not dry_run:
            # Backup erstellen
            backup_path = filepath.with_suffix(filepath.suffix + '.policy.bak')
            shutil.copy2(filepath, backup_path)
            
            # Neue Version schreiben
            filepath.write_text(new_content, encoding='utf-8')
        
        result["success"] = True
        result["message"] = "Erfolgreich" + (" (dry-run)" if dry_run else "")
        return result
    
    def _inject_header(self, content: str, policy_name: str, policy: Dict) -> str:
        """Injiziert Header-Policy (Shebang, Encoding)."""
        lines = content.split('\n')
        new_lines = []
        
        has_shebang = lines and lines[0].startswith('#!')
        has_encoding = any('coding:' in line or 'coding=' in line for line in lines[:3])
        
        # Shebang
        if not has_shebang:
            new_lines.append("#!/usr/bin/env python3")
        else:
            new_lines.append(lines[0])
            lines = lines[1:]
        
        # Encoding
        if not has_encoding:
            new_lines.append("# -*- coding: utf-8 -*-")
        
        # Rest der Datei
        for line in lines:
            if 'coding:' in line or 'coding=' in line:
                continue  # Alte Encoding-Zeile ueberspringen
            new_lines.append(line)
        
        return '\n'.join(new_lines)
    
    def _inject_inline(self, content: str, policy_content: str, policy: Dict) -> str:
        """Injiziert Policy inline nach Imports."""
        lines = content.split('\n')
        
        # Finde letzte Import-Zeile
        last_import_idx = -1
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith('import ') or stripped.startswith('from '):
                last_import_idx = i
        
        # Injection-Punkt bestimmen
        if last_import_idx >= 0:
            inject_idx = last_import_idx + 1
        else:
            # Nach Docstring/Header
            inject_idx = 0
            for i, line in enumerate(lines):
                if line.strip() and not line.startswith('#') and not line.startswith('"""') and not line.startswith("'''"):
                    inject_idx = i
                    break
        
        # Einfuegen mit Leerzeilen
        new_lines = lines[:inject_idx]
        new_lines.append("")
        new_lines.extend(policy_content.split('\n'))
        new_lines.append("")
        new_lines.extend(lines[inject_idx:])
        
        return '\n'.join(new_lines)
    
    def _inject_external(self, filepath: Path, content: str, 
                         policy_name: str, policy: Dict, 
                         policy_content: str, dry_run: bool) -> Tuple[str, str]:
        """Erstellt externe Policy-Datei und fuegt Import hinzu."""
        external_filename = policy.get("external_filename", f"{policy_name}.py")
        external_path = filepath.parent / external_filename
        
        # Externe Datei erstellen
        if not dry_run:
            # Vollstaendigen Policy-Code aus Datei holen
            policy_file = SCRIPT_DIR / policy["file"]
            if policy_file.exists():
                full_content = policy_file.read_text(encoding='utf-8')
                external_path.write_text(full_content, encoding='utf-8')
        
        # Import hinzufuegen
        module_name = external_filename.replace('.py', '')
        import_line = f"from {module_name} import *  # POLICY:{policy_name}"
        
        if import_line not in content:
            lines = content.split('\n')
            
            # Nach anderen Imports einfuegen
            last_import_idx = -1
            for i, line in enumerate(lines):
                if line.strip().startswith('import ') or line.strip().startswith('from '):
                    last_import_idx = i
            
            if last_import_idx >= 0:
                lines.insert(last_import_idx + 1, import_line)
            else:
                # Am Anfang nach Header
                for i, line in enumerate(lines):
                    if line.strip() and not line.startswith('#'):
                        lines.insert(i, import_line)
                        break
            
            content = '\n'.join(lines)
        
        return content, external_filename
    
    def inject_set(self, filepath: Path, set_name: str, 
                   dry_run: bool = False, force: bool = False) -> List[Dict]:
        """Injiziert alle Policies eines Sets."""
        results = []
        
        if set_name not in self.sets:
            return [{"error": f"Set '{set_name}' nicht gefunden"}]
        
        policy_names = self.sets[set_name].get("policies", [])
        
        for policy_name in policy_names:
            result = self.inject_policy(filepath, policy_name, dry_run, force)
            results.append(result)
        
        return results
    
    def list_policies(self) -> None:
        """Listet alle verfuegbaren Policies."""
        print("\n" + "=" * 60)
        print("VERFUEGBARE POLICIES")
        print("=" * 60)
        
        for name, policy in self.policies.items():
            mode = policy.get("inject_mode", "inline")
            size = policy.get("size", "?")
            version = policy.get("version", "?")
            desc = policy.get("description", "")
            
            print(f"\n  {name} (v{version})")
            print(f"    Mode: {mode}, Size: {size}")
            print(f"    {desc}")
        
        print("\n" + "=" * 60)
    
    def list_sets(self) -> None:
        """Listet alle verfuegbaren Sets."""
        print("\n" + "=" * 60)
        print("VERFUEGBARE POLICY-SETS")
        print("=" * 60)
        
        for name, set_def in self.sets.items():
            desc = set_def.get("description", "")
            policies = set_def.get("policies", [])
            
            print(f"\n  {name}")
            print(f"    {desc}")
            print(f"    Policies: {', '.join(policies)}")
        
        print("\n" + "=" * 60)


# ============================================================================
# CLI
# ============================================================================

def process_file(manager: PolicyManager, filepath: Path, 
                 policy: Optional[str] = None, 
                 set_name: Optional[str] = None,
                 check_only: bool = False,
                 dry_run: bool = False,
                 force: bool = False) -> List[Dict]:
    """Verarbeitet eine einzelne Datei."""
    results = []
    
    if check_only and policy:
        results.append(manager.check_policy(filepath, policy))
    elif policy:
        results.append(manager.inject_policy(filepath, policy, dry_run, force))
    elif set_name:
        results.extend(manager.inject_set(filepath, set_name, dry_run, force))
    
    return results


def process_directory(manager: PolicyManager, dirpath: Path, 
                      policy: Optional[str] = None,
                      set_name: Optional[str] = None,
                      check_only: bool = False,
                      dry_run: bool = False,
                      force: bool = False) -> List[Dict]:
    """Verarbeitet alle Python-Dateien in einem Verzeichnis."""
    results = []
    
    for filepath in dirpath.rglob("*.py"):
        if "__pycache__" in str(filepath) or ".bak" in str(filepath):
            continue
        results.extend(process_file(manager, filepath, policy, set_name, check_only, dry_run, force))
    
    return results


def print_results(results: List[Dict]) -> None:
    """Gibt Ergebnisse formatiert aus."""
    print("\n" + "=" * 60)
    print("POLICY CONTROL ERGEBNIS")
    print("=" * 60)
    
    success = sum(1 for r in results if r.get("success", False))
    failed = len(results) - success
    
    print(f"Verarbeitet: {len(results)}")
    print(f"Erfolgreich: {success}")
    print(f"Fehlgeschlagen: {failed}")
    print("-" * 60)
    
    for result in results:
        status = "[OK]" if result.get("success") else "[FEHLER]"
        policy = result.get("policy", "?")
        action = result.get("action", "")
        message = result.get("message", "")
        
        file_short = Path(result.get("file", "")).name
        
        print(f"{status} {file_short}: {policy}")
        if action:
            print(f"      Action: {action}")
        if message:
            print(f"      {message}")


def main():
    if len(sys.argv) < 2 or '--help' in sys.argv or '-h' in sys.argv:
        print(__doc__)
        sys.exit(0)
    
    manager = PolicyManager()
    
    # List-Befehle
    if '--list' in sys.argv:
        manager.list_policies()
        sys.exit(0)
    
    if '--list-sets' in sys.argv:
        manager.list_sets()
        sys.exit(0)
    
    # Target-Pfad
    target = Path(sys.argv[1])
    
    if not target.exists():
        print(f"[FEHLER] Pfad nicht gefunden: {target}")
        sys.exit(1)
    
    # Optionen parsen
    policy = None
    set_name = None
    check_only = '--check' in sys.argv
    dry_run = '--dry-run' in sys.argv
    force = '--force' in sys.argv
    recursive = '--recursive' in sys.argv
    
    for arg in sys.argv:
        if arg.startswith('--inject='):
            policy = arg.split('=')[1]
        elif arg.startswith('--set='):
            set_name = arg.split('=')[1]
        elif arg == '--inject' and sys.argv.index(arg) + 1 < len(sys.argv):
            policy = sys.argv[sys.argv.index(arg) + 1]
        elif arg == '--set' and sys.argv.index(arg) + 1 < len(sys.argv):
            set_name = sys.argv[sys.argv.index(arg) + 1]
        elif arg == '--check' and sys.argv.index(arg) + 1 < len(sys.argv):
            next_arg = sys.argv[sys.argv.index(arg) + 1]
            if not next_arg.startswith('--'):
                policy = next_arg
                check_only = True
    
    if not policy and not set_name:
        print("[FEHLER] --inject <policy> oder --set <set_name> erforderlich")
        print("         Nutze --list oder --list-sets fuer verfuegbare Optionen")
        sys.exit(1)
    
    # Verarbeiten
    if target.is_file():
        results = process_file(manager, target, policy, set_name, check_only, dry_run, force)
    elif target.is_dir():
        if recursive:
            results = process_directory(manager, target, policy, set_name, check_only, dry_run, force)
        else:
            results = []
            for f in target.iterdir():
                if f.is_file() and f.suffix == '.py':
                    results.extend(process_file(manager, f, policy, set_name, check_only, dry_run, force))
    else:
        print(f"[FEHLER] Unbekannter Pfadtyp: {target}")
        sys.exit(1)
    
    print_results(results)
    
    has_errors = any(not r.get("success", False) for r in results)
    sys.exit(1 if has_errors else 0)


if __name__ == "__main__":
    main()
