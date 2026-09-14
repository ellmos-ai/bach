#!/usr/bin/env bash
# ============================================================================
# OPERATOR-RUNBOOK: Task #1255 — Wächter in starr laufende Services laden
# ----------------------------------------------------------------------------
# Zweck:  com.bach.chat-tray (idle-worker + Terminal-Wächter, Port 8081) und
#         com.bach.telegram-bot (24/7-Agent-Session) mit launchctl neu starten,
#         damit die idle-loop-Fixes (Commits fe4fc31 + d46a384, #1240 done)
#         aktiv geladen werden. Danach ist die Resurrektions-Loop gebrochen.
#
# WARNUNG:
#   * Beendet die laufende 24/7-Session (telegram_chat.py) -> kurzer
#     Telegram-Downtime, bis der Bot wieder connectet.
#   * Dieses Skript MUSS von einem echten Terminal (nicht von BACH aus)
#     ausgeführt werden, sonst wird es beim eigenen kill mitgetötet.
#
# Voraussetzungen (verifiziert 2026-09-13 01:5x, AKTUALISIERT 02:39):
#   * HEAD = d46a384, chat_tray.py kompiliert sauber (py_compile OK)
#   * chat_tray.py UND telegram_chat.py selbst = kein uncommitted diff
#    * !!! NEU 02:39: chat-SUBSYSTEM UNCOMMITTED:
#     agent_runner.py / chat_runtime.py / message_worker.py (M) +
#      _messages_compat.py / operator_control.py (??)
#      -> launchd-Restart laedt den WORKING-TREE: diese in-flight
#         Aenderungen wuerden in die 24/7-Session gezogen!
#      -> VOR Restart pruefen: commit/verwerfen ODER bewusst mitnehmen.
#    * !!! Beide live-PIPs starteten NACH d46a384:
#     chat-tray 67023 @23:30:43, telegram 67195 @23:31:33 (vs 23:20:01)
#      -> Waechter evtl. BEREITS geladen. Voller Neustart (Opt A)
#         evtl. ueberfluessig -> Opt B (nur chat-tray) oder C praefern.
#
# Nutzung:  bash ~/services/bach/system/bin/operator-1255-restart-watchers.sh
# ============================================================================
set -uo pipefail

GUI="gui/501"
LABELS=("com.bach.chat-tray" "com.bach.telegram-bot")
LOGDIR="$HOME/Library/Logs/bach"
MIN_START="2026-09-12 23:20:01"   # d46a384 — neuer Prozesstart = Wächter geladen

say() { printf '\033[1;34m[runbook-1255]\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m[ABBRUCH]\033[0m %s\n' "$*"; exit 1; }

say "Start $(date '+%Y-%m-%d %H:%M:%S')"

# --- 0) Pre-Check: Code-Präzedenz ---
if ! git -C "$HOME/services/bach/system" rev-parse --short HEAD 2>/dev/null | grep -q '^d46a384$'; then
  say "ACHTUNG: HEAD ist NICHT d46a384, sondern $(git -C "$HOME/services/bach/system" rev-parse --short HEAD 2>/dev/null)."
  say "Wächter-Fixes evtl. nicht lokal -> bitte erst commit/checkout prüfen."
fi
if ! "$HOME/.venvs/bach/bin/python" -c "import py_compile; py_compile.compile('$HOME/services/bach/system/hub/_services/chat/chat_tray.py', doraise=True)" 2>/dev/null; then
  fail "chat_tray.py kompiliert NICHT sauber -> NEUSTART WÜRDE KRÄHEN. Zuerst Syntax fixen."
fi
say "Pre-Check OK: HEAD=d46a384, chat_tray.py kompiliert."

# --- 1) chat-tray (Control-API / idle-worker) zuerst ---
for L in "${LABELS[@]}"; do
  say "Kickstart $L"
  launchctl kickstart -k "$GUI/$L" || fail "kickstart $L fehlgeschlagen"
  sleep 4
done

# --- 2) Stabilität prüfen (bis beide aktiv, max 60s) ---
say "Warte auf Stabilität (ThrottleInterval=30s) ..."
for i in $(seq 1 12); do
  sleep 5
  OUT="$(launchctl list | grep -E 'com.bach.chat-tray|com.bach.telegram-bot')"
  if echo "$OUT" | grep -qE 'com.bach.chat-tray'  && echo "$OUT" | grep -qE 'com.bach.telegram-bot'; then
    BAD="$(echo "$OUT" | awk '$2 ~ /^-/' | grep -c .)"
    if [ "$BAD" = "0" ]; then
      say "Beide Services stabil aktiv (Versuch $i)."
      break
    fi
  fi
  say "noch nicht stabil (Versuch $i), wiederhole ..."
done

# --- 3) Verifikation: Wächter geladen (Prozesstart > d46a384-Zeit) ---
say "=== Verifikation ==="
launchctl list | grep -E 'com.bach.chat-tray|com.bach.telegram-bot|com.bach.gui-server'
for L in "${LABELS[@]}"; do
  PID="$(launchctl list | awk -v l="$L" '$3==l{print $1}')"
  if [ -n "${PID:-}" ] && [ "$PID" != "0" ]; then
    START="$(ps -p "$PID" -o lstart= 2>/dev/null | xargs)"
    say "$L -> PID $PID, gestartet: $START"
    # rohe Zeitstempel-Vergleich (gg. Manuelle Prüfung, da 'lstart' kein UNIX-epoch)
  else
    say "$L -> LAUFT NICHT (PID leer/0)!"
  fi
done

# --- 4) Log-Grep: Wächter-Meldung aktiv ---
say "=== chat-tray.log (Wächter-Aktivität) ==="
tail -n 25 "$LOGDIR/chat-tray.log" 2>/dev/null | grep -E "terminal|Wächter|resurrect|done" || say "(noch keine Wächter-Meldung im Log — normal, fires erst bei terminalem Task)"

say "FERTIG. #1255: Wächter sollte geladen sein. #1236 bleibt offen bis Operator GRÜN auf 3 Hosts."
