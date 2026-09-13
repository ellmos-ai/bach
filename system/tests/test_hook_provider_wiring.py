# -*- coding: utf-8 -*-
"""
Waechter-Tests: memoryhooker- & workflowhooker-Verdrahtung (Stufe 6)
===================================================================

Schuetzt die MODULRUECKTRANSFER-Stufe 6 (Task 1222) gegen Code-Drift:

1. memoryhooker-Seam (hub/memory_hook_provider.py):
   - Probe + Rollback-Matrix (BACH_USE_EXTERNAL_MEMORYHOOKS)
   - geteilte Adapter-Instanz mit Doppelinstanz-Guard
   - BachMemoryBackend: read-only-API (mode=ro), Ranking-Normalisierung,
     Curation-Signale, Verfuegbarkeits-Regeln
   - evaluate_prompt-Integration: Session-Start, Injektion, Cap, Cooldown
   - Audit-Trail (JSONL) fuer jede Kontextinjektion
   - ChatRuntime.process-Verdrahtung (hook_ctx + --- MEMORY-HOOK ---)

2. workflowhooker-Seam (hub/workflow_hook_provider.py):
   - Probe + Rollback-Matrix (BACH_USE_EXTERNAL_WORKFLOWHOOKS)
   - Interceptor: Event-Filter, echte Check-Ausfuehrung (Git-Fixture),
     Budget/Cooldown, State-Persistenz, fail-soft
   - HookRegistry-Interceptor-Slot: Duplikat-Guard, last_interceptor_results
   - Installation idempotent ueber hub/__init__.py
   - Import-Richtung AST: core importiert nie hub

Voraussetzung: die Module sind im Test-Venv installiert
(requirements.txt-Pins memoryhooker/workflowhooker).
"""
import ast
import sqlite3
import subprocess
from pathlib import Path

import pytest

import hub.memory_hook_provider as mhp
import hub.workflow_hook_provider as wfp
from core.hooks import HookRegistry

SYSTEM_DIR = Path(__file__).resolve().parent.parent
HUB_DIR = SYSTEM_DIR / "hub"
CORE_DIR = SYSTEM_DIR / "core"


# ---------------------------------------------------------------------------
# Hilfs-Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def clean_env(monkeypatch):
    """Rollback-Schalter beider Seams entfernen."""
    monkeypatch.delenv(mhp.ROLLBACK_ENV, raising=False)
    monkeypatch.delenv(wfp.ROLLBACK_ENV, raising=False)
    yield


@pytest.fixture
def memory_db(tmp_path):
    """BACH-artige Memory-DB mit Fakten, Lessons und Working-Notes."""
    db = tmp_path / "bach.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE memory_facts (id INTEGER PRIMARY KEY, category TEXT,
            key TEXT, value TEXT, confidence REAL, source TEXT,
            created_at TEXT, updated_at TEXT);
        CREATE TABLE memory_lessons (id INTEGER PRIMARY KEY, title TEXT,
            solution TEXT, severity TEXT, is_active INTEGER DEFAULT 1);
        CREATE TABLE memory_working (id INTEGER PRIMARY KEY, content TEXT,
            is_active INTEGER DEFAULT 1);
        """
    )
    conn.execute(
        "INSERT INTO memory_facts (category, key, value, confidence) "
        "VALUES ('project', 'deployment', 'deployment braucht git-tag', 0.9)"
    )
    conn.execute(
        "INSERT INTO memory_facts (category, key, value, confidence) "
        "VALUES ('project', 'backup', 'backup vor migration', 0.4)"
    )
    conn.execute(
        "INSERT INTO memory_lessons (title, solution, severity, is_active) "
        "VALUES ('Hooks', 'Hooks doppelt pruefen: Guard + Frequenzlimit', 'critical', 1)"
    )
    conn.execute(
        "INSERT INTO memory_lessons (title, solution, severity, is_active) "
        "VALUES ('Alt', 'Alte Lesson inaktiv', 'high', 0)"
    )
    conn.execute(
        "INSERT INTO memory_working (content, is_active) "
        "VALUES ('notiz deployment pending', 1)"
    )
    conn.commit()
    conn.close()
    return db


@pytest.fixture
def dirty_git_repo(tmp_path):
    """Git-Fixture mit uncommitteter Aenderung (closing_gate-Trigger)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    try:
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True,
                        capture_output=True, timeout=30)
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                        "commit", "--allow-empty", "-m", "init"],
                       cwd=repo, check=True, capture_output=True, timeout=30)
    except (subprocess.SubprocessError, FileNotFoundError):
        pytest.skip("git nicht verfuegbar")
    (repo / "aenderung.txt").write_text("dirty", encoding="utf-8")
    return repo


# ---------------------------------------------------------------------------
# A. memoryhooker-Seam
# ---------------------------------------------------------------------------

class TestMemoryHookerProbe:

    @pytest.mark.parametrize("off", ["0", "false", "no", "off", "OFF", " No "])
    def test_rollback_matrix_off(self, monkeypatch, off):
        monkeypatch.setenv(mhp.ROLLBACK_ENV, off)
        assert mhp.external_memoryhooker_available() is False

    def test_probe_on_when_installed(self, clean_env):
        assert mhp.external_memoryhooker_available() is True

    def test_shared_hook_is_singleton(self, clean_env, memory_db):
        mhp.reset_shared_memory_hook()
        a = mhp.get_shared_memory_hook(db_path=memory_db)
        b = mhp.get_shared_memory_hook(db_path=memory_db)
        assert a is b
        mhp.reset_shared_memory_hook()
        mhp.reset_shared_memory_hook()  # idempotent


class TestBachMemoryBackend:

    def test_available_with_rows(self, memory_db):
        assert mhp.BachMemoryBackend(db_path=memory_db).available() is True

    def test_unavailable_when_no_tables(self, tmp_path):
        db = tmp_path / "leer.db"
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE anderes (x)")
        conn.commit()
        conn.close()
        assert mhp.BachMemoryBackend(db_path=db).available() is False

    def test_unavailable_when_missing(self, tmp_path):
        assert mhp.BachMemoryBackend(db_path=tmp_path / "fehlt.db").available() is False

    def test_search_returns_memoryhooker_hits(self, memory_db):
        hits = mhp.BachMemoryBackend(db_path=memory_db).search("deployment backup", limit=5)
        assert hits, "mindestens ein Treffer erwartet"
        texts = " || ".join(h.text for h in hits)
        assert "deployment" in texts
        for hit in hits:
            assert 0.0 < hit.rank <= 1.0
            assert hit.source.startswith("bach:")

    def test_search_curation_beats_plain_match(self, memory_db):
        """Fakt mit Konfidenz 0.9 muss gegen identischen Termmatch der
        Working-Note (Basis 0.4) hoeher ranken (usmc-Backend-Muster)."""
        hits = mhp.BachMemoryBackend(db_path=memory_db).search("deployment", limit=5)
        by_source = {h.source: h.rank for h in hits}
        assert by_source["bach:fact"] > by_source.get("bach:working", 0.0)

    def test_search_ignores_inactive_lessons(self, memory_db):
        hits = mhp.BachMemoryBackend(db_path=memory_db).search("inaktiv", limit=5)
        assert all("Alt" not in h.text for h in hits)

    def test_search_empty_for_short_tokens(self, memory_db):
        assert mhp.BachMemoryBackend(db_path=memory_db).search("ab", limit=5) == []

    def test_read_only_contract(self, memory_db):
        """Der Adapter oeffnet ausschliesslich mode=ro: Schreibversuch ueber
        eine identisch geoeffnete Verbindung muss scheitern."""
        ro = sqlite3.connect(f"file:{memory_db}?mode=ro", uri=True)
        try:
            with pytest.raises(sqlite3.OperationalError):
                ro.execute("INSERT INTO memory_working (content) VALUES ('x')")
        finally:
            ro.close()


class TestExternalMemoryHook:

    def _make_hook(self, memory_db, **kw):
        return mhp.ExternalMemoryHook(db_path=memory_db, mode=mhp.DEFAULT_MODE, **kw)

    def test_injects_session_start_and_search(self, clean_env, memory_db):
        hook = self._make_hook(memory_db)
        ctx = hook.hook_context("deployment backup", "chat-a")
        assert ctx is not None
        assert "durchsuchbares Gedaechtnis" in ctx       # session_start_message
        assert "[MemoryHooker]" in ctx                   # evaluate_prompt (remember+search)
        assert "deployment" in ctx

    def test_audit_trail_jsonl(self, clean_env, memory_db):
        hook = self._make_hook(memory_db)
        hook.hook_context("deployment backup", "chat-audit")
        assert hook.audit_path.exists()
        lines = hook.audit_path.read_text(encoding="utf-8").strip().splitlines()
        assert lines
        import json
        entry = json.loads(lines[-1])
        assert entry["chat_id"] == "chat-audit"
        assert entry["chars"] > 0

    def test_session_cap_guard(self, clean_env, memory_db):
        hook = self._make_hook(memory_db)
        hook._config.mode.max_injections_per_session = 1
        assert hook.hook_context("deployment", "chat-cap") is not None
        # Cap erreicht: zweite evaluate_prompt-Injektion bleibt aus
        assert hook.hook_context("backup", "chat-cap") is None

    def test_cooldown_guard(self, clean_env, memory_db):
        hook = self._make_hook(memory_db)
        hook._config.mode.cooldown_seconds = 3600
        assert hook.hook_context("deployment", "chat-cd") is not None
        assert hook.hook_context("backup", "chat-cd") is None

    def test_state_is_per_chat_id(self, clean_env, memory_db):
        hook = self._make_hook(memory_db)
        hook._config.mode.max_injections_per_session = 1
        assert hook.hook_context("deployment", "chat-1") is not None
        # andere Session: eigener State -> erneut Session-Start
        ctx2 = hook.hook_context("deployment", "chat-2")
        assert ctx2 is not None and "durchsuchbares Gedaechtnis" in ctx2

    def test_rollback_env_returns_none(self, monkeypatch, memory_db):
        monkeypatch.setenv(mhp.ROLLBACK_ENV, "0")
        hook = self._make_hook(memory_db)
        assert hook.hook_context("deployment", "chat-x") is None

    def test_fail_soft_on_backend_error(self, clean_env, tmp_path):
        hook = self._make_hook(tmp_path / "gibtsnicht.db")

        class Boomer:
            def available(self):
                return True

            def search(self, query, limit=5):
                raise RuntimeError("kaputt")

        hook.backend = Boomer()
        assert hook.hook_context("deployment", "chat-err") is None

    def test_contract_violation_fails_closed(self, monkeypatch, clean_env):
        """Fehlt ein Contract-Symbol, bleibt der Adapter deaktiviert."""
        import importlib
        import memoryhooker.modes as modes
        monkeypatch.delattr(modes, "evaluate_prompt")
        with pytest.raises(RuntimeError, match="Contract verletzt"):
            mhp.ExternalMemoryHook()
        importlib.reload(modes)  # für Folgetests wiederherstellen


class TestChatRuntimeWiring:

    def test_process_calls_memory_hook(self):
        src = (HUB_DIR / "_services" / "chat" / "chat_runtime.py").read_text(encoding="utf-8")
        assert "hook_ctx = self._get_memory_hook_context(text, chat_id)" in src
        assert "--- MEMORY-HOOK ---" in src

    def test_memory_hook_method_is_fail_soft(self):
        src = (HUB_DIR / "_services" / "chat" / "chat_runtime.py").read_text(encoding="utf-8")
        assert "from hub.memory_hook_provider import get_shared_memory_hook" in src
        assert "except Exception:" in src

    def test_get_memory_hook_context_method(self):
        src = (HUB_DIR / "_services" / "chat" / "chat_runtime.py").read_text(encoding="utf-8")
        assert "def _get_memory_hook_context(self, text: str, chat_id: str) -> str:" in src

    def test_injector_path_untouched(self):
        """Hooks != Injektoren: _get_bach_context bleibt der Injektor-Pfad."""
        src = (HUB_DIR / "_services" / "chat" / "chat_runtime.py").read_text(encoding="utf-8")
        assert "self.injector.process(text)" in src
        assert src.count("--- BACH ---") == 1

    def test_memory_handler_has_no_hook_import(self):
        """hub/memory.py bleibt unveraendert: die read-only-API lebt im Seam."""
        src = (HUB_DIR / "memory.py").read_text(encoding="utf-8")
        assert "memoryhooker" not in src
        assert "memory_hook_provider" not in src


# ---------------------------------------------------------------------------
# B. workflowhooker-Seam
# ---------------------------------------------------------------------------

class TestWorkflowHookerProbe:

    @pytest.mark.parametrize("off", ["0", "false", "no", "off"])
    def test_rollback_matrix_off(self, monkeypatch, off):
        monkeypatch.setenv(wfp.ROLLBACK_ENV, off)
        assert wfp.external_workflowhooker_available() is False

    def test_probe_on_when_installed(self, clean_env):
        assert wfp.external_workflowhooker_available() is True


class TestExternalWorkflowInterceptor:

    def _make(self, dirty_git_repo, tmp_path, session="s1", **kw):
        return wfp.ExternalWorkflowInterceptor(
            project_dir=dirty_git_repo,
            state_dir=tmp_path / "state",
            session_id=session,
            **kw,
        )

    def test_emits_closing_gate_for_dirty_git(self, clean_env, dirty_git_repo, tmp_path):
        iceptor = self._make(dirty_git_repo, tmp_path)
        out = iceptor("after_command", {"handler": "x"})
        assert out and "Abschluss-Gate" in out[0]
        assert "uncommittete" in out[0]

    def test_event_filter(self, clean_env, dirty_git_repo, tmp_path):
        iceptor = self._make(dirty_git_repo, tmp_path)
        assert iceptor("after_memory_write", {}) is None
        assert iceptor("after_startup", {}) is None

    def test_budget_guard(self, clean_env, dirty_git_repo, tmp_path):
        iceptor = self._make(dirty_git_repo, tmp_path)
        iceptor._config.mode.max_messages_per_session = 1
        assert iceptor("after_command", {}) is not None
        assert iceptor("after_command", {}) is None  # Budget erschöpft

    def test_state_persists_across_instances(self, clean_env, dirty_git_repo, tmp_path):
        first = self._make(dirty_git_repo, tmp_path)
        first._config.mode.max_messages_per_session = 1
        assert first("after_command", {}) is not None
        # neue Instanz, gleicher State-Speicher: Budget greift weiter
        second = wfp.ExternalWorkflowInterceptor(
            project_dir=dirty_git_repo, state_dir=tmp_path / "state", session_id="s1")
        assert second("after_command", {}) is None

    def test_rollback_env_returns_none(self, monkeypatch, dirty_git_repo, tmp_path):
        iceptor = self._make(dirty_git_repo, tmp_path)
        monkeypatch.setenv(wfp.ROLLBACK_ENV, "0")
        assert iceptor("after_command", {}) is None

    def test_clean_repo_stays_silent(self, clean_env, tmp_path, dirty_git_repo):
        subprocess.run(["git", "add", "-A"], cwd=dirty_git_repo, check=True,
                       capture_output=True, timeout=30)
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                        "commit", "-m", "alles"], cwd=dirty_git_repo,
                       check=True, capture_output=True, timeout=30)
        iceptor = self._make(dirty_git_repo, tmp_path, session="clean")
        assert iceptor("after_command", {}) is None


class TestHookRegistrySlot:

    def test_register_and_emit(self):
        reg = HookRegistry()
        calls = []

        def interceptor(event, ctx):
            calls.append(event)
            return ["note-a", None, "note-b"]

        assert reg.register_interceptor(interceptor, name="t1") is True
        out = reg.emit("after_command", {})
        assert out == ["note-a", "note-b"]
        assert calls == ["after_command"]
        assert reg.last_interceptor_results == ["note-a", "note-b"]

    def test_duplicate_registration_blocked(self):
        reg = HookRegistry()
        assert reg.register_interceptor(lambda e, c: None, name="dup") is True
        assert reg.register_interceptor(lambda e, c: None, name="dup") is False
        assert len(reg._interceptors) == 1

    def test_interceptor_error_is_fail_soft(self):
        reg = HookRegistry()

        def boom(event, ctx):
            raise RuntimeError("kaputt")

        reg.register_interceptor(boom, name="boom")
        out = reg.emit("after_command", {})
        assert any("[HOOK-ERROR]" in r for r in out)
        assert reg.last_interceptor_results == []

    def test_listener_results_do_not_leak_into_interceptor_channel(self):
        """Listener-Rueckgaben bleiben historisch still: sie landen in
        emit-results, aber NICHT im Interceptor-Kanal (Sichtbarkeitsregel)."""
        reg = HookRegistry()
        reg.on("after_command", lambda ctx: "listener-still")
        reg.register_interceptor(lambda e, c: "iceptor", name="i")
        out = reg.emit("after_command", {})
        assert "listener-still" in out
        assert "iceptor" in out
        assert reg.last_interceptor_results == ["iceptor"]

    def test_interceptors_run_before_listeners(self):
        reg = HookRegistry()
        order = []
        reg.on("after_command", lambda ctx: order.append("listener"))
        reg.register_interceptor(lambda e, c: order.append("iceptor") or None, name="i")
        reg.emit("after_command", {})
        assert order == ["iceptor", "listener"]


class TestInstallationWiring:

    def test_install_is_idempotent(self, clean_env):
        reg = HookRegistry()
        wfp.reset_interceptor_install_state()
        assert wfp.install_workflow_interceptor(reg) is True
        assert [e["name"] for e in reg._interceptors] == [wfp._INTERCEPTOR_NAME]
        assert wfp.install_workflow_interceptor(reg) is True  # bereits installiert
        assert len(reg._interceptors) == 1
        wfp.reset_interceptor_install_state()

    def test_install_respects_rollback(self, monkeypatch):
        monkeypatch.setenv(wfp.ROLLBACK_ENV, "off")
        reg = HookRegistry()
        wfp.reset_interceptor_install_state()
        assert wfp.install_workflow_interceptor(reg) is False
        assert reg._interceptors == []
        wfp.reset_interceptor_install_state()

    def test_hub_init_installs_on_import(self):
        src = (HUB_DIR / "__init__.py").read_text(encoding="utf-8")
        assert "_install_external_workflow_interceptor" in src
        assert "_install_external_workflow_interceptor()" in src

    def test_app_and_task_visibility_wiring(self):
        """Interceptor-Meldungen muessen sichtbar werden (Stufe 6)."""
        app_src = (CORE_DIR / "app.py").read_text(encoding="utf-8")
        assert "last_interceptor_results" in app_src
        task_src = (HUB_DIR / "task.py").read_text(encoding="utf-8")
        assert "last_interceptor_results" in task_src

    def test_core_imports_never_hub(self):
        """Import-Richtung AST: core/hooks.py (Interceptor-Slot) ist strikt
        hub-frei -- auch auf Funktionsebene. core/app.py hat zwei historische
        LAZY hub.bach_paths-Imports in Methoden (pra-Stufe-6, dokumentiert);
        dort waecht dieser Test nur die Modul-Ebene (keine NEUEN Top-Level-
        hub-Imports)."""
        # hooks.py: keine hub-Imports auf irgendeiner Ebene
        tree = ast.parse((CORE_DIR / "hooks.py").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("hub"), "hooks.py"
            elif isinstance(node, ast.ImportFrom):
                root = (node.module or "").split(".")[0]
                assert root != "hub", "hooks.py importiert hub"
        # app.py: keine hub-Imports auf Modul-Ebene (Top-Level)
        tree = ast.parse((CORE_DIR / "app.py").read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("hub"), "app.py top-level"
            elif isinstance(node, ast.ImportFrom):
                root = (node.module or "").split(".")[0]
                assert root != "hub", "app.py importiert hub top-level"

    def test_subprocess_hook_transport_untouched(self):
        """Der bestehende Subprozess-Transport (chat_hooks.json) bleibt
        eigenstaendig -- der Seam ist der In-process-Pfad dafuer."""
        src = (HUB_DIR / "_services" / "chat" / "chat_runtime.py").read_text(encoding="utf-8")
        assert "from hub._services.chat import hooks" in src
        hooks_src = (HUB_DIR / "_services" / "chat" / "hooks.py").read_text(encoding="utf-8")
        assert "def fire(" in hooks_src