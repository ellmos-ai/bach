"""Isolated source authority, version bindings and native evidence contracts."""
import copy
import hashlib
import json
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
import pytest
from hub._services.learning_source_service import LearningSourceService, SOURCE_SCHEMA
from hub._services.learning_review_service import LearningConflict
from hub._services.hermes_distillation_service import HermesDistillationService
from hub._services.skill_source_service import read_skill


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def ctx(tmp_path):
    sources = tmp_path / "sources"; sources.mkdir()
    skills = tmp_path / "skills"
    for name, version in [("skill-extractor", "1.3.1"), ("workflow-extract", "1.1.0")]:
        path = skills / name / "SKILL.md"; path.parent.mkdir(parents=True)
        path.write_text(f"---\nname: {name}\nversion: {version}\n---\n# Testanleitung\n", encoding="utf-8")
    db = tmp_path / "bach.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE tasks (id INTEGER PRIMARY KEY,title TEXT)")
    svc = LearningSourceService(db, source_roots={"sessions": sources}, skill_roots=[skills], write_guard=lambda: None)
    src = sources / "bounded.json"
    src.write_text(json.dumps({"schema": SOURCE_SCHEMA, "session_id": "example-session",
        "events": [{"id": "user-1", "role": "user", "content": "Beim nächsten Mal als Skill verwenden."},
                   {"id": "tool-2", "role": "tool", "content": "Prüfung abgeschlossen."}]}, ensure_ascii=False), encoding="utf-8")
    payload = {"source": {"kind": "session", "root": "sessions", "path": src.name, "sha256": sha(src)},
        "proposal": {"kind": "skill", "name": "source-check", "trigger": "Quellen prüfen",
            "reason": "Wiederkehrende Quellenprüfung mit erhaltenem Beleg",
            "body": "---\nname: source-check\nversion: 1.0.0\n---\n# Quellen prüfen\nVorher den Hash prüfen.\n",
            "event_ids": ["user-1", "tool-2"], "parameters": [], "side_effects": [],
            "required_capabilities": ["filesystem.read"],
            "dedup": {"decision": "new", "reason": "Anderer Kern als die Extraktionsanleitungen"}}}
    return svc, payload, src, skills, db


def native_voyage(ctx, tmp_path):
    import nemofold
    from nemofold import voyages

    _, data, _, skills, db = ctx
    root = tmp_path / "nemofold"
    root.mkdir()
    documents = root / "documents"
    documents.mkdir()
    store = voyages.VoyageStore(root, (str(root),))
    saved = store.save({"name": "Quellenprüfung", "description": "Testplan", "steps": [
        {"workflow": "fact_distill", "job": {
            "schema": "nemofold.job.v1", "workflow": "fact_distill",
            "input_roots": [str(documents)], "output_dir": str(root / "out" / "01"),
            "privacy_mode": "local_only", "action_mode": "dry_run",
            "parameters": {"dedupe_scope": "normalized", "formats": ["md"]},
        }, "note": "Prüfung"},
    ]})
    library = root / "run-reports" / "web-console" / "voyages"
    voyage = library / f"{saved['voyage_id']}.json"
    receipt = library / "_receipts" / f"{saved['voyage_id']}.json"
    data = copy.deepcopy(data)
    data["source"] = {"kind": "nemofold_voyage", "root": "sessions",
        "path": str(voyage.relative_to(root)), "sha256": sha(voyage)}
    data["proposal"]["event_ids"] = [saved["voyage_id"]]
    svc = LearningSourceService(db, source_roots={"sessions": root},
        skill_roots=[skills], write_guard=lambda: None)
    return svc, data, nemofold, voyages, saved, voyage, receipt


def isolated_learning_cli(ctx, tmp_path, monkeypatch):
    import sys
    import bach_api
    from core.app import App
    from core.registry import HandlerRegistry
    from hub.learning import LearningHandler

    _, data, source, skills, _ = ctx
    request = tmp_path / "learning-request.json"
    request.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    app_root = tmp_path / "learning-cli-app"
    data_dir = app_root / "data"
    data_dir.mkdir(parents=True)
    db = data_dir / "bach.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE tasks (id INTEGER PRIMARY KEY,title TEXT)")

    # App.execute is real, while the temporary path and test hook prevent any
    # access to the user DB or global hooks.
    monkeypatch.setattr(sys, "path", list(sys.path))
    app = App(app_root)
    app._db = object()

    class StubHooks:
        last_interceptor_results = []

        @staticmethod
        def emit(*_args, **_kwargs):
            return None

    app.hooks = StubHooks()
    registry = HandlerRegistry()
    registry.register("learning", LearningHandler)
    app._registry = registry

    def analyze(payload, *, db_path, actor, persist):
        service = LearningSourceService(
            db_path, source_roots={"sessions": source.parent},
            skill_roots=[skills], write_guard=lambda: None,
        )
        return service.analyze(payload, actor=actor, persist=persist)

    monkeypatch.setattr(LearningHandler, "analyze_payload", staticmethod(analyze))
    monkeypatch.setattr(bach_api, "_app", app)
    return app, app.get_handler("learning"), request, db, bach_api


@pytest.mark.parametrize("flag", ["--dry-run", "-n"])
@pytest.mark.parametrize("flag_first", [False, True])
def test_learning_handler_dry_run_flags_are_removed_before_path_validation(
        ctx, tmp_path, monkeypatch, flag, flag_first):
    _, handler, request, db, _ = isolated_learning_cli(ctx, tmp_path, monkeypatch)
    before = db.read_bytes()
    args = [flag, str(request)] if flag_first else [str(request), flag]

    for operation in ("analyze", "store"):
        success, message = handler.handle(operation, args, dry_run=False)
        assert success, message
        assert not json.loads(message)["persisted"]
        assert db.read_bytes() == before


def test_learning_handler_rejects_unknown_extra_options(ctx, tmp_path, monkeypatch):
    _, handler, request, db, _ = isolated_learning_cli(ctx, tmp_path, monkeypatch)
    before = db.read_bytes()
    for args in ([str(request), "--unexpected"], ["--unexpected", str(request)],
                 ["--unexpected"]):
        success, message = handler.handle("store", args)
        assert not success and "JSON-Auftragsdatei" in message
    assert db.read_bytes() == before


def test_bach_api_learning_uses_isolated_registry_and_preserves_message_shapes(
        ctx, tmp_path, monkeypatch):
    app, _, request, db, bach_api = isolated_learning_cli(ctx, tmp_path, monkeypatch)
    before = db.read_bytes()

    raw = bach_api.learning.raw("analyze", str(request))
    assert isinstance(raw, tuple) and raw[0]
    assert not json.loads(raw[1])["persisted"]
    analyze_message = bach_api.learning.analyze(str(request), "-n")
    assert isinstance(analyze_message, str)
    assert not json.loads(analyze_message)["persisted"]
    dry_run_message = bach_api.learning.store("--dry-run", str(request))
    assert isinstance(dry_run_message, str)
    assert not json.loads(dry_run_message)["persisted"]
    assert db.read_bytes() == before

    stored_message = bach_api.learning.store(str(request))
    assert isinstance(stored_message, str)
    assert json.loads(stored_message)["persisted"]
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM hermes_skill_candidates").fetchone()[0] == 1

    before_dry_run = db.read_bytes()
    after_path_flag = bach_api.learning.store(str(request), "-n")
    assert isinstance(after_path_flag, str)
    assert not json.loads(after_path_flag)["persisted"]
    assert db.read_bytes() == before_dry_run


def test_deep_session_source_and_proposal_recursion_is_value_error_without_mutation(ctx, monkeypatch):
    from hub._services import learning_source_service as source_service

    svc, data, source, _, db = ctx
    depth = sys.getrecursionlimit() + 200
    source.write_text("[" * depth + "0" + "]" * depth, encoding="utf-8")
    data["source"]["sha256"] = sha(source)
    before = db.read_bytes()
    original_json = source_service.json
    def recursion_loads(_raw):
        raise RecursionError("injected deep source JSON")
    with monkeypatch.context() as parser_patch:
        parser_patch.setattr(source_service, "json", SimpleNamespace(
            dumps=original_json.dumps, loads=recursion_loads))
        with pytest.raises(ValueError, match="verschachtelt"):
            svc.analyze(data, actor="device:7")
    assert db.read_bytes() == before
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='hermes_skill_candidates'").fetchone() is None

    source.write_text(json.dumps({"schema": SOURCE_SCHEMA, "session_id": "depth-check",
        "events": [{"id": "user-1", "role": "user", "content": "Beim nächsten Mal als Skill verwenden."},
                   {"id": "tool-2", "role": "tool", "content": "Prüfung abgeschlossen."}]}, ensure_ascii=False),
        encoding="utf-8")
    data["source"]["sha256"] = sha(source)
    nested = []
    for _ in range(depth):
        nested = [nested]
    data["proposal"]["body"] = nested
    before = db.read_bytes()
    original_encoded = source_service.encoded
    def recursion_encoded(value):
        if value is data:
            raise RecursionError("injected deep proposal encoding")
        return original_encoded(value)
    with monkeypatch.context() as encoder_patch:
        encoder_patch.setattr(source_service, "encoded", recursion_encoded)
        with pytest.raises(ValueError, match="verschachtelt"):
            svc.analyze(data, actor="device:7")
    assert db.read_bytes() == before


def test_learning_cli_reports_deep_request_json_as_readable_error(ctx, tmp_path, monkeypatch):
    from hub import learning as learning_module

    app, _, _, db, _ = isolated_learning_cli(ctx, tmp_path, monkeypatch)
    request = tmp_path / "deep-learning-request.json"
    depth = sys.getrecursionlimit() + 200
    request.write_text("{\"nested\":[" + "[" * depth + "0" + "]" * depth + "]}", encoding="utf-8")
    before = db.read_bytes()
    def recursion_loads(_raw):
        raise RecursionError("injected deep request JSON")
    original_json = learning_module.json
    with monkeypatch.context() as parser_patch:
        parser_patch.setattr(learning_module, "json", SimpleNamespace(
            dumps=original_json.dumps, loads=recursion_loads))
        success, message = app.execute("learning", "analyze", [str(request)])
    assert not success and "zu tief verschachtelt" in message
    assert db.read_bytes() == before


def test_preview_reads_real_sources_without_mutation(ctx):
    svc, data, _, _, db = ctx; before = db.read_bytes()
    result = svc.analyze(data, actor="device:7")
    assert db.read_bytes() == before
    assert result["status"] == "candidate" and not result["persisted"]
    c = result["contract"]
    assert c["extractors"][0]["version"] == "1.3.1"
    assert all(not e["executed"] for e in c["extractors"])
    assert c["events"][0]["locator"]["session_id"] == "example-session"
    assert not c["selection"]["empirically_validated"] and not c["tools_granted"]


@pytest.mark.parametrize("case", ["no-proposal", "no-signal", "covered"])
def test_no_candidate_has_no_schema_or_run_effect(ctx, case):
    svc, data, src, _, db = ctx
    if case == "no-proposal": data["proposal"] = None
    elif case == "no-signal":
        source = json.loads(src.read_text(encoding="utf-8")); source["events"][0]["content"] = "Hallo."
        src.write_text(json.dumps(source), encoding="utf-8"); data["source"]["sha256"] = sha(src)
    else:
        target = read_skill("skill-extractor", roots=svc.skill_roots)
        data["proposal"]["dedup"] = {"decision": "covered", "reason": "Im Bestand abgedeckt",
            "target": target["id"], "basis_version": target["source_version"]}
    before = db.read_bytes(); result = svc.analyze(data, actor="device:7", persist=True)
    assert result["status"] == "no_candidate" and not result["persisted"] and not result["targets_published"]
    assert db.read_bytes() == before


@pytest.mark.parametrize("case", ["unknown-root", "traversal", "absolute", "hash", "event"])
def test_source_authority_and_event_binding(ctx, case):
    svc, data, src, _, _ = ctx
    if case == "unknown-root": data["source"]["root"] = "foreign"
    elif case == "traversal": data["source"]["path"] = "../bounded.json"
    elif case == "absolute": data["source"]["path"] = str(src)
    elif case == "hash": data["source"]["sha256"] = "0" * 64
    else: data["proposal"]["event_ids"] = ["not-read"]
    with pytest.raises((ValueError, PermissionError)): svc.analyze(data, actor="device:7", persist=True)


@pytest.mark.parametrize("root_id", [[], {}, 1, None])
def test_source_root_id_types_fail_with_value_error(ctx, root_id):
    svc, data, *_ = ctx
    data["source"]["root"] = root_id
    with pytest.raises(ValueError, match="Wurzel-ID"):
        svc.analyze(data, actor="device:7")


def test_duplicate_events_and_file_bound(ctx):
    svc, data, src, _, _ = ctx
    v = json.loads(src.read_text(encoding="utf-8")); v["events"].append(v["events"][0])
    src.write_text(json.dumps(v), encoding="utf-8"); data["source"]["sha256"] = sha(src)
    with pytest.raises(ValueError, match="doppeltes"): svc.analyze(data, actor="device:7")
    src.write_text("x" * 1_000_001, encoding="utf-8"); data["source"]["sha256"] = sha(src)
    with pytest.raises(ValueError, match="Lesegrenze"): svc.analyze(data, actor="device:7")


def test_neutralization_stores_only_parameter_definitions(ctx):
    svc, data, _, _, _ = ctx; value = r"C:\Users\Example\project"
    data["proposal"]["body"] += f"\nLies {value}.\n"
    data["proposal"]["parameters"] = [{"name": "PROJECT_ROOT", "value": value, "description": "Zielprojektwurzel"}]
    result = svc.analyze(data, actor="device:7", persist=True)
    row = HermesDistillationService(svc.db_path).get_candidate(result["candidate_id"])
    assert value not in row["proposal_json"] and "<PROJECT_ROOT>" in row["content"]
    assert row["review_available"] and row["confidence"] is None


@pytest.mark.parametrize("leak", [r"C:\Users\Example\project", "/Users/example/project", "example@example.org", "api_key=secret"])
def test_private_or_secret_proposal_is_rejected(ctx, leak):
    svc, data, _, _, _ = ctx; data["proposal"]["body"] += "\n" + leak
    with pytest.raises(ValueError, match="neutralisierte"): svc.analyze(data, actor="device:7", persist=True)


@pytest.mark.parametrize("key", [
    "api_key", "apiKey", "password", "access_token", "client-secret",
    "Authorization", "private_key",
])
def test_nested_credential_fields_are_rejected(ctx, key):
    svc, data, *_ = ctx
    data["proposal"]["body"] = {"nested": {key: "credential-value"}}
    with pytest.raises(ValueError, match="Credentialfelder"):
        svc.analyze(data, actor="device:7")


@pytest.mark.parametrize("name", ["API_KEY", "ACCESS_TOKEN", "CLIENT_SECRET"])
def test_credential_parameter_names_are_rejected(ctx, name):
    svc, data, *_ = ctx
    data["proposal"]["parameters"] = [{
        "name": name, "value": "secret-value", "description": "Kein übernehmbarer Parameter",
    }]
    with pytest.raises(ValueError, match="Credentials"):
        svc.analyze(data, actor="device:7")


@pytest.mark.parametrize("body", [
    "---\nname: source-check\nversion: 1.0.0\n# Abschluss fehlt\n",
    "---\nname: another-skill\nversion: 1.0.0\n---\nInhalt\n",
    "---\nname: [broken\nversion: 1.0.0\n---\nInhalt\n",
    "---\nname: source-check\n---\nInhalt\n",
    "---\nname: source-check\nversion: 1.0.0\n---\n \n",
])
def test_skill_frontmatter_identity_and_body_are_required(ctx, body):
    svc, data, *_ = ctx
    data["proposal"]["body"] = body
    with pytest.raises(ValueError):
        svc.analyze(data, actor="device:7")


def test_skill_frontmatter_version_is_persisted(ctx):
    svc, data, *_ = ctx
    data["proposal"]["body"] = (
        "---\nname: source-check\nversion: 2.3.4\n---\n# Quellen prüfen\nVersion gebunden.\n"
    )
    result = svc.analyze(data, actor="device:7", persist=True)
    row = HermesDistillationService(svc.db_path).get_candidate(result["candidate_id"])
    assert row["version"] == "2.3.4"


def test_mentioned_guidance_reference_hash_changes_contract(ctx):
    svc, data, _, skills, _ = ctx
    guide = skills / "skill-extractor" / "SKILL.md"
    guide.write_text(guide.read_text(encoding="utf-8") + "\nSiehe neutralisierung.md.\n", encoding="utf-8")
    reference = guide.parent / "neutralisierung.md"
    reference.write_text("Regelstand eins.\n", encoding="utf-8")
    first = svc.analyze(data, actor="device:7")
    reference.write_text("Regelstand zwei.\n", encoding="utf-8")
    second = svc.analyze(data, actor="device:7")
    assert first["contract"]["extractors"][0]["references"][0]["sha256"] != \
        second["contract"]["extractors"][0]["references"][0]["sha256"]
    assert first["contract_digest"] != second["contract_digest"]


@pytest.mark.parametrize("revision", [True, 1.0, "1", None, 0, -1])
def test_cas_revision_requires_positive_exact_int(ctx, revision):
    svc, data, *_ = ctx
    data.update(expected_revision=revision, expected_digest="0" * 64)
    with pytest.raises(ValueError, match="CAS"):
        svc.analyze(data, actor="device:7")


@pytest.mark.parametrize("field,value", [
    ("expected_revision", 1), ("expected_digest", "0" * 64),
])
def test_cas_fields_must_be_supplied_together(ctx, field, value):
    svc, data, *_ = ctx
    data[field] = value
    with pytest.raises(ValueError, match="CAS"):
        svc.analyze(data, actor="device:7")


@pytest.mark.parametrize("candidate_digest", ["0" * 63, "0" * 65, "A" * 64, "g" * 64])
def test_cas_digest_requires_full_lowercase_sha256(ctx, candidate_digest):
    svc, data, *_ = ctx
    data.update(expected_revision=1, expected_digest=candidate_digest)
    with pytest.raises(ValueError, match="CAS"):
        svc.analyze(data, actor="device:7")


def test_identical_source_replays_and_revision_requires_cas(ctx):
    svc, data, _, _, db = ctx
    first = svc.analyze(data, actor="device:7", persist=True)
    again = svc.analyze(data, actor="device:8", persist=True)
    assert again["candidate_id"] == first["candidate_id"] and again["replayed"]
    data["proposal"]["body"] += "\nBeleg nachher erneut lesen.\n"
    with pytest.raises(LearningConflict): svc.analyze(data, actor="device:7", persist=True)
    data.update(expected_revision=first["candidate_revision"], expected_digest=first["candidate_digest"])
    revised = svc.analyze(data, actor="device:7", persist=True)
    assert revised["candidate_revision"] == 2
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM hermes_skill_candidates").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM memory_lessons").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM skill_versions").fetchone()[0] == 0


def test_tampered_prior_contract_cannot_be_revised(ctx):
    svc, data, _, _, db = ctx
    result = svc.analyze(data, actor="device:7", persist=True)
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE hermes_skill_candidates SET candidate_contract_json='{}' WHERE id=?",
                     (result["candidate_id"],))
    data["proposal"]["body"] += "\nNeue Prüfregel.\n"
    data.update(expected_revision=result["candidate_revision"], expected_digest=result["candidate_digest"])
    with pytest.raises(LearningConflict, match="nicht verifizierbar"):
        svc.analyze(data, actor="device:7", persist=True)
    row = HermesDistillationService(db).get_candidate(result["candidate_id"])
    assert row["candidate_revision"] == 1 and row["review_state"] == "legacy_unverified"


def test_disappeared_update_row_conflicts_without_recreation(ctx):
    svc, data, _, _, db = ctx
    first = svc.analyze(data, actor="device:7", persist=True)
    data["proposal"]["body"] += "\nRevision nach CAS.\n"
    data.update(expected_revision=first["candidate_revision"], expected_digest=first["candidate_digest"])
    with sqlite3.connect(db) as conn:
        conn.execute("""CREATE TRIGGER vanish_candidate_after_update
            AFTER UPDATE ON hermes_skill_candidates
            WHEN OLD.name='source-check'
            BEGIN DELETE FROM hermes_skill_candidates WHERE id=OLD.id; END""")
    with pytest.raises(LearningConflict, match="verschwunden"):
        svc.analyze(data, actor="device:7", persist=True)
    with sqlite3.connect(db) as conn:
        rows = conn.execute("SELECT id,candidate_revision FROM hermes_skill_candidates").fetchall()
    assert rows == [(first["candidate_id"], 1)]


def test_contract_tamper_invalidates_review(ctx):
    svc, data, _, _, db = ctx; result = svc.analyze(data, actor="device:7", persist=True)
    with sqlite3.connect(db) as conn: conn.execute("UPDATE hermes_skill_candidates SET candidate_contract_json='{}'")
    row = HermesDistillationService(db).get_candidate(result["candidate_id"])
    assert not row["review_available"] and row["review_state"] == "legacy_unverified"


def test_extension_basis_is_actually_read(ctx):
    svc, data, _, skills, _ = ctx; target = read_skill("skill-extractor", roots=[skills])
    data["proposal"]["dedup"] = {"decision": "extend", "target": target["id"],
        "basis_version": target["source_version"], "reason": "Ergänzt Quellenbindung"}
    result = svc.analyze(data, actor="device:7")
    assert result["contract"]["basis_version"] == target["source_version"]
    (skills / "skill-extractor" / "SKILL.md").write_text(target["content"] + "\nNeue Fassung.\n", encoding="utf-8")
    with pytest.raises(LearningConflict, match="Basisversion"): svc.analyze(data, actor="device:7")


def test_concurrent_identical_import_keeps_one_candidate(ctx):
    svc, data, _, _, db = ctx
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(lambda _: svc.analyze(copy.deepcopy(data), actor="device:7", persist=True), range(2)))
    assert len({r["candidate_id"] for r in replies}) == 1
    assert sorted(r["replayed"] for r in replies) == [False, True]


def test_native_hermes_manifest_and_limit_of_its_evidence(ctx):
    svc, data, _, _, _ = ctx; root = svc.roots["sessions"]
    skill = root / "SKILL.md"; skill.write_text("---\nname: example\n---\nPflegebeleg.\n", encoding="utf-8")
    entry_id = "123456abcdef"; ledger = root / "ledger.jsonl"
    ledger.write_text(json.dumps({"id": entry_id, "actor": "curator", "action": "edit", "skill": "example",
        "evidence": {"session_id": "hermes-session"}, "before": [],
        "after": [{"path": str(skill), "sha256": sha(skill)}]}) + "\n", encoding="utf-8")
    data["source"] = {"kind": "hermes_ledger", "root": "sessions", "path": ledger.name,
                      "sha256": sha(ledger), "entry_id": entry_id}
    data["proposal"]["event_ids"] = [entry_id]; result = svc.analyze(data, actor="device:7")
    p = result["contract"]["source"]["provenance"]
    assert p["evidence_kind"] == "native_hermes_mutation_manifest" and not p["ledger_is_authorization"]
    skill.write_text("Andere Fassung", encoding="utf-8")
    with pytest.raises(LearningConflict): svc.analyze(data, actor="device:7")


def test_chain_draft_uses_native_definition_without_activating(ctx):
    svc, data, _, _, db = ctx
    data["proposal"].update(kind="chain", body={"name": "source-check", "mode": "agents", "steps": [
        {"label": "Quelle prüfen", "agent_slot": "reviewer", "skill_ids": [], "instructions": "Hash vergleichen."}]})
    result = svc.analyze(data, actor="device:7", persist=True)
    assert result["provider"] == "nemofold"
    from hub._services.chat.sequence_store import SequenceStore
    assert SequenceStore(db).chains() == []
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM nemofold_workflow_candidates").fetchone()[0] == 1
    data["proposal"]["body"]["steps"][0] = {"step_index": 0, "name": "Legacy"}
    with pytest.raises(ValueError): svc.analyze(data, actor="device:7")


def test_chain_candidate_name_must_match_native_definition(ctx):
    svc, data, *_ = ctx
    data["proposal"].update(kind="chain", body={"name": "other-chain", "mode": "agents", "steps": [
        {"label": "Quelle prüfen", "agent_slot": "reviewer", "skill_ids": [],
         "instructions": "Hash vergleichen."}]})
    with pytest.raises(ValueError, match="Kettenidentität"):
        svc.analyze(data, actor="device:7")


def test_native_nemofold_reader_receipt_and_version_are_bound(ctx, tmp_path):
    svc, data, nemofold, voyages, saved, voyage, receipt = native_voyage(ctx, tmp_path)
    result = svc.analyze(data, actor="device:7")
    provenance = result["contract"]["source"]["provenance"]
    assert provenance["evidence_kind"] == "native_nemofold_saved_plan"
    assert provenance["reader_sha256"] == sha(Path(voyages.__file__))
    assert provenance["receipt_sha256"] == sha(receipt)
    assert provenance["provider_version"] == nemofold.__version__
    assert provenance["executed"] is False
    assert result["contract"]["events"][0]["locator"]["voyage_id"] == saved["voyage_id"]
    assert voyage.is_file()


@pytest.mark.parametrize("case", ["missing", "wrong"])
def test_native_nemofold_missing_or_wrong_receipt_is_rejected(ctx, tmp_path, case):
    svc, data, _, _, _, _, receipt = native_voyage(ctx, tmp_path)
    if case == "missing":
        receipt.unlink()
    else:
        value = json.loads(receipt.read_text(encoding="utf-8"))
        value["sha256"] = "0" * 64
        receipt.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError):
        svc.analyze(data, actor="device:7")


def test_native_nemofold_receipt_swap_after_original_load_conflicts(ctx, tmp_path, monkeypatch):
    svc, data, _, voyages, saved, _, receipt = native_voyage(ctx, tmp_path)
    original_load = voyages.VoyageStore.load
    calls = []

    def load_then_change_receipt(store, voyage_id, *, require_receipt=False):
        result = original_load(store, voyage_id, require_receipt=require_receipt)
        calls.append(voyage_id)
        receipt.write_bytes(receipt.read_bytes() + b"\n")
        return result

    monkeypatch.setattr(voyages.VoyageStore, "load", load_then_change_receipt)
    with pytest.raises(LearningConflict, match="geändert"):
        svc.analyze(data, actor="device:7")
    assert calls == [saved["voyage_id"]]


def test_native_nemofold_wrong_payload_id_conflicts_with_matching_hashes(ctx, tmp_path):
    svc, data, _, _, saved, voyage, receipt = native_voyage(ctx, tmp_path)
    value = json.loads(voyage.read_text(encoding="utf-8"))
    value["voyage_id"] = "different-voyage"
    voyage.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    receipt_value = json.loads(receipt.read_text(encoding="utf-8"))
    receipt_value["sha256"] = sha(voyage)
    receipt.write_text(json.dumps(receipt_value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    data["source"]["sha256"] = sha(voyage)
    with pytest.raises(LearningConflict, match="Voyageidentität"):
        svc.analyze(data, actor="device:7")
    assert saved["voyage_id"] != "different-voyage"


def test_http_auth_precedes_source_read(ctx, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from gui.api import unified_api
    from hub.learning import LearningHandler
    svc, data, _, _, db = ctx
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE devices (id INTEGER PRIMARY KEY,token_hash TEXT,status TEXT)")
        conn.execute("INSERT INTO devices VALUES (7,?,'active')", (hashlib.sha256(b"isolated-test-token").hexdigest(),))
    monkeypatch.setattr(unified_api, "BACH_DB", db); calls = []
    def run(payload, **kwargs):
        calls.append(kwargs); return svc.analyze(payload, actor=kwargs["actor"], persist=kwargs["persist"])
    monkeypatch.setattr(LearningHandler, "analyze_payload", staticmethod(run))
    app = FastAPI(); app.include_router(unified_api.router); client = TestClient(app)
    for endpoint in ("analyze", "store"):
        assert client.post("/api/learning/sources/" + endpoint, json=data).status_code == 401
    assert calls == []
    result = client.post("/api/learning/sources/store", json=data, headers={"Authorization": "Bearer isolated-test-token"})
    assert result.status_code == 200 and calls[0]["actor"] == "device:7"
    assert result.json()["persisted"] and not result.json()["targets_published"]
