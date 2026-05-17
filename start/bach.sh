#!/usr/bin/env bash
# BACH Launcher — macOS / Linux
# Usage: bach.sh <chat|gui|status|stop>
# Server mode: BACH_HOST=macstudvonlukas bach.sh status

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SYS_DIR="$(cd "$SCRIPT_DIR/../system" 2>/dev/null && pwd)" || SYS_DIR=""
if [ -z "$SYS_DIR" ] || [ ! -f "$SYS_DIR/bach.py" ]; then
    echo "BACH system/ nicht gefunden relativ zu $SCRIPT_DIR (erwartet: .../BACH/start/bach.sh)" >&2
    exit 1
fi

export PYTHONIOENCODING=utf-8
export PYTHONUNBUFFERED=1
export PYTHONPATH="$SYS_DIR"

if [ -f "$HOME/.venvs/bach/bin/python" ]; then
    PYTHON="$HOME/.venvs/bach/bin/python"
elif [ -f "$HOME/.venvs/science/bin/python" ]; then
    PYTHON="$HOME/.venvs/science/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON=python3
else
    PYTHON=python
fi

CHAT_DIR="$SYS_DIR/hub/_services/chat"
HOST="${BACH_HOST:-}"

usage() {
    cat <<'EOF'
BACH — LLM Operating System

Usage: bach.sh <command>

Commands:
  chat    Chat-Services starten (Telegram Bot + Tray + Control API)
  gui     GUI Dashboard starten
  status  Service-Status anzeigen
  stop    Alle BACH-Services stoppen

Server-Modus (Remote-Steuerung):
  BACH_HOST=macstudvonlukas bach.sh status
  BACH_HOST=macstudvonlukas bach.sh gui
EOF
}

cmd_chat() {
    if [ -n "$HOST" ]; then
        echo "Remote-Modus: Tray verbindet zu $HOST"
        "$PYTHON" "$CHAT_DIR/chat_tray.py" --host "$HOST" --port 8081
        return
    fi

    echo "Starte BACH Chat-Services..."

    local log_dir
    if [[ "$OSTYPE" == darwin* ]]; then
        log_dir="${HOME}/Library/Logs/bach"
    else
        log_dir="${HOME}/.local/state/bach/logs"
    fi
    mkdir -p "$log_dir"

    nohup "$PYTHON" "$CHAT_DIR/telegram_chat.py" > "$log_dir/telegram-bot.log" 2>&1 &
    echo "  Telegram Bot gestartet (PID $!)"

    nohup "$PYTHON" "$CHAT_DIR/chat_tray.py" --port 8081 > "$log_dir/chat-tray.log" 2>&1 &
    echo "  System Tray + Control API gestartet (PID $!)"

    echo "Fertig. Logs: $log_dir/"
}

cmd_gui() {
    local target="${HOST:-0.0.0.0}"
    local port=8000

    if [ -n "$HOST" ]; then
        local url="http://${HOST}:${port}"
        echo "Remote-GUI: $url"
        open "$url" 2>/dev/null || xdg-open "$url" 2>/dev/null || echo "Im Browser öffnen: $url"
        return
    fi

    echo "Starte BACH GUI Dashboard..."

    local pids=""
    if command -v lsof >/dev/null 2>&1; then
        pids=$(lsof -ti:"$port" 2>/dev/null || true)
    elif command -v fuser >/dev/null 2>&1; then
        fuser -k "$port/tcp" 2>/dev/null || true
    fi
    if [ -n "$pids" ]; then
        echo "$pids" | xargs kill -9 2>/dev/null || true
    fi

    local log_dir
    if [[ "$OSTYPE" == darwin* ]]; then
        log_dir="${HOME}/Library/Logs/bach"
    else
        log_dir="${HOME}/.local/state/bach/logs"
    fi
    mkdir -p "$log_dir"

    nohup "$PYTHON" "$SYS_DIR/gui/server.py" --host 0.0.0.0 --port "$port" > "$log_dir/gui-server.log" 2>&1 &
    echo "  GUI Server gestartet (PID $!)"

    sleep 2
    local url="http://127.0.0.1:${port}"
    if [ "${BACH_NO_BROWSER:-}" = "1" ]; then
        echo "  Browser nicht geöffnet (BACH_NO_BROWSER=1)"
        echo "  URL: $url"
    else
        open "$url" 2>/dev/null || xdg-open "$url" 2>/dev/null || echo "Im Browser öffnen: $url"
    fi
}

cmd_status() {
    local target="${HOST:-127.0.0.1}"
    local api_port=8081
    local gui_port=8000

    echo "BACH Service-Status"
    echo "==================="

    if curl -s --max-time 3 "http://${target}:${api_port}/api/status" >/dev/null 2>&1; then
        echo "  Control API (${target}:${api_port}): ONLINE"
        curl -s --max-time 3 "http://${target}:${api_port}/api/status" | "$PYTHON" -m json.tool 2>/dev/null || true
    else
        echo "  Control API (${target}:${api_port}): OFFLINE"
    fi

    if curl -s --max-time 3 "http://${target}:${gui_port}/" >/dev/null 2>&1; then
        echo "  GUI Dashboard (${target}:${gui_port}): ONLINE"
    else
        echo "  GUI Dashboard (${target}:${gui_port}): OFFLINE"
    fi

    if [ "$target" = "127.0.0.1" ] || [ "$target" = "localhost" ]; then
        echo ""
        echo "Lokale Prozesse:"
        ps aux | grep -E "(telegram_chat|chat_tray|gui/server)" | grep -v grep || echo "  (keine)"
    fi
}

cmd_stop() {
    echo "Stoppe BACH-Services..."

    pkill -f "telegram_chat.py" 2>/dev/null && echo "  Telegram Bot gestoppt" || echo "  Telegram Bot lief nicht"
    pkill -f "chat_tray.py" 2>/dev/null && echo "  System Tray gestoppt" || echo "  System Tray lief nicht"
    pkill -f "gui/server.py" 2>/dev/null && echo "  GUI Dashboard gestoppt" || echo "  GUI Dashboard lief nicht"

    echo "Fertig."
}

case "${1:-}" in
    chat)   cmd_chat ;;
    gui)    cmd_gui ;;
    status) cmd_status ;;
    stop)   cmd_stop ;;
    *)      usage ;;
esac
