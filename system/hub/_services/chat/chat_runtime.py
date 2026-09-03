#!/usr/bin/env python3
"""BACH Chat Runtime -- compatibility seam over the neutral ``ellmos-chat`` module.

Since wave 2 of the BACH-GUI module cut (decision D-20260830-002) the session
management, tool-use loop and context compression live in ``ellmos_chat``.
This file keeps BACH's import path and its public surface unchanged:

    from hub._services.chat.chat_runtime import ChatRuntime, RUNTIME_BACH_DB

BACH keeps what is BACH's and injects it:

* **Tools** -- ``bach_tools.BachToolProvider`` (``bach_command`` into the 110+
  CHIAH handlers, plus the lazy ``hub._services.*`` imports for recurring
  tasks, the Foerderbericht pipeline and the weather service).
* **Transcripts** -- ``session_store.SQLiteChatSessionStore``, i.e.
  ``session_snapshots``/``chat-transcript.v1`` in the canonical ``bach.db``.
  ``_SnapshotStoreAdapter`` below presents it as the module's ``ChatStore``
  protocol. There is no second chat database.
* **System prompt** -- BACH's hand-written capability text, not the module's
  generated one.

Only telegram_chat.py imports this module directly; the tray and the GUI
``/chat`` page reach the same runtime through the Control API on :8081.
"""
import logging

from ellmos_chat import ChatRuntime as _ModuleChatRuntime

from hub._services.chat.bach_tools import RUNTIME_BACH_DB, BachToolProvider  # noqa: F401

log = logging.getLogger("bach.chat")


class _SnapshotStoreAdapter:
    """The module's ``ChatStore`` protocol on BACH's snapshot session store.

    The module appends message by message; BACH's store holds one snapshot of
    the whole transcript per chat. Each append therefore writes the runtime's
    current in-memory transcript -- the same thing BACH persisted before the
    cut, just twice per turn instead of once. Reading first would risk wiping a
    good snapshot after a transient read error.
    """

    def __init__(self, runtime: "ChatRuntime"):
        self._runtime = runtime

    def load(self, chat_id: str) -> list[dict]:
        return self._runtime._load_messages(chat_id)

    def append(self, chat_id: str, role: str, content: str) -> None:
        session = self._runtime._sessions.get(chat_id)
        messages = (
            session.messages if session is not None
            else [{"role": role, "content": content}]
        )
        self._runtime._persist(chat_id, messages)

    def replace(self, chat_id: str, messages: list[dict]) -> None:
        self._runtime._persist(chat_id, messages)

    def clear(self, chat_id: str) -> None:
        store = self._runtime.session_store
        if store is None:
            return
        try:
            store.delete(chat_id)
        except Exception as exc:  # already reported by clear_session
            log.warning("Chat-Persistenz konnte nicht geloescht werden: %s", exc)


class ChatRuntime(_ModuleChatRuntime):
    """BACH's ChatRuntime: the module's runtime plus BACH's data and prompt."""

    def __init__(self, backend, system_prompt: str = "",
                 bach_app=None, memory_fn=None, injector=None,
                 session_store=None):
        self.bach_app = bach_app
        self.session_store = session_store
        self._persistence_error: str | None = None
        super().__init__(
            backend,
            system_prompt=system_prompt,
            store=_SnapshotStoreAdapter(self),
            registry=BachToolProvider(bach_app, backend.get_default_model),
            memory_fn=memory_fn,
            injector=injector,
        )

    # -- Persistenz (bach.db session_snapshots) ------------------------------

    def _load_messages(self, chat_id: str) -> list[dict]:
        if self.session_store is None:
            return []
        try:
            messages = self.session_store.load(chat_id)
            self._persistence_error = None
            return messages
        except Exception as exc:
            self._persistence_error = str(exc)
            log.warning("Chat-Persistenz konnte nicht gelesen werden: %s", exc)
            return []

    def _persist(self, chat_id: str, messages: list[dict]) -> None:
        if self.session_store is None:
            return
        try:
            self.session_store.save(chat_id, messages)
            self._persistence_error = None
        except Exception as exc:
            self._persistence_error = str(exc)
            log.warning("Chat-Persistenz konnte nicht geschrieben werden: %s", exc)

    def persistence_status(self) -> dict:
        """Non-sensitive health readback for the Control API."""
        return {
            "enabled": self.session_store is not None,
            "ok": self.session_store is not None and self._persistence_error is None,
            "error": self._persistence_error or "",
        }

    # -- Sessions ------------------------------------------------------------

    @property
    def sessions(self) -> dict:
        """BACH's name for the module's in-memory session map (Control API reads it)."""
        return self._sessions

    def get_session(self, chat_id: str):
        session = super().get_session(chat_id)
        if not hasattr(session, "voice_output"):
            session.voice_output = False
        return session

    def clear_session(self, chat_id: str) -> None:
        lock = self._session_locks.get(chat_id)
        if lock is not None and lock.locked():
            raise RuntimeError(
                "Session kann waehrend einer laufenden Antwort nicht geloescht werden"
            )
        if self.session_store is not None:
            try:
                self.session_store.delete(chat_id)
                self._persistence_error = None
            except Exception as exc:
                self._persistence_error = str(exc)
                log.error("Chat-Persistenz konnte nicht gelöscht werden: %s", exc)
                raise RuntimeError(
                    "Persistierter Chatverlauf konnte nicht gelöscht werden"
                ) from exc
        super().clear_session(chat_id)

    def history(self, chat_id: str) -> list[dict]:
        """Read-only transcript of a session: the visible user/assistant turns in order.

        Does not create a session (unknown chat_id -> []). Internal entries -- the
        summarised-context message, tool traffic -- stay hidden. The GUI restores
        exactly this list when the chat page is reopened (plan item 1.1.7 / 1.2.4).
        """
        session = self._sessions.get(chat_id)
        messages = session.messages if session is not None else self._load_messages(chat_id)
        return [
            {"role": m["role"], "content": m.get("content", "")}
            for m in messages
            if m.get("role") in ("user", "assistant")
        ]

    # -- System-Prompt -------------------------------------------------------

    def build_system_prompt(self, session) -> str:
        capabilities = """
Du hast Zugriff auf Werkzeuge (Tools), die du bei Bedarf aufrufen kannst.

SAFE-MODUS (Standard):
- list_directory, read_file, search_text — Dateisystem lesen
- edit_file — Text in Dateien ersetzen (suchen/ersetzen)
- move_file — Dateien/Ordner verschieben oder umbenennen
- copy_file — Dateien/Ordner kopieren
- file_info — Detaillierte Datei-/Ordner-Informationen
- recycle — In Papierkorb verschieben (wiederherstellbar, statt Löschen)
- create_directory — Neuen Ordner erstellen
- safe_shell — Lesende Shell-Befehle (ls, cat, grep, git, docker, ps, etc.)
- system_status — Systeminfos (CPU, RAM, Disk)
- ollama_info — Modelle und Status
- bach_command — BACH Memory, Tasks, Suche, Status
- get_datetime — Datum/Uhrzeit
- web_search — Im Internet suchen (DuckDuckGo)
- web_fetch — Inhalt einer URL abrufen (Webseite, API, JSON)
- weather — Aktuelles Wetter abfragen
- task_manage — Tasks anlegen, auflisten, erledigen
- maintain — Systemwartung: fällige Tasks (check), Wartung (run), BACH-Status (health), Service-Check (services)
- foerderbericht — Förderbericht-Pipeline: Anonymisierung (prepare), Status (status), Aufräumen (cleanup)
- delegate — Aufgabe an Claude Code oder Codex CLI delegieren

FULL-MODUS (nur nach /mode full bestätigt):
- execute_command — Beliebige Shell-Befehle
- write_file — Dateien schreiben

BACH-HANDLER (alle via bach_command nutzbar):
- denkarium write/read/search/brainstorm/promote/stats — Gedanken-Sammler und Logbuch
- calendar list/add/today/week — Termine und Kalender
- contact list/search/show — Kontaktverwaltung
- routine list/add/complete — Routinen und Gewohnheiten
- countdown list — Countdowns und Timer
- mem write/read/fact/facts/search/context — Memory-System
- lesson add/list — Lessons Learned
- mediplaner export/import/help — JSON-Austausch zwischen BACH-Gesundheitsdaten und MediPlaner
- help <thema> — Dokumentation zu jedem Thema (260+ Help-Dateien)

WICHTIGSTE REGEL — SUCHE ALS FALLBACK:
Wenn der User einen Service, ein Tool oder eine Funktion anfragt die du nicht kennst:
1. ZUERST: bach_command mit "help <thema>" nutzen — findet die passende Dokumentation
2. DANN: bach_command mit "search <begriff>" — durchsucht Handler, Tools und Skills
3. NIEMALS sagen "das kann ich nicht" ohne vorher gesucht zu haben
BACH hat 110+ Handler — du kennst hier nur die wichtigsten. Die Suche findet den Rest.

REGELN:
- Nutze Tools aktiv, wenn der User nach Informationen fragt
- Nutze web_search, wenn du aktuelle Informationen brauchst oder der User fragt
- Nutze task_manage, wenn der User Tasks verwalten will
- Nutze maintain, wenn der User nach Systemstatus, Wartung oder Health fragt
- Nutze delegate, wenn eine Aufgabe besser von Claude (Coding, Analyse) oder Codex (schnelle Code-Generierung) erledigt wird
- Nutze edit_file zum Bearbeiten von Dateien (suchen/ersetzen)
- Nutze recycle zum Löschen — verschiebt in den Papierkorb statt endgültig zu löschen
- Nutze weather für Wetterabfragen
- Nutze denkarium, wenn der User Gedanken notieren, im Logbuch schreiben oder brainstormen will
- Nutze calendar, wenn der User nach Terminen fragt oder welche anlegen will
- Nutze contact, wenn der User Kontakte sucht oder anzeigen will
- Nutze routine, wenn der User nach Routinen oder Gewohnheiten fragt
- Führe Befehle aus, wenn der User es wünscht
- Antworte immer auf Deutsch
- Sei präzise, hilfreich, und zeige Tool-Ergebnisse klar an
- Du KANNST Befehle ausführen — sag nicht, dass du das nicht kannst

WARTUNGSROLLE:
Du bist auch für Systemwartung zuständig. Wenn der User danach fragt:
- maintain(check) zeigt fällige wiederkehrende Tasks
- maintain(run, operation) führt Wartung aus (registry, skills, docs, backup, clean, memory, recurring)
- maintain(health) zeigt den Gesamtstatus
"""
        s = self.base_system + "\n\n" + capabilities
        s += (
            f"\n[Modus={session.mode.value}, "
            f"Denken={'AN' if session.think else 'AUS'}, "
            f"Modell={session.model}]"
        )
        return s

    def _get_bach_context(self, text: str) -> str:
        """BACH's name for the module's injector/memory context hook."""
        return self._get_extra_context(text)
