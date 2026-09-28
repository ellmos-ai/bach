"""Phase-5-Tests: Node-Auth, Epochen, Lead-Terme und Fencing."""

import json
import os

import pytest

from hub._services.trithon import fencing


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
