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

import pytest

from hub._services.chat import plan_runner, task_runner, worker
from hub._services.chat import chat_runtime
from hub._services.chat.chat_runtime import TOOLS_FULL, TOOLS_SAFE, exec_tool


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
# Welcher Runner startet mit welchem Modus
# --------------------------------------------------------------------------

def test_planer_plant_standardmaessig_ohne_bauwerkzeug():
    """Der Planprompt verbietet Bauen -- der Modus muss es auch verbieten."""
    args = plan_runner._parser().parse_args(["--category", "demo", "--auftrag", "x"])
    assert args.mode == "safe"


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
