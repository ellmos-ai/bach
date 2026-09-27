# -*- coding: utf-8 -*-
"""safe_shell, Argument-Ebene: Befehle aus SAFE_BASES duerfen auch ohne
Metazeichen nichts ausfuehren oder schreiben (find-Aktionen, git-Optionen,
entfernte Basisbefehle, Setzer bei date/hostname/sysctl, Secrets-Pfade)."""
import pytest

from hub._services.chat.chat_runtime import (
    SAFE_BASES,
    check_safe_shell_args,
    exec_tool,
)


def _blocked(cmd):
    result = exec_tool("safe_shell", {"command": cmd}, "safe")
    return "Sicherheit" in result or "Safe-Liste" in result


@pytest.mark.parametrize("base", ["env", "docker", "pip", "pip3", "npm", "npx",
                                  "curl", "wget", "brew", "bach", "xargs", "awk",
                                  "sed", "python", "python3", "bash", "sh",
                                  "powershell", "pwsh", "cmd"])
def test_program_starters_not_in_safe_bases(base):
    assert base not in SAFE_BASES


@pytest.mark.parametrize("cmd", [
    "env ls",
    "docker ps",
    "pip install demo",
    "curl -o out.txt http://example.invalid",
    "bach status",
])
def test_removed_bases_blocked(cmd):
    assert _blocked(cmd)


@pytest.mark.parametrize("action", ["-exec", "-execdir", "-ok", "-okdir",
                                    "-delete", "-fprint", "-fprint0", "-fprintf", "-fls"])
def test_find_actions_rejected(action):
    assert check_safe_shell_args(["find", ".", "-name", "x", action, "y"])
    assert _blocked(f"find . -name x {action} y")


@pytest.mark.parametrize("args", [
    ["-c", "core.pager=x", "log"],
    ["--config-env=core.pager=X", "log"],
    ["--exec-path=/tmp", "status"],
    ["-C", "/tmp", "status"],
    ["fetch", "--upload-pack=x"],
    ["push", "--receive-pack=x"],
    ["myalias"],
    ["checkout", "main"],
    ["config", "core.pager", "x"],
    ["log", "--output=out.txt"],
    ["diff", "--ext-diff"],
    ["branch", "neu"],
    ["branch", "-D", "main"],
    [],
])
def test_git_rejected(args):
    assert check_safe_shell_args(["git", *args])


@pytest.mark.parametrize("args", [
    ["status"], ["log", "-n", "5"], ["diff", "--stat"], ["show", "HEAD"],
    ["branch", "--list"], ["branch"], ["rev-parse", "HEAD"], ["ls-files"],
])
def test_git_read_allowed(args):
    assert check_safe_shell_args(["git", *args]) is None


@pytest.mark.parametrize("tokens", [
    ["ollama", "rm", "modell"],
    ["ollama", "pull", "modell"],
    ["ollama", "run", "modell"],
    ["sysctl", "-w", "kern.x=1"],
    ["sysctl", "kern.x=1"],
    ["date", "-s", "2020-01-01"],
    ["date", "--set=2020-01-01"],
    ["hostname", "neuer-name"],
    ["hostname", "-F", "datei"],
    ["cat", "~/.ssh/id_rsa"],
    ["grep", "-r", "token", "/home/x/CREDENTIALS"],
    ["grep", "--file=/home/x/.ssh/id_ed25519", "x"],
    ["cat", "/home/x/.config/bach/telegram_chat.json"],
    ["cat", "projekt/.env"],
    ["cat", "/home/x/.npmrc"],
    ["cat", "/home/x/.codex/auth.json"],
    ["git", "log", "ext::irgendwas"],
])
def test_other_writers_and_secrets_rejected(tokens):
    assert check_safe_shell_args(tokens)


@pytest.mark.parametrize("tokens", [
    ["ollama", "list"], ["ollama", "show", "llama3"], ["sysctl", "-n", "hw.ncpu"],
    ["date", "+%Y"], ["hostname"], ["find", ".", "-name", "*.py"], ["ls", "-la"],
])
def test_read_only_allowed(tokens):
    assert check_safe_shell_args(tokens) is None
