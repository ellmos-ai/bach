# -*- coding: utf-8 -*-
"""Zentrale Stelle fuer die Laufzeit-Grenzen von BACH.

Alle Werte hier waren vorher fest im Code verdrahtet. Sie behalten exakt
ihren bisherigen Default - gesetzt wird nur, wer eine Umgebungsvariable
setzt. Damit aendert sich ohne Zutun nichts am Verhalten.

Muster uebernommen von BACH_DELEGATION_DEPTH, das es schon gab.

    BACH_LLM_TIMEOUT          Sekunden je Modellantwort (Ollama, think=an)
    BACH_LLM_TIMEOUT_FAST     Sekunden je Modellantwort (think=aus, API-Backends)
    BACH_CLI_MAX_TURNS        Runden im CLI-Backend
    BACH_CLI_IDLE_TIMEOUT     Sekunden ohne Lebenszeichen im CLI-Backend
    BACH_CMD_TIMEOUT          Sekunden je Shell-Befehl
    BACH_DELEGATE_TIMEOUT     Sekunden je Delegation an Claude/Codex
    BACH_MAX_TOOL_ROUNDS      Werkzeug-Runden je Antwort (0 = unbegrenzt)
    BACH_MAX_CONTEXT_CHARS    Zeichen, ab denen der Kontext hart gekuerzt wird
    BACH_SUMMARIZE_THRESHOLD  Zeichen, ab denen zusammengefasst wird
    BACH_MAX_MESSAGES         Nachrichten, ab denen zusammengefasst wird
    BACH_AUTO_CONTINUE        Nachschuebe im Loop-Mode (0 = aus, siehe /auto)
    BACH_CONTEXT_LIMIT        Kontextfenster des Modells in Token
    BACH_HANDOFF_PERCENT      ab wie viel Prozent Fuellstand uebergeben wird (0 = nie)
    BACH_HOOK_EVERY           nach wie vielen Werkzeugrunden Hooks gefragt werden
    BACH_LLM_IDLE_TIMEOUT     Sekunden Stille, bevor bei Ollama nachgefragt wird
    BACH_LLM_IDLE_GRACE       so oft darf die Nachfrage "lebt noch" ergeben
    BACH_LLM_PING_TIMEOUT     Sekunden fuer die /api/ps-Nachfrage
    BACH_LLM_TOTAL_CAP        harte Obergrenze je Antwort (0 = keine)
    BACH_FACKEL_KAPAZITAET_MB modelltauglicher Speicher (0 = messen)
    BACH_DELEGATION_DEPTH     Delegationstiefe (>=2 sperrt Delegation)

Lesen: python3 -c "from hub._services.limits import report; report()"
"""
import os

DEFAULTS = {
    "BACH_LLM_TIMEOUT": 180,
    "BACH_LLM_TIMEOUT_FAST": 120,
    "BACH_CLI_MAX_TURNS": 30,
    "BACH_CLI_IDLE_TIMEOUT": 300,
    "BACH_CMD_TIMEOUT": 30,
    "BACH_DELEGATE_TIMEOUT": 120,
    "BACH_MAX_TOOL_ROUNDS": 12,
    "BACH_MAX_CONTEXT_CHARS": 24000,
    "BACH_SUMMARIZE_THRESHOLD": 16000,
    "BACH_MAX_MESSAGES": 40,
    "BACH_AUTO_CONTINUE": 0,
    "BACH_CONTEXT_LIMIT": 32768,
    "BACH_HANDOFF_PERCENT": 75,
    "BACH_HOOK_EVERY": 3,
    "BACH_LLM_IDLE_TIMEOUT": 120,
    "BACH_LLM_IDLE_GRACE": 10,
    "BACH_LLM_PING_TIMEOUT": 10,
    "BACH_LLM_TOTAL_CAP": 7200,
    # 0 heisst: nicht gesetzt, also messen (Metal bzw. was laeuft).
    # Nur setzen, wo die Messung fehlschlaegt oder bewusst
    # gedeckelt werden soll - siehe hub/_services/fackel.py.
    "BACH_FACKEL_KAPAZITAET_MB": 0,
}


def limit(name: str, default=None) -> int:
    """Wert aus der Umgebung, sonst der bisherige Default.

    Ein leerer oder unlesbarer Wert faellt auf den Default zurueck - eine
    kaputte Variable soll BACH nicht lahmlegen.
    """
    if default is None:
        default = DEFAULTS.get(name, 0)
    raw = os.environ.get(name, "")
    if not raw:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def report():
    """Zeigt, welche Grenzen gerade gelten und welche gesetzt wurden."""
    print(f"{'Grenze':26} {'gilt':>8}  {'Default':>8}  Quelle")
    for name, dflt in sorted(DEFAULTS.items()):
        val = limit(name)
        src = "ENV" if os.environ.get(name) else "-"
        print(f"{name:26} {val:>8}  {dflt:>8}  {src}")


if __name__ == "__main__":
    report()
