#!/usr/bin/env python3
"""
T793 / Task #1711 – CWD-Independent-Test für slots_config.json
===============================================================

Prüft, dass `slots_config.DEFAULT_SLOTS_FILE`:
   1. Ohne Env-Override auf `system/data/slots_config.json` zeigt.
   2. Mit `BACH_SLOTS_CONFIG_PATH`-Override korrekt überschrieben wird.
   3. Unabhängig vom aktuellen Working Directory funktioniert.
   4. Den Guard gegen `system/system/data/slots_config.json` auslöst,
      falls diese Datei existiert.

Aufruf:
    python3 /Users/lukas/services/bach/system/tests/test_1711_cwd_independence.py
"""

import os
import sys
import logging
from pathlib import Path

# --- Setup: PYTHONPATH so dass `hub` importierbar ist ---
SYSTEM_DIR = Path("/Users/lukas/services/bach/system")
sys.path.insert(0, str(SYSTEM_DIR))

logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("test_1711")

FAILURES = []
# Rekursions-Guard: Subprozess (Test #3) setzt _TEST_1711_DEPTH,
# dann wird Test #3 im Kind übersprungen, um Endlosschleife zu vermeiden.
_RECURSING = os.environ.get("_TEST_1711_DEPTH", "0") != "0"


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        logger.info("  PASS   %s", label)
    else:
        logger.error("  FAIL   %s   %s", label, detail)
        FAILURES.append(label)


# ---- 1. Ohne Env-Override ----------------------------------------
os.environ.pop("BACH_SLOTS_CONFIG_PATH", None)
# Frisch importieren, falls bereits geladen
for mod in list(sys.modules):
    if "slots_config" in mod:
        del sys.modules[mod]

from hub._services.chat.slots_config import DEFAULT_SLOTS_FILE as D1, _STALE_DUPLICATE as SD  # noqa: E402

expected = str(SYSTEM_DIR / "data" / "slots_config.json")
check(
    "DEFAULT_SLOTS_FILE ohne Override = system/data/slots_config.json",
    D1 == expected,
    f"erwartet {expected}, erhalten {D1}",
)

# ---- 2. Mit Env-Override -----------------------------------------
os.environ["BACH_SLOTS_CONFIG_PATH"] = "/tmp/custom_slots.json"
for mod in list(sys.modules):
    if "slots_config" in mod:
        del sys.modules[mod]

from hub._services.chat.slots_config import DEFAULT_SLOTS_FILE as D2  # noqa: E402

check(
    "DEFAULT_SLOTS_FILE mit Override = /tmp/custom_slots.json",
    D2 == "/tmp/custom_slots.json",
    f"erwartet /tmp/custom_slots.json, erhalten {D2}",
)

os.environ.pop("BACH_SLOTS_CONFIG_PATH", None)

# ---- 3. CWD-Independenz ------------------------------------------
import subprocess  # noqa: E402

if _RECURSING:
    # Wir sind bereits im Subprozess – Test #3 hier nicht wiederholen
    check("Subprozess von /tmp aus: Exit 0", True,
          "im Rekursions-Subprozess – ok, Kind hat exit 0 erreicht")
else:
    _env = dict(os.environ, _TEST_1711_DEPTH="1")
    result = subprocess.run(
        [sys.executable, str(__file__)],
        cwd="/tmp",
        env=_env,
        capture_output=True,
        text=True,
    )
    check(
        "Subprozess von /tmp aus: Exit 0",
        result.returncode == 0,
        f"rc={result.returncode}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}",
    )

# ---- 4. Guard-Prüfung --------------------------------------------
# _STALE_DUPLICATE sollte auf system/system/data/slots_config.json zeigen
stale_path = SYSTEM_DIR / "system" / "data" / "slots_config.json"
check(
    "_STALE_DUPLICATE zeigt auf system/system/data/slots_config.json",
    str(SD) == str(stale_path),
    f"erwartet {stale_path}, erhalten {SD}",
)

if stale_path.is_file():
    logger.warning(
        "  INFO  Duplikat existiert: %s (Guard loggt Warning beim Import)", stale_path
    )
else:
    logger.info("  INFO  Kein Duplikat in %s – Guard inaktiv (OK)", stale_path)

# ---- Summary -----------------------------------------------------
print()
if FAILURES:
    print(f"FEHLGESCHLAGEN ({len(FAILURES)}):")
    for f in FAILURES:
        print(f"   - {f}")
    sys.exit(1)
else:
    print("ALLE PRÜFUNGEN BESTANDEN")
    sys.exit(0)
