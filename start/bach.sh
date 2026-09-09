#!/usr/bin/env bash
# BACH Launcher — macOS / Linux
# Dünner Adapter zur gemeinsamen, pfadunabhängigen Startspine.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SYS_DIR="$(cd "$SCRIPT_DIR/../system" 2>/dev/null && pwd)" || SYS_DIR=""
STARTSPINE="$SCRIPT_DIR/startspine.py"
if [ -z "$SYS_DIR" ] || [ ! -f "$SYS_DIR/bach.py" ] || [ ! -f "$STARTSPINE" ]; then
    echo "BACH system/ oder start/startspine.py nicht gefunden relativ zu $SCRIPT_DIR" >&2
    exit 1
fi

export PYTHONIOENCODING=utf-8
export PYTHONUNBUFFERED=1
export PYTHONPATH="$SYS_DIR${PYTHONPATH:+:$PYTHONPATH}"

if [ -x "$HOME/.venvs/bach/bin/python" ]; then
    PYTHON="$HOME/.venvs/bach/bin/python"
elif [ -x "$HOME/.venvs/science/bin/python" ]; then
    PYTHON="$HOME/.venvs/science/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON=python3
else
    PYTHON=python
fi

HOST="${BACH_HOST:-127.0.0.1}"

usage() {
    cat <<'EOF'
BACH — LLM Operating System

Usage: bach.sh <start|chat|gui|status|stop>

Commands:
  start   GUI und Tray starten; der Tray verbindet sich bei Chat-Readiness
  chat    Telegram Bot, Control API und Tray starten
  gui     GUI Dashboard starten
  status  Readiness, Ownership, PIDs und Ports anzeigen
  stop    Nur von der Startspine registrierte BACH-Prozesse beenden

Konfiguration:
  BACH_GUI_PORT=8000       gewünschter GUI-Port
  BACH_CONTROL_PORT=8081   gewünschter Control-Port
  BACH_HOST=hostname       Remote-Status bzw. Remote-Tray
EOF
}

cmd_start() {
    "$PYTHON" "$STARTSPINE" start --gui --tray --open-browser
}

cmd_chat() {
    if [ "$HOST" != "127.0.0.1" ] && [ "$HOST" != "localhost" ]; then
        "$PYTHON" "$STARTSPINE" start --tray --host "$HOST"
    else
        "$PYTHON" "$STARTSPINE" start --chat --tray
    fi
}

cmd_gui() {
    if [ "$HOST" != "127.0.0.1" ] && [ "$HOST" != "localhost" ]; then
        "$PYTHON" "$STARTSPINE" status --host "$HOST" || true
        local port="${BACH_GUI_PORT:-8000}"
        local url="http://${HOST}:${port}"
        open "$url" 2>/dev/null || xdg-open "$url" 2>/dev/null || echo "Im Browser öffnen: $url"
    else
        "$PYTHON" "$STARTSPINE" start --gui --open-browser
    fi
}

cmd_status() {
    "$PYTHON" "$STARTSPINE" status --host "$HOST"
}

cmd_stop() {
    "$PYTHON" "$STARTSPINE" stop --services all
}

case "${1:-}" in
    start)  cmd_start ;;
    chat)   cmd_chat ;;
    gui)    cmd_gui ;;
    status) cmd_status ;;
    stop)   cmd_stop ;;
    help|-h|--help) usage ;;
    *)      usage >&2; exit 2 ;;
esac
