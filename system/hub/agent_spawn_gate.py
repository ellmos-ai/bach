"""Providerloser Unix-Starter mit erhaltenem Konsolen-Standardeingang."""

import os
import sys
import time
from pathlib import Path


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        return 86
    token, gate_path, *command = argv
    # Eindeutiger Marker statt stdin-PIPE: der spätere Runner behält seine
    # ursprüngliche interaktive Eingabe. Ohne Freigabe läuft nur dieser Starter.
    deadline = time.monotonic() + 10
    marker = Path(gate_path)
    while time.monotonic() < deadline:
        try:
            answer = marker.read_text(encoding="ascii")
        except FileNotFoundError:
            time.sleep(0.05)
            continue
        except OSError:
            return 86
        if answer != token:
            return 86
        break
    else:
        return 86
    os.execvp(command[0], command)
    return 87  # pragma: no cover - execvp ersetzt den Prozess


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
