from pathlib import Path

import pytest

from hub._services import skill_source_service as source
from hub._services.chat import slots_config


def make_skill(root, name="example", text="Erstelle einen ausführlichen Überblick.\n"):
    target = root / "dev" / name / "SKILL.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("---\nname: Example\nversion: v2.3.1\ndescription: Aktuelle Anleitung\n---\n" + text, encoding="utf-8")
    return target


def test_catalog_uses_real_version_and_excludes_archive(tmp_path):
    make_skill(tmp_path)
    make_skill(tmp_path / "_archive", "stale")
    catalog = source.source_catalog([tmp_path])
    assert set(catalog) == {"example"}
    assert catalog["example"]["version"] == "v2.3.1"
    assert len(catalog["example"]["source_version"]) == 64


def test_skill_symbol_is_current_source_metadata_and_part_of_historical_version(tmp_path, monkeypatch):
    own = tmp_path / 'own'
    monkeypatch.setenv('BACH_USER_SKILLS_ROOT', str(own))
    first = '---\nname: Grüße\nsymbol: wissen\n---\n# Inhalt\n'
    saved = source.save_skill('example', first, '0', roots=[], write_root=own, guard=lambda p: None)
    assert saved['symbol'] == 'wissen'
    source.save_skill('example', first.replace('wissen', 'scripts'), saved['source_version'],
                      roots=[own], write_root=own, guard=lambda p: None)
    assert source.read_skill_history('example', saved['source_version'])['symbol'] == 'wissen'


def test_pinned_skill_content_is_in_actual_worker_prompt(tmp_path, monkeypatch):
    root = tmp_path / "skills"
    make_skill(root, text="Nutze echte Umlaute: ä ö ü ß.\n")
    monkeypatch.setattr(source, "skill_roots", lambda: [root])
    pins = source.pin_skills(["example"])
    prompt = slots_config.compose_worker_prompt({"include_system_prompt": False, "skill_refs": pins})
    assert "Nutze echte Umlaute: ä ö ü ß." in prompt
    assert pins[0]["source_version"] in prompt
    assert "ändern keine Werkzeugfreigaben" in prompt


def test_changed_source_revokes_pin(tmp_path):
    path = make_skill(tmp_path)
    pins = source.pin_skills(["example"], roots=[tmp_path])
    path.write_text("Neue Anleitung", encoding="utf-8")
    with pytest.raises(RuntimeError, match="neu einrichten"):
        source.load_skill_instructions(pins, roots=[tmp_path])


@pytest.mark.parametrize("pins", [None, {}, False, ["example"], [{"id": "example"}]])
def test_malformed_bindings_are_rejected(pins):
    with pytest.raises(ValueError):
        source.load_skill_instructions(pins, roots=[])


def test_declared_skill_has_no_fake_instructions(tmp_path):
    with pytest.raises(ValueError, match="keine ausführbare"):
        source.pin_skills(["git-hygiene"], roots=[tmp_path])


def test_editor_reads_factory_and_saves_versioned_local_override(tmp_path):
    factory = tmp_path / "factory"
    own = tmp_path / "own"
    original = make_skill(factory)
    old_bytes = original.read_bytes()
    current = source.read_skill("example", roots=[factory])
    guards = []
    saved = source.save_skill("example", current["content"] + "\nNeue Prüfung.\n", current["source_version"],
                             roots=[factory], write_root=own, guard=lambda p: guards.append(p))
    assert original.read_bytes() == old_bytes
    assert saved["content"].endswith("Neue Prüfung.\n")
    assert saved["source_path"] == str(own / "example/SKILL.md")
    assert saved["receipt"] == {"source_saved": True, "tools_granted": False, "agent_started": False}
    assert (own / ".history/example" / (current["source_version"] + ".md")).read_bytes() == old_bytes
    assert len(guards) >= 4
    with pytest.raises(RuntimeError, match="conflict"):
        source.save_skill("example", "Veraltet", current["source_version"], roots=[factory], write_root=own, guard=lambda p: None)


def test_create_is_cas_and_never_overwrites_existing_skill(tmp_path):
    saved = source.save_skill("new-skill", "# Ablauf\n1. Lesen.\n", "0", roots=[], write_root=tmp_path, guard=lambda p: None)
    assert saved["previous_version"] == "0"
    with pytest.raises(RuntimeError, match="conflict"):
        source.save_skill("new-skill", "Andere Anleitung", "0", roots=[], write_root=tmp_path, guard=lambda p: None)


def test_unknown_lock_state_prevents_all_writes(tmp_path):
    target = tmp_path / "own"
    def blocked(path):
        raise PermissionError("Ungeprüft")
    with pytest.raises(PermissionError):
        source.save_skill("new-skill", "Ablauf", "0", roots=[], write_root=target, guard=blocked)
    assert not target.exists()


def test_symlink_escape_is_not_catalogued(tmp_path):
    outside = tmp_path / "outside.md"
    outside.write_text("Private Anleitung", encoding="utf-8")
    root = tmp_path / "skills"
    skill = root / "example"
    skill.mkdir(parents=True)
    try:
        (skill / "SKILL.md").symlink_to(outside)
    except OSError:
        pytest.skip("Symlinks auf diesem Host nicht verfügbar")
    assert source.source_catalog([root]) == {}


def test_prompt_budget_fails_instead_of_truncating_instructions(tmp_path):
    make_skill(tmp_path, text="x" * (source.MAX_PROMPT_CHARS + 1))
    with pytest.raises(ValueError, match="Promptbudget"):
        source.pin_skills(["example"], roots=[tmp_path])


def test_duplicate_pins_and_relative_write_roots_are_rejected(tmp_path, monkeypatch):
    make_skill(tmp_path)
    pin = source.pin_skills(["example"], roots=[tmp_path])[0]
    with pytest.raises(ValueError): source.load_skill_instructions([pin, pin], roots=[tmp_path])
    monkeypatch.setenv("BACH_USER_SKILLS_ROOT", "relative/path")
    with pytest.raises(ValueError, match="absolut"): source.user_skills_root()


def test_ancestor_symlink_blocks_writes(tmp_path):
    actual = tmp_path / "actual"
    actual.mkdir()
    link = tmp_path / "link"
    try: link.symlink_to(actual, target_is_directory=True)
    except OSError: pytest.skip("Symlinks auf diesem Host nicht verfügbar")
    with pytest.raises(PermissionError):
        source.save_skill("new-skill", "Ablauf", "0", roots=[], write_root=link / "nested", guard=lambda p: None)
    assert list(actual.iterdir()) == []


def test_history_symlink_cannot_modify_foreign_content(tmp_path):
    original = make_skill(tmp_path / "factory")
    own = tmp_path / "own"
    own.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    try: (own / ".history").symlink_to(outside, target_is_directory=True)
    except OSError: pytest.skip("Symlinks auf diesem Host nicht verfügbar")
    current = source.read_skill("example", roots=[tmp_path / "factory"])
    with pytest.raises(PermissionError):
        source.save_skill("example", "Andere Anleitung", current["source_version"],
            roots=[tmp_path / "factory"], write_root=own, guard=lambda p: None)
    assert list(outside.iterdir()) == [] and original.read_text(encoding="utf-8") == current["content"]


def test_two_editors_have_only_one_successful_cas_write(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    own = tmp_path / "own"
    first = source.save_skill("example", "Erste Anleitung", "0", roots=[], write_root=own, guard=lambda p: None)
    def save(text):
        try:
            return source.save_skill("example", text, first["source_version"], roots=[], write_root=own, guard=lambda p: None)
        except RuntimeError as exc:
            return str(exc)
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(save, ["Zweite Anleitung", "Dritte Anleitung"]))
    assert sum(isinstance(outcome, dict) for outcome in outcomes) == 1
    assert outcomes.count("skill_source_version_conflict") == 1
    assert source.read_skill("example", roots=[own])["content"] in {"Zweite Anleitung", "Dritte Anleitung"}


def test_skill_change_revokes_foreground_slot_tools(tmp_path, monkeypatch):
    from hub._services.chat.chat_runtime import ChatSession, ChatRuntime, FailedAnswer
    root = tmp_path / "skills"
    skill = make_skill(root)
    monkeypatch.setattr(source, "skill_roots", lambda: [root])
    slot = {"id": "owned-slot", "enabled": True, "skill_refs": source.pin_skills(["example"])}
    session = ChatSession()
    session.system_slot_id = "owned-slot"
    session.system_slot_reader = lambda: slot
    session.system_slot_configuration = {"enabled": True}
    assert ChatRuntime._refresh_worker_tools(session) is None
    skill.write_text("Geänderte Anleitung", encoding="utf-8")
    assert isinstance(ChatRuntime._refresh_worker_tools(session), FailedAnswer)
    assert session.allow_tools is False


def test_dynamic_worker_keeps_skill_and_tool_bindings_in_configuration(tmp_path, monkeypatch):
    root = tmp_path / "skills"
    make_skill(root)
    monkeypatch.setattr(source, "skill_roots", lambda: [root])
    path = str(tmp_path / "slots.json")
    slots_config.initialize_slots_config(path)
    refs = source.pin_skills(["example"])
    worker = slots_config.add_worker({"name": "Eigener Worker", "task_prompt": "Prüfe den Auftrag.", "skill_refs": refs,
        "allowed_tools": ["read_file"]}, path)
    assert worker["skill_refs"] == refs and worker["allowed_tools"] == ["read_file"]
    assert "Erstelle einen ausführlichen Überblick." in worker["system_prompt"]
    before = slots_config.worker_configuration_snapshot(worker["id"], path=path)
    slots_config.change_worker_configuration(worker["id"], before["configuration_version"],
        {"allowed_tools": ["task_manage"]}, path=path)
    assert slots_config.worker_configuration_snapshot(worker["id"], path=path)["configuration_version"] != before["configuration_version"]
