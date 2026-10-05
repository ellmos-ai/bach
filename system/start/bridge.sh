#!/bin/bash
# BACH Claude Bridge - manueller Start (pfadfest)
# Funktioniert unabhaengig vom aktuellen Arbeitsverzeichnis.
# Die Bridge ist auch ohne hinterlegte Connectoren startbar
# (siehe config.json: bridge.start_without_connectors).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."
PYTHONIOENCODING=utf-8 python3 bach.py claude-bridge start "$@"
