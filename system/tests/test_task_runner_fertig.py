"""task_runner: FERTIG am Ende eines langen Berichts hakt den Task ab."""

import sys
import types

import hub._services.chat as chat_pkg
from hub._services.chat import task_runner


class _Runtime:
    max_tool_rounds = None
    auto_continue = None
    goal = None

    def __init__(self, answer):
        self.answer = answer

    def get_session(self, chat_id):
        return types.SimpleNamespace(mode=None, think=None, model=None)

    async def process(self, text, chat_id):
        return self.answer


def _run(monkeypatch, tmp_path, answer):
    fake = types.SimpleNamespace(runtime=_Runtime(answer), _global_defaults={})
    monkeypatch.setitem(sys.modules, "hub._services.chat.telegram_chat", fake)
    monkeypatch.setattr(chat_pkg, "telegram_chat", fake, raising=False)
    monkeypatch.setattr(task_runner, "offene_tasks", lambda db, project: [{"id": 7, "title": "Aufgabe"}])
    done = []
    monkeypatch.setattr(task_runner, "markiere_erledigt", lambda cli, task_id: done.append(task_id) or True)
    monkeypatch.chdir(tmp_path)
    task_runner.main(["--project", "p", "--workdir", str(tmp_path / "work"), "--db", str(tmp_path / "x.db")])
    return done


def test_long_report_ending_with_fertig_is_done(monkeypatch, tmp_path):
    bericht = "Ich habe den Collector gebaut und die Tests ausgefuehrt. " * 20 + "\nFERTIG"
    assert _run(monkeypatch, tmp_path, bericht) == [7]


def test_answer_without_fertig_stays_open(monkeypatch, tmp_path):
    assert _run(monkeypatch, tmp_path, "Backend-Fehler: ReadTimeout") == []
