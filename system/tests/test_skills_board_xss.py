# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Static Analysis Regressionstest: Stored-XSS-Schutz in skills-board.js (T-20260913-304635102)
==========================================================================================

Stellt sicher, dass:
  1. In den 8 GUI-Render-Funktionen von skills-board.js kein Template-Literal mehr
     innerhalb von onclick-/on*-Attributen interpoliert wird (onclick="...${...}...").
  2. In der gesamten skills-board.js-Datei kein onclick="[^"]*\\$\\{ vorkommt.
  3. Die Hilfsfunktion escapeAttr(text) implementiert und exportiert ist.
  4. Datenvariablen (wie displayName, item.name, item.description) mittels
     escapeHtml bzw. escapeAttr geschützt werden.
  5. Die tote Duplikat-Datei agents-board.js geloescht bleibt.
"""

from pathlib import Path
import re
import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
SKILLS_BOARD_JS = SYSTEM_ROOT / "gui" / "static" / "js" / "skills-board.js"
AGENTS_BOARD_JS = SYSTEM_ROOT / "gui" / "static" / "js" / "agents-board.js"

TARGET_FUNCTIONS = [
    "renderTreeItem",
    "renderNestedAssignments",
    "renderDetailView",
    "renderAgentAssignments",
    "renderItemUsage",
    "renderTaskForm",
    "renderExpertSkillsSelector",
    "renderFlowNodes",
]


@pytest.fixture
def js_content() -> str:
    assert SKILLS_BOARD_JS.exists(), f"Datei {SKILLS_BOARD_JS} nicht gefunden"
    return SKILLS_BOARD_JS.read_text(encoding="utf-8")


def extract_function_body(content: str, func_name: str) -> str:
    """Extrahiert den Funktionskoerper einer JS-Funktion anhand geschweifter Klammern."""
    pattern = rf"function\s+{func_name}\s*\([^)]*\)\s*\{{"
    match = re.search(pattern, content)
    assert match is not None, f"Funktion {func_name} nicht in skills-board.js gefunden"

    start_pos = match.end() - 1
    depth = 0
    end_pos = start_pos

    for i in range(start_pos, len(content)):
        char = content[i]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                end_pos = i + 1
                break

    return content[start_pos:end_pos]


def test_skills_board_file_exists():
    """skills-board.js muss existieren."""
    assert SKILLS_BOARD_JS.is_file()


def test_agents_board_duplicate_removed():
    """Die tote Duplikat-Datei agents-board.js darf nicht mehr existieren."""
    assert not AGENTS_BOARD_JS.exists()


def test_escape_attr_function_defined(js_content: str):
    """escapeAttr muss definiert und an window exportiert sein."""
    assert "function escapeAttr(" in js_content
    assert "window.escapeAttr = escapeAttr" in js_content
    assert "&quot;" in js_content
    assert "&#x27;" in js_content


def test_escape_html_function_defined(js_content: str):
    """escapeHtml muss definiert und an window exportiert sein."""
    assert "function escapeHtml(" in js_content
    assert "window.escapeHtml = escapeHtml" in js_content


@pytest.mark.parametrize("func_name", TARGET_FUNCTIONS)
def test_no_interpolated_onclick_in_target_functions(js_content: str, func_name: str):
    """In keiner der 8 Zielfunktionen darf ein interpoliertes onclick=${...} vorkommen."""
    body = extract_function_body(js_content, func_name)
    matches = re.findall(r'onclick="[^"]*\$\{', body)
    assert not matches, (
        f"In Funktion '{func_name}' wurde ein interpoliertes onclick-Attribut gefunden: {matches}"
    )


@pytest.mark.parametrize("func_name", TARGET_FUNCTIONS)
def test_no_interpolated_event_handler_in_target_functions(js_content: str, func_name: str):
    """In keiner der 8 Zielfunktionen darf ein beliebiges interpoliertes on*=${...} vorkommen."""
    body = extract_function_body(js_content, func_name)
    matches = re.findall(r'\bon[a-z]+="[^"]*\$\{', body)
    assert not matches, (
        f"In Funktion '{func_name}' wurde ein interpolierter Event-Handler gefunden: {matches}"
    )


def test_no_interpolated_onclick_in_entire_file(js_content: str):
    """Auch dateiweit darf kein onclick=\"[^\"]*\\${ vorkommen."""
    matches = re.findall(r'onclick="[^"]*\$\{', js_content)
    assert not matches, (
        f"In skills-board.js wurden dateiweit interpolierte onclick-Attribute gefunden: {matches}"
    )


def test_data_escaping_in_render_tree_item(js_content: str):
    """renderTreeItem muss displayName und Attribute escapen."""
    body = extract_function_body(js_content, "renderTreeItem")
    assert "${escapeHtml(displayName)}" in body
    assert 'data-id="${escapeAttr(item.id)}"' in body
    assert 'data-type="${escapeAttr(type)}"' in body
    assert 'data-name="${escapeAttr(item.name' in body


def test_data_escaping_in_render_detail_view(js_content: str):
    """renderDetailView muss displayName, description und Attribute escapen."""
    body = extract_function_body(js_content, "renderDetailView")
    assert "${escapeHtml(displayName)}" in body
    assert "escapeHtml(item.description" in body
    assert 'data-id="${escapeAttr(item.id)}"' in body
    assert 'data-type="${escapeAttr(type)}"' in body


def test_delegated_listeners_defined(js_content: str):
    """Delegierte Event-Listener fuer Tree und Detailansicht muessen definiert sein."""
    assert "function setupTreeDelegation(" in js_content
    assert "function setupDetailDelegation(" in js_content
    assert "treeContainer.addEventListener('click'" in js_content
    assert "panel.addEventListener('click'" in js_content


def test_data_escaping_in_render_nested_assignments(js_content: str):
    """renderNestedAssignments muss item.name und Attribute escapen."""
    body = extract_function_body(js_content, "renderNestedAssignments")
    assert "${escapeHtml(item.name)}" in body
    assert 'data-id="${escapeAttr(id)}"' in body
    assert 'data-type="${escapeAttr(type)}"' in body


def test_data_escaping_in_render_agent_assignments(js_content: str):
    """renderAgentAssignments muss item.name und Attribute escapen."""
    body = extract_function_body(js_content, "renderAgentAssignments")
    assert "${escapeHtml(item.name)}" in body
    assert 'data-drop-zone="${escapeAttr(section.type)}"' in body
    assert 'data-agent="${escapeAttr(agentId)}"' in body
    assert 'data-agent-id="${escapeAttr(agentId)}"' in body


def test_data_escaping_in_render_item_usage(js_content: str):
    """renderItemUsage muss agent.name und agent.id escapen."""
    body = extract_function_body(js_content, "renderItemUsage")
    assert "${escapeHtml(agent.name)}" in body
    assert 'data-id="${escapeAttr(agent.id)}"' in body


def test_data_escaping_in_render_task_form(js_content: str):
    """renderTaskForm muss agentName und agentId in data-Attributen absichern."""
    body = extract_function_body(js_content, "renderTaskForm")
    assert 'data-agent-name="${escapeAttr(agentName)}"' in body
    assert 'data-agent-id="${escapeAttr(agentId)}"' in body


def test_data_escaping_in_edit_item(js_content: str):
    """editItem muss Attribute mit escapeAttr und Textarea mit escapeHtml absichern."""
    body = extract_function_body(js_content, "editItem")
    assert 'value="${escapeAttr(item.name' in body
    assert "escapeHtml(item.description" in body
    assert 'data-id="${escapeAttr(id)}"' in body


def test_data_escaping_in_render_expert_skills_selector(js_content: str):
    """renderExpertSkillsSelector muss IDs und Namen escapen."""
    body = extract_function_body(js_content, "renderExpertSkillsSelector")
    assert 'value="${escapeAttr(skill.id)}"' in body
    assert 'data-expert-id="${escapeAttr(expertId)}"' in body
    assert 'data-skill-id="${escapeAttr(skill.id)}"' in body
    assert "${escapeHtml(skill.name)}" in body


def test_data_escaping_in_render_flow_nodes(js_content: str):
    """renderFlowNodes muss node.type und node.name escapen."""
    body = extract_function_body(js_content, "renderFlowNodes")
    assert 'bg-${escapeAttr(node.type)}' in body
    assert "${escapeHtml(node.name)}" in body


def test_node_check_passes():
    """node -c system/gui/static/js/skills-board.js muss ohne Fehler (Exit 0) durchlaufen."""
    import subprocess
    result = subprocess.run(
        ["node", "-c", str(SKILLS_BOARD_JS)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Node Syntaxfehler:\n{result.stderr}"
