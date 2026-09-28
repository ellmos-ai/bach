"""Phase-5.2-Tests: Receipt-Provider (git/native/db) und deterministische Faltung."""

import json
import sqlite3
import subprocess

import pytest

from hub._services.trithon import receipt_providers as rp


def _raw(signature, status="done", evidence=None, **kw):
    raw = {
        "signature": signature,
        "status": status,
        "executed_by": kw.pop("executed_by", "node-a"),
        "actual_provider": kw.pop("actual_provider", ""),
        "occurred_at": kw.pop("occurred_at", "2026-09-28T10:00:00+00:00"),
        "evidence": evidence if evidence is not None else {"k": "v"},
        "ticket_id": kw.pop("ticket_id", "t-1"),
    }
    raw.update(kw)
    return raw


def _normalized(signature, occurred_at, executed_by="node-a", source="git",
                evidence=None, ticket_id="t-1"):
    out = _raw(signature, "done", evidence or {"k": "v"},
               executed_by=executed_by, actual_provider=source,
               occurred_at=occurred_at, ticket_id=ticket_id)
    out["provider_source"] = source
    out.setdefault("actual_provider", source)
    return out


# ---------------------------------------------------------------- git-Provider

def _git_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    env = ["-c", "user.email=t@example.org", "-c", "user.name=Tester"]
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    for msg in ("c1", "c2"):
        subprocess.run(
            ["git", *env, "-C", str(repo), "commit", "-q", "--allow-empty", "-m", msg],
            check=True,
        )
    return repo


def test_git_receipts_aus_repo(tmp_path):
    repo = _git_repo(tmp_path)
    receipts = rp.git_receipts(repo, ticket_id="t-99")
    assert len(receipts) == 2
    for r in receipts:
        assert r["status"] == "done"
        assert r["signature"]
        assert r["provider_source"] == "git"
        assert r["executed_by"] == "Tester"
        assert r["evidence"]["rev"] == r["signature"]
        assert r["evidence"]["repo"] == str(repo)
        assert r["ticket_id"] == "t-99"
        assert "T" in r["occurred_at"]  # ISO-Format
    sigs = {r["signature"] for r in receipts}
    assert len(sigs) == 2  # ein Receipt pro Commit


def test_git_receipts_provider_unavailable(tmp_path):
    with pytest.raises(rp.ProviderUnavailable):
        rp.git_receipts(tmp_path / "gibts-nicht")
    leer = tmp_path / "leer"
    leer.mkdir()
    subprocess.run(["git", "-C", str(leer), "init", "-q"], check=True)
    with pytest.raises(rp.ProviderUnavailable):  # Repo ohne Commits
        rp.git_receipts(leer)


# ------------------------------------------------------------- native-Provider

def test_native_receipts_mit_helfern():
    def gut():
        return _raw("sig-native")

    def schlecht():
        return _raw("sig-invalid", status="claimed")

    receipts = rp.native_receipts([gut, schlecht])
    assert len(receipts) == 1
    assert receipts[0]["signature"] == "sig-native"
    assert receipts[0]["provider_source"] == "native"


def test_native_receipts_helfer_fehler_provider_unavailable():
    def kaputt():
        raise RuntimeError("boom")

    with pytest.raises(rp.ProviderUnavailable):
        rp.native_receipts([kaputt])


# ----------------------------------------------------------------- db-Provider

def _db(tmp_path, rows):
    db = tmp_path / "receipts.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE receipts (payload TEXT)")
    conn.executemany("INSERT INTO receipts VALUES (?)", [(r,) for r in rows])
    conn.commit()
    conn.close()
    return db


def test_db_receipts_aus_sqlite(tmp_path):
    valid = _raw("sig-db", evidence={"n": 1})
    db = _db(tmp_path, [
        json.dumps(valid),
        "{kaputtes-json",
        json.dumps(_raw("sig-x", status="claimed")),  # nicht final -> weg
        json.dumps(_raw("sig-y", evidence={})),       # evidence falsy -> weg
        json.dumps(_raw("")),                          # leere Signatur -> weg
    ])
    receipts = rp.db_receipts(db)
    assert len(receipts) == 1
    assert receipts[0]["signature"] == "sig-db"
    assert receipts[0]["provider_source"] == "db"
    assert receipts[0]["evidence"] == {"n": 1}


def test_db_receipts_provider_unavailable(tmp_path):
    with pytest.raises(rp.ProviderUnavailable):
        rp.db_receipts(tmp_path / "gibts-nicht.db")
    conn = sqlite3.connect(tmp_path / "ohne-tabelle.db")
    conn.close()
    with pytest.raises(rp.ProviderUnavailable):
        rp.db_receipts(tmp_path / "ohne-tabelle.db")


# -------------------------------------------------------------------- Validitaet

def test_is_valid_receipt_spiegelt_validate_receipt():
    assert rp.is_valid_receipt(_raw("s")) is True
    assert rp.is_valid_receipt(_raw("s", status="blocked")) is True
    assert rp.is_valid_receipt(_raw("s", status="claimed")) is False
    assert rp.is_valid_receipt(_raw("s", status="pending")) is False
    assert rp.is_valid_receipt(_raw("s", evidence={})) is False
    none_ev = _raw("s")
    none_ev["evidence"] = None
    assert rp.is_valid_receipt(none_ev) is False
    assert rp.is_valid_receipt("kein-dict") is False


# -------------------------------------------------------------------- Faltung

def test_fold_dedupe_gleiche_signatur():
    a = _normalized("sig-x", "2026-09-28T10:00:00+00:00", executed_by="node-a")
    b = _normalized("sig-x", "2026-09-27T09:00:00+00:00", executed_by="node-b")
    out = rp.fold_receipts([[a], [b]])
    assert out["stats"]["count_in"] == 2
    assert out["stats"]["count_out"] == 1
    assert out["stats"]["duplicates"] == 1
    assert out["stats"]["invalid"] == 0
    assert out["receipts"] == [b]  # frueheres occurred_at gewinnt deterministisch


def test_fold_deterministisch_bei_stream_reihenfolge():
    s1 = [
        _normalized("sig-1", "2026-09-28T10:00:00+00:00"),
        _normalized("sig-2", "2026-09-26T08:00:00+00:00", ticket_id="t-2"),
    ]
    s2 = [
        _normalized("sig-2", "2026-09-27T09:00:00+00:00", ticket_id="t-2"),  # Duplikat
        _normalized("sig-3", "2026-09-25T07:00:00+00:00", source="db",
                    ticket_id="t-3"),
    ]
    vorwaerts = rp.fold_receipts([s1, s2])
    rueckwaerts = rp.fold_receipts([s2, s1])
    assert vorwaerts == rueckwaerts
    sigs = [r["signature"] for r in vorwaerts["receipts"]]
    # Sortierung occurred_at aufsteigend: sig-3 (25.), sig-2 (26.), sig-1 (28.)
    assert sigs == ["sig-3", "sig-2", "sig-1"]
    assert len(vorwaerts["receipts"]) == 3
    assert vorwaerts["stats"]["duplicates"] == 1


def test_fold_sortierung_occurred_at_dann_signatur():
    receipts = [
        _normalized("sig-b", "2026-09-28T10:00:00+00:00"),
        _normalized("sig-a", "2026-09-28T10:00:00+00:00"),
        _normalized("sig-c", "2026-09-27T10:00:00+00:00"),
    ]
    out = rp.fold_receipts([reversed(receipts)])
    assert [r["signature"] for r in out["receipts"]] == ["sig-c", "sig-a", "sig-b"]


def test_fold_invalid_fliegt_raus():
    streams = [[
        _raw("sig-ok"),                              # gueltig
        _raw("sig-claimed", status="claimed"),       # status nicht final
        _raw("sig-ev", evidence={}),                 # evidence falsy
        "kein-dict",                                  # kein dict
        {**_raw("sig-t"), "provider_source": "native"},  # bereits normalisiert
    ]]
    out = rp.fold_receipts(streams)
    assert [r["signature"] for r in out["receipts"]] == ["sig-ok", "sig-t"]
    assert out["stats"]["count_in"] == 5
    assert out["stats"]["count_out"] == 2
    assert out["stats"]["invalid"] == 3
    assert out["stats"]["duplicates"] == 0


def test_fold_leere_signatur_wird_gedroppt():
    # bereits normalisiert (provider_source vorhanden), aber Signatur leer:
    # darf nicht im Ergebnis landen, zaehlt als invalid
    bogus = _normalized("", "2026-09-28T10:00:00+00:00")
    out = rp.fold_receipts([[bogus, _normalized("sig-1", "2026-09-27T00:00:00+00:00")]])
    assert [r["signature"] for r in out["receipts"]] == ["sig-1"]
    assert out["stats"]["invalid"] == 1
    assert out["stats"]["duplicates"] == 0


def test_fold_by_ticket_erster_gewinnt():
    receipts = [
        _normalized("sig-2", "2026-09-28T10:00:00+00:00", ticket_id="t"),
        _normalized("sig-1", "2026-09-27T10:00:00+00:00", ticket_id="t"),
        _normalized("sig-x", "2026-09-26T10:00:00+00:00", ticket_id=""),  # kein Ticket
    ]
    out = rp.fold_receipts([receipts])
    assert out["by_ticket"]["t"]["signature"] == "sig-1"
    assert "" not in out["by_ticket"]
