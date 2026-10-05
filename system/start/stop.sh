#!/bin/bash
# BACH Claude Bridge - manueller Stop (pfadfest)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."
PYTHONIOENCODING=utf-8 python3 bach.py claude-bridge stop "$@"
