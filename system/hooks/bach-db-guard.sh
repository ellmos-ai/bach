#!/bin/bash
# BACH DB-Schutz Hook (PreToolUse:Bash)
# Blockiert direkte schreibende Zugriffe auf bach.db ohne BACH-API.
#
# Installation: bach setup hooks
# Wird nach ~/.claude/hooks/ kopiert und in settings.json registriert.
#
# Daten kommen via STDIN als JSON: { "tool_input": { "command": "..." } }
# Exit 0 = ALLOW, Exit 2 + stderr = BLOCK

# --- Befehl aus STDIN extrahieren ---
INPUT=$(cat)
PYTHON_CMD=$(command -v python3 2>/dev/null || command -v python 2>/dev/null || echo "")
if [ -z "$PYTHON_CMD" ]; then
    exit 0
fi
CMD=$(echo "$INPUT" | "$PYTHON_CMD" -c "import sys,json; d=json.load(sys.stdin); print(d.get('tool_input',{}).get('command',''))" 2>/dev/null)

# Kein Befehl -> ALLOW
[ -z "$CMD" ] && exit 0

# --- Pattern-Check: Schreibender Zugriff auf bach.db? ---
WRITE_OPS="(INSERT|UPDATE|DELETE|DROP|ALTER)"

# sqlite3 CLI mit schreibenden Operationen
if echo "$CMD" | grep -qi 'sqlite3.*bach\.db' && echo "$CMD" | grep -qiE "$WRITE_OPS"; then
    echo "BLOCK - Direkter schreibender sqlite3-Zugriff auf bach.db. Nutze bach_api oder BACH CLI." >&2
    exit 2
fi

# Python sqlite3.connect mit bach.db + schreibende Operationen
if echo "$CMD" | grep -qi 'sqlite3' && echo "$CMD" | grep -qi 'bach\.db' && echo "$CMD" | grep -qiE "$WRITE_OPS"; then
    # Erlaubt wenn ueber BACH-API/Core
    if echo "$CMD" | grep -qiE 'bach_api|from core\.|from hub\.'; then
        exit 0
    fi
    echo "BLOCK - Direkter schreibender Zugriff auf bach.db ohne BACH-API. Nutze bach_api oder BACH CLI." >&2
    exit 2
fi

# Alles andere -> ALLOW
exit 0
