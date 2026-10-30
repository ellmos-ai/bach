"""Tests fuer benannte Tool-Profile (Settings/Slots) und read-evidence-Entkopplung.

Deckt ab:
- TOOL_PROFILES: Schluesselmenge und Hierarchie readonly subset files subset standard subset all
- resolve_tool_profile: unbekanntes Profil -> None, bound_worker-Abbau
- slots_config: tool_profile als editierbares Feld
"""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from hub._services.chat.bach_tools import (
    _READ_EVIDENCE_EXTRA_READ_TOOLS,
    _READ_EVIDENCE_READ_ONLY_TOOLS,
    _read_evidence_readonly_worker_enabled,
    TOOL_PROFILES,
    resolve_tool_profile,
)
from hub._services.chat.slots_config import CORE_EDITABLE_FIELDS
from hub._services.chat.worker_lease_binding import WorkerLeaseBinding


EXPECTED_PROFILE_KEYS = {"standard", "readonly", "files", "code_delivery", "all"}


def test_profile_keys():
    assert set(TOOL_PROFILES) == EXPECTED_PROFILE_KEYS


def test_readonly_profile_minimal_tools():
    names = resolve_tool_profile("readonly")
    assert names is not None
    for expected in (
        "read_file",
        "search_text",
        "task_manage",
        "list_directory",
        "get_datetime",
    ):
        assert expected in names, f"{expected} fehlt im readonly-Profil"


def test_profile_hierarchy_readonly_files_standard_all():
    readonly = set(resolve_tool_profile("readonly"))
    files = set(resolve_tool_profile("files"))
    standard = set(resolve_tool_profile("standard"))
    all_tools = set(resolve_tool_profile("all"))

    assert readonly < files, "readonly muss echte Teilmenge von files sein"
    assert files <= standard, "files muss Teilmenge von standard sein"
    assert standard <= all_tools, "standard muss Teilmenge von all sein"


def test_files_profile_adds_file_tools():
    readonly = set(resolve_tool_profile("readonly"))
    files = set(resolve_tool_profile("files"))
    added = {
        "file_info",
        "write_file",
        "edit_file",
        "create_directory",
        "move_file",
        "copy_file",
        "recycle",
    }
    assert added <= files
    assert not (added & readonly)


def test_code_delivery_profile_tools():
    readonly = set(resolve_tool_profile("readonly"))
    code = set(resolve_tool_profile("code_delivery"))
    added = {
        "file_info",
        "write_file",
        "edit_file",
        "execute_command",
        "start_task_worktree",
        "finish_task",
    }
    assert added <= code
    assert not (added & readonly)


def test_unknown_profile_returns_none():
    assert resolve_tool_profile("unbekannt") is None
    assert resolve_tool_profile("") is None
    assert resolve_tool_profile(None) is None


def test_bound_worker_strips_delegation_tools():
    full = set(resolve_tool_profile("all", bound_worker=True))
    assert "delegate" not in full
    assert "cleanup_task_worktree" not in full

    unbound = set(resolve_tool_profile("all", bound_worker=False))
    assert "delegate" in unbound
    assert "cleanup_task_worktree" in unbound


def test_profile_returns_copy():
    """Mutation des Ergebnisses darf das Profil nicht veraendern."""
    first = resolve_tool_profile("readonly")
    first.append("write_file")
    second = resolve_tool_profile("readonly")
    assert "write_file" not in second


def test_tool_profile_is_core_editable_field():
    assert "tool_profile" in CORE_EDITABLE_FIELDS


def _active_binding_stub():
    """Minimale aktive Bindung fuer read-evidence-Pruefungen (kein echter Ack)."""
    return WorkerLeaseBinding(
        None,
        {"task_version": 1},
        SimpleNamespace(
            lease_id="L",
            fence=1,
            assert_locally_valid=lambda now: None,
        ),
        generation=1,
        is_current=lambda: True,
        stop_event=threading.Event(),
    )


def test_read_evidence_extra_tools_include_file_mutation():
    """Datei-Mutationen sind read-evidence-zulaessig, Ausfuehrung/Delegation nicht."""
    grants = {
        "read_file",
        "write_file",
        "edit_file",
        "create_directory",
        "move_file",
        "copy_file",
        "recycle",
        "task_manage",
    }
    assert _read_evidence_readonly_worker_enabled(_active_binding_stub(), grants) is True

    allowed = _READ_EVIDENCE_READ_ONLY_TOOLS | _READ_EVIDENCE_EXTRA_READ_TOOLS
    assert "execute_command" not in allowed
    assert "delegate" not in allowed


def test_read_evidence_rejects_execution_tool():
    """Ein Ausfuehrungswerkzeug in den Grants hebt die Freigabe auf."""
    grants = {
        "read_file",
        "write_file",
        "task_manage",
        "execute_command",
    }
    assert _read_evidence_readonly_worker_enabled(_active_binding_stub(), grants) is False
