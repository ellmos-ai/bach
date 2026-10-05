"""Tests fuer system/gui/composition.rules.json (deklarativer GUI-Kompositionsvertrag).

QUEUED 387788448 - Task #1416 (P1-GUI-Kette).
Kette: #1410 GUI-Schale (QUEUED 652455601) -> #1414 Tray (QUEUED 112086128)
    -> #1416 composition.rules.json (QUEUED 387788448).

composition.rules.json beschreibt deklarativ Rollen-, Modi-, Server-Start- und
Verbindungsregeln der GUI-Komposition. Autoritative Quelle ist system/gui/shell.py
(die gleiche Kette steht im Modul-Docstring von gui/shell.py). Diese Tests stellen
sicher, dass jeder in der JSON-Datei deklarierte Wert exakt zu den Konstanten und
dem Verhalten aus gui/shell.py passt; eine Abweichung schlaegt fehl, bis shell.py
oder die Datei angepasst wird. Die Modi-Menge {"safe", "full"} wird zusaetzlich in
agents_heart.py authorize_role erzwungen (AssignmentDenied bei unbekanntem Modus).
"""

import json
import sys
from pathlib import Path

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from gui.shell import (  # noqa: E402
    DEFAULT_HOST,
    DEFAULT_MODE,
    DEFAULT_PORT,
    DEFAULT_ROLE_ID,
    HEALTH_PATH,
    _STATUS_COMPLETED,
    _STATUS_ERROR,
    _STATUS_RELEASED,
)

RULES_PATH = SYSTEM_ROOT / "gui" / "composition.rules.json"


def _load_rules():
    with RULES_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def test_rules_file_exists():
    assert RULES_PATH.is_file(), f"fehlt: {RULES_PATH}"


def test_meta_schema_and_version():
    meta = _load_rules()["_meta"]
    assert meta["schema"] == "bach.gui.composition.rules"
    assert meta["version"] == 1


def test_meta_source_documents_queued_id():
    meta = _load_rules()["_meta"]
    assert meta["source"] == "QUEUED 387788448"


def test_meta_chain_documents_full_gui_chain():
    chain = _load_rules()["_meta"]["chain"]
    queued = {entry["queued"] for entry in chain}
    assert queued == {
        "QUEUED 652455601",
        "QUEUED 112086128",
        "QUEUED 387788448",
    }


def test_meta_authoritative_code_points_to_shell():
    meta = _load_rules()["_meta"]
    assert meta["authoritative_code"] == "system/gui/shell.py"


def test_roles_match_shell_defaults():
    roles = _load_rules()["roles"]
    assert roles["default_role_id"] == DEFAULT_ROLE_ID == "expert_role"
    assert DEFAULT_ROLE_ID in roles["known_roles"]
    assert roles["fail_closed"] is True


def test_modes_match_shell_and_heart():
    modes = _load_rules()["modes"]
    assert modes["default_mode"] == DEFAULT_MODE == "safe"
    assert set(modes["allowed_modes"]) == {"safe", "full"}
    assert modes["validated_in_constructor"] is False
    assert "authorize_role" in modes["enforced_by"]
    assert "AssignmentDenied" in modes["enforced_by"]


def test_connection_defaults_match_shell():
    connection = _load_rules()["connection"]
    assert connection["default_host"] == DEFAULT_HOST == "127.0.0.1"
    assert connection["default_port"] == DEFAULT_PORT == 8000
    assert connection["base_url_format"] == "http://{host}:{port}"
    assert connection["connect_before_start"] is True


def test_health_check_matches_shell():
    health = _load_rules()["connection"]["health_check"]
    assert health["method"] == "GET"
    assert health["path"] == HEALTH_PATH == "/api/status"
    assert health["success_status_code"] == 200
    assert health["timeout_seconds"] == 2.0


def test_server_section_matches_shell():
    server = _load_rules()["server"]
    assert server["start_timeout_seconds"] == 30.0
    assert server["poll_interval_seconds"] == 0.5
    assert server["log_file"] == "gui_shell.log"
    assert server["default_log_dir"] == "system/data/logs"


def test_server_script_exists():
    rules = _load_rules()
    server_script = SYSTEM_ROOT / rules["server"]["server_script"]
    assert server_script.is_file(), f"fehlt: {server_script}"


def test_server_command_template_shape():
    template = _load_rules()["server"]["default_command_template"]
    assert template[0] == "<python>"
    assert template[1] == "gui/server.py"
    assert template[2:] == ["--host", "<host>", "--port", "<port>"]


def test_assignment_section_matches_shell():
    assignment = _load_rules()["assignment"]
    assert assignment["slot_id"] == "gui_shell"
    assert assignment["backend_id"] == "bach-gui"
    assert assignment["model_id"] == "web-gui"
    assert assignment["agent_instance_id_format"] == "gui-shell-{pid}"
    assert assignment["session_id"] == "uuid4"
    assert assignment["initiated_by"] == "user"


def test_outcomes_match_shell_status_constants():
    outcomes = _load_rules()["outcomes"]
    assert outcomes["gui_ready"]["status"] == _STATUS_COMPLETED == "completed"
    assert outcomes["gui_connect_failed"]["status"] == _STATUS_ERROR == "error"
    assert outcomes["window_open_failed"]["status"] == _STATUS_RELEASED == "released"
    assert outcomes["denied"]["status"] == "denied"


def test_outcomes_ok_flags():
    outcomes = _load_rules()["outcomes"]
    assert outcomes["gui_ready"]["ok"] is True
    assert outcomes["gui_connect_failed"]["ok"] is False
    assert outcomes["window_open_failed"]["ok"] is False
    assert outcomes["denied"]["ok"] is False


def test_cli_section_matches_shell_main():
    cli = _load_rules()["cli"]
    assert cli["prog"] == "gui-shell"
    assert set(cli["mode_choices"]) == {"safe", "full"}
    assert cli["start_timeout_default_seconds"] == 30.0
    assert cli["exit_codes"]["healthy"] == 0
    assert cli["exit_codes"]["down"] == 1


def test_env_section_matches_shell_from_env():
    env = _load_rules()["env"]
    assert set(env["variables"]) == {"BACH_GUI_URL", "BACH_GUI_HOST", "BACH_GUI_PORT"}
    precedence = env["precedence"]
    assert precedence[0] == "BACH_GUI_URL"
    assert "BACH_GUI_HOST/BACH_GUI_PORT" in precedence
    assert precedence[-1] == "defaults"