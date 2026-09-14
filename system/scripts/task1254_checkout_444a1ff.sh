#!/usr/bin/env bash
# DEPRECATED — bitte stattdessen das offizielle Transfer-Skript verwenden.
# Siehe Task #1241 und docs/OPERATOR-1240-ssh-transfer.md
#
# Dieses Skript ruft jetzt automatisch das gepflegte Transfer-Skript auf:
#   system/bin/transfer-assistant-core-444a1ff.sh

set -euo pipefail

cd "${HOME}/services/bach" || { echo "[FAIL] BACH-Dir nicht gefunden"; exit 2; }

NEW_SCRIPT="system/bin/transfer-assistant-core-444a1ff.sh"
if [[ ! -f "$NEW_SCRIPT" ]]; then
  echo "[FAIL] Neues Transfer-Skript nicht gefunden: $NEW_SCRIPT"
  exit 2
fi

echo "[INFO] task1254_checkout_444a1ff.sh ist deprecated."
echo "[INFO] Leite weiter zu: $NEW_SCRIPT"
echo ""

exec bash "$NEW_SCRIPT" "$@"
