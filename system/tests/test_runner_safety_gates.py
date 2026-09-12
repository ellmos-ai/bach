#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sicherheitsgates der Chat-Runner (T-20260906-446028036).

Die drei Runner starten dasselbe Modell mit denselben Werkzeugen, aber mit
verschiedenem Auftrag:

- ``worker``      arbeitet Tasks ab, wenn der Chat ruht -> baut
- ``task_runner`` arbeitet Pakete ab                    -> baut
- ``plan_runner`` zerlegt einen Auftrag in Pakete       -> baut NICHT

Genau das muss auch technisch gelten. `TOOLS_FULL` unterscheidet sich von
`TOOLS_SAFE` um exakt zwei Werkzeuge: `execute_command` (beliebige Shell) und
`write_file`. Ein Planer, der nichts bauen soll, braucht beide nicht -- und
`task_manage`, mit dem er seine Pakete anlegt, steht ohnehin in `TOOLS_SAFE`.

Dazu der Deckel auf die Delegationstiefe: `delegate` startet einen fremden
Agenten, der seinerseits delegieren koennte. Ohne Deckel ist das eine Kette
ohne Ende; der Deckel existierte, war aber durch nichts gesichert.
"""

import types
from pathlib import Path

import pytest

from hub._services.chat import plan_runner, task_runner, worker
from hub._services.chat import chat_runtime
from hub._services.chat.chat_runtime import (
    TOOLS_FULL,
    TOOLS_PLAN,
    TOOLS_SAFE,
    exec_tool,
    is_safe_write_path,
    tools_for_mode,
)

#: Werkzeuge, die das Dateisystem veraendern. `write_file` und
#: `execute_command` pruefen zusaetzlich selbst auf den full-Modus; die
#: uebrigen fuenf laufen alle durch `is_safe_write_path`.
SCHREIBENDE_WERKZEUGE = frozenset({
    "edit_file", "move_file", "copy_file", "recycle", "create_directory",
    "write_file", "execute_command",
})


def _namen(tools):
    return {eintrag["function"]["name"] for eintrag in tools}


# --------------------------------------------------------------------------
# Was "safe" bedeutet
# --------------------------------------------------------------------------

def test_safe_kennt_task_manage_aber_weder_shell_noch_write_file():
    """Der Planer kommt mit `safe` aus -- das ist die Grundlage des Gates."""
    safe = _namen(TOOLS_SAFE)
    assert "task_manage" in safe
    assert "execute_command" not in safe
    assert "write_file" not in safe


def test_full_unterscheidet_sich_um_genau_diese_zwei_werkzeuge():
    assert _namen(TOOLS_FULL) - _namen(TOOLS_SAFE) == {"execute_command", "write_file"}


# --------------------------------------------------------------------------
# Was "plan" bedeutet (T-20260912-605163733)
#
# `safe` heisst "ohne beliebige Shell", nicht "ohne Schreiben": edit_file,
# move_file, copy_file, recycle und create_directory stehen darin. Fuer den
# interaktiven Chat ist das richtig so -- /mode full kuendigt ausdruecklich
# "Shell-Befehle und Dateischreiben" an, also ist safe der Modus, in dem man
# mit Dateien arbeitet, ohne die Shell zu oeffnen. Ein Planlauf braucht davon
# nichts. Deshalb eine dritte Menge statt einer Verengung von TOOLS_SAFE.
# --------------------------------------------------------------------------

def test_die_mengen_sind_geschachtelt():
    plan, safe, full = _namen(TOOLS_PLAN), _namen(TOOLS_SAFE), _namen(TOOLS_FULL)
    assert plan < safe < full


def test_plan_enthaelt_kein_schreibendes_werkzeug():
    assert _namen(TOOLS_PLAN) & SCHREIBENDE_WERKZEUGE == set()


def test_plan_kann_trotzdem_pakete_anlegen_und_nachsehen():
    """Ohne task_manage waere der Planer arbeitsunfaehig, ohne Lesen blind."""
    plan = _namen(TOOLS_PLAN)
    assert "task_manage" in plan
    assert {"read_file", "search_text", "list_directory"} <= plan


def test_der_modus_waehlt_die_menge():
    assert tools_for_mode("plan") is TOOLS_PLAN
    assert tools_for_mode("safe") is TOOLS_SAFE
    assert tools_for_mode("full") is TOOLS_FULL


def test_unbekannter_modus_faellt_auf_safe_zurueck_nicht_auf_full():
    """Ein Tippfehler darf niemals mehr Rechte geben als angefordert."""
    assert tools_for_mode("pln") is TOOLS_SAFE
    assert tools_for_mode("") is TOOLS_SAFE


# --------------------------------------------------------------------------
# Der Engpass: alle schreibenden Werkzeuge laufen durch is_safe_write_path
# --------------------------------------------------------------------------

def test_planmodus_verbietet_auch_pfade_die_safe_erlaubt():
    """Sonst waere 'plan' nur eine andere Werkzeugliste, kein Gate."""
    harmlos = str(Path.home() / "notizen.txt")
    assert is_safe_write_path(harmlos, "safe") is None
    assert is_safe_write_path(harmlos, "plan") is not None


def test_erfundener_schreibaufruf_im_planmodus_aendert_nichts(tmp_path):
    """Ein Modell kann ein Werkzeug aufrufen, das ihm nie angeboten wurde."""
    datei = tmp_path / "quelle.txt"
    datei.write_text("original", encoding="utf-8")

    antwort = exec_tool(
        "edit_file",
        {"path": str(datei), "old_text": "original", "new_text": "veraendert"},
        "plan",
    )

    assert datei.read_text(encoding="utf-8") == "original"
    assert "Planmodus" in antwort


# --------------------------------------------------------------------------
# Welcher Runner startet mit welchem Modus
# --------------------------------------------------------------------------

def test_planer_plant_standardmaessig_ohne_bauwerkzeug():
    """Der Planprompt verbietet Bauen -- der Modus muss es auch verbieten."""
    args = plan_runner._parser().parse_args(["--category", "demo", "--auftrag", "x"])
    assert args.mode == "plan"


def test_planer_laesst_sich_bewusst_auf_full_stellen():
    args = plan_runner._parser().parse_args(
        ["--category", "demo", "--auftrag", "x", "--mode", "full"]
    )
    assert args.mode == "full"


@pytest.mark.parametrize("modul,argv", [
    (worker, ["--category", "demo", "--workdir", "."]),
    (task_runner, ["--project", "demo", "--workdir", "."]),
])
def test_die_bauenden_runner_starten_bewusst_mit_full(modul, argv):
    """Kein Versehen, sondern Zweck: worker und task_runner sollen bauen."""
    assert modul._parser().parse_args(argv).mode == "full"


# --------------------------------------------------------------------------
# Deckel auf die Delegationstiefe
# --------------------------------------------------------------------------

def test_delegation_bricht_an_der_hoechsten_tiefe_ab(monkeypatch):
    """Bei erreichter Tiefe darf gar kein fremder Prozess mehr starten."""
    monkeypatch.setenv("BACH_DELEGATION_DEPTH", "2")

    def _darf_nicht_starten(*a, **k):
        raise AssertionError("delegate hat trotz erreichter Tiefe einen Prozess gestartet")

    monkeypatch.setattr(chat_runtime.subprocess, "run", _darf_nicht_starten)

    antwort = exec_tool("delegate", {"target": "codex", "prompt": "irgendwas"}, "safe")
    assert "Delegationstiefe" in antwort


def test_delegation_reicht_die_erhoehte_tiefe_an_das_kind_weiter(monkeypatch):
    """Ohne Weitergabe zaehlt jede Ebene wieder bei null -- Kette ohne Ende."""
    monkeypatch.setenv("BACH_DELEGATION_DEPTH", "0")
    gesehen = {}

    def _fake_run(cmd, **kwargs):
        gesehen["cmd"] = cmd
        gesehen["env"] = kwargs.get("env") or {}
        return types.SimpleNamespace(stdout="fertig", stderr="", returncode=0)

    monkeypatch.setattr(chat_runtime.subprocess, "run", _fake_run)

    antwort = exec_tool("delegate", {"target": "codex", "prompt": "irgendwas"}, "safe")
    assert "fertig" in antwort
    assert gesehen["cmd"][0] == "codex"
    assert gesehen["env"]["BACH_DELEGATION_DEPTH"] == "1"
