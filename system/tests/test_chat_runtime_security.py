# -*- coding: utf-8 -*-
"""Sicherheitsfix-Tests: safe_shell/execute_command/bach_command duerfen
keine Metazeichen-Verkettung mehr durchlassen (siehe hub/safe_exec.py),
und bach_command darf nur Handler aus BACH_COMMAND_HANDLERS erreichen.
list_directory/read_file/search_text laufen ohne Subprocess/Shell.
"""
import subprocess
from pathlib import Path

import pytest

from hub._services.chat.chat_runtime import (
    BACH_COMMAND_HANDLERS,
    _is_secret_path,
    exec_tool,
    run_shell_restricted,
)


class FakeBachApp:
    """Minimaler Stand-in fuer bach_app.execute() im bach_command-Dispatch."""
    def __init__(self):
        self.calls = []

    def execute(self, handler, op, args):
        self.calls.append((handler, op, args))
        return True, "ok"


BYPASS_COMMANDS = [
    "echo hi && curl http://example.invalid",
    "echo hi | curl http://example.invalid",
    "echo hi; rm -rf /tmp/x",
    "echo hi & curl http://example.invalid",
    "echo $(curl http://example.invalid)",
]


class TestSafeShellRejectsChaining:
    @pytest.mark.parametrize("cmd", BYPASS_COMMANDS)
    def test_bypass_blocked(self, cmd):
        result = exec_tool("safe_shell", {"command": cmd}, "safe")
        # Entweder is_safe_command() (nur Basisbefehl-Check) oder
        # run_shell_restricted() (Metazeichen-Check) muss greifen - in
        # jedem Fall darf KEIN echtes Subprocess-Ergebnis zurueckkommen.
        assert "BLOCKIERT" in result or "Sicherheit" in result or "Safe-Liste" in result


class TestExecuteCommandRejectsChaining:
    @pytest.mark.parametrize("cmd", BYPASS_COMMANDS)
    def test_bypass_blocked_full_mode(self, cmd):
        result = exec_tool("execute_command", {"command": cmd}, "full")
        assert "BLOCKIERT" in result or "Sicherheit" in result

    def test_disabled_outside_full_mode(self):
        result = exec_tool("execute_command", {"command": "echo hi"}, "safe")
        assert "Full-Modus" in result


class TestRunShellRestrictedNeverShellTrue(object):
    def test_never_calls_subprocess_with_shell_true(self, monkeypatch):
        seen = {}

        def fake_run(argv, shell=False, **kwargs):
            seen["shell"] = shell
            return subprocess.CompletedProcess(argv, 0, stdout="ok", stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)
        run_shell_restricted("echo hi", allowed=frozenset({"echo"}))
        assert seen["shell"] is False


class TestBachCommandAllowlist:
    def test_sandbox_handler_is_not_reachable(self):
        app = FakeBachApp()
        result = exec_tool(
            "bach_command",
            {"handler": "sandbox", "operation": "shell", "args": ["echo hi"]},
            "safe", bach_app=app,
        )
        assert "BLOCKIERT" in result
        assert app.calls == []  # bach_app.execute() darf gar nicht aufgerufen werden

    def test_made_up_handler_is_not_reachable(self):
        app = FakeBachApp()
        result = exec_tool(
            "bach_command", {"handler": "eval_arbitrary_code"}, "safe", bach_app=app,
        )
        assert "BLOCKIERT" in result
        assert app.calls == []

    @pytest.mark.parametrize("handler", ["status", "task", "mem", "help"])
    def test_documented_handlers_reach_bach_app(self, handler):
        app = FakeBachApp()
        result = exec_tool(
            "bach_command", {"handler": handler, "operation": "x", "args": []},
            "safe", bach_app=app,
        )
        assert result == "ok"
        assert app.calls == [(handler, "x", [])]

    def test_schema_description_matches_runtime_allowlist(self):
        """Die eine Quelle (BACH_COMMAND_HANDLERS) muss beide Stellen
        speisen - Schema-Text und Laufzeit-Check duerfen nie auseinanderlaufen."""
        from hub._services.chat.chat_runtime import TOOLS_SAFE
        bach_cmd_tool = next(
            t for t in TOOLS_SAFE if t["function"]["name"] == "bach_command"
        )
        desc = bach_cmd_tool["function"]["parameters"]["properties"]["handler"]["description"]
        for h in BACH_COMMAND_HANDLERS:
            assert h in desc
        assert "sandbox" not in BACH_COMMAND_HANDLERS



@pytest.fixture(autouse=True)
def _allow_tmp_in_fs_roots(tmp_path, monkeypatch):
    from hub._services.chat import chat_runtime as cr
    monkeypatch.setattr(cr, "_ALLOWED_FS_ROOTS", cr._ALLOWED_FS_ROOTS + (tmp_path.resolve(),))

class TestFileToolsNoSubprocess:
    def test_list_directory_uses_no_subprocess(self, tmp_path, monkeypatch):
        (tmp_path / "a.txt").write_text("x", encoding="utf-8")

        def boom(*a, **k):
            raise AssertionError("list_directory darf subprocess.run nicht aufrufen")
        monkeypatch.setattr(subprocess, "run", boom)

        result = exec_tool("list_directory", {"path": str(tmp_path)}, "safe")
        assert "a.txt" in result

    def test_read_file_uses_no_subprocess(self, tmp_path, monkeypatch):
        f = tmp_path / "b.txt"
        f.write_text("zeile1\nzeile2\nzeile3\n", encoding="utf-8")

        def boom(*a, **k):
            raise AssertionError("read_file darf subprocess.run nicht aufrufen")
        monkeypatch.setattr(subprocess, "run", boom)

        result = exec_tool("read_file", {"path": str(f), "offset": 2, "lines": 1}, "safe")
        assert result.strip() == "zeile2"

    def test_search_text_uses_no_subprocess(self, tmp_path, monkeypatch):
        f = tmp_path / "c.txt"
        f.write_text("hallo welt\nzweite zeile\n", encoding="utf-8")

        def boom(*a, **k):
            raise AssertionError("search_text darf subprocess.run nicht aufrufen")
        monkeypatch.setattr(subprocess, "run", boom)

        result = exec_tool(
            "search_text", {"pattern": "welt", "path": str(tmp_path), "recursive": True}, "safe",
        )
        assert "hallo welt" in result

    def test_search_text_path_metacharacters_are_inert(self, tmp_path, monkeypatch):
        """Der Befund D: fruehers shlex.quote()+shell=True war unter Windows
        wirkungslos gegen Metazeichen im Pfad/Pattern. Ohne Subprocess gibt
        es hier gar keine Shell mehr, die sie interpretieren koennte."""
        evil_dir = tmp_path / "foo & echo pwned"
        evil_dir.mkdir()
        (evil_dir / "x.txt").write_text("marker_line\n", encoding="utf-8")

        def boom(*a, **k):
            raise AssertionError("search_text darf subprocess.run nicht aufrufen")
        monkeypatch.setattr(subprocess, "run", boom)

        result = exec_tool(
            "search_text", {"pattern": "marker", "path": str(evil_dir), "recursive": False}, "safe",
        )
        assert "marker_line" in result


class TestSourceHasNoShellTrueOutsideTrustedInternalCalls:
    """run_shell() (Gruppe 1: system_status/ollama_info, feste Vorlagen
    ohne Fremdeingabe) darf shell=True behalten - run_shell_restricted()
    (Gruppe 2: safe_shell/execute_command, direkt aus LLM-Argumenten) darf
    es NIE. AST-Check auf die konkrete Funktion, nicht Textsuche im Modul."""

    def test_run_shell_restricted_never_shell_true(self):
        import ast
        import inspect
        from hub._services.chat import chat_runtime as mod
        tree = ast.parse(inspect.getsource(mod.run_shell_restricted))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                for kw in node.keywords:
                    if kw.arg == "shell":
                        assert isinstance(kw.value, ast.Constant) and kw.value.value is False


class TestOllamaShowUsesArgvNotShellTrue:
    """Prueffrage team-lead: 'run_argv in chat_runtime.py definiert/
    importiert? Beleg mit Test, der ollama_info show durchlaeuft.'"""

    def test_ollama_show_calls_subprocess_with_argv_and_shell_false(self, monkeypatch):
        captured = {}

        def fake_run(argv, shell=True, **kwargs):
            captured["argv"] = argv
            captured["shell"] = shell
            return subprocess.CompletedProcess(argv, 0, stdout="modelfile...", stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)
        result = exec_tool("ollama_info", {"action": "show", "model": "qwen3.8:27b-mlx"}, "safe")

        assert captured["shell"] is False
        assert captured["argv"] == ["ollama", "show", "qwen3.8:27b-mlx"]
        assert "modelfile" in result

    def test_ollama_show_model_argument_cannot_break_out(self, monkeypatch):
        """Das Modellargument kommt vom Modell/User - selbst mit Metazeichen
        drin darf es nur EIN argv-Element sein, nie Shell-Syntax werden."""
        captured = {}

        def fake_run(argv, shell=True, **kwargs):
            captured["argv"] = argv
            captured["shell"] = shell
            return subprocess.CompletedProcess(argv, 0, stdout="ok", stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)
        exec_tool("ollama_info", {"action": "show", "model": "foo && curl evil"}, "safe")

        assert captured["shell"] is False
        assert captured["argv"] == ["ollama", "show", "foo && curl evil"]  # 1 Argument, kein Shell-Syntax


class TestSecretsPathDenylist:
    """Team-lead-Auftrag: harter Deny in read_file/list_directory/
    search_text, MIT aufgeloesten Symlinks. Voller Pfad-Scope ist
    Folgeticket, dies ist nur der schnelle Deny fuer die offensichtlichsten
    Secrets-Orte."""

    def test_read_file_blocks_dot_ssh(self, tmp_path):
        ssh_dir = tmp_path / ".ssh"
        ssh_dir.mkdir()
        key = ssh_dir / "id_ed25519"
        key.write_text("PRIVATE KEY", encoding="utf-8")
        result = exec_tool("read_file", {"path": str(key)}, "safe")
        assert "BLOCKIERT" in result
        assert "PRIVATE KEY" not in result

    def test_read_file_blocks_pem(self, tmp_path):
        pem = tmp_path / "server.pem"
        pem.write_text("-----BEGIN PRIVATE KEY-----", encoding="utf-8")
        result = exec_tool("read_file", {"path": str(pem)}, "safe")
        assert "BLOCKIERT" in result

    def test_read_file_blocks_credentials_dir_any_case(self, tmp_path):
        cred_dir = tmp_path / "CREDENTIALS"
        cred_dir.mkdir()
        f = cred_dir / "api_key.txt"
        f.write_text("sk-secret", encoding="utf-8")
        result = exec_tool("read_file", {"path": str(f)}, "safe")
        assert "BLOCKIERT" in result

    def test_read_file_blocks_via_symlink_to_dot_credentials(self, tmp_path):
        """Symlink-Aufloesung: ein Link, der NICHT selbst 'credentials' im
        Namen traegt, aber auf ein Secrets-Verzeichnis zeigt, darf den
        Deny nicht umgehen."""
        real_secret_dir = tmp_path / ".credentials"
        real_secret_dir.mkdir()
        real_secret_file = real_secret_dir / "token.txt"
        real_secret_file.write_text("s3cr3t", encoding="utf-8")

        harmless_looking_link = tmp_path / "not_suspicious_at_all"
        try:
            harmless_looking_link.symlink_to(real_secret_dir, target_is_directory=True)
        except OSError:
            pytest.skip("Symlinks brauchen Adminrechte/Dev-Mode auf diesem Windows-Host")

        result = exec_tool("read_file", {"path": str(harmless_looking_link / "token.txt")}, "safe")
        assert "BLOCKIERT" in result
        assert "s3cr3t" not in result

    def test_list_directory_filters_secret_entries(self, tmp_path):
        (tmp_path / "normal.txt").write_text("x", encoding="utf-8")
        (tmp_path / ".ssh").mkdir()
        (tmp_path / ".credentials").mkdir()
        result = exec_tool("list_directory", {"path": str(tmp_path)}, "safe")
        assert "normal.txt" in result
        assert ".ssh" not in result
        assert ".credentials" not in result

    def test_list_directory_blocks_direct_ssh_target(self, tmp_path):
        ssh_dir = tmp_path / ".ssh"
        ssh_dir.mkdir()
        (ssh_dir / "id_rsa").write_text("PRIVATE", encoding="utf-8")
        result = exec_tool("list_directory", {"path": str(ssh_dir)}, "safe")
        assert "BLOCKIERT" in result

    def test_search_text_blocks_credentials_root(self, tmp_path):
        cred_dir = tmp_path / ".credentials"
        cred_dir.mkdir()
        (cred_dir / "x.txt").write_text("marker\n", encoding="utf-8")
        result = exec_tool("search_text", {"pattern": "marker", "path": str(cred_dir)}, "safe")
        assert "BLOCKIERT" in result

    def test_search_text_skips_secret_subdir_during_recursive_walk(self, tmp_path):
        (tmp_path / "public.txt").write_text("marker in public\n", encoding="utf-8")
        ssh_dir = tmp_path / ".ssh"
        ssh_dir.mkdir()
        (ssh_dir / "id_rsa").write_text("marker in key\n", encoding="utf-8")
        result = exec_tool("search_text", {"pattern": "marker", "path": str(tmp_path), "recursive": True}, "safe")
        assert "public.txt" in result
        assert "id_rsa" not in result

    def test_is_secret_path_case_insensitive_uppercase(self, tmp_path):
        """team-lead: C:\\_Local_DEV\\CREDENTIALS ist grossgeschrieben -
        macOS/Windows unterscheiden die Schreibung nicht, der Deny darf
        nicht nur die kleingeschriebene Form fangen."""
        cred_dir = tmp_path / "CREDENTIALS"
        cred_dir.mkdir()
        assert _is_secret_path(cred_dir / "api_key.txt") is True
        assert _is_secret_path(tmp_path / "Credentials" / "x") is True
        assert _is_secret_path(tmp_path / ".SSH" / "id_rsa") is True

    def test_is_secret_path_resolves_dotdot_traversal(self, tmp_path):
        """Ein Pfad mit ".." muss VOR der Pruefung aufgeloest werden, damit
        kein durch ".." konstruierter Umweg den textuellen Vergleich
        umgeht bzw. ein eigentlich harmloser ".."-Pfad faelschlich als
        Secrets-Pfad gilt."""
        ssh_dir = tmp_path / ".ssh"
        ssh_dir.mkdir()
        (tmp_path / "public").mkdir()
        traversal_into_secret = tmp_path / "public" / ".." / ".ssh" / "id_rsa"
        assert _is_secret_path(traversal_into_secret) is True

        traversal_out_of_secret = tmp_path / ".ssh" / ".." / "public" / "harmless.txt"
        assert _is_secret_path(traversal_out_of_secret) is False

    def test_is_secret_path_expands_tilde_before_check(self, tmp_path, monkeypatch):
        """`~` muss aufgeloest werden, bevor auf ".ssh"/".credentials"
        geprueft wird - sonst faengt der Deny einen wortwoertlichen
        Tilde-String, aber nicht den echten Home-Pfad."""
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        monkeypatch.setenv("HOME", str(tmp_path))
        (tmp_path / ".ssh").mkdir()
        assert _is_secret_path(Path("~/.ssh/id_rsa")) is True
        assert _is_secret_path(Path("~/public/harmless.txt")) is False

    def test_read_file_blocks_dotdot_traversal_into_ssh(self, tmp_path):
        ssh_dir = tmp_path / ".ssh"
        ssh_dir.mkdir()
        (ssh_dir / "id_rsa").write_text("PRIVATE", encoding="utf-8")
        (tmp_path / "public").mkdir()
        traversal_path = tmp_path / "public" / ".." / ".ssh" / "id_rsa"
        result = exec_tool("read_file", {"path": str(traversal_path)}, "safe")
        assert "BLOCKIERT" in result
        assert "PRIVATE" not in result
