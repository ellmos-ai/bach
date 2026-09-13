# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
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
SandboxHandler - Isolierte Code-Ausfuehrung (ersetzt E2B MCP)
==============================================================
bach sandbox run <datei>        Python-Datei in Sandbox ausfuehren
bach sandbox eval "<code>"      Python-Ausdruck evaluieren
bach sandbox test <datei>       pytest auf Datei ausfuehren
bach sandbox shell "<cmd>"      Shell-Befehl mit Timeout
bach sandbox limit [mb]         Memory-Limit anzeigen/setzen

Stufe 1+2: Policy (Allowlist/Blocklist, Timeouts) + Resource-Bounds
(Memory-Limit via RLIMIT_AS, Prozessgruppen-Kill) ueber core.sandbox.

Task: 995, 1071
"""
import json
import os
import re
import shlex
import sys
import subprocess
import tempfile
from pathlib import Path
from typing import FrozenSet, List, Tuple
from .base import BaseHandler

os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
if sys.stdout:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr:
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')


class SandboxHandler(BaseHandler):
    # Allowed interpreters (python, node) can execute arbitrary code —
    # this sandbox provides resource bounds, not containment.

    TIMEOUT = 30  # Sekunden
    DEFAULT_MEMORY_LIMIT_MB = 512  # Sandbox Stufe 2: RLIMIT_AS

    DEFAULT_ALLOWED_COMMANDS: FrozenSet[str] = frozenset({
        "echo", "cat", "head", "tail", "wc", "sort", "uniq", "diff",
        "ls", "dir", "find", "type", "where", "which",
        "grep", "rg", "fd",
        "python", "python3", "pip", "pip3", "pytest",
        "git", "node", "npm", "npx",
    })

    BLOCKED_PATTERNS: FrozenSet[str] = frozenset({
        "rm -rf /", "rm -rf /*", "del /f /s /q c:\\",
        "format c:", "mkfs", "shutdown", "reboot", "halt",
        ":(){", "fork", ">(){ :|:& };:",
    })

    def __init__(self, base_path_or_app):
        super().__init__(base_path_or_app)
        self._allowed_commands: FrozenSet[str] = self._load_allowed_commands()
        self._memory_limit_mb = self._load_memory_limit()

    @property
    def profile_name(self) -> str:
        return "sandbox"

    @property
    def target_file(self) -> Path:
        return self.base_path / "tools"

    def get_operations(self) -> dict:
        return {
            "run": "Python-Datei ausfuehren: run <datei> [args...]",
            "eval": "Python-Ausdruck: eval '<code>'",
            "test": "pytest ausfuehren: test <datei>",
            "shell": "Shell-Befehl: shell '<cmd>'",
            "policy": "Sandbox-Policy anzeigen (erlaubte Befehle)",
            "allow": "Befehl zur Allowlist hinzufuegen: allow <cmd>",
            "deny": "Befehl von der Allowlist entfernen: deny <cmd>",
            "limit": "Memory-Limit anzeigen/setzen: limit [mb]",
        }

    def handle(self, operation: str, args: List[str], dry_run: bool = False) -> Tuple[bool, str]:
        if dry_run:
            return True, f"[DRY-RUN] sandbox {operation} {' '.join(args)}"

        if operation == "run" and args:
            return self._run_file(args[0], args[1:])
        elif operation == "eval" and args:
            return self._eval(" ".join(args))
        elif operation == "test" and args:
            return self._test(args[0])
        elif operation == "shell" and args:
            return self._shell(" ".join(args))
        elif operation == "policy":
            return self._policy()
        elif operation == "allow" and args:
            return self._allow_command(args[0])
        elif operation == "deny" and args:
            return self._deny_command(args[0])
        elif operation == "limit":
            return self._limit(args)
        else:
            ops = "\n".join(f"  {k}: {v}" for k, v in self.get_operations().items())
            return False, f"Nutzung:\n{ops}"

    def _run_file(self, filepath: str, extra_args: List[str]) -> Tuple[bool, str]:
        """Fuehrt Python-Datei in Sandbox aus."""
        # Pfad aufloesen
        fpath = Path(filepath)
        if not fpath.is_absolute():
            fpath = self.base_path / filepath
        if not fpath.exists():
            return False, f"Datei nicht gefunden: {fpath}"

        try:
            result = self._isolated(
                [sys.executable, str(fpath)] + extra_args,
                timeout=self.TIMEOUT,
                cwd=str(fpath.parent),
                env={**os.environ, 'PYTHONIOENCODING': 'utf-8'},
            )
            if result.timed_out:
                return False, f"TIMEOUT ({self.TIMEOUT}s) bei {fpath.name}"
            output = self._format_result(result, f"run {fpath.name}")
            if result.memory_exceeded:
                return False, f"MEMORY-LIMIT ({self._memory_limit_mb}MB) bei {fpath.name}\n{output}"
            return result.returncode == 0, output
        except Exception as e:
            return False, f"Fehler: {e}"

    def _eval(self, code: str) -> Tuple[bool, str]:
        """Evaluiert Python-Ausdruck in isoliertem Prozess."""
        # Code als temp-Datei ausfuehren (sicherer als eval)
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as f:
            # Wrapper der stdout captured
            f.write(f"import sys\nsys.stdout.reconfigure(encoding='utf-8', errors='replace')\n")
            f.write(f"try:\n")
            f.write(f"    _result = {code}\n")
            f.write(f"    if _result is not None:\n")
            f.write(f"        print(_result)\n")
            f.write(f"except SyntaxError:\n")
            f.write(f"    exec({repr(code)})\n")
            tmp_path = f.name

        try:
            result = self._isolated(
                [sys.executable, tmp_path],
                timeout=self.TIMEOUT,
                cwd=tempfile.gettempdir(),
            )
            if result.timed_out:
                return False, f"TIMEOUT ({self.TIMEOUT}s)"
            output = self._format_result(result, f"eval")
            if result.memory_exceeded:
                return False, f"MEMORY-LIMIT ({self._memory_limit_mb}MB)\n{output}"
            return result.returncode == 0, output
        except Exception as e:
            return False, f"Fehler: {e}"
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    def _test(self, filepath: str) -> Tuple[bool, str]:
        """Fuehrt pytest auf Datei aus."""
        fpath = Path(filepath)
        if not fpath.is_absolute():
            fpath = self.base_path / filepath
        if not fpath.exists():
            return False, f"Datei nicht gefunden: {fpath}"

        try:
            result = self._isolated(
                [sys.executable, "-m", "pytest", str(fpath), "-v", "--tb=short"],
                timeout=self.TIMEOUT * 2,
                cwd=str(self.base_path),
                env={**os.environ, 'PYTHONIOENCODING': 'utf-8'},
            )
            if result.timed_out:
                return False, f"TIMEOUT ({self.TIMEOUT * 2}s) bei Tests"
            output = self._format_result(result, f"test {fpath.name}")
            return result.returncode == 0, output
        except Exception as e:
            return False, f"Fehler: {e}"

    def _shell(self, cmd: str) -> Tuple[bool, str]:
        """Shell-Befehl mit Sandbox (temp cwd, timeout, capability check)."""
        allowed, reason = self._check_shell_allowed(cmd)
        if not allowed:
            return False, reason

        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                result = self._isolated(
                    cmd,
                    timeout=self.TIMEOUT,
                    cwd=tmpdir,
                    shell=True,
                )
                if result.timed_out:
                    return False, f"TIMEOUT ({self.TIMEOUT}s)"
                output = self._format_result(result, f"shell")
                if result.memory_exceeded:
                    return False, f"MEMORY-LIMIT ({self._memory_limit_mb}MB)\n{output}"
                return result.returncode == 0, output
            except Exception as e:
                return False, f"Fehler: {e}"

    # ------------------------------------------------------------------
    # Resource-Bounds (Sandbox Stufe 2, Task 1071)
    # ------------------------------------------------------------------

    def _isolated(self, cmd, timeout: int, cwd=None, env=None, shell: bool = False):
        """Fuehrt Befehl ueber core.sandbox.run_isolated aus
        (Timeout + Memory-Limit + Prozessgruppen-Kill)."""
        from core.sandbox import SandboxLimits, run_isolated
        limits = SandboxLimits(timeout_sec=timeout, memory_mb=self._memory_limit_mb)
        return run_isolated(cmd, limits=limits, cwd=cwd, env=env, shell=shell)

    def _load_memory_limit(self):
        """Laedt Memory-Limit (MB) aus system_config, Default 512MB."""
        db = getattr(self, "_canonical_db", None)
        if not db or not Path(db).exists():
            return self.DEFAULT_MEMORY_LIMIT_MB
        try:
            import sqlite3
            conn = sqlite3.connect(str(db))
            cur = conn.execute(
                "SELECT value FROM system_config WHERE key = 'sandbox.memory_limit_mb'"
            )
            row = cur.fetchone()
            conn.close()
            if row and row[0] is not None:
                val = int(str(row[0]).strip())
                if val > 0:
                    return val
        except Exception:
            pass
        return self.DEFAULT_MEMORY_LIMIT_MB

    def _save_memory_limit(self, mb: int) -> bool:
        db = getattr(self, "_canonical_db", None)
        if not db or not Path(db).exists():
            return False
        try:
            import sqlite3
            conn = sqlite3.connect(str(db))
            conn.execute(
                "INSERT OR REPLACE INTO system_config (key, value, category) "
                "VALUES ('sandbox.memory_limit_mb', ?, 'sandbox')",
                (str(int(mb)),)
            )
            conn.commit()
            conn.close()
            return True
        except Exception:
            return False

    def _limit(self, args: List[str]) -> Tuple[bool, str]:
        """Memory-Limit anzeigen oder setzen."""
        if not args:
            return True, (
                f"Memory-Limit: {self._memory_limit_mb}MB "
                f"(Default: {self.DEFAULT_MEMORY_LIMIT_MB}MB)\n"
                f"Setzen: bach sandbox limit <mb>"
            )
        try:
            mb = int(args[0])
            if mb < 64:
                return False, "Limit zu klein (Minimum: 64MB)"
        except ValueError:
            return False, f"Ungueltiger Wert: {args[0]} (Zahl in MB erwartet)"
        if self._save_memory_limit(mb):
            self._memory_limit_mb = mb
            return True, f"Memory-Limit auf {mb}MB gesetzt (persistiert)"
        self._memory_limit_mb = mb
        return True, f"Memory-Limit auf {mb}MB gesetzt (nur Session, DB nicht verfuegbar)"

    # ------------------------------------------------------------------
    # Capability System (SANDBOX-002)
    # ------------------------------------------------------------------

    def _load_allowed_commands(self) -> FrozenSet[str]:
        db = self._canonical_db
        if not db or not Path(db).exists():
            return self.DEFAULT_ALLOWED_COMMANDS
        try:
            import sqlite3
            conn = sqlite3.connect(str(db))
            cur = conn.execute(
                "SELECT value FROM system_config WHERE key = 'sandbox.allowed_commands'"
            )
            row = cur.fetchone()
            conn.close()
            if row:
                custom = set(json.loads(row[0]))
                return frozenset(custom)
        except Exception:
            pass
        return self.DEFAULT_ALLOWED_COMMANDS

    def _save_allowed_commands(self, commands: FrozenSet[str]) -> bool:
        db = self._canonical_db
        if not db or not Path(db).exists():
            return False
        try:
            import sqlite3
            conn = sqlite3.connect(str(db))
            conn.execute(
                "INSERT OR REPLACE INTO system_config (key, value, category) "
                "VALUES ('sandbox.allowed_commands', ?, 'sandbox')",
                (json.dumps(sorted(commands)),)
            )
            conn.commit()
            conn.close()
            return True
        except Exception:
            return False

    def _extract_base_command(self, cmd: str) -> str:
        """Extrahiert den Basis-Befehl (erstes Token) aus einem Shell-String."""
        cmd_stripped = cmd.strip()
        if not cmd_stripped:
            return ""
        # Windows-Pfade: Backslash ist Pfadtrenner, kein Escape —
        # vor shlex behandeln (shlex posix frisst Backslashes)
        first_raw = cmd_stripped.split()[0]
        if "\\" in first_raw:
            base = first_raw.strip('"').strip("'")
            return Path(base.rsplit("\\", 1)[-1]).stem.lower()
        try:
            tokens = shlex.split(cmd_stripped, posix=(os.name != "nt"))
            if tokens:
                raw = tokens[0].strip('"').strip("'")
                return Path(raw).stem.lower()
        except ValueError:
            pass
        first = cmd_stripped.split()[0] if cmd_stripped.split() else ""
        return Path(first).stem.lower()

    def _check_shell_allowed(self, cmd: str) -> Tuple[bool, str]:
        cmd_lower = cmd.lower().strip()
        for pattern in self.BLOCKED_PATTERNS:
            escaped = re.escape(pattern)
            if re.search(rf"(?:^|\s){escaped}(?:\s|$)", cmd_lower):
                return False, f"BLOCKIERT: Befehl enthaelt verbotenes Muster '{pattern}'"

        base_cmd = self._extract_base_command(cmd)
        if not base_cmd:
            return False, "BLOCKIERT: Leerer Befehl"

        if base_cmd not in self._allowed_commands:
            return False, (
                f"BLOCKIERT: '{base_cmd}' ist nicht in der Sandbox-Allowlist.\n"
                f"Erlaubte Befehle: {', '.join(sorted(self._allowed_commands))}\n"
                f"Hinzufuegen: bach sandbox allow {base_cmd}"
            )
        return True, ""

    def _policy(self) -> Tuple[bool, str]:
        from core.sandbox import HAS_RLIMIT, IS_POSIX
        if HAS_RLIMIT:
            bounds = f"aktiv (RLIMIT_AS, Prozessgruppen-Kill, {self._memory_limit_mb}MB)"
        elif IS_POSIX:
            bounds = "eingeschraenkt (resource-Modul fehlt)"
        else:
            bounds = "eingeschraenkt (Windows: nur Timeout, kein Memory-Limit)"
        lines = [
            "Sandbox Policy (SANDBOX-002)",
            "=" * 40,
            f"  Timeout: {self.TIMEOUT}s (shell), {self.TIMEOUT * 2}s (test)",
            f"  Memory-Limit: {self._memory_limit_mb}MB",
            f"  Resource-Bounds (Stufe 2): {bounds}",
            f"  Shell-Modus: fail-closed (nur erlaubte Befehle)",
            "",
            f"  Erlaubte Befehle ({len(self._allowed_commands)}):",
        ]
        for cmd in sorted(self._allowed_commands):
            lines.append(f"    - {cmd}")
        lines.append("")
        lines.append(f"  Blockierte Muster ({len(self.BLOCKED_PATTERNS)}):")
        for p in sorted(self.BLOCKED_PATTERNS):
            lines.append(f"    - {p}")
        return True, "\n".join(lines)

    def _allow_command(self, cmd: str) -> Tuple[bool, str]:
        cmd = cmd.lower().strip()
        if not cmd:
            return False, "Kein Befehl angegeben"
        new_set = set(self._allowed_commands) | {cmd}
        if self._save_allowed_commands(frozenset(new_set)):
            self._allowed_commands = frozenset(new_set)
            return True, f"'{cmd}' zur Sandbox-Allowlist hinzugefuegt"
        self._allowed_commands = frozenset(new_set)
        return True, f"'{cmd}' zur Sandbox-Allowlist hinzugefuegt (nur Session, DB nicht verfuegbar)"

    def _deny_command(self, cmd: str) -> Tuple[bool, str]:
        cmd = cmd.lower().strip()
        if not cmd:
            return False, "Kein Befehl angegeben"
        if cmd not in self._allowed_commands:
            return False, f"'{cmd}' ist nicht in der Allowlist"
        new_set = set(self._allowed_commands) - {cmd}
        if self._save_allowed_commands(frozenset(new_set)):
            self._allowed_commands = frozenset(new_set)
            return True, f"'{cmd}' von der Sandbox-Allowlist entfernt"
        self._allowed_commands = frozenset(new_set)
        return True, f"'{cmd}' von der Sandbox-Allowlist entfernt (nur Session, DB nicht verfuegbar)"

    def _format_result(self, result: subprocess.CompletedProcess, label: str) -> str:
        """Formatiert subprocess-Ergebnis."""
        lines = [f"[SANDBOX] {label}", f"Exit: {result.returncode}", "=" * 35]
        if result.stdout:
            lines.append("STDOUT:")
            lines.append(result.stdout.strip()[:3000])
        if result.stderr:
            lines.append("STDERR:")
            lines.append(result.stderr.strip()[:1000])
        if not result.stdout and not result.stderr:
            lines.append("(keine Ausgabe)")
        return "\n".join(lines)
