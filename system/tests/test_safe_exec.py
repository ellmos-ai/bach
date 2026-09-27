# -*- coding: utf-8 -*-
"""Tests fuer hub/safe_exec.py - der gemeinsame fail-closed Shell-Helfer.

Deckt die Befunde ab, die zu diesem Modul gefuehrt haben: Metazeichen
duerfen NIE ein "erlaubtes" Ergebnis liefern, auch nicht ueber Quoting-/
Leerzeichen-Tricks, waehrend legitime Aufrufe (Pfade mit Leerzeichen,
zitierte Codezeilen mit `;`/`(`) weiter funktionieren muessen.
"""
import subprocess
import sys

import pytest

from hub.safe_exec import (
    CommandRejected,
    base_command_name,
    dequote,
    has_shell_metacharacters,
    resolve_executable,
    run_safe,
    tokenize,
)

ALLOWED = frozenset({"echo", "python", "git"})


class TestBypassesRejected:
    """Jede dieser Zeichenketten war vor dem Fix ein funktionierender
    Metazeichen-Bypass der Allowlist (Basisbefehl allowed, ganzer String
    trotzdem per shell=True ausgefuehrt). Alle muessen jetzt scheitern."""

    @pytest.mark.parametrize("cmd", [
        "echo hi && curl http://example.invalid",
        "echo hi | curl http://example.invalid",
        "echo hi; rm -rf /tmp/x",
        "git status; curl http://example.invalid",
        "echo hi & curl http://example.invalid",
        "echo $(curl http://example.invalid)",
        "echo `curl http://example.invalid`",
        "echo hi > /tmp/pwned",
        "echo hi < /etc/passwd",
    ])
    def test_rejected(self, cmd):
        with pytest.raises(CommandRejected):
            resolve_executable(cmd, ALLOWED)

    def test_disallowed_base_rejected(self):
        with pytest.raises(CommandRejected):
            resolve_executable("curl http://example.invalid", ALLOWED)

    def test_empty_rejected(self):
        with pytest.raises(CommandRejected):
            resolve_executable("", ALLOWED)

    def test_unbalanced_quotes_rejected(self):
        with pytest.raises(CommandRejected):
            resolve_executable("echo 'unmatched", ALLOWED)


class TestQuotingBypassClosed:
    """Der urspruengliche Parser-Bug: _extract_base_command() splittete
    naiv auf Leerzeichen, BEVOR Anfuehrungszeichen entfernt wurden - ein
    zitierter Pfad mit Leerzeichen ergab einen falschen Basisbefehl."""

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-Pfad")
    def test_quoted_path_with_spaces_resolves_correctly(self):
        argv = resolve_executable('"C:\\Program Files\\Python312\\python.exe" -c "1"', ALLOWED)
        assert base_command_name(argv[0].split("\\")[-1]) == "python" or "python" in argv[0].lower()

    @pytest.mark.skipif(sys.platform != "win32",
                        reason="unter POSIX ist py\"thon\" wie in einer Shell schlicht python")
    def test_py_thon_quoting_trick_not_recognized_as_python(self):
        # py"thon" -> Basisname enthaelt ein eingebettetes Anfuehrungszeichen,
        # ist also NICHT "python" - muss an der Allowlist scheitern, nicht
        # unbeabsichtigt durchrutschen.
        with pytest.raises(CommandRejected):
            resolve_executable('py"thon" evil', ALLOWED)


class TestQuotedMetacharsAreSafe:
    """Ein voll zitiertes Token darf Metazeichen enthalten (z. B. eine
    `-c`-Codezeile mit Semikolon) - shell=False fuehrt es als EIN
    woertliches argv-Element aus, keine Shell interpretiert den Inhalt."""

    def test_quoted_semicolon_allowed(self):
        argv = resolve_executable('python -c "import time; pass"', ALLOWED)
        assert argv[1:] == ["-c", "import time; pass"]

    def test_dequote_strips_matching_quotes_only(self):
        assert dequote('"a b"') == "a b"
        assert dequote("'a b'") == "a b"
        assert dequote("noquotes") == "noquotes"
        assert dequote('"mismatched\'') == "\"mismatched'"


class TestRunSafeNeverUsesShellTrue:
    def test_run_safe_executes_with_shell_false(self, monkeypatch):
        captured = {}

        def fake_run(argv, shell, **kwargs):
            captured["argv"] = argv
            captured["shell"] = shell
            return subprocess.CompletedProcess(argv, 0, stdout="ok", stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)
        result = run_safe("echo hallo", ALLOWED, capture_output=True, text=True)
        assert captured["shell"] is False
        assert result.stdout == "ok"

    def test_run_safe_ignores_caller_supplied_shell_kwarg(self, monkeypatch):
        captured = {}

        def fake_run(argv, shell, **kwargs):
            captured["shell"] = shell
            return subprocess.CompletedProcess(argv, 0)

        monkeypatch.setattr(subprocess, "run", fake_run)
        run_safe("echo hallo", ALLOWED, shell=True)  # darf NICHT durchdringen
        assert captured["shell"] is False


class TestNoShellTrueLeftInModule:
    def test_no_subprocess_call_passes_shell_true(self):
        """AST-Check statt Textsuche, damit die Erklaerung des alten Bugs
        im Docstring (die woertlich "shell=True" enthaelt) keinen
        Falsch-Alarm ausloest."""
        import ast
        import hub.safe_exec as mod
        tree = ast.parse(open(mod.__file__, encoding="utf-8").read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                for kw in node.keywords:
                    if kw.arg == "shell":
                        assert isinstance(kw.value, ast.Constant) and kw.value.value is False, (
                            f"subprocess-Aufruf mit shell != False gefunden: Zeile {node.lineno}"
                        )


def test_demo_self_check_runs():
    from hub import safe_exec
    safe_exec.demo()  # wirft bei Fehlschlag


@pytest.mark.skipif(sys.platform != "win32", reason="Batch-Sperre betrifft nur Windows")
def test_batch_script_rejected_on_windows(tmp_path, monkeypatch):
    (tmp_path / "fakebatch.cmd").write_text("@echo off\n", encoding="utf-8")
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(CommandRejected):
        resolve_executable('fakebatch "x"', frozenset({"fakebatch"}))
