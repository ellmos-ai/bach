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
import sys
import subprocess
import tempfile
from pathlib import Path
from typing import FrozenSet, List, Tuple
from .base import BaseHandler
from .safe_exec import CommandRejected, base_command_name, resolve_executable, tokenize

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
        self._backend = self._load_backend()
        self._container_mode = self._load_container_mode()

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
            "backend": "Backend anzeigen/setzen: backend [docker|local|auto]",
            "container": "Container-Isolation (Stufe 3): container status|build|run <datei>|mode [auto|on|off]",
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
        elif operation == "container":
            return self._container(args)
        elif operation == "backend":
            return self._backend_op(args)
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

        # Stufe 3: Container-Isolation (optional, mit Rollback auf _isolated)
        force_container = "--container" in extra_args
        extra_args = [a for a in extra_args if a != "--container"]
        use_container = force_container or self._container_mode == "on"
        if not use_container and self._container_mode == "auto":
            use_container = self._container_available()
        if use_container:
            try:
                from core.container_sandbox import ContainerUnavailable, run_in_container
                from core.sandbox import SandboxLimits
            except ImportError:
                pass  # Modul nicht verfuegbar -> Fallback auf _isolated
            else:
                try:
                    result = run_in_container(
                        str(fpath),
                        limits=SandboxLimits(timeout_sec=self.TIMEOUT, memory_mb=self._memory_limit_mb),
                        workspace=str(self.base_path),
                    )
                    if result.timed_out:
                        return False, f"TIMEOUT ({self.TIMEOUT}s) bei {fpath.name} [container]"
                    output = self._format_result(result, f"run {fpath.name} [container]")
                    if result.memory_exceeded:
                        return False, f"MEMORY-LIMIT ({self._memory_limit_mb}MB) bei {fpath.name} [container]\n{output}"
                    return result.returncode == 0, output
                except ContainerUnavailable:
                    pass  # Docker/Image nicht verfuegbar -> Fallback auf _isolated

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
        """Shell-Befehl mit Sandbox (temp cwd, timeout, capability check).

        Fuehrt NIE mit shell=True aus: argv wird tokenisiert und der
        Basisbefehl per shutil.which() gegen die Allowlist aufgeloest
        (siehe hub/safe_exec.py). So kann kein Metazeichen (&& | ; $()
        etc.) einen zweiten, nicht erlaubten Befehl anhaengen."""
        allowed, reason, argv = self._check_shell_allowed(cmd)
        if not allowed:
            return False, reason

        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                result = self._isolated(
                    argv,
                    timeout=self.TIMEOUT,
                    cwd=tmpdir,
                    shell=False,
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
        """Fuehrt Befehl ueber core.sandbox mit explizitem Backend-Routing aus.

        backend == "local"  -> core.run_isolated(..., backend="local")
        backend == "docker" -> core.docker_run_isolated(...)
        backend == "auto"   -> docker_available() ? docker_run_isolated(...) : run_isolated(..., backend="local")
        """
        from core.sandbox import SandboxLimits, docker_available, docker_run_isolated, run_isolated
        limits = SandboxLimits(timeout_sec=timeout, memory_mb=self._memory_limit_mb)
        if self._backend == "local":
            return run_isolated(cmd, limits=limits, cwd=cwd, env=env, shell=shell,
                                backend="local")
        if self._backend == "docker":
            return docker_run_isolated(cmd, limits=limits, cwd=cwd, env=env, shell=shell)
        # auto
        if docker_available():
            return docker_run_isolated(cmd, limits=limits, cwd=cwd, env=env, shell=shell)
        return run_isolated(cmd, limits=limits, cwd=cwd, env=env, shell=shell,
                            backend="local")

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

    def _container_env_disabled(self) -> bool:
        """True wenn Container via Env global deaktiviert sind."""
        try:
            from core.container_sandbox import container_disabled_by_env
            return container_disabled_by_env()
        except Exception:
            return False

    def _load_container_mode(self) -> str:
        """Laedt Container-Modus aus system_config (Default 'auto').
        Env-Disable (BACH_SANDBOX_CONTAINER_DISABLED=1) hat Vorrang."""
        if self._container_env_disabled():
            return "off"
        db = getattr(self, "_canonical_db", None)
        if db and Path(db).exists():
            try:
                import sqlite3
                conn = sqlite3.connect(str(db))
                cur = conn.execute(
                    "SELECT value FROM system_config WHERE key = 'sandbox.container_mode'"
                )
                row = cur.fetchone()
                conn.close()
                if row and row[0] is not None:
                    val = str(row[0]).strip().lower()
                    if val in ("auto", "on", "off"):
                        return val
            except Exception:
                pass
        return "auto"

    def _save_container_mode(self, mode: str) -> bool:
        db = getattr(self, "_canonical_db", None)
        if not db or not Path(db).exists():
            return False
        try:
            import sqlite3
            conn = sqlite3.connect(str(db))
            conn.execute(
                "INSERT OR REPLACE INTO system_config (key, value, category) "
                "VALUES ('sandbox.container_mode', ?, 'sandbox')",
                (mode,)
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

    def _load_backend(self) -> str:
        db = getattr(self, "_canonical_db", None)
        if db and Path(db).exists():
            try:
                import sqlite3
                conn = sqlite3.connect(str(db))
                cur = conn.execute(
                    "SELECT value FROM system_config WHERE key = 'sandbox.backend'"
                )
                row = cur.fetchone()
                conn.close()
                if row and row[0] is not None:
                    val = str(row[0]).strip().lower()
                    if val in ("docker", "local", "auto"):
                        return val
            except Exception:
                pass
        return "auto"

    def _save_backend(self, backend: str) -> bool:
        db = getattr(self, "_canonical_db", None)
        if not db or not Path(db).exists():
            return False
        try:
            import sqlite3
            conn = sqlite3.connect(str(db))
            conn.execute(
                "INSERT OR REPLACE INTO system_config (key, value, category) "
                "VALUES ('sandbox.backend', ?, 'sandbox')",
                (backend,)
            )
            conn.commit()
            conn.close()
            return True
        except Exception:
            return False

    def _backend_op(self, args: List[str]) -> Tuple[bool, str]:
        from core.sandbox import docker_available
        if not args:
            docker_ok = "verfuegbar" if docker_available() else "nicht verfuegbar"
            return True, chr(10).join([
                f"Backend: {self._backend} (Docker: {docker_ok})",
                "Setzen: bach sandbox backend <docker|local|auto>",
            ])
        value = str(args[0]).strip().lower()
        if value not in ("docker", "local", "auto"):
            return False, f"Ungueltiges Backend: {args[0]} (erwartet: docker|local|auto)"
        if self._save_backend(value):
            self._backend = value
            return True, f"Backend auf {value} gesetzt (persistiert)"
        self._backend = value
        return True, f"Backend auf {value} gesetzt (nur Session, DB nicht verfuegbar)"

    # ------------------------------------------------------------------
    # Container-Isolation (Sandbox Stufe 3, Task 1385)
    # ------------------------------------------------------------------

    def _container_available(self) -> bool:
        """True wenn Docker-Runtime fuer Stufe 3 nutzbar ist."""
        if self._container_env_disabled():
            return False
        try:
            from core.container_sandbox import docker_available
            return docker_available()
        except Exception:
            return False

    def _container(self, args: List[str]) -> Tuple[bool, str]:
        """Container-Isolation: status | build | run <datei> | mode [auto|on|off]."""
        sub = args[0] if args else "status"

        if sub == "status":
            try:
                from core.container_sandbox import container_status
                st = container_status()
            except ImportError:
                return False, "core.container_sandbox nicht verfuegbar"
            lines = [
                "Container-Isolation (Stufe 3)",
                "=" * 40,
                f"  mode: {self._container_mode}",
                f"  docker_available: {'ja' if st['docker_available'] else 'nein'}",
                f"  disabled_by_env: {'ja' if st['disabled_by_env'] else 'nein'}",
                f"  image: {st['image']}",
                f"  image_exists: {'ja' if st['image_exists'] else 'nein'}",
                f"  hardening: {', '.join(st['hardening'])}",
                f"  fallback: {st['fallback']}",
            ]
            return True, "\n".join(lines)

        if sub == "build":
            try:
                from core.container_sandbox import build_image
            except ImportError:
                return False, "core.container_sandbox nicht verfuegbar"
            ok, msg = build_image()
            return ok, msg

        if sub == "run":
            if len(args) < 2:
                return False, "Nutzung: sandbox container run <datei> [args...]"
            return self._run_file(args[1], ["--container"] + args[2:])

        if sub == "mode":
            if len(args) < 2:
                return True, (
                    f"Container-Modus: {self._container_mode}\n"
                    f"Modi: auto (wenn Docker verfuegbar), on (erzwingen), "
                    f"off (Rollback auf Stufe 2)\n"
                    f"Setzen: bach sandbox container mode [auto|on|off]"
                )
            mode = args[1].strip().lower()
            if mode not in ("auto", "on", "off"):
                return False, f"Ungueltiger Modus: {args[1]} (auto|on|off)"
            warning = ""
            if mode != "off" and self._container_env_disabled():
                warning = ("\nHINWEIS: BACH_SANDBOX_CONTAINER_DISABLED=1 gesetzt — "
                           "Env-Disable hat Vorrang, Container bleiben deaktiviert")
            if self._save_container_mode(mode):
                self._container_mode = mode
                return True, f"Container-Modus auf '{mode}' gesetzt (persistiert){warning}"
            self._container_mode = mode
            return True, (
                f"Container-Modus auf '{mode}' gesetzt "
                f"(nur Session, DB nicht verfuegbar){warning}"
            )

        return False, (
            "Nutzung: sandbox container status|build|run <datei>|mode [auto|on|off]"
        )

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
        """Extrahiert den Basis-Befehl (erstes Token) aus einem Shell-String.

        Delegiert an hub.safe_exec.tokenize()/base_command_name() (fail-closed
        shlex-Tokenisierung statt naivem .split()[0], das an Quoting/Leerzeichen
        in Pfaden mit Spaces scheiterte, siehe T-20260921-750493182). Gibt bei
        Ablehnung "" zurueck (Kompatibilitaet zu bestehenden Aufrufern/Tests)."""
        first_raw = cmd.strip().split()[0] if cmd.strip() else ""
        if "\\" in first_raw:
            # Windows-Pfad: unter POSIX wuerde shlex die Backslashes schlucken.
            return base_command_name(first_raw.rsplit("\\", 1)[-1])
        try:
            tokens = tokenize(cmd)
        except CommandRejected:
            return ""
        return base_command_name(tokens[0])

    def _check_shell_allowed(self, cmd: str) -> Tuple[bool, str, List[str]]:
        """Prueft cmd fail-closed und liefert das fertige argv fuer shell=False.

        Gibt (allowed, reason, argv) zurueck. `argv` ist nur bei allowed=True
        gefuellt - der von shutil.which() aufgeloeste, echte Pfad als argv[0],
        NIE der vom Aufrufer gelieferte String (siehe hub/safe_exec.py)."""
        cmd_lower = cmd.lower().strip()
        for pattern in self.BLOCKED_PATTERNS:
            escaped = re.escape(pattern)
            if re.search(rf"(?:^|\s){escaped}(?:\s|$)", cmd_lower):
                return False, f"BLOCKIERT: Befehl enthaelt verbotenes Muster '{pattern}'", []

        try:
            tokens = tokenize(cmd)
        except CommandRejected as e:
            return False, f"BLOCKIERT: {e}", []

        base_cmd = base_command_name(tokens[0])
        if base_cmd not in self._allowed_commands:
            return False, (
                f"BLOCKIERT: '{base_cmd}' ist nicht in der Sandbox-Allowlist.\n"
                f"Erlaubte Befehle: {', '.join(sorted(self._allowed_commands))}\n"
                f"Hinzufuegen: bach sandbox allow {base_cmd}"
            ), []

        try:
            argv = resolve_executable(cmd, self._allowed_commands)
        except CommandRejected as e:
            return False, f"BLOCKIERT: {e}", []
        return True, "", argv

    def _policy(self) -> Tuple[bool, str]:
        from core.sandbox import HAS_RLIMIT, IS_POSIX, docker_available
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
            f"  Backend (Stufe 3): {self._backend} (Docker: {'verfuegbar' if docker_available() else 'nicht verfuegbar'})",
            f"  Container-Isolation (Stufe 3): {self._container_mode} (docker: {'ja' if self._container_available() else 'nein'})",
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
