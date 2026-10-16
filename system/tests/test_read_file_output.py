from __future__ import annotations

import pytest
from hub._services.chat import bach_tools
from hub._services.read_file_formatter import (
    MAX_READ_FILE_LINES,
    MAX_READ_FILE_OUTPUT_CHARS,
    format_read_file_output,
)

from system.tests.test_worker_write_guard import (
    FakeBinding,
    FakeClient,
    _public_reader_tree,
)


@pytest.fixture(autouse=True)
def _allow_tmp_in_legacy_roots(tmp_path, monkeypatch):
    from hub._services.chat import chat_runtime

    monkeypatch.setattr(
        chat_runtime,
        "_ALLOWED_FS_ROOTS",
        chat_runtime._ALLOWED_FS_ROOTS + (tmp_path.resolve(),),
    )


def _bound_provider(binding=None):
    return bach_tools.BachToolProvider(
        worker_task_binding=binding or FakeBinding(),
        require_task_binding=True,
        allowed_tools={"read_file", "start_task_worktree"},
    )


def _task_file(tmp_path, monkeypatch, content: bytes):
    _repo, _worktrees, target, _private = _public_reader_tree(tmp_path, monkeypatch)
    path = target / "src" / "review.txt"
    path.write_bytes(content)
    return target, path


def test_task_bound_provider_defaults_to_physical_numbers_and_page_metadata(tmp_path, monkeypatch):
    _target, path = _task_file(tmp_path, monkeypatch, "erste\r\n\r\nDritte äöü\r\nvierte".encode())
    provider = _bound_provider()

    result = provider.execute("read_file", {"path": str(path), "offset": 2, "lines": 2}, "safe")

    assert result.startswith("Physische Zeilen 2–3 von 4; Offset=2; angezeigt=2/2; weitere Zeilen vorhanden")
    assert "fortsetzen mit offset=4" in result
    assert "     2 | \n     3 | Dritte äöü" in result
    assert "     4 |" not in result
    tool = next(item for item in provider.get_tools("safe") if item["function"]["name"] == "read_file")
    props = tool["function"]["parameters"]["properties"]
    assert props["line_numbers"]["type"] == "boolean"
    assert "Zeilennummern" in tool["function"]["description"]
    assert "nicht verifiziert" in tool["function"]["description"]


def test_explicit_raw_mode_and_unbound_legacy_default_remain_raw(tmp_path, monkeypatch):
    _target, path = _task_file(tmp_path, monkeypatch, "eins\r\n\r\nzwei äöü\r\n".encode())
    provider = _bound_provider()
    bound_raw = provider.execute(
        "read_file", {"path": str(path), "offset": 2, "lines": 2, "line_numbers": False}, "safe",
    )
    legacy = bach_tools.BachToolProvider().execute(
        "read_file", {"path": str(path), "offset": 2, "lines": 2}, "safe",
    )

    assert bound_raw == "\nzwei äöü\n"
    assert legacy == bound_raw
    assert "Physische Zeilen" not in bound_raw and "     2 |" not in bound_raw


@pytest.mark.parametrize("key,value", [
    ("lines", True), ("lines", "2"), ("lines", 0),
    ("offset", True), ("offset", "1"), ("offset", 0),
    ("line_numbers", 1), ("line_numbers", "false"),
])
def test_provider_rejects_malformed_integer_and_boolean_parameters_without_content(
        tmp_path, monkeypatch, key, value):
    _target, path = _task_file(tmp_path, monkeypatch, b"must not be returned\n")
    result = _bound_provider().execute("read_file", {"path": str(path), key: value}, "safe")
    assert "Fehler:" in result
    assert "must not be returned" not in result
    assert str(path) not in result


def test_line_request_above_cap_is_honestly_limited_to_200(tmp_path, monkeypatch):
    rows = "".join(f"line-{number:03d}\n" for number in range(1, 202)).encode()
    _target, path = _task_file(tmp_path, monkeypatch, rows)
    result = _bound_provider().execute(
        "read_file", {"path": str(path), "lines": MAX_READ_FILE_LINES + 1}, "safe",
    )

    assert "Anfrage auf höchstens 200 Zeilen begrenzt" in result
    assert "weitere Zeilen vorhanden" in result
    assert "   200 | line-200" in result
    assert "   201 |" not in result


def test_long_line_is_numbered_and_truncation_is_visible_within_4000_chars(tmp_path, monkeypatch):
    _target, path = _task_file(tmp_path, monkeypatch, ("x" * 6000 + "\nrest\n").encode())
    result = _bound_provider().execute(
        "read_file", {"path": str(path), "lines": 2, "line_numbers": True}, "safe",
    )

    assert len(result) <= MAX_READ_FILE_OUTPUT_CHARS
    assert result.startswith("Auszug ab physischer Zeile 1; Limit=2; Datei=2 physische Zeilen.")
    assert "     1 | " in result
    assert "Ausgabe bei 4000 Zeichen gekürzt" in result
    assert "Zeile 1 ist unvollständig angezeigt" in result
    assert "offset=1" in result
    assert "     2 | rest" not in result


def test_many_line_excerpt_truncation_keeps_physical_number_and_resume_offset(tmp_path, monkeypatch):
    content = "".join(f"row-{number:03d}-" + ("x" * 80) + "\n" for number in range(1, 81))
    _target, path = _task_file(tmp_path, monkeypatch, content.encode())
    result = _bound_provider().execute(
        "read_file", {"path": str(path), "lines": 80}, "safe",
    )

    assert "Zeile " in result and "ist unvollständig angezeigt" in result
    continuation = int(result.rsplit("Zeile ", 1)[1].split(" ", 1)[0])
    visible_rows = []
    for output_line in result.splitlines():
        prefix = output_line.partition("|")[0].strip()
        if prefix.isdigit():
            visible_rows.append(int(prefix))
    assert len(result) <= MAX_READ_FILE_OUTPUT_CHARS
    assert visible_rows == list(range(1, continuation + 1))
    assert f"offset={continuation}" in result


def test_empty_file_and_offset_after_eof_are_explicit(tmp_path, monkeypatch):
    target, _path = _task_file(tmp_path, monkeypatch, b"")
    provider = _bound_provider()
    empty = provider.execute("read_file", {"path": str(target / "src" / "review.txt")}, "safe")
    (target / "src" / "review.txt").write_bytes(b"one\ntwo\n")
    past_eof = provider.execute(
        "read_file", {"path": str(target / "src" / "review.txt"), "offset": 3}, "safe",
    )

    assert empty == "Datei leer (0 physische Zeilen); Offset=1; angezeigt=0/50."
    assert "Dateiende bei Zeile 2; Offset=3 liegt dahinter" in past_eof


@pytest.mark.parametrize("bad_view", [
    {"own": False}, {"leased": False}, {"fence": 3}, {"task_version": "stale"},
])
def test_task_reader_guard_denials_stay_fail_closed(tmp_path, monkeypatch, bad_view):
    _target, path = _task_file(tmp_path, monkeypatch, b"private task source marker\n")
    view = {
        "own": True, "leased": True, "fence": 4,
        "status": "in_progress", "task_version": "v" * 64,
    }
    view.update(bad_view)
    binding = FakeBinding(FakeClient(view))

    result = _bound_provider(binding).execute("read_file", {"path": str(path)}, "safe")

    assert "BLOCKIERT" in result
    assert "private task source marker" not in result
    assert str(path) not in result


def test_task_reader_still_blocks_secrets_and_paths_outside_snapshot(tmp_path, monkeypatch):
    _repo, _worktrees, target, private = _public_reader_tree(tmp_path, monkeypatch)
    provider = _bound_provider()

    secret = provider.execute("read_file", {"path": str(target / "src" / "secret.pem")}, "safe")
    outside = provider.execute("read_file", {"path": str(private)}, "safe")
    assert "BLOCKIERT" in secret and "needle secret" not in secret
    assert "BLOCKIERT" in outside and "needle private target" not in outside


def test_task_reader_still_blocks_symlink_paths(tmp_path, monkeypatch):
    _repo, _worktrees, target, _private = _public_reader_tree(tmp_path, monkeypatch)
    link = target / "src" / "link.py"
    if not link.is_symlink():
        pytest.skip("Symlink creation is unavailable")

    linked = _bound_provider().execute("read_file", {"path": str(link)}, "safe")
    assert "BLOCKIERT" in linked and "needle private target" not in linked


def test_formatter_rejects_boolean_integer_fields():
    with pytest.raises(ValueError):
        format_read_file_output([], offset=True, requested_lines=1, effective_lines=1, total_lines=0)
    with pytest.raises(ValueError):
        format_read_file_output([], offset=1, requested_lines=True, effective_lines=1, total_lines=0)
