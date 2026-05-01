# -*- coding: utf-8 -*-
"""
Copyright (c) 2026 BACH Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

"""
Capability System - Zugriffskontrolle fuer BACH Plugins
========================================================

Stufe 1 des Sandbox-Systems: Plugins deklarieren benoetigte
Faehigkeiten, BACH prueft und durchsetzt basierend auf Trust-Level.

Verknuepft mit dem bestehenden Trust-System (data/skill_sources.json).

Nutzung:
    from core.capabilities import capability_manager

    # Plugin registrieren
    capability_manager.register_plugin('mein-plugin', 'trusted', ['db_read', 'hook_listen'])

    # Capability pruefen
    allowed, reason = capability_manager.check('mein-plugin', 'db_write')

    # Trust-Level aendern
    capability_manager.set_plugin_trust('mein-plugin', 'goldstandard')

Version: 1.0.0
"""

import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional


# Alle definierten Capabilities
CAPABILITIES = {
    'db_read':          'Datenbank lesen',
    'db_write':         'Datenbank schreiben',
    'file_read':        'Dateien lesen',
    'file_write':       'Dateien schreiben',
    'hook_listen':      'Auf Events lauschen',
    'hook_emit':        'Events emittieren',
    'tool_register':    'Neue Tools registrieren',
    'handler_register': 'Neue CLI-Handler registrieren',
    'workflow_create':  'Workflows erstellen',
    'network':          'Netzwerk-Zugriff (HTTP/API)',
    'shell':            'Shell-Befehle ausfuehren',
}

# Fallback Trust-Profile (werden bevorzugt aus skill_sources.json geladen)
DEFAULT_TRUST_PROFILES = {
    'goldstandard': {
        'trust': 100,
        'capabilities': ['*'],
        'description': 'Alle Faehigkeiten erlaubt',
    },
    'trusted': {
        'trust': 80,
        'capabilities': [
            'db_read', 'db_write', 'file_read', 'file_write',
            'hook_listen', 'hook_emit', 'tool_register',
            'handler_register', 'workflow_create',
        ],
        'description': 'Alles ausser Shell und Netzwerk',
    },
    'untrusted': {
        'trust': 20,
        'capabilities': ['db_read', 'file_read', 'hook_listen'],
        'description': 'Nur lesen und lauschen',
    },
    'blacklist': {
        'trust': 0,
        'capabilities': [],
        'description': 'Komplett gesperrt',
    },
}


class CapabilityManager:
    """Verwaltet Plugin-Capabilities und Trust-Level Enforcement."""

    def __init__(self):
        self._plugins: dict[str, dict] = {}  # name -> {trust, capabilities, ...}
        self._profiles: dict[str, dict] = {}
        self._audit_log: list[dict] = []
        self._audit_max = 200
        self._base_path: Optional[Path] = None
        self._load_profiles()

    def _get_base_path(self) -> Path:
        if self._base_path is None:
            self._base_path = Path(__file__).parent.parent
        return self._base_path

    def _load_profiles(self):
        """Laedt Trust-Profile aus skill_sources.json oder Fallback."""
        self._profiles = dict(DEFAULT_TRUST_PROFILES)
        try:
            base = self._get_base_path()
            sources_path = base / "data" / "skill_sources.json"
            if sources_path.exists():
                data = json.loads(sources_path.read_text(encoding='utf-8'))
                profiles = data.get('capability_profiles', {})
                for name, profile in profiles.items():
                    if name in self._profiles:
                        self._profiles[name]['capabilities'] = profile.get(
                            'capabilities', self._profiles[name]['capabilities']
                        )
                        if 'description' in profile:
                            self._profiles[name]['description'] = profile['description']
        except Exception:
            pass  # Fallback-Profile verwenden

    # ==================================================================
    # PLUGIN REGISTRATION
    # ==================================================================

    def register_plugin(self, name: str, source: str = 'untrusted',
                        requested_caps: list = None):
        """Registriert ein Plugin mit Trust-Level und gewuenschten Capabilities.

        Args:
            name: Plugin-Name
            source: Trust-Level (goldstandard/trusted/untrusted/blacklist)
            requested_caps: Liste der angeforderten Capabilities
        """
        if source not in self._profiles:
            source = 'untrusted'

        profile = self._profiles[source]
        allowed_caps = set(profile.get('capabilities', []))
        requested = set(requested_caps or [])

        # Wildcard aufloesen
        if '*' in allowed_caps:
            effective_caps = set(CAPABILITIES.keys())
        else:
            effective_caps = allowed_caps & (requested | allowed_caps)

        self._plugins[name] = {
            'source': source,
            'trust': profile.get('trust', 0),
            'requested': requested,
            'effective': effective_caps,
            'registered_at': datetime.now().isoformat(),
        }

    def unregister_plugin(self, name: str):
        """Entfernt ein Plugin aus dem Capability-System."""
        self._plugins.pop(name, None)

    # ==================================================================
    # CAPABILITY CHECKS
    # ==================================================================

    def check(self, plugin: str, capability: str) -> tuple:
        """Prueft ob ein Plugin eine bestimmte Capability hat.

        Args:
            plugin: Plugin-Name
            capability: Gewuenschte Capability

        Returns:
            (allowed: bool, reason: str)
        """
        # Runtime-Plugins ohne Registrierung (z.B. _runtime) = goldstandard
        if plugin == '_runtime' or plugin not in self._plugins:
            result = (True, 'Runtime/unregistriert: erlaubt (goldstandard)')
            self._audit(plugin, capability, True, result[1])
            return result

        info = self._plugins[plugin]

        # Blacklist: sofort ablehnen
        if info['source'] == 'blacklist':
            result = (False, f"Plugin '{plugin}' ist auf der Blacklist")
            self._audit(plugin, capability, False, result[1])
            self._emit_denied(plugin, capability, result[1])
            return result

        # Capability pruefen
        if capability in info['effective']:
            result = (True, f"Erlaubt (source={info['source']}, trust={info['trust']})")
            self._audit(plugin, capability, True, result[1])
            return result

        reason = (
            f"Capability '{capability}' nicht erlaubt fuer "
            f"'{plugin}' (source={info['source']}, trust={info['trust']}). "
            f"Erlaubt: {sorted(info['effective'])}"
        )
        self._audit(plugin, capability, False, reason)
        self._emit_denied(plugin, capability, reason)
        return (False, reason)

    def check_all(self, plugin: str, capabilities: list) -> list:
        """Prueft mehrere Capabilities auf einmal.

        Args:
            plugin: Plugin-Name
            capabilities: Liste der zu pruefenden Capabilities

        Returns:
            Liste der verweigerten Capabilities (leer = alle erlaubt)
        """
        denied = []
        for cap in capabilities:
            if cap == '*':
                continue
            allowed, _ = self.check(plugin, cap)
            if not allowed:
                denied.append(cap)
        return denied

    # ==================================================================
    # TRUST MANAGEMENT
    # ==================================================================

    def set_plugin_trust(self, name: str, trust_level: str) -> tuple:
        """Aendert das Trust-Level eines Plugins.

        Args:
            name: Plugin-Name
            trust_level: Neues Trust-Level

        Returns:
            (success: bool, message: str)
        """
        if trust_level not in self._profiles:
            return (False, f"Unbekanntes Trust-Level: {trust_level}")

        if name not in self._plugins:
            return (False, f"Plugin '{name}' nicht registriert")

        old_source = self._plugins[name]['source']
        profile = self._profiles[trust_level]
        allowed_caps = set(profile.get('capabilities', []))

        if '*' in allowed_caps:
            effective = set(CAPABILITIES.keys())
        else:
            effective = allowed_caps & (self._plugins[name]['requested'] | allowed_caps)

        self._plugins[name]['source'] = trust_level
        self._plugins[name]['trust'] = profile.get('trust', 0)
        self._plugins[name]['effective'] = effective

        msg = f"Plugin '{name}': {old_source} -> {trust_level}"
        self._audit(name, 'trust_change', True, msg)
        return (True, msg)

    def get_plugin_capabilities(self, name: str) -> set:
        """Gibt die effektiven Capabilities eines Plugins zurueck."""
        if name not in self._plugins:
            return set(CAPABILITIES.keys())  # Unregistriert = goldstandard
        return self._plugins[name].get('effective', set())

    # ==================================================================
    # SECURITY CHECKS (Integration mit skill_sources.json)
    # ==================================================================

    def run_security_checks(self, code_path: str) -> list:
        """Fuehrt statische Sicherheitspruefungen auf Code durch.

        Nutzt die Checks aus skill_sources.json:
        - code_injection: eval, exec, subprocess, __import__
        - prompt_injection: Base64, Unicode-Tricks
        - dependency_check: unbekannte Pakete

        Args:
            code_path: Pfad zur Python-Datei

        Returns:
            Liste von Findings (leer = sicher)
        """
        findings = []
        path = Path(code_path)
        if not path.exists():
            return [f"Datei nicht gefunden: {code_path}"]

        try:
            content = path.read_text(encoding='utf-8')
        except Exception as e:
            return [f"Lesefehler: {e}"]

        # Code-Injection Checks
        dangerous_patterns = [
            (r'\beval\s*\(', 'eval() Aufruf gefunden'),
            (r'\bexec\s*\(', 'exec() Aufruf gefunden'),
            (r'\bFunction\s*\(', 'Dynamischer JavaScript Function() Aufruf gefunden'),
            (r'child_process\.(exec|execSync)\s*\(', 'Node child_process exec-Aufruf gefunden'),
            (r'subprocess.*shell\s*=\s*True', 'subprocess mit shell=True'),
            (r'__import__\s*\(', 'Dynamischer Import via __import__()'),
            (r'os\.system\s*\(', 'os.system() Aufruf gefunden'),
        ]

        for pattern, message in dangerous_patterns:
            if re.search(pattern, content):
                findings.append(f"[CODE_INJECTION] {message}")

        # Prompt-Injection Checks (fuer .md/.txt Dateien)
        if path.suffix in ('.md', '.txt'):
            if re.search(r'[A-Za-z0-9+/]{40,}={0,2}', content):
                findings.append("[PROMPT_INJECTION] Moeglicherweise Base64-kodierter String")

        # Netzwerk-Zugriff
        if re.search(r'requests\.(get|post|put|delete)\s*\(', content):
            findings.append("[NETWORK] HTTP-Requests an externe URLs")
        if re.search(r'urllib', content):
            findings.append("[NETWORK] urllib-Nutzung erkannt")

        return findings

    def scan_tree(self, root_path: str | Path,
                  suffixes: tuple[str, ...] = (
                      '.py', '.js', '.ts', '.mjs', '.cjs',
                      '.sh', '.ps1', '.md', '.txt', '.json', '.yaml', '.yml',
                  )) -> dict[str, list[str]]:
        """Scannt ein Verzeichnis rekursiv und gibt Findings pro Datei zurueck."""
        root = Path(root_path)
        if not root.exists():
            return {str(root): [f"Pfad nicht gefunden: {root}"]}

        report: dict[str, list[str]] = {}
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if "__pycache__" in path.parts:
                continue
            if suffixes and path.suffix.lower() not in suffixes:
                continue

            findings = self.run_security_checks(str(path))
            if findings:
                report[str(path)] = findings

        return report

    def categorize_scan_findings(self, findings_by_file: dict[str, list[str]]) -> tuple[list[str], list[str]]:
        """Trennt Findings in blockierende und informative Eintraege."""
        blocking: list[str] = []
        warnings: list[str] = []

        for file_path, findings in findings_by_file.items():
            label = Path(file_path).name
            for finding in findings:
                line = f"{label}: {finding}"
                if finding.startswith("[CODE_INJECTION]"):
                    blocking.append(line)
                else:
                    warnings.append(line)

        return blocking, warnings

    def quarantine_path(self, source_path: str | Path, base_path: str | Path,
                        kind: str, findings_by_file: dict[str, list[str]],
                        reason: str, metadata: dict | None = None) -> Path:
        """Kopiert einen blockierten Importpfad in eine lokale Quarantaene.

        Die Quarantaene ist absichtlich nicht destruktiv: Originale bleiben
        unveraendert, BACH legt nur eine pruefbare Kopie mit report.json ab.
        """
        base = Path(base_path)
        source = Path(source_path)
        safe_kind = re.sub(r"[^A-Za-z0-9._-]+", "_", kind or "unknown").strip("_")
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", source.name or "payload").strip("_")
        if not safe_kind:
            safe_kind = "unknown"
        if not safe_name:
            safe_name = "payload"

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        quarantine_dir = base / "data" / "quarantine" / safe_kind / f"{stamp}_{safe_name[:80]}"
        payload_dir = quarantine_dir / "payload"
        quarantine_dir.mkdir(parents=True, exist_ok=False)

        copied = False
        copy_error = None
        try:
            if source.exists() and source.is_dir():
                shutil.copytree(
                    source,
                    payload_dir / source.name,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
                )
                copied = True
            elif source.exists() and source.is_file():
                payload_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, payload_dir / source.name)
                copied = True
        except Exception as exc:
            copy_error = f"{type(exc).__name__}: {exc}"

        report = {
            "created_at": datetime.now().isoformat(),
            "kind": safe_kind,
            "source_path": str(source),
            "reason": reason,
            "copied": copied,
            "copy_error": copy_error,
            "findings": findings_by_file,
            "metadata": metadata or {},
        }
        (quarantine_dir / "report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return quarantine_dir

    # ==================================================================
    # AUDIT LOG
    # ==================================================================

    def _audit(self, plugin: str, capability: str, allowed: bool, reason: str):
        """Schreibt einen Audit-Eintrag."""
        entry = {
            'timestamp': datetime.now().isoformat(),
            'plugin': plugin,
            'capability': capability,
            'allowed': allowed,
            'reason': reason,
        }
        self._audit_log.append(entry)

        # In-Memory begrenzen
        if len(self._audit_log) > self._audit_max:
            self._audit_log = self._audit_log[-self._audit_max:]

        # Auf Disk schreiben
        self._write_audit_file(entry)

    def _write_audit_file(self, entry: dict):
        """Schreibt Audit-Eintrag in Log-Datei."""
        try:
            base = self._get_base_path()
            log_dir = base / "data" / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = log_dir / "capability_audit.log"

            status = "ALLOW" if entry['allowed'] else "DENY"
            line = (
                f"[{entry['timestamp'][:19]}] {status} "
                f"plugin={entry['plugin']} cap={entry['capability']} "
                f"reason={entry['reason']}\n"
            )

            # Log-Rotation: bei >1000 Zeilen auf 500 kuerzen
            if log_file.exists():
                lines = log_file.read_text(encoding='utf-8').splitlines()
                if len(lines) > 1000:
                    log_file.write_text(
                        '\n'.join(lines[-500:]) + '\n',
                        encoding='utf-8'
                    )

            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(line)
        except Exception:
            pass  # Audit-Fehler duerfen nichts blockieren

    def _emit_denied(self, plugin: str, capability: str, reason: str):
        """Emittiert Hook bei verweigerter Capability."""
        try:
            from .hooks import hooks
            hooks.emit('after_capability_denied', {
                'plugin': plugin,
                'capability': capability,
                'reason': reason,
            })
        except Exception:
            pass

    # ==================================================================
    # STATUS & REPORTING
    # ==================================================================

    def status(self) -> str:
        """Gibt formatierten Status zurueck."""
        lines = ["CAPABILITY-SYSTEM STATUS", "=" * 50]
        lines.append(f"\nDefinierte Capabilities: {len(CAPABILITIES)}")
        lines.append(f"Registrierte Plugins: {len(self._plugins)}")
        lines.append(f"Trust-Profile: {len(self._profiles)}")

        if self._plugins:
            lines.append(f"\n{'Plugin':<25} {'Source':<15} {'Caps':>5}")
            lines.append("-" * 47)
            for name, info in sorted(self._plugins.items()):
                caps = len(info.get('effective', set()))
                lines.append(f"  {name:<23} {info['source']:<15} {caps:>5}")

        lines.append(f"\nTrust-Profile:")
        for name, profile in sorted(self._profiles.items(),
                                     key=lambda x: -x[1].get('trust', 0)):
            trust = profile.get('trust', 0)
            caps = profile.get('capabilities', [])
            cap_str = '*' if '*' in caps else str(len(caps))
            lines.append(f"  {name:<15} trust={trust:>3}  caps={cap_str}")

        if self._audit_log:
            denied = sum(1 for e in self._audit_log if not e['allowed'])
            lines.append(f"\nAudit-Log: {len(self._audit_log)} Eintraege "
                         f"({denied} denied)")

        return "\n".join(lines)

    def get_audit_log(self, limit: int = 20) -> str:
        """Gibt die letzten Audit-Eintraege formatiert zurueck."""
        if not self._audit_log:
            return "Keine Audit-Eintraege vorhanden."

        entries = self._audit_log[-limit:]
        lines = [f"CAPABILITY AUDIT LOG (letzte {len(entries)})", "=" * 60]
        for entry in entries:
            status = "ALLOW" if entry['allowed'] else "DENY "
            lines.append(
                f"  [{entry['timestamp'][:19]}] {status} "
                f"{entry['plugin']:<20} {entry['capability']:<18} "
            )
        return "\n".join(lines)

    def get_profiles(self) -> str:
        """Gibt alle Trust-Profile mit Capabilities zurueck."""
        lines = ["CAPABILITY TRUST-PROFILE", "=" * 50]
        for name, profile in sorted(self._profiles.items(),
                                     key=lambda x: -x[1].get('trust', 0)):
            trust = profile.get('trust', 0)
            desc = profile.get('description', '')
            caps = profile.get('capabilities', [])
            lines.append(f"\n  [{name}] trust={trust}")
            lines.append(f"    {desc}")
            if '*' in caps:
                lines.append(f"    Capabilities: ALLE ({len(CAPABILITIES)})")
            else:
                lines.append(f"    Capabilities: {', '.join(sorted(caps)) or 'keine'}")
        return "\n".join(lines)


# Singleton-Instanz
capability_manager = CapabilityManager()
