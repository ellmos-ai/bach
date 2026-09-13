#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Zurechnung des ~/.bach-Waechters (T-20260912-679116669).

Der Waechter `_guard_production_bach_dir` in conftest.py soll beantworten:
"Hat DIESER Testlauf in das produktive ~/.bach geschrieben?" Gemessen hat er
bisher etwas anderes: "Hat sich in ~/.bach irgendetwas geaendert?" Auf einem
Rechner mit laufendem BACH-Dienst (chat_tray.py schreibt dort sein Log) war
damit jeder Volllauf rot, ohne dass die Suite etwas angefasst hatte
(gemessen 2026-09-12: chat_tray.log, PID 10204, gestartet 7 h vor dem Lauf).

Diese Tests fixieren die Zurechnung:
- eigener Schreibzugriff  -> rot, auch wenn nebenher ein Dienst laeuft
- nur fremder Dienst      -> gruen, mit benannter Warnung
- Aenderung ohne Dienst   -> rot (fail-closed, deckt Subprozesse ab)
"""

import os
from pathlib import Path

from tests.conftest import (
    _classify_home_writes,
    _note_write_if_under,
    _opens_for_write,
)


# --------------------------------------------------------------------------
# Zurechnung: wer hat geschrieben?
# --------------------------------------------------------------------------

def test_eigener_schreibzugriff_ist_rot_auch_wenn_ein_dienst_laeuft():
    """Der Fehlalarm-Fix darf echte Treffer nicht verschlucken."""
    fail, message = _classify_home_writes(
        own_writes={"bach_secrets.json"},
        changed=["bach_secrets.json", "chat_tray.log"],
        foreign=[(10204, "chat_tray.py")],
    )
    assert fail is True
    assert "bach_secrets.json" in message


def test_nur_fremder_dienst_ist_gruen_und_nennt_den_verursacher():
    """Der gemessene Fehlalarm-Fall vom 2026-09-12."""
    fail, message = _classify_home_writes(
        own_writes=set(),
        changed=["chat_tray.log"],
        foreign=[(10204, "chat_tray.py")],
    )
    assert fail is False
    assert message is not None
    assert "10204" in message and "chat_tray" in message


def test_aenderung_ohne_fremden_dienst_bleibt_rot():
    """Fail-closed: lief kein Dienst, geht die Aenderung auf den Lauf."""
    fail, message = _classify_home_writes(
        own_writes=set(), changed=["chat_tray.log"], foreign=[]
    )
    assert fail is True
    assert "chat_tray.log" in message


def test_ohne_befund_bleibt_alles_still():
    fail, message = _classify_home_writes(own_writes=set(), changed=[], foreign=[])
    assert fail is False
    assert message is None


# --------------------------------------------------------------------------
# Aufzeichnung: welcher Pfad zaehlt als Schreibzugriff unter ~/.bach?
# --------------------------------------------------------------------------

def test_pfad_unter_der_wurzel_wird_relativ_aufgezeichnet(tmp_path):
    sink = set()
    _note_write_if_under(tmp_path / "backups" / "x.db", tmp_path, sink)
    assert sink == {"backups/x.db"}


def test_pfad_ausserhalb_der_wurzel_wird_ignoriert(tmp_path):
    sink = set()
    _note_write_if_under(tmp_path.parent / "woanders.txt", tmp_path, sink)
    assert sink == set()


def test_praefix_allein_reicht_nicht(tmp_path):
    """~/.bach_backup ist NICHT ~/.bach -- sonst faengt der Waechter Fremdes."""
    sink = set()
    _note_write_if_under(str(tmp_path) + "_backup/x.txt", tmp_path, sink)
    assert sink == set()


def test_schreibweise_egal_auf_windows(tmp_path):
    """Windows-Pfade sind case-insensitiv und kommen mit / wie mit \\."""
    if os.name != "nt":
        return
    sink = set()
    _note_write_if_under(str(tmp_path).upper().replace("\\", "/") + "/plans/p.json", tmp_path, sink)
    assert sink == {"plans/p.json"}


def test_unbrauchbare_argumente_stuerzen_nicht_ab(tmp_path):
    """Ein Audit-Hook laeuft bei JEDEM open() -- er darf nie werfen."""
    sink = set()
    for kaputt in (None, 3, object(), b"\xff\xfe"):
        _note_write_if_under(kaputt, tmp_path, sink)
    assert sink == set()


def test_nur_schreibende_opens_zaehlen():
    """Lesen ist erlaubt -- nur Schreiben soll der Waechter sehen."""
    assert _opens_for_write("w", None) is True
    assert _opens_for_write("a", None) is True
    assert _opens_for_write("r+", None) is True
    assert _opens_for_write("rb", None) is False
    assert _opens_for_write("r", None) is False
    # os.open meldet keinen Modus, sondern Flags:
    assert _opens_for_write(None, os.O_RDONLY) is False
    assert _opens_for_write(None, os.O_WRONLY | os.O_CREAT) is True
    assert _opens_for_write(None, None) is False


# --------------------------------------------------------------------------
# End-to-End: der scharf geschaltete Waechter in einem echten pytest-Lauf
# --------------------------------------------------------------------------

def test_waechter_wird_rot_wenn_ein_test_wirklich_nach_home_bach_schreibt(tmp_path):
    """Der Fehlalarm-Fix darf den Waechter nicht entschaerfen.

    Laeuft als Subprozess mit umgelenktem HOME/USERPROFILE -- das echte
    ~/.bach wird dabei nicht angefasst. Der Kindlauf schreibt bewusst nach
    `Path.home()/".bach"` und MUSS daran scheitern.
    """
    import subprocess
    import sys as _sys

    heim = tmp_path / "heim"
    (heim / ".bach").mkdir(parents=True)
    (heim / ".bach" / "vorher.txt").write_text("alt", encoding="utf-8")

    testdatei = tmp_path / "test_schreibt_nach_home.py"
    testdatei.write_text(
        "from pathlib import Path\n"
        "\n"
        "def test_schreibt():\n"
        "    ziel = Path.home() / '.bach' / 'probe.txt'\n"
        "    ziel.write_text('x', encoding='utf-8')\n",
        encoding="utf-8",
    )

    repo = Path(__file__).resolve().parents[2]
    umgebung = dict(os.environ)
    umgebung.pop("BACH_ALLOW_HOME_WRITES", None)
    umgebung.update(
        HOME=str(heim),
        USERPROFILE=str(heim),
        PYTHONPATH=str(repo / "system"),
        PYTHONIOENCODING="utf-8",
    )

    lauf = subprocess.run(
        [_sys.executable, "-m", "pytest", str(testdatei),
         "-p", "tests.conftest", "-p", "no:cacheprovider", "-q"],
        cwd=str(tmp_path), env=umgebung, capture_output=True, text=True, timeout=180,
    )

    assert lauf.returncode != 0, f"Waechter blieb still:\n{lauf.stdout}\n{lauf.stderr}"
    assert "probe.txt" in lauf.stdout, lauf.stdout
    # ... und das echte Heimverzeichnis blieb aussen vor:
    assert (heim / ".bach" / "probe.txt").exists()


def test_waechter_bleibt_gruen_wenn_nur_ein_fremder_dienst_schreibt(tmp_path):
    """Der gemessene Fehlalarm-Fall, live nachgestellt.

    Ein fremder Prozess (hier eine Kopie namens chat_tray.py) schreibt
    waehrend des Laufs nach `~/.bach`. Der Kindlauf selbst fasst nichts an
    und muss deshalb gruen bleiben -- mit benannter Warnung statt Fehler.
    """
    import subprocess
    import sys as _sys
    import time

    heim = tmp_path / "heim"
    (heim / ".bach").mkdir(parents=True)
    (heim / ".bach" / "chat_tray.log").write_text("start\n", encoding="utf-8")

    # Fremder Schreiber: kein Kind des Testlaufs, Name wie ein BACH-Dienst.
    schreiber_py = tmp_path / "chat_tray.py"
    schreiber_py.write_text(
        "import sys, time\n"
        "ziel = sys.argv[1]\n"
        "ende = time.time() + 60\n"
        "while time.time() < ende:\n"
        "    open(ziel, 'a', encoding='utf-8').write('tick\\n')\n"
        "    time.sleep(0.1)\n",
        encoding="utf-8",
    )

    testdatei = tmp_path / "test_faesst_nichts_an.py"
    testdatei.write_text("def test_still():\n    assert True\n", encoding="utf-8")

    repo = Path(__file__).resolve().parents[2]
    umgebung = dict(os.environ)
    umgebung.pop("BACH_ALLOW_HOME_WRITES", None)
    umgebung.update(
        HOME=str(heim),
        USERPROFILE=str(heim),
        PYTHONPATH=str(repo / "system"),
        PYTHONIOENCODING="utf-8",
    )

    schreiber = subprocess.Popen(
        [_sys.executable, str(schreiber_py), str(heim / ".bach" / "chat_tray.log")],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(0.5)  # sicherstellen, dass er VOR dem Lauf schon laeuft
        lauf = subprocess.run(
            [_sys.executable, "-m", "pytest", str(testdatei),
             "-p", "tests.conftest", "-p", "no:cacheprovider", "-q"],
            cwd=str(tmp_path), env=umgebung, capture_output=True, text=True, timeout=180,
        )
    finally:
        schreiber.kill()
        schreiber.wait(timeout=30)

    ausgabe = lauf.stdout + lauf.stderr
    assert lauf.returncode == 0, f"Fehlalarm ist zurueck:\n{ausgabe}"
    assert "Nicht der Suite zugerechnet" in ausgabe, ausgabe
    assert "chat_tray" in ausgabe, ausgabe
