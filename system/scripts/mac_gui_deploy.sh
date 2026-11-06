#!/usr/bin/env bash
# PB-9 Mac-Deploy: GUI 0.2.34 + bach/task-master auf dem Mac Studio.
# Aufruf vom Laptop (Skript laeuft auf dem Mac, wird per stdin uebergeben):
#   ssh -i ~/.ssh/id_ed25519_mcmc lukas@100.119.69.90 'bash -s -- --dry-run' < pb9_deploy.sh
#   ssh ... 'bash -s -- --apply'    < pb9_deploy.sh
#   ssh ... 'bash -s -- --rollback' < pb9_deploy.sh
# Archiv: --archive=<Pfad> nimmt ein per scp bereitgestelltes ZIP (kein Netz noetig); ohne Parameter wird das
# Release-Asset von GitHub geholt. In beiden Faellen wird der SHA-256 gegen den Pin geprueft.
#   ssh ... "bash -s -- --apply --archive=\$HOME/compute/rollback-20261106/<archiv>.zip" < pb9_deploy.sh
# Optional: --probe-tasks (nur sinnvoll mit --dry-run: zusaetzlich Cookie-Session minten, Tasks lesen, abmelden).
#
# Soll-Werte (Version, Commit, Archivname, SHA-256) kommen aus system/gui/kit_manifest.json:
# bei --apply aus dem frisch gezogenen bach-Stand, bei --dry-run aus origin/main (raw.githubusercontent).
# Ueberschreibbar: GUI_VERSION, GUI_COMMIT, GUI_ARCHIVE, GUI_SHA256.
#
# Designentscheidung: das laufende dist wird NICHT ueberschrieben. Der Server liest sein dist aus
# ELLMOS_SYSTEM_GUI_DIST (plist). Die neue Fassung wird als eigenes Verzeichnis
# shared-release-<version>-<sha12>/ abgelegt und nur diese eine plist-Variable umgestellt.
# Das alte Verzeichnis bleibt unveraendert und ist der Rollback; zusaetzlich wird es nach
# ~/compute/rollback-20261106/dist-0.2.33 kopiert.
#
# Rollback des Codes mit "git reset --keep <alter-SHA>": bricht ab statt lokale Aenderungen zu verlieren,
# bewegt den Branch zurueck (spaeteres "pull --ff-only" funktioniert wieder), Commits bleiben ueber origin
# und reflog erreichbar. Kein --hard, kein checkout --.
# Alles in main(), damit bash das Skript vollstaendig parst, bevor etwas laeuft (stdin-Skript).

set -euo pipefail

main() {
  local MODE="dry-run" PROBE=0 ARCHIVE_PATH="" arg
  for arg in "$@"; do
    case "$arg" in
      --dry-run) MODE="dry-run" ;;
      --apply) MODE="apply" ;;
      --rollback) MODE="rollback" ;;
      --probe-tasks) PROBE=1 ;;
      --archive=*) ARCHIVE_PATH="${arg#--archive=}" ;;
      *) echo "Unbekanntes Argument: $arg" >&2; return 2 ;;
    esac
  done

  local SVC="$HOME/services" GUIDIR="$HOME/services/bach/system/gui"
  local PLIST="$HOME/Library/LaunchAgents/com.bach.gui-server.plist" LABEL="com.bach.gui-server"
  local ROLL="$HOME/compute/rollback-20261106" DOMAIN="gui/$(id -u)"
  local STATE="$ROLL/state.env" BASE="http://127.0.0.1:8000"
  local REPO_GUI="ellmos-ai/ellmos-system-gui" PROBLEMS=0

  say() { printf '%s\n' "$*"; }
  hdr() { printf '\n== %s\n' "$*"; }
  bad() { say "PROBLEM: $*"; PROBLEMS=$((PROBLEMS + 1)); }
  die() { say "ABBRUCH: $*" >&2; exit 1; }

  branch_of() { case "$1" in task-master) echo master ;; *) echo main ;; esac; }

  # ---- Hilfsfunktionen -------------------------------------------------------------------------
  tracked_changes() { git -C "$1" status --porcelain --untracked-files=no </dev/null; }

  repo_readback() { # (a)
    local r d br
    hdr "(a) Vorab-Readback der Repos"
    for r in bach ellmos-system-gui task-master lock-master; do
      d="$SVC/$r"
      if [ ! -d "$d/.git" ]; then say "$r: nicht vorhanden"; continue; fi
      br=$(git -C "$d" branch --show-current </dev/null)
      say "$r: $(git -C "$d" rev-parse HEAD </dev/null) ($br)"
      local tracked untracked
      tracked=$(tracked_changes "$d")
      untracked=$(git -C "$d" status --porcelain --untracked-files=normal </dev/null | grep '^??' || true)
      [ -n "$untracked" ] && say "  untracked (ok): $(printf '%s' "$untracked" | tr '\n' ' ')"
      if [ -n "$tracked" ]; then
        say "  getrackte Aenderungen:"; printf '%s\n' "$tracked" | sed 's/^/    /'
        case "$r" in bach|task-master) bad "$r hat getrackte Aenderungen - nichts wird verworfen, Deploy bricht ab" ;; esac
      fi
    done
    say "plist ELLMOS_SYSTEM_GUI_DIST: $(plutil -extract EnvironmentVariables.ELLMOS_SYSTEM_GUI_DIST raw "$PLIST" </dev/null)"
    say "GUI-Prozess: $(launchctl list </dev/null | awk -v l="$LABEL" '$3==l {print "pid="$1" status="$2}')"
  }

  expected_from_text() { # liest kit_manifest-JSON aus stdin, setzt Soll-Werte, falls nicht per env gesetzt
    python3 -c '
import json,sys
m=json.load(sys.stdin)
print(m["version"]); print(m["pinned_source_commit"]); print(m["release_archive"]); print(m["release_archive_sha256"]); print(m["expected_page_count"])'
  }

  load_expected() { # $1 = Quelle: "worktree" oder "remote"
    local out
    if [ "$1" = worktree ]; then out=$(expected_from_text < "$GUIDIR/kit_manifest.json")
    else out=$(curl -fsS "https://raw.githubusercontent.com/ellmos-ai/bach/main/system/gui/kit_manifest.json" </dev/null | expected_from_text)
    fi
    { read -r E_VERSION; read -r E_COMMIT; read -r E_ARCHIVE; read -r E_SHA; read -r E_PAGES; } <<<"$out"
    E_VERSION="${GUI_VERSION:-$E_VERSION}"; E_COMMIT="${GUI_COMMIT:-$E_COMMIT}"
    E_ARCHIVE="${GUI_ARCHIVE:-$E_ARCHIVE}"; E_SHA="${GUI_SHA256:-$E_SHA}"
    NEWDIR="$GUIDIR/shared-release-${E_VERSION}-${E_COMMIT:0:12}"
    TAG="v${E_VERSION}"
    URL="https://github.com/$REPO_GUI/releases/download/$TAG/$E_ARCHIVE"
  }

  show_expected() {
    say "Soll: version=$E_VERSION commit=$E_COMMIT pages=$E_PAGES"
    say "      archiv=$E_ARCHIVE sha256=$E_SHA"
    say "      Ziel-dist: $NEWDIR/dist"
  }

  verify_dist_dir() { # $1 = Verzeichnis mit dist/ + LICENSE ; prueft Manifest-Commit, alle Hashes, Dateimenge
    python3 - "$1" "$E_COMMIT" <<'PY'
import hashlib, json, pathlib, sys
root = pathlib.Path(sys.argv[1]); commit = sys.argv[2]
dist = root / "dist"
m = json.loads((dist / "dist-manifest.json").read_text(encoding="utf-8"))
assert m.get("schema") == "ellmos-system-gui.dist.v1", "Manifest-Schema"
assert m.get("source_commit") == commit, f"source_commit {m.get('source_commit')} != {commit}"
files = m["files"]
actual = {p.relative_to(dist).as_posix() for p in dist.rglob("*") if p.is_file()}
assert actual == set(files) | {"dist-manifest.json"}, "Dateimenge weicht vom Manifest ab"
for name, digest in files.items():
    assert hashlib.sha256((dist / name).read_bytes()).hexdigest() == digest, f"Hash {name}"
assert (root / "LICENSE").is_file(), "LICENSE fehlt"
print(f"dist ok: {len(files)} Dateien, Commit {commit[:12]}")
PY
  }

  caps_readback() { # $1 = erwartete Version
    local body
    body=$(curl -fsS --max-time 20 "$BASE/api/gui/capabilities" </dev/null) || { bad "capabilities nicht erreichbar"; return 1; }
    printf '%s' "$body" | python3 -c '
import json,sys
d=json.load(sys.stdin); k=d["kit"]
keep={x:k.get(x) for x in ("version","revision","verified","installed_files_verified","dist_page_count","reason_code")}
print("capabilities.kit:", json.dumps(keep))
sys.exit(0 if (len(sys.argv)<2 or not sys.argv[1] or k.get("version")==sys.argv[1]) else 3)' "${1:-}" || return 1
    printf '%s' "$body" | python3 -c '
import json,sys
k=json.load(sys.stdin)["kit"]; want=int(sys.argv[1]) if len(sys.argv)>1 and sys.argv[1] else None
ok = k.get("verified") is True and k.get("installed_files_verified") is True and (want is None or k.get("dist_page_count")==want)
sys.exit(0 if ok else 4)' "${2:-}"
  }

  tasks_readback() { # Cookie-Session minten, Tasks lesen, abmelden
    local jar; jar=$(mktemp -t pb9jar) || return 1
    curl -fsS --max-time 20 -o /dev/null -c "$jar" -H 'Sec-Fetch-Dest: document' "$BASE/" </dev/null || { rm -f "$jar"; bad "GET / fehlgeschlagen"; return 1; }
    if ! grep -q bach_device_token "$jar"; then rm -f "$jar"; bad "keine Loopback-Session erhalten (Device-ID unbekannt?)"; return 1; fi
    local rc=0
    local PYT
    PYT=$(cat <<'PY'
import json, sys
d = json.load(sys.stdin)
t = d.get("tasks") or []
arch = [x for x in t if str(x.get("status", "")).strip().lower() == "archived"]
print("tasks nonterminal: geliefert=%d total=%s archived=%d" % (len(t), d.get("total"), len(arch)))
sys.exit(0 if (d.get("success") and not arch) else 5)
PY
)
    curl -fsS --max-time 60 -b "$jar" "$BASE/api/tasks?status=nonterminal&limit=1000" </dev/null | python3 -c "$PYT" || rc=$?
    curl -fsS --max-time 20 -X POST -b "$jar" -o /dev/null -w "logout http=%{http_code}\n" "$BASE/api/devices/session/logout" </dev/null || say "Hinweis: Logout nicht bestaetigt"
    rm -f "$jar"
    return $rc
  }

  wait_healthy() { # bis zu 120 s auf capabilities warten
    local i
    for i in $(seq 1 60); do
      if curl -fsS --max-time 3 -o /dev/null "$BASE/api/gui/capabilities" </dev/null 2>/dev/null; then return 0; fi
      sleep 2
    done
    return 1
  }

  restart_gui() { # bootout + bootstrap, weil kickstart die plist nicht neu liest
    launchctl bootout "$DOMAIN/$LABEL" </dev/null 2>/dev/null || true
    local n
    for n in 1 2 3 4 5; do
      sleep 3
      if launchctl bootstrap "$DOMAIN" "$PLIST" </dev/null 2>/dev/null; then return 0; fi
    done
    launchctl bootstrap "$DOMAIN" "$PLIST" </dev/null
  }

  restore_plist() { # $1 = Sicherung
    cp -p "$1" "$PLIST" && plutil -lint "$PLIST" </dev/null >/dev/null
  }

  # ---- Modi ------------------------------------------------------------------------------------
  if [ "$MODE" = dry-run ]; then
    say "PB-9 Deploy DRY-RUN $(date '+%Y-%m-%d %H:%M:%S %Z') auf $(hostname)"
    repo_readback
    hdr "(b) Repo-Stand gegen origin (nur ls-remote, kein fetch)"
    local r d br remote
    for r in bach task-master; do
      d="$SVC/$r"; br=$(branch_of "$r")
      remote=$(git -C "$d" ls-remote origin "refs/heads/$br" </dev/null | cut -f1)
      if [ "$remote" = "$(git -C "$d" rev-parse HEAD </dev/null)" ]; then say "$r: bereits auf origin/$br ($remote)"
      else say "$r: lokal $(git -C "$d" rev-parse --short HEAD </dev/null), origin/$br $remote -> pull --ff-only wuerde vorruecken"; fi
    done
    hdr "(c) Soll-Werte und Archiv"
    load_expected remote; show_expected
    say "Release-URL: $URL"
    if [ -n "$ARCHIVE_PATH" ]; then
      if [ -f "$ARCHIVE_PATH" ]; then say "Archiv-Parameter: $ARCHIVE_PATH, sha256 $(shasum -a 256 "$ARCHIVE_PATH" </dev/null | awk '{print $1}')"; else bad "Archiv $ARCHIVE_PATH fehlt"; fi
    fi
    local code; code=$(curl -s -o /dev/null -w '%{http_code}' -I -L "$URL" </dev/null || true)
    say "Release-Asset HTTP: $code (200 erwartet; 404 heisst: Release noch nicht veroeffentlicht oder Pin noch nicht in origin/main)"
    [ -e "$NEWDIR" ] && say "Hinweis: $NEWDIR existiert bereits" || say "Ziel-dist existiert noch nicht (gut)"
    [ -e "$STATE" ] && bad "$STATE existiert bereits - ein frueherer Lauf hat Rollback-Daten hinterlegt; --apply bricht ohne FORCE=1 ab"
    say "Aktuelle dist-Verzeichnisse mit Daten:"; ls -d "$GUIDIR"/shared-release-0.2.3[2-4]* 2>/dev/null | sed 's/^/  /' || true
    say "Freier Platz: $(df -h "$HOME" </dev/null | tail -1 | awk '{print $4}')"
    hdr "(d) Neustartweg"
    say "plist-Sicherung -> $ROLL/, plutil -replace ELLMOS_SYSTEM_GUI_DIST, launchctl bootout+bootstrap $DOMAIN/$LABEL"
    launchctl print "$DOMAIN/$LABEL" </dev/null | grep -E 'state =|pid =' | head -2 | sed 's/^/  /'
    hdr "(e) Readback gegen den laufenden Stand (vor dem Deploy)"
    caps_readback "" "" || say "(erwartet: Version != Soll vor dem Deploy)"
    if [ "$PROBE" = 1 ]; then tasks_readback || bad "tasks-Readback (Probe)"; else say "tasks-Readback nicht ausgefuehrt (--probe-tasks setzt es, mintet kurz eine Loopback-Session)"; fi
    hdr "Ergebnis"
    [ "$PROBLEMS" = 0 ] && say "DRY-RUN ok, --apply kann laufen (sofern Release-Asset 200 und Pin in origin/main)." || { say "$PROBLEMS Problem(e) - siehe oben."; return 1; }
    return 0
  fi

  if [ "$MODE" = apply ]; then
    say "PB-9 Deploy APPLY $(date '+%Y-%m-%d %H:%M:%S %Z') auf $(hostname)"
    repo_readback
    [ "$PROBLEMS" = 0 ] || die "Vorab-Pruefung nicht sauber"
    [ ! -e "$STATE" ] || [ "${FORCE:-0}" = 1 ] || die "$STATE existiert (frueherer Lauf). Erst --rollback oder Sicherung pruefen; FORCE=1 ueberschreibt bewusst."
    mkdir -p "$ROLL"

    hdr "(b) Pull --ff-only"
    local PREV_BACH PREV_TM PREV_DIST
    PREV_BACH=$(git -C "$SVC/bach" rev-parse HEAD </dev/null); PREV_TM=$(git -C "$SVC/task-master" rev-parse HEAD </dev/null)
    PREV_DIST=$(plutil -extract EnvironmentVariables.ELLMOS_SYSTEM_GUI_DIST raw "$PLIST" </dev/null)
    git -C "$SVC/bach" fetch --quiet origin </dev/null
    # Pin vor dem Pull pruefen: sonst wuerde bach vorruecken, ohne dass ein Archiv zum Pin existiert.
    git -C "$SVC/bach" show origin/main:system/gui/kit_manifest.json </dev/null > "$ROLL/kit_manifest.origin-main.json"
    E_VERSION= ; load_expected remote
    local pin_version; pin_version=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["version"])' "$ROLL/kit_manifest.origin-main.json")
    [ "$pin_version" = "$E_VERSION" ] || die "origin/main pinnt GUI $pin_version, erwartet $E_VERSION (Pin-PR noch nicht gemergt?)"
    show_expected
    # Archiv zuerst holen und pruefen: scheitert es, hat noch nichts am Mac etwas veraendert ausser dem Rollback-Ordner.
    hdr "(c) Archiv holen und pruefen"
    local DL="$ROLL/dl" ZIP; mkdir -p "$DL"
    if [ -n "$ARCHIVE_PATH" ]; then
      ZIP="$ARCHIVE_PATH"; [ -f "$ZIP" ] || die "Archiv $ZIP nicht gefunden"
      say "Archiv aus Parameter: $ZIP"
    else
      ZIP="$DL/$E_ARCHIVE"; curl -fL --retry 3 --max-time 300 -o "$ZIP" "$URL" </dev/null
    fi
    local got; got=$(shasum -a 256 "$ZIP" </dev/null | awk '{print $1}')
    [ "$got" = "$E_SHA" ] || die "SHA-256 des Archivs $got != $E_SHA"
    say "Archiv-SHA-256 ok: $got"
    local STAGE="$GUIDIR/.stage-${E_VERSION}-$$"; rm -rf "$STAGE"; mkdir -p "$STAGE"
    python3 - "$ZIP" "$STAGE" <<'PY'
import pathlib, sys, zipfile
z = zipfile.ZipFile(sys.argv[1]); out = pathlib.Path(sys.argv[2]).resolve()
for n in z.namelist():
    assert n == "LICENSE" or n.startswith("dist/"), f"unerwarteter Eintrag {n}"
    assert (out / n).resolve().is_relative_to(out), f"Pfad verlaesst Ziel: {n}"
z.extractall(out)
PY
    verify_dist_dir "$STAGE"
    [ ! -e "$NEWDIR" ] || die "$NEWDIR existiert bereits"

    # Ab hier aendert sich der Mac. Rollback-Daten zuerst sichern.
    hdr "Sicherung"
    cp -p "$PLIST" "$ROLL/com.bach.gui-server.plist.orig"
    cp -p "$PLIST" "$PLIST.bak-20261106"
    cp -R "$PREV_DIST" "$ROLL/dist-0.2.33"
    cat > "$STATE" <<EOF
PREV_BACH=$PREV_BACH
PREV_TM=$PREV_TM
PREV_DIST=$PREV_DIST
NEWDIR=$NEWDIR
EOF
    say "Rollback-Daten: $STATE (bach $PREV_BACH, task-master $PREV_TM, dist $PREV_DIST)"

    git -C "$SVC/bach" pull --ff-only --quiet origin main </dev/null
    git -C "$SVC/task-master" pull --ff-only --quiet origin master </dev/null
    say "bach jetzt $(git -C "$SVC/bach" rev-parse HEAD </dev/null), task-master $(git -C "$SVC/task-master" rev-parse HEAD </dev/null)"
    [ "$(python3 -c 'import json;print(json.load(open("'"$GUIDIR"'/kit_manifest.json"))["version"])')" = "$E_VERSION" ] || die "kit_manifest im Arbeitsbaum != $E_VERSION"

    mv "$STAGE" "$NEWDIR"
    verify_dist_dir "$NEWDIR"

    hdr "(d) Umstellen und Neustart"
    plutil -replace EnvironmentVariables.ELLMOS_SYSTEM_GUI_DIST -string "$NEWDIR/dist" "$PLIST" </dev/null
    plutil -lint "$PLIST" </dev/null
    restart_gui || { say "bootstrap fehlgeschlagen - stelle plist wieder her"; restore_plist "$ROLL/com.bach.gui-server.plist.orig"; restart_gui || true; die "Neustart fehlgeschlagen, plist zurueckgesetzt (Code ist weiterhin auf neuem Stand; --rollback fuer beides)"; }
    if ! wait_healthy; then say "GUI nach 120 s nicht erreichbar - stelle plist wieder her"; restore_plist "$ROLL/com.bach.gui-server.plist.orig"; restart_gui || true; die "GUI nicht gesund, plist zurueckgesetzt (--rollback fuer den Code)"; fi

    hdr "(e) Readback"
    local rc=0
    caps_readback "$E_VERSION" "$E_PAGES" || { bad "capabilities weicht ab"; rc=1; }
    tasks_readback || { bad "tasks-Readback"; rc=1; }
    hdr "Ergebnis"
    if [ "$rc" = 0 ]; then say "APPLY ok: GUI $E_VERSION verified, keine archivierten Tasks im Offen-Filter."; else say "APPLY mit Abweichungen - pruefen, ggf. --rollback."; return 1; fi
    return 0
  fi

  if [ "$MODE" = rollback ]; then
    say "PB-9 Deploy ROLLBACK $(date '+%Y-%m-%d %H:%M:%S %Z') auf $(hostname)"
    [ -f "$STATE" ] || die "$STATE fehlt - kein Rollback-Stand vorhanden"
    # shellcheck disable=SC1090
    . "$STATE"
    say "Ziel: dist $PREV_DIST, bach $PREV_BACH, task-master $PREV_TM"
    local d
    for d in bach task-master; do
      [ -z "$(tracked_changes "$SVC/$d")" ] || die "$d hat getrackte Aenderungen - Rollback bricht ab (nichts wird verworfen)"
    done
    cp -p "$ROLL/com.bach.gui-server.plist.orig" "$PLIST"; plutil -lint "$PLIST" </dev/null
    say "plist: $(plutil -extract EnvironmentVariables.ELLMOS_SYSTEM_GUI_DIST raw "$PLIST" </dev/null)"
    git -C "$SVC/bach" reset --keep "$PREV_BACH" </dev/null
    git -C "$SVC/task-master" reset --keep "$PREV_TM" </dev/null
    say "bach $(git -C "$SVC/bach" rev-parse HEAD </dev/null), task-master $(git -C "$SVC/task-master" rev-parse HEAD </dev/null)"
    restart_gui
    wait_healthy || die "GUI nach Rollback nicht erreichbar - Log: ~/Library/Logs/bach/gui-server.err.log"
    caps_readback "0.2.33" "" || bad "capabilities nach Rollback"
    [ "$PROBLEMS" = 0 ] && say "ROLLBACK ok. Das neue Verzeichnis ${NEWDIR:-?} bleibt liegen (zum Aufraeumen manuell)." || return 1
    mv "$STATE" "$STATE.rolled-back-$(date +%H%M%S)"
    return 0
  fi
}

main "$@"
