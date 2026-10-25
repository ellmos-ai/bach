# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""The context handoff note carries the run's read trail (local worker harness, 25.10.2026).

After a handoff the local worker re-read files it had already read (#2505: 37 of
53 tool calls were read_file). The resumed context must therefore name the files
and line ranges already read and the searches already run, bounded, and only for
calls that actually returned content.
"""

import asyncio
import json
import sys
from pathlib import Path

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub._services.chat.worker_tool_errors import ToolErrorText


def _numbered(first, last, total=500):
    header = f"Physische Zeilen {first}–{last} von {total}; Offset={first}; angezeigt={last - first + 1}/200."
    return header + "\n" + "\n".join(f"{n:>6} | line {n}" for n in range(first, last + 1))


def _call(name, arguments):
    return {"function": {"name": name, "arguments": arguments}}


def test_handoff_resumes_with_trail_of_successful_reads_and_searches(monkeypatch):
    from hub._services.chat.chat_runtime import ChatRuntime, ChatSession, HANDOFF_PROMPT

    results = {
        ("read_file", "src/a.py", 1): _numbered(1, 200),
        ("read_file", "src/a.py", 201): _numbered(201, 260, total=260),
        ("read_file", "secrets/key.txt", 1): ToolErrorText(
            "BLOCKIERT: Secrets-Datei darf nicht gelesen werden.",
            code="tool_policy_denied", reason="secret_path_denied"),
        ("search_text", "src", None): "/w/src/a.py:12:def run():\n/w/src/b.py:40:    run()",
    }

    def fake_exec_tool(name, args, *_a, **_kw):
        args = json.loads(args) if isinstance(args, str) else args
        return results[(name, args.get("path"), args.get("offset"))]

    monkeypatch.setattr("hub._services.chat.chat_runtime.exec_tool", fake_exec_tool)
    script = [
        [_call("read_file", {"path": "src/a.py", "offset": 1, "lines": 200}),
         _call("read_file", {"path": "secrets/key.txt", "offset": 1})],
        [_call("read_file", {"path": "src/a.py", "offset": 201, "lines": 200}),
         _call("search_text", {"pattern": "def run", "path": "src"})],
    ]

    class Backend:
        manages_own_tools = False

        def __init__(self):
            self.calls = []

        def get_default_model(self):
            return "qwen3.8:27b-mlx"

        def tool_response_message(self, content, tool_call_id):
            return {"role": "tool", "content": content, "tool_call_id": tool_call_id}

        async def chat(self, messages, **kwargs):
            self.calls.append([dict(m) for m in messages])
            if messages[-1]["content"] == HANDOFF_PROMPT:
                return {"content": "FAKTEN: run() in a.py:12\nRESUME: edit a.py"}
            if script:
                return {"content": "", "prompt_tokens": 10, "tool_calls": script.pop(0)}
            if not any("RESUME: edit a.py" in str(m.get("content")) for m in messages):
                return {"content": "", "prompt_tokens": 90}
            return {"content": "continued", "prompt_tokens": 10}

    backend = Backend()
    runtime = ChatRuntime(backend)
    runtime.handoff_percent = 75
    session = ChatSession()
    session.allow_tools = True
    session.max_tool_rounds = 10
    answer = asyncio.run(runtime._tool_loop(
        [{"role": "system", "content": "Worker role"}], session,
        tools=[{"name": "read"}], context_limit=100))

    assert answer == "continued"
    resumed = "\n".join(str(m.get("content")) for m in backend.calls[-1])
    assert "RESUME: edit a.py" in resumed
    assert "LESESPUR" in resumed
    assert "- gelesen src/a.py: Zeilen 1–260" in resumed
    assert "- gesucht 'def run' in src: 2 Treffer (a.py:12, b.py:40)" in resumed
    assert "secrets/key.txt" not in resumed
    assert "line 12" not in resumed  # ranges only, never file content
    assert sum("LESESPUR" in str(m.get("content")) for m in session.messages) == 1


def test_read_trail_is_bounded_and_keeps_the_latest_entries():
    from hub._services.chat.chat_runtime import READ_TRAIL_LIMIT, READ_TRAIL_MAX_CHARS, _ReadTrail

    trail = _ReadTrail()
    for n in range(READ_TRAIL_LIMIT + 15):
        trail.record("read_file", {"path": f"docs/f{n}.md", "offset": 1}, _numbered(1, 30))
    text = trail.render()
    assert "docs/f0.md" not in text
    assert f"docs/f{READ_TRAIL_LIMIT + 14}.md" in text
    assert text.count("- gelesen ") <= READ_TRAIL_LIMIT
    assert len(text) <= READ_TRAIL_MAX_CHARS + 300


def test_read_trail_uses_v1_pages_and_ignores_unavailable_or_failed_reads():
    from hub._services.chat.chat_runtime import _ReadTrail

    trail = _ReadTrail()
    page = json.dumps({"schema": "ellmos.read-evidence.v1", "start_line": 5, "end_line": 7,
                       "lines": [], "next_cursor": None})
    unavailable = json.dumps({"schema": "bach.read-evidence-capability.v1", "available": False})
    trail.record("read_file", {"path": "a.py", "output_format": "ellmos.read-evidence.v1",
                               "start_line": 5}, page)
    trail.record("read_file", {"path": "b.py", "output_format": "ellmos.read-evidence.v1"}, unavailable)
    trail.record("read_file", {"path": "c.py"}, "Fehler: offset muss eine gültige positive Ganzzahl sein.")
    trail.record("read_file", {"path": "d.py"}, "Werkzeugausführung nicht bestätigt; Wirkung unbekannt.")
    trail.record("search_text", {"pattern": "x", "path": "e"}, "(keine Treffer)")
    trail.record("write_file", {"path": "f.py"}, "ok")
    text = trail.render()
    assert "- gelesen a.py: Zeilen 5–7" in text
    assert "- gesucht 'x' in e: 0 Treffer" in text
    for absent in ("b.py", "c.py", "d.py", "f.py"):
        assert absent not in text
    assert _ReadTrail().render() == ""
