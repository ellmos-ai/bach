"""Zuschnittregel für Teilaufgaben, die lokale Modelle (OLLAMA, Buddha) abarbeiten.

Gemessen am 25.10.2026: Buddha schließt nur Aufgaben mit höchstens zwei Kontextübergaben ab.
Eine Quelle für die Rolle ``task-divider`` (slots_config), den Worker-Zerlegungshinweis
(chat_runtime, worker_lease_binding, worker_task_actions) und die Tests.
"""
from __future__ import annotations

TASK_CUT_RULE = (
    "Zuschnittregel für Teilaufgaben, die lokale Modelle (OLLAMA, Buddha) abarbeiten sollen "
    "(gemessen am 25.10.2026: Buddha schließt nur Aufgaben mit höchstens zwei Kontextübergaben ab). "
    "Schneide jede Teilaufgabe so, dass sie\n"
    "(a) mit höchstens zwei Kontextübergaben auskommt: wenige Dateien, jede Datei unter etwa 4000 Zeichen zu lesen;\n"
    "(b) vollständig im eigenen Task-Arbeitsbaum lösbar ist: ein gebundener Worker sieht weder andere Tasks noch "
    "etwas außerhalb seines Arbeitsbaums, setze also nichts voraus, was nur dort draußen steht;\n"
    "(c) mit einem Text bis 3000 Zeichen oder mit einer Datei plus PR endet;\n"
    "(d) assigned_to OLLAMA oder den eigenen Slot trägt, niemals ein Themenwort (Themen gehören in category);\n"
    "(e) einen Bauort hat, der im Arbeitsbaum des Workers liegt: Aufgaben, deren Bauort ein anderes Repository ist "
    "(z. B. ellmos-system-gui), nicht an OLLAMA geben, solange die Worker-Git-Anbindung nur ellmos-ai/bach kennt "
    "(Erweiterung auf Modulrepos: Task #2577); sie einem Bearbeiter mit Zugriff auf dieses Repository zuweisen."
)

TASK_CUT_RULE_SHORT = (
    "Zuschnitt: höchstens zwei Kontextübergaben (wenige Dateien, je unter ca. 4000 Zeichen), vollständig im "
    "eigenen Arbeitsbaum lösbar, Ende mit Text bis 3000 Zeichen oder Datei plus PR, assigned_to OLLAMA bzw. eigener "
    "Slot (kein Themenwort), Bauort außerhalb des Arbeitsbaums nicht an OLLAMA."
)
