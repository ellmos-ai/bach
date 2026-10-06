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


@pytest.mark.parametrize("base", ["grep", "egrep", "fgrep", "rg",
                                  "env", "docker", "pip", "pip3", "npm", "npx",
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


@pytest.mark.parametrize("cmd", [
    "grep token datei.txt",
    "grep -r token .",
    "grep -rn token .",
    "grep -R token .",
    "grep --recursive token .",
    "grep --directories=recurse token .",
    "grep -d recurse token .",
])
def test_grep_in_any_form_blocked(cmd):
    assert _blocked(cmd)


@pytest.mark.parametrize("action", ["-exec", "-execdir", "-ok", "-okdir",
                                    "-delete", "-fprint", "-fprint0", "-fprintf", "-fls"])
def test_find_actions_rejected(action):
    assert check_safe_shell_args(["find", ".", "-name", "x", action, "y"])
    assert _blocked(f"find . -name x {action} y")


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".ssh").mkdir(parents=True)
    (home / ".config" / "bach").mkdir(parents=True)
    (home / ".bach").mkdir()
    (home / "projekt").mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.delenv("BACH_SECRETS_FILE", raising=False)
    return home


@pytest.mark.parametrize("args", [["-R", "{h}"], ["-laR", "{h}"], ["--recursive", "{h}"],
                                  ["-R", "{h}/.."]])
def test_recursive_ls_on_secret_ancestor_rejected(fake_home, args):
    tokens = ["ls", *(a.format(h=fake_home) for a in args)]
    assert check_safe_shell_args(tokens)


def test_du_on_secret_ancestor_rejected(fake_home):
    assert check_safe_shell_args(["du", "-s", str(fake_home)])


def test_find_on_secret_ancestor_rejected(fake_home):
    assert check_safe_shell_args(["find", str(fake_home), "-name", "*.pub"])


def test_find_on_clean_dir_allowed(fake_home):
    assert check_safe_shell_args(["find", str(fake_home / "projekt"), "-name", "*.py"]) is None


def test_recursive_on_dir_with_credentials_child_rejected(tmp_path, fake_home):
    (tmp_path / "dev" / "CREDENTIALS").mkdir(parents=True)
    assert check_safe_shell_args(["ls", "-R", str(tmp_path / "dev")])


def test_recursive_on_clean_dir_allowed(fake_home):
    assert check_safe_shell_args(["ls", "-R", str(fake_home / "projekt")]) is None
    assert check_safe_shell_args(["du", "-sh", str(fake_home / "projekt")]) is None


def test_non_recursive_ls_on_home_allowed(fake_home):
    assert check_safe_shell_args(["ls", "-la", str(fake_home)]) is None


@pytest.mark.parametrize("rel", [
    ".config/bach/telegram_chat.json",
    ".config/bach/irgendwas.json",
    ".config/BACH/Telegram_Chat.JSON",
    ".bach/bach_secrets.json",
    ".bach/api_token.txt",
    ".bach/Client_Secret.json",
    "projekt/.env",
    "projekt/.env.local",
])
def test_bach_secret_files_rejected(fake_home, rel):
    assert check_safe_shell_args(["cat", str(fake_home / rel)])
    assert check_safe_shell_args(["head", f"--file={fake_home / rel}"])


def test_bach_secrets_file_env_override_rejected(fake_home, tmp_path, monkeypatch):
    target = tmp_path / "woanders" / "geheim.json"
    monkeypatch.setenv("BACH_SECRETS_FILE", str(target))
    assert check_safe_shell_args(["cat", str(target)])


def test_bach_db_readable(fake_home):
    assert check_safe_shell_args(["stat", str(fake_home / ".bach" / "bach.db")]) is None


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
    ["diff"],
    ["diff", "--stat"],
    ["diff", "--no-index", "a", "b"],
    ["diff", "HEAD~1", "--", "/tmp/x"],
    ["branch", "neu"],
    ["branch", "-D", "main"],
    [],
])
def test_git_rejected(args):
    assert check_safe_shell_args(["git", *args])


@pytest.mark.parametrize("args", [
    ["status"], ["log", "-n", "5"], ["log", "-p", "-n", "1"], ["show", "HEAD"],
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
    ["cat", "/home/x/CREDENTIALS/key.txt"],
    ["tail", "--file=/home/x/.ssh/id_ed25519"],
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
    ["date", "+%Y"], ["hostname"], ["wc", "-l", "x.txt"], ["ls", "-la"],
])
def test_read_only_allowed(tokens):
    assert check_safe_shell_args(tokens) is None


def test_file_tools_block_bot_config(fake_home):
    cfg = fake_home / ".config" / "bach" / "telegram_chat.json"
    cfg.write_text("{}", encoding="utf-8")
    assert "BLOCKIERT" in exec_tool("read_file", {"path": str(cfg)}, "safe")
    assert "BLOCKIERT" in exec_tool("list_directory", {"path": str(cfg.parent)}, "safe")


@pytest.mark.parametrize("opts", [["-L"], ["-H"], ["-P"], ["-O3"], ["-D", "stat"], ["-L", "-O2"]])
def test_find_leading_options_do_not_hide_start_path(fake_home, opts):
    assert check_safe_shell_args(["find", *opts, str(fake_home), "-name", "*.pub"])
