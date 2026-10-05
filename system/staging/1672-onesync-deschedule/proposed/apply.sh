#!/bin/bash
# ============================================================================
# apply.sh — Task #1672: OneDrive-Sync-Schedule entzerren
# ACHTUNG: Dies ist eine VORLAGE. Es wird NICHT automatisch ausgefuehrt.
# launchd-Reload (unload/load) braucht eine User-Session mit TTY.
# Ausfuehren NUR nach expliziter Bestaetigung des Nutzers in der User-Session.
# ============================================================================
set -euo pipefail

STAGING="/Users/lukas/services/bach/system/staging/1672-onesync-deschedule"
LA="/Users/lukas/Library/LaunchAgents"
PINNER="/Users/lukas/services/onedrive-pinner/onedrive_pinner.py"

echo "!!! VORLAGE — wird nicht autoausgefuehrt !!!"
echo "!!! launchd-Reload brauchte User-Session (TTY). !!!"
read -r -p "Bestaetigen [ja/Abbruch]: " ANS
[ "$ANS" = "ja" ] || { echo "Abgebrochen."; exit 0; }

# 0) Sicherheits-Backup der LIVE-Plists (doppelte Sicherheit neben backup/)
for f in com.ollama.healthcheck com.bach.downloads-watcher \
         com.lukas.computequeue com.lukas.generalcomputequeue; do
  [ -f "$LA/$f.plist" ] && cp -p "$LA/$f.plist" "$LA/$f.plist.pre-1672"
done
cp -p "$PINNER" "$PINNER.pre-1672"

# 1) 4 Plists: proposed -> LIVE
cp -p "$STAGING/proposed/com.ollama.healthcheck.plist"      "$LA/"
cp -p "$STAGING/proposed/com.bach.downloads-watcher.plist"  "$LA/"
cp -p "$STAGING/proposed/com.lukas.computequeue.plist"      "$LA/"
cp -p "$STAGING/proposed/com.lukas.generalcomputequeue.plist" "$LA/"

# 2) onedrive_pinner.py — EINZELZEILEN-Edit (NICHT ganze Datei!).
#    Anchor "# 5 min" ist eindeutig -> nur die CORE-Zeile (300 -> 600).
python3 - "$PINNER" <<'PY'
import sys
p = sys.argv[1]
s = open(p, encoding="utf-8").read()
old = '"interval": 300,    # 5 min'
new = '"interval": 600,    # 10 min (entzerren T1672)'
if old not in s:
    # Toleranz bei Leerzeichen-Varianten: Zeilen-basierter Ersatz
    lines = s.splitlines(keepends=True)
    hit = 0
    for i, ln in enumerate(lines):
        if '"interval": 300' in ln and '# 5 min' in ln:
            lines[i] = ln.replace('300', '600').replace('# 5 min', '# 10 min (entzerren T1672)')
            hit += 1
    if hit != 1:
        raise SystemExit(f"Anchor nicht eindeutig gefunden (hits={hit}) — Abbruch, nichts geaendert.")
    s = "".join(lines)
else:
    s = s.replace(old, new, 1)
open(p, "w", encoding="utf-8").write(s)
print("Pinner CORE-Interval 300 -> 600 gesetzt.")
PY

# 3) launchd-Reload (NUR in User-Session!)
for f in com.ollama.healthcheck com.bach.downloads-watcher \
         com.lukas.computequeue com.lukas.generalcomputequeue com.onedrive.pinner; do
  launchctl unload "$LA/$f.plist" 2>/dev/null || true
  launchctl load   "$LA/$f.plist"
done

echo "Erledigt. Spike-Zaehler weiterfuehren zur Verifikation."

# ---- ROLLBACK (Kommentar) -------------------------------------------------
#   cp -p "$LA/$f.plist.pre-1672" "$LA/$f.plist"  (je Agent)
#   cp -p "$PINNER.pre-1672" "$PINNER"
#   launchctl unload/load (je Agent, User-Session)
#   oder aus staging: cp -p $STAGING/backup/*.plist.bak -> $LA/  +  .py.bak
# ============================================================================
