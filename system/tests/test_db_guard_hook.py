# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Regression tests for the BACH DB-Guard Claude Code hook."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
HOOK_SCRIPT = SYSTEM_ROOT / "hooks" / "bach-db-guard.sh"


def _run_hook(command: str) -> tuple[int, str, str]:
    """Run the hook with the given Bash command as JSON input."""
    payload = json.dumps({"tool_input": {"command": command}})
    result = subprocess.run(
        ["bash", str(HOOK_SCRIPT)],
        input=payload,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result.returncode, result.stdout, result.stderr


class TestDbGuardHookBlocksDirectDbAccess:
    def test_sqlite3_cli_insert_blocked(self):
        rc, out, err = _run_hook("sqlite3 data/bach.db 'INSERT INTO tasks(title) VALUES(\"x\");'")
        assert rc == 2
        assert "BLOCK" in err
        assert "bach_api" in err
        assert "bach task" in err

    def test_sqlite3_cli_update_blocked(self):
        rc, out, err = _run_hook("sqlite3 bach.db 'UPDATE tasks SET status=\"done\" WHERE id=1;'")
        assert rc == 2
        assert "BLOCK" in err
        assert "from bach_api import" in err

    def test_python_sqlite3_connect_blocked(self):
        rc, out, err = _run_hook(
            "python3 -c \"import sqlite3; c=sqlite3.connect('bach.db'); c.execute('DELETE FROM tasks'); c.commit()\""
        )
        assert rc == 2
        assert "BLOCK" in err
        assert "app().execute" in err

    def test_python_sqlite3_update_blocked(self):
        rc, out, err = _run_hook(
            "python3 -c \"import sqlite3; con=sqlite3.connect('/Users/lukas/.bach/bach.db'); "
            "con.execute('UPDATE memory_working SET content=\\\"x\\\"'); con.commit()\""
        )
        assert rc == 2
        assert "BLOCK" in err


class TestDbGuardHookAllowsBachApiAndCore:
    def test_bach_api_import_allowed(self):
        rc, out, err = _run_hook(
            "python3 -c \"from bach_api import task; task.add('demo')\""
        )
        assert rc == 0
        assert "BLOCK" not in err

    def test_bach_cli_insert_allowed(self):
        rc, out, err = _run_hook("bach task add 'demo task'")
        assert rc == 0
        assert "BLOCK" not in err

    def test_core_db_handler_allowed(self):
        rc, out, err = _run_hook(
            "python3 -c \"from core.db import get_connection; get_connection()\""
        )
        assert rc == 0
        assert "BLOCK" not in err

    def test_readonly_sqlite_select_allowed(self):
        rc, out, err = _run_hook("sqlite3 bach.db 'SELECT COUNT(*) FROM tasks;'")
        assert rc == 0
        assert "BLOCK" not in err


class TestDbGuardHookEdgeCases:
    def test_empty_command_allowed(self):
        rc, out, err = _run_hook("")
        assert rc == 0
        assert "BLOCK" not in err

    def test_non_db_command_allowed(self):
        rc, out, err = _run_hook("ls -la /tmp")
        assert rc == 0
        assert "BLOCK" not in err

    def test_block_message_recommends_bach_api_db(self):
        rc, out, err = _run_hook("sqlite3 bach.db 'DELETE FROM tasks;'")
        assert rc == 2
        assert "from bach_api import task, memory, steuer, backup" in err
        assert "bach task|mem|steuer|backup" in err


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
