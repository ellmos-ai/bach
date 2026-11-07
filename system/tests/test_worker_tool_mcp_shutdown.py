"""The stdio MCP shim must exit when its parent closes stdin, even mid-request.

Regression for the bach-suite hang on the Mac (T-20261107-512211369): the shim kept
running while an executor thread sat in a relay HTTP call (timeout 130 s), so the
parent waited on a child that never ended.
"""
import json
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("mcp")

SCRIPT = Path(__file__).resolve().parents[1] / "hub/_services/chat/worker_tool_mcp.py"


def _send(proc, message):
    proc.stdin.write((json.dumps(message) + "\n").encode("utf-8"))
    proc.stdin.flush()


def test_shim_exits_promptly_after_stdin_close_with_relay_request_in_flight():
    accepted = threading.Event()
    held = []
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)

    def accept_and_stay_silent():  # a relay that never answers
        conn, _ = server.accept()
        held.append(conn)
        accepted.set()

    threading.Thread(target=accept_and_stay_silent, daemon=True).start()
    env = {
        "BACH_WORKER_TOOL_URL": f"http://127.0.0.1:{server.getsockname()[1]}",
        "BACH_WORKER_TOOL_TOKEN": "t" * 32,
        "BACH_WORKER_TOOL_GENERATION": "a" * 32,
        "BACH_WORKER_TOOL_TASK_ID": "1",
    }
    import os
    proc = subprocess.Popen([sys.executable, "-X", "utf8", str(SCRIPT)], stdin=subprocess.PIPE,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            env={**os.environ, **env})
    try:
        _send(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "pytest", "version": "0"}}})
        _send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        _send(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        assert accepted.wait(30), "shim never contacted the relay"
        proc.stdin.close()
        started = time.monotonic()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            pytest.fail("shim still running 20 s after stdin close (hung on in-flight relay request)")
        assert time.monotonic() - started < 20
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        for conn in held:
            conn.close()
        server.close()
