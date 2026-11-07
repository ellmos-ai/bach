# -*- coding: utf-8 -*-
from pathlib import Path
import importlib.util
import sys
import pytest

src_file = Path(__file__).parent.parent / "src" / "tools.py"
spec = importlib.util.spec_from_file_location("standalone_tools_mod", src_file)
tools_mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = tools_mod
spec.loader.exec_module(tools_mod)
ToolRegistry = tools_mod.ToolRegistry
ToolMetadata = tools_mod.ToolMetadata


def test_tool_registration():
    reg = ToolRegistry()
    assert reg.register_tool(
        name="calc_sum",
        description="Add two numbers",
        parameters={"a": "int", "b": "int"},
        category="math",
        handler=lambda a, b: a + b
    ) is True

    t = reg.get_tool("calc_sum")
    assert t is not None
    assert t.category == "math"


def test_tool_invocation_success():
    reg = ToolRegistry()
    reg.register_tool(
        name="greet",
        handler=lambda name="World": f"Hello {name}!",
    )
    ok, res = reg.invoke_tool("greet", {"name": "Lukas"})
    assert ok is True
    assert res == "Hello Lukas!"


def test_tool_invocation_permission_check():
    reg = ToolRegistry()
    reg.register_tool(
        name="reboot",
        permissions_required=["system_admin"],
        handler=lambda: "Rebooting..."
    )

    # Ohne Berechtigung verweigert
    ok, err = reg.invoke_tool("reboot", caller_permissions=[])
    assert ok is False
    assert "Fehlende Berechtigung" in err

    # Mit Berechtigung erlaubt
    ok, res = reg.invoke_tool("reboot", caller_permissions=["system_admin"])
    assert ok is True
    assert res == "Rebooting..."

    # Audit Log enthält beide Aufrufe
    log = reg.get_audit_log()
    assert len(log) == 2
    assert log[0]["success"] is True
    assert log[1]["success"] is False
