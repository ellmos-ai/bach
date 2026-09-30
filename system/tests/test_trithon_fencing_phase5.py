"""Phase-5-Tests: Node-Auth, Epochen, Lead-Terme und Fencing."""

import json
import multiprocessing
import os
from importlib.machinery import PathFinder
from pathlib import Path

import pytest
from hub._services.trithon import fencing

from tests.trithon_fencing_process_helpers import (
    _exit_while_holding_lock,
    _fencing_process,
)


@pytest.fixture(params=[False, True], ids=["inherited-imports", "hub-shadowed-imports"])
def spawn_imports(request, monkeypatch):
    """Keep the real suite's hub/email shadowing in spawned children."""
    if request.param:
        hub = Path(__file__).resolve().parents[1] / "hub"
        spec = PathFinder.find_spec("email", [str(hub)])
        assert Path(spec.origin) == hub / "email.py"
        assert spec.submodule_search_locations is None
        monkeypatch.syspath_prepend(str(hub))


def _setup_node(tmp_path, node_id="node-a", token="secret-a", salt="salt-a"):
    return fencing.register_node(tmp_path, node_id, token, salt=salt)


def test_register_and_authenticate(tmp_path):
    entry = _setup_node(tmp_path)
    assert entry["node_id"] == "node-a"
    assert entry["salt"] == "salt-a"
    assert fencing.authenticate(tmp_path, "node-a", "secret-a") is True
    assert fencing.authenticate(tmp_path, "node-a", "falsch") is False
    assert fencing.authenticate(tmp_path, "unbekannt", "secret-a") is False
    assert fencing.authenticate(tmp_path, "", "") is False


def test_authenticate_fail_closed_ohne_nodes_file(tmp_path):
    assert fencing.authenticate(tmp_path, "node-a", "secret-a") is False
    (tmp_path / fencing.NODES_FILE).write_text("{kaputt", encoding="utf-8")
    assert fencing.authenticate(tmp_path, "node-a", "secret-a") is False


def test_claim_lead_monotoner_term(tmp_path):
    _setup_node(tmp_path)
    lead1 = fencing.claim_lead(tmp_path, "node-a", "secret-a")
    assert lead1["term"] == 1
    assert fencing.current_term(tmp_path) == 1
    lead2 = fencing.claim_lead(tmp_path, "node-a", "secret-a")
    assert lead2["term"] == 2
    assert lead2["fencing_token"] != lead1["fencing_token"]
    with pytest.raises(fencing.FencingError):
        fencing.claim_lead(tmp_path, "node-a", "secret-a", term=2)
    with pytest.raises(fencing.FencingError):
        fencing.claim_lead(tmp_path, "node-a", "secret-a", term=1)


def test_claim_lead_erfordert_auth(tmp_path):
    _setup_node(tmp_path)
    with pytest.raises(fencing.FencingError):
        fencing.claim_lead(tmp_path, "node-a", "falsch")
    with pytest.raises(fencing.FencingError):
        fencing.claim_lead(tmp_path, "fremd", "secret-a")
    assert fencing.current_term(tmp_path) == 0


def test_claim_lead_zwei_nodes_split_schutz(tmp_path):
    _setup_node(tmp_path)
    fencing.register_node(tmp_path, "node-b", "secret-b", salt="salt-b")
    a = fencing.claim_lead(tmp_path, "node-a", "secret-a")
    b = fencing.claim_lead(tmp_path, "node-b", "secret-b")
    assert b["term"] > a["term"]
    assert fencing.check_fencing(tmp_path, b["term"], b["fencing_token"]) is True
    assert fencing.check_fencing(tmp_path, a["term"], a["fencing_token"]) is False


def test_check_fencing_fail_closed(tmp_path):
    assert fencing.check_fencing(tmp_path, 1, "irgendwas") is False
    _setup_node(tmp_path)
    lead = fencing.claim_lead(tmp_path, "node-a", "secret-a")
    assert fencing.check_fencing(tmp_path, lead["term"], "falsch") is False
    assert fencing.check_fencing(tmp_path, lead["term"] + 1, lead["fencing_token"]) is False
    assert fencing.check_fencing(tmp_path, None, lead["fencing_token"]) is False


def test_epoch_monoton_ueber_epochen(tmp_path):
    _setup_node(tmp_path)
    assert fencing.current_epoch(tmp_path) == 0
    assert fencing.bump_epoch(tmp_path) == 1
    assert fencing.current_epoch(tmp_path) == 1
    term_vor = fencing.claim_lead(tmp_path, "node-a", "secret-a")["term"]
    fencing.bump_epoch(tmp_path)
    lead = fencing.claim_lead(tmp_path, "node-a", "secret-a")
    assert lead["term"] > term_vor
    assert lead["epoch"] == 2


def test_term_file_atomar_und_lesbar(tmp_path):
    _setup_node(tmp_path)
    fencing.claim_lead(tmp_path, "node-a", "secret-a")
    data = json.loads((tmp_path / fencing.TERM_FILE).read_text(encoding="utf-8"))
    assert data["term"] == 1
    assert data["leader"] == "node-a"
    reste = [p for p in os.listdir(tmp_path) if p.endswith(".tmp")]
    assert reste == []


def _run_processes(directory, operation, count=4):
    # spawn tests Windows and POSIX without inherited lock descriptors or caches.
    context = multiprocessing.get_context("spawn")
    ready, results, start = context.Queue(), context.Queue(), context.Event()
    processes = [context.Process(target=_fencing_process,
                                args=(str(directory), i, operation, ready, start, results))
                 for i in range(count)]
    try:
        for process in processes:
            process.start()
        for _ in processes:
            ready.get(timeout=20)
        start.set()
        collected = [results.get(timeout=20) for _ in processes]
        for process in processes:
            process.join(timeout=20)
            assert process.exitcode == 0
        return collected
    finally:
        start.set()
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
            process.close()
        ready.close()
        results.close()


def test_multiprocess_claims_get_unique_monotone_terms(tmp_path, spawn_imports):
    for i in range(4):
        fencing.register_node(tmp_path, f"node-{i}", f"synthetic-{i}")
    results = _run_processes(tmp_path, "claim")
    assert sorted(result for status, result in results if status == "ok") == [1, 2, 3, 4]
    assert fencing.current_term(tmp_path) == 4


def test_multiprocess_explicit_term_has_exactly_one_winner(tmp_path, spawn_imports):
    for i in range(4):
        fencing.register_node(tmp_path, f"node-{i}", f"synthetic-{i}")
    results = _run_processes(tmp_path, "explicit-claim")
    assert sum(status == "ok" for status, _ in results) == 1
    assert sum(status == "refused" for status, _ in results) == 3
    assert fencing.current_term(tmp_path) == 1


def test_multiprocess_fresh_registration_does_not_drop_nodes(tmp_path, spawn_imports):
    results = _run_processes(tmp_path, "register")
    assert all(status == "ok" for status, _ in results)
    assert set(fencing.load_nodes(tmp_path)["nodes"]) == {f"node-{i}" for i in range(4)}
    assert fencing.current_term(tmp_path) == 0


def test_multiprocess_epoch_changes_do_not_drop_increments(tmp_path, spawn_imports):
    _setup_node(tmp_path)
    results = _run_processes(tmp_path, "epoch")
    assert sorted(result for status, result in results if status == "ok") == [1, 2, 3, 4]
    assert fencing.current_epoch(tmp_path) == 4


@pytest.mark.parametrize("corruption", ["missing", "{broken", "[]", "null",
                                      '{"term":true,"epoch":0}',
                                      '{"term":-1,"epoch":0}',
                                      '{"term":1,"epoch":false}',
                                      '{"term":1,"epoch":0,"leader":"a"}'])
def test_existing_corrupt_term_never_resets_authority(tmp_path, corruption):
    _setup_node(tmp_path)
    previous = fencing.claim_lead(tmp_path, "node-a", "secret-a")
    path = tmp_path / fencing.TERM_FILE
    if corruption == "missing":
        path.unlink()
    else:
        path.write_text(corruption, encoding="utf-8")
    before = path.read_bytes() if path.exists() else None
    for operation in (
        lambda: fencing.claim_lead(tmp_path, "node-a", "secret-a"),
        lambda: fencing.bump_epoch(tmp_path),
        lambda: fencing.register_node(tmp_path, "node-b", "secret-b"),
        lambda: fencing.save_nodes(tmp_path, {"nodes": {}}),
        lambda: fencing.current_term(tmp_path),
    ):
        with pytest.raises(fencing.FencingError):
            operation()
    assert fencing.check_fencing(tmp_path, previous["term"], previous["fencing_token"]) is False
    assert (path.read_bytes() if path.exists() else None) == before


@pytest.mark.parametrize("bad_term", [True, False, 0, -1, 1.5, "1"])
def test_claim_rejects_invalid_term_before_replacement(tmp_path, bad_term):
    _setup_node(tmp_path)
    before = (tmp_path / fencing.TERM_FILE).read_bytes()
    with pytest.raises(fencing.FencingError):
        fencing.claim_lead(tmp_path, "node-a", "secret-a", term=bad_term)
    assert (tmp_path / fencing.TERM_FILE).read_bytes() == before


def test_epoch_change_revokes_previous_fence_immediately(tmp_path):
    _setup_node(tmp_path)
    previous = fencing.claim_lead(tmp_path, "node-a", "secret-a")
    fencing.bump_epoch(tmp_path)
    assert fencing.current_term(tmp_path) == previous["term"]
    assert fencing.check_fencing(tmp_path, previous["term"], previous["fencing_token"]) is False
    next_lead = fencing.claim_lead(tmp_path, "node-a", "secret-a")
    assert next_lead["term"] > previous["term"]


def test_interrupted_first_registration_requires_recovery(tmp_path, monkeypatch):
    original = fencing._write_json_atomic

    def fail_node_write(path, data):
        if path.name == fencing.NODES_FILE:
            raise OSError("synthetic interrupted initialization")
        return original(path, data)

    monkeypatch.setattr(fencing, "_write_json_atomic", fail_node_write)
    with pytest.raises(fencing.FencingError):
        _setup_node(tmp_path)
    monkeypatch.setattr(fencing, "_write_json_atomic", original)
    with pytest.raises(fencing.FencingError):
        _setup_node(tmp_path)
    assert not (tmp_path / fencing.NODES_FILE).exists()


def test_lock_timeout_refuses_without_changing_state(tmp_path, monkeypatch):
    from filelock import FileLock

    _setup_node(tmp_path)
    before = (tmp_path / fencing.TERM_FILE).read_bytes()
    monkeypatch.setattr(fencing, "LOCK_TIMEOUT_SECONDS", 0.1)
    with FileLock(str(tmp_path / fencing.LOCK_FILE)), pytest.raises(fencing.FencingError):
        fencing.claim_lead(tmp_path, "node-a", "secret-a")
    assert (tmp_path / fencing.TERM_FILE).read_bytes() == before


def test_state_directory_aliases_use_the_same_lock(tmp_path, monkeypatch):
    from filelock import FileLock

    _setup_node(tmp_path)
    monkeypatch.setattr(fencing, "LOCK_TIMEOUT_SECONDS", 0.1)
    alias = tmp_path / "child" / ".."
    with FileLock(str(tmp_path / fencing.LOCK_FILE)), pytest.raises(fencing.FencingError):
        fencing.claim_lead(alias, "node-a", "secret-a")


def test_unicode_node_credentials_remain_supported(tmp_path):
    fencing.register_node(tmp_path, "synthetisch-ä", "synthetisch-ö", salt="synthetisch-ü")
    assert fencing.authenticate(tmp_path, "synthetisch-ä", "synthetisch-ö")
    assert fencing.claim_lead(tmp_path, "synthetisch-ä", "synthetisch-ö")["term"] == 1


def test_corrupt_nodes_do_not_get_overwritten_or_advance_epoch(tmp_path):
    _setup_node(tmp_path)
    (tmp_path / fencing.NODES_FILE).write_text('{"nodes":{"a":null}}', encoding="utf-8")
    before = (tmp_path / fencing.TERM_FILE).read_bytes()
    with pytest.raises(fencing.FencingError):
        fencing.register_node(tmp_path, "node-b", "secret-b")
    with pytest.raises(fencing.FencingError):
        fencing.bump_epoch(tmp_path)
    assert (tmp_path / fencing.TERM_FILE).read_bytes() == before


def test_crashed_process_releases_kernel_lock_without_unlinking_it(tmp_path, spawn_imports):
    """A dead holder cannot leave permanent local ownership on either OS."""
    _setup_node(tmp_path)
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=_exit_while_holding_lock, args=(str(tmp_path), sender))
    try:
        process.start()
        assert receiver.poll(15)
        assert receiver.recv() == "locked"
        process.join(timeout=15)
        assert process.exitcode == 23
        assert (tmp_path / fencing.LOCK_FILE).exists()
        assert fencing.claim_lead(tmp_path, "node-a", "secret-a")["term"] == 1
    finally:
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
        process.close()
        receiver.close()
        sender.close()


@pytest.mark.parametrize("corrupt_entry", [
    None,
    {"token": "secret-a", "salt": "salt-a"},
    {"node_id": "other-node", "token": "secret-a", "salt": "salt-a"},
    {"node_id": "node-a", "salt": "salt-a"},
    {"node_id": "node-a", "token": 7, "salt": "salt-a"},
    {"node_id": "node-a", "token": "", "salt": "salt-a"},
    {"node_id": "node-a", "token": "secret-a"},
    {"node_id": "node-a", "token": "secret-a", "salt": 7},
    {"node_id": "node-a", "token": "secret-a", "salt": True},
    {"node_id": "node-a", "token": "secret-a", "salt": []},
    {"node_id": "node-a", "token": "secret-a", "salt": {}},
])
def test_claim_rejects_every_malformed_registered_entry_without_changing_term(tmp_path, corrupt_entry):
    _setup_node(tmp_path)
    fencing.claim_lead(tmp_path, "node-a", "secret-a")
    registry_path = tmp_path / fencing.NODES_FILE
    registry_path.write_text(json.dumps({"nodes": {"node-a": corrupt_entry}}), encoding="utf-8")
    before_term = (tmp_path / fencing.TERM_FILE).read_bytes()
    before_nodes = registry_path.read_bytes()
    with pytest.raises(fencing.FencingError):
        fencing.claim_lead(tmp_path, "node-a", "secret-a")
    assert (tmp_path / fencing.TERM_FILE).read_bytes() == before_term
    assert registry_path.read_bytes() == before_nodes


@pytest.mark.parametrize("registry", [None, {}, {"nodes": []}, {"nodes": {"node-b": None}}])
def test_claim_requires_a_complete_registry_including_other_nodes(tmp_path, registry):
    _setup_node(tmp_path)
    before_term = (tmp_path / fencing.TERM_FILE).read_bytes()
    (tmp_path / fencing.NODES_FILE).write_text(json.dumps(registry), encoding="utf-8")
    with pytest.raises(fencing.FencingError):
        fencing.claim_lead(tmp_path, "node-a", "secret-a")
    assert (tmp_path / fencing.TERM_FILE).read_bytes() == before_term


def test_claim_does_not_ignore_a_corrupt_unrelated_node(tmp_path):
    _setup_node(tmp_path)
    registry_path = tmp_path / fencing.NODES_FILE
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["nodes"]["node-b"] = {"node_id": "node-b", "token": "secret-b", "salt": []}
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    before_term = (tmp_path / fencing.TERM_FILE).read_bytes()
    with pytest.raises(fencing.FencingError):
        fencing.claim_lead(tmp_path, "node-a", "secret-a")
    assert (tmp_path / fencing.TERM_FILE).read_bytes() == before_term


@pytest.mark.parametrize("salt", [None, "", "synthetisch-ü"])
def test_explicit_valid_salt_remains_supported(tmp_path, salt):
    fencing.register_node(tmp_path, "node-a", "secret-a", salt=salt)
    result = fencing.claim_lead(tmp_path, "node-a", "secret-a")
    assert result["salt"] == salt
    assert result["fencing_token"] == fencing._fencing_token("node-a", 1, salt)


def test_claim_auth_and_salt_use_one_registry_snapshot_under_the_claim_lock(tmp_path, monkeypatch):
    from filelock import FileLock, Timeout

    _setup_node(tmp_path)
    original_read = fencing._read_json
    reads = []

    def read_once(path):
        if path.name == fencing.NODES_FILE:
            with pytest.raises(Timeout), FileLock(str(tmp_path / fencing.LOCK_FILE), timeout=0):
                pytest.fail("claim registry was read outside its native lock")
            reads.append(path)
        return original_read(path)

    monkeypatch.setattr(fencing, "_read_json", read_once)
    result = fencing.claim_lead(tmp_path, "node-a", "secret-a")
    assert len(reads) == 1
    assert result["salt"] == "salt-a"
    assert result["fencing_token"] == fencing._fencing_token("node-a", 1, "salt-a")
