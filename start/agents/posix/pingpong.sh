#!/usr/bin/env bash
set -euo pipefail
python3 -c 'import taskplan.startcenter' >/dev/null 2>&1 || {
  printf '%s\n' 'TASKPLAN with Startcenter is missing. Install the version with starter resources.' >&2
  exit 2
}
exec python3 -m taskplan startcenter --role pingpong "$@"
