"""Providerloser Unix-Starter: Runner erst nach einer einmaligen Freigabe ausführen."""

import os
import sys


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        return 86
    token, *command = argv
    # Ein EOF/Fehler vor der Freigabe darf den Runner niemals starten.
    try:
        answer = sys.stdin.buffer.readline(128)
    except OSError:
        return 86
    if answer != (token + "\n").encode("ascii"):
        return 86
    os.execvp(command[0], command)
    return 87  # pragma: no cover - execvp ersetzt den Prozess


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
