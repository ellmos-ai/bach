"""Einmal-Test Task 2628: entfernt Altlasten des Vorgänger-Workers.

Diese Datei existiert nur für einen einzelnen Lauf: Sie löscht die beiden
untracked Altlasten system/tests/_probe_2628.txt und system/tests/_last_run_2628.txt
und entfernt sich selbst, damit nichts davon in Commit oder PR gelangt.
Nach dem Lauf darf sie nicht mehr existieren.
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
LEGACY = [
    os.path.join(HERE, "_probe_2628.txt"),
    os.path.join(HERE, "_last_run_2628.txt"),
]


def test_remove_legacy_probe_files_and_self():
    removed = 0
    for path in LEGACY:
        if os.path.exists(path):
            os.remove(path)
            removed += 1
    self_path = os.path.abspath(__file__)
    if os.path.exists(self_path):
        os.remove(self_path)
        removed += 1
    assert removed >= 1, "Es wurde nichts entfernt (Altlasten fehlen bereits? Datei konnte sich nicht selbst entfernen)"