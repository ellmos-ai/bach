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
safe_exec.py - Gemeinsamer, fail-closed Shell-Ausfuehrungs-Helfer
==================================================================
Ersetzt das Muster "Basisbefehl gegen eine Allowlist pruefen, dann den
KOMPLETTEN Original-String trotzdem mit subprocess(shell=True) ausfuehren".
Dieses Muster prueft nur das erste Token, interpretiert die Shell aber den
ganzen String - Metazeichen wie && | ; $() erlauben dadurch beliebige
Befehlsverkettung trotz Allowlist-Pruefung.

Kontrakt: tokenisieren (shlex, fail-closed) -> Metazeichen ablehnen
(Verteidigung in der Tiefe, auch wenn wir nie shell=True nutzen) ->
argv[0] per shutil.which() als Binaerdatei-NAME gegen die Allowlist
aufloesen -> mit shell=False ausfuehren. argv[0] ist danach immer der
von shutil.which() aufgeloeste, echte Pfad - nie der vom Aufrufer
gelieferte String (verhindert, dass ein passender Basisname eine
untergeschobene Datei an anderem Pfad startet).

Aufrufer:
- hub/sandbox.py (SandboxHandler._shell) - Allowlist
- hub/_services/chat/chat_runtime.py (safe_shell-Tool) - Allowlist
- hub/_services/chat/chat_runtime.py (execute_command-Tool, Full-Mode) -
  keine Allowlist, aber Verkettung/Metazeichen sind auch dort nie erlaubt
"""
import os
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import FrozenSet, List, Optional

# Zeichen, die eine Shell interpretieren wuerde: Verkettung (&&, ;),
# Pipes (|), Umleitung (< >), Substitution ($() ``), Hintergrund (&),
# Batch-Variablenexpansion (%VAR%), das Windows-Escape-Zeichen (^) und
# Zeilenumbruch (mehrere Befehle in einer "Zeile"). Fail-closed: im
# Zweifel ablehnen statt zu raten.
_SHELL_METACHARS = set('&|;<>`$(){}%^\n\r')


class CommandRejected(Exception):
    """Ein Befehl wurde fail-closed abgelehnt (Metazeichen, leer,
    nicht parsbar oder nicht in der Allowlist)."""


def has_shell_metacharacters(cmd: str) -> bool:
    return any(ch in _SHELL_METACHARS for ch in cmd)


def _is_quoted_literal(token: str) -> bool:
    """True, wenn `token` vollstaendig in EINEM Anfuehrungszeichen-Paar
    steht (z. B. '"import time; time.sleep(10)"'). shell=False fuehrt so
    ein Token IMMER als ein einziges, woertliches argv-Element aus - der
    Inhalt wird nie von einer Shell interpretiert, Metazeichen darin sind
    also unschaedlich (z. B. `python -c "import os; foo()"`)."""
    return len(token) >= 2 and (
        (token[0] == '"' and token[-1] == '"')
        or (token[0] == "'" and token[-1] == "'")
    )


def tokenize(cmd: str) -> List[str]:
    """Tokenisiert fail-closed. Wirft CommandRejected statt zu raten.

    Metazeichen werden PRO TOKEN geprueft, nicht am Rohstring: ein voll
    zitiertes Token (z. B. eine `-c`-Codezeile) darf Metazeichen enthalten,
    ein NICHT zitiertes Token mit `&&`/`|`/`;`/`$(`/`` ` ``/... wird
    abgelehnt - genau das ist der Verkettungs-/Substitutionsversuch."""
    cmd = cmd.strip()
    if not cmd:
        raise CommandRejected("Leerer Befehl")
    try:
        # Die Metazeichen-Pruefung laeuft IMMER auf posix=False-Tokens: nur
        # dort bleiben die Anfuehrungszeichen erhalten, und nur so ist ein
        # zitiertes Literal von einem nackten Metazeichen zu unterscheiden.
        # Ausgefuehrt wird unter Windows dasselbe (erhaelt Backslashes in
        # Pfaden), unter POSIX das posix=True-Ergebnis (Quotes entfernt, wie
        # es eine Shell auch taete).
        raw = shlex.split(cmd, posix=False)
        tokens = raw if os.name == "nt" else shlex.split(cmd, posix=True)
    except ValueError as e:
        raise CommandRejected(f"Befehl konnte nicht geparst werden: {e}") from e
    if not tokens:
        raise CommandRejected("Leerer Befehl nach dem Parsen")
    for tok in raw:
        if not _is_quoted_literal(tok) and has_shell_metacharacters(tok):
            raise CommandRejected(
                f"Befehl enthaelt ein nicht zitiertes Shell-Metazeichen ({tok!r}) "
                "- Verkettung/Substitution ist nie erlaubt"
            )
    return tokens


def dequote(token: str) -> str:
    """Entfernt EIN aeusseres, passendes Anfuehrungszeichen-Paar (falls
    vorhanden) fuer die tatsaechliche Ausfuehrung. shlex(posix=False)
    laesst Quotes im Token stehen (noetig, um Backslashes in Windows-Pfaden
    nicht zu verschlucken) - ohne diesen Schritt wuerde z. B. `-c "code"`
    die Anfuehrungszeichen woertlich an den Zielprozess weiterreichen."""
    if _is_quoted_literal(token):
        return token[1:-1]
    return token


def base_command_name(token0: str) -> str:
    """Name des Basisbefehls: ohne Pfad, ohne Extension, kleingeschrieben."""
    name = token0.strip('"').strip("'")
    return Path(name).stem.lower()


def resolve_executable(cmd: str, allowed: Optional[FrozenSet[str]] = None) -> List[str]:
    """Tokenisiert cmd; wenn `allowed` gesetzt ist, muss der Basisname
    darin vorkommen. argv[0] wird IMMER durch den von shutil.which()
    aufgeloesten, echten Pfad ersetzt (nicht den Original-String).
    Wirft CommandRejected bei jeder Ablehnung."""
    tokens = tokenize(cmd)
    base = base_command_name(tokens[0])
    if allowed is not None and base not in allowed:
        raise CommandRejected(
            f"'{base}' ist nicht in der Allowlist ({', '.join(sorted(allowed))})"
        )
    return [which_checked(base), *(dequote(t) for t in tokens[1:])]


def which_checked(base: str) -> str:
    """shutil.which() plus Batch-Sperre. Unter Windows startet CreateProcess
    eine .bat/.cmd implizit ueber cmd.exe - dessen Argument-Parsing folgt
    nicht list2cmdline(), zitierte Argumente koennten dort also doch wieder
    als Shell-Syntax gelesen werden. Deshalb fail-closed ablehnen."""
    resolved = shutil.which(base)
    if resolved is None:
        raise CommandRejected(f"'{base}' wurde nicht im PATH gefunden")
    if os.name == "nt" and Path(resolved).suffix.lower() in (".bat", ".cmd"):
        raise CommandRejected(
            f"'{base}' ist ein Batch-Skript ({Path(resolved).name}) - "
            "wird ohne Shell nicht sicher ausgefuehrt"
        )
    return resolved


def run_safe(cmd: str, allowed: Optional[FrozenSet[str]], **subprocess_kwargs) -> subprocess.CompletedProcess:
    """Fuehrt cmd aus - IMMER shell=False, argv[0] via shutil.which()
    aufgeloest. `allowed=None` bedeutet "jeder Basisbefehl ist erlaubt"
    (execute_command/Full-Mode); Metazeichen/Verkettung bleiben in jedem
    Fall verboten (tokenize() prueft das schon vor der Allowlist)."""
    argv = resolve_executable(cmd, allowed)
    subprocess_kwargs.pop("shell", None)  # nie durch den Aufrufer ueberschreibbar
    return subprocess.run(argv, shell=False, **subprocess_kwargs)


def demo() -> None:
    """Kleiner Selbsttest (siehe auch tests/test_safe_exec.py)."""
    allowed = frozenset({"echo", "python"})

    ok, argv = True, None
    try:
        argv = resolve_executable("echo hallo", allowed)
        assert argv[1:] == ["hallo"]
    except CommandRejected:
        ok = False
    assert ok, "legitimer Befehl wurde abgelehnt"

    for bad in ("echo hi && curl evil", "echo hi | curl evil", "echo hi; rm -rf /",
                "echo hi & curl evil", "echo $(curl evil)", "echo `curl evil`"):
        try:
            resolve_executable(bad, allowed)
            raise AssertionError(f"Umgehung nicht erkannt: {bad!r}")
        except CommandRejected:
            pass

    try:
        resolve_executable("curl evil.com", allowed)
        raise AssertionError("nicht erlaubter Basisbefehl wurde nicht abgelehnt")
    except CommandRejected:
        pass

    print("OK: safe_exec demo bestanden.")


if __name__ == "__main__":
    demo()
