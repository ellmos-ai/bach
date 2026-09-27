#!/usr/bin/env bash
# BACH Operator Transfer Script: assistant-core -> pin 444a1ff
# Task: #1241 / #1236 / #1248
#
# Purpose: idempotently switch the local assistant-core checkout from the
# current HEAD (ccadcf9 / v0.1.0) to the pinned commit 444a1fffd56236078988d088f6237f706c3e15a9.
#
# Safety: the script aborts BEFORE changing the repo if GitHub SSH authentication
# is not working.  It creates a local backup bundle of the current state before
# checkout so the operator can rollback with `git checkout -` if needed.
#
# Usage:
#   cd ~/services/bach
#   bash system/bin/transfer-assistant-core-444a1ff.sh
#   bash system/bin/transfer-assistant-core-444a1ff.sh --dry-run
#
# Must be executed on each of the 3 hosts after the host's SSH key has been
# registered at https://github.com/settings/ssh/new

set -euo pipefail

REPO_DIR="${REPO_DIR:-${HOME}/services/assistant-core}"
BACH_DIR="${BACH_DIR:-${HOME}/services/bach}"
VENV_PYTHON="${VENV_PYTHON:-${HOME}/.venvs/bach/bin/python}"
TARGET_PIN="444a1fffd56236078988d088f6237f706c3e15a9"
TARGET_SHORT="444a1ff"
REMOTE_SSH="git@github.com:ellmos-ai/assistant-core.git"
REMOTE_HTTPS="https://github.com/ellmos-ai/assistant-core.git"
DRY_RUN=0

log() { echo "[TRANSFER-444a1ff] $*"; }
err() { echo "[TRANSFER-444a1ff] ERROR: $*" >&2; }
warn() { echo "[TRANSFER-444a1ff] WARN: $*" >&2; }

# --- argument parsing ---------------------------------------------------------
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    -h|--help)
      sed -n '2,25p' "$0"
      exit 0
      ;;
    *) err "Unbekanntes Argument: $arg"; exit 1 ;;
  esac
done

if [[ "$DRY_RUN" -eq 1 ]]; then
  log "DRY-RUN: Es werden KEINE Repo-Aenderungen vorgenommen."
fi

HOSTNAME_TAG="${HOSTNAME:-$(hostname -s 2>/dev/null || hostname)}"
log "Starte auf Host: ${HOSTNAME_TAG}"

# --- helper: find candidate SSH public keys -----------------------------------
find_ssh_keys() {
  local keys=""
  for f in "${HOME}/.ssh/id_ed25519.pub" "${HOME}/.ssh/id_rsa.pub" "${HOME}/.ssh/id_ecdsa.pub" "${HOME}/.ssh/id_ed25519_sk.pub"; do
    if [[ -f "$f" ]]; then
      keys="${keys}\n  $f"
    fi
  done
  echo -e "${keys:-\n  (keine .pub-Dateien in ~/.ssh gefunden)}"
}

# --- 1. Verify repo exists ----------------------------------------------------
if [[ ! -d "${REPO_DIR}/.git" ]]; then
  err "Repo ${REPO_DIR} nicht gefunden oder kein Git-Repo."
  err "Erstelle es zuerst, z.B.:"
  err "  git clone ${REMOTE_HTTPS} ${REPO_DIR}"
  exit 1
fi

# --- 2. SSH diagnostics -------------------------------------------------------
log "Pruefe SSH-Agent und verfuegbare Keys ..."
if command -v ssh-add >/dev/null 2>&1; then
  if ! ssh-add -l >/dev/null 2>&1; then
    warn "SSH-Agent laeuft, enthaelt aber keine geladenen Keys."
    warn "Falls die Authentifizierung fehlschlaegt, versuche: ssh-add ~/.ssh/id_ed25519"
  else
    log "SSH-Agent enthaelt geladene Keys."
  fi
else
  warn "ssh-add nicht verfuegbar. Stelle sicher, dass der private Key zugaenglich ist."
fi

log "Gefundene SSH-Public-Keys auf diesem Host:"
find_ssh_keys

log "Pruefe SSH-Authentifizierung gegen github.com (BatchMode, Timeout 10s) ..."
SSH_TEST_OUTPUT="$(ssh -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -T git@github.com 2>&1 || true)"

if ! echo "$SSH_TEST_OUTPUT" | grep -qiE "successfully authenticated|hi .*!"; then
  err "SSH-Authentifizierung gegen github.com fehlgeschlagen."
  err "Diagnose:"
  err "  Ausgabe: ${SSH_TEST_OUTPUT}"
  err ""
  err "Bitte den Host-SSH-Key bei GitHub registrieren:"
  err "  https://github.com/settings/ssh/new"
  err ""
  err "Moegliche Public-Keys dieses Hosts:"
  find_ssh_keys >&2
  err ""
  err "Falls der Key bereits registriert ist, pruefe:"
  err "  - Laeuft ssh-agent und ist der private Key geladen?"
  err "  - Ist ~/.ssh/config korrekt?"
  err "  - Tippfehler im Key auf GitHub?"
  exit 1
fi
log "SSH-Authentifizierung OK."

# --- 3. Inspect current state -------------------------------------------------
cd "${REPO_DIR}"
CURRENT_REMOTE="$(git remote get-url origin 2>/dev/null || echo 'NONE')"
CURRENT_HEAD="$(git rev-parse --short HEAD 2>/dev/null || echo 'UNKNOWN')"

log "Aktueller Remote: ${CURRENT_REMOTE}"
log "Aktueller HEAD:   ${CURRENT_HEAD}"

if [[ "$CURRENT_HEAD" == "$TARGET_SHORT" || "$CURRENT_HEAD" == "$TARGET_PIN" ]]; then
  log "HEAD ist bereits der Ziel-Pin. Fahre mit pytest-Check fort."
fi

if [[ "$DRY_RUN" -eq 1 ]]; then
  log "DRY-RUN: Wuerde remote auf ${REMOTE_SSH} setzen, fetch origin, checkout ${TARGET_PIN}."
  log "DRY-RUN: Wuerde anschliessend pytest system/tests/test_notify_via_assistant_core.py ausfuehren."
  log "DRY-RUN beendet. Keine Aenderungen vorgenommen."
  exit 0
fi

# --- 4. Backup current state --------------------------------------------------
BACKUP_DIR="${BACH_DIR}/data/assistant-core-backups"
mkdir -p "${BACKUP_DIR}"
BACKUP_BUNDLE="${BACKUP_DIR}/assistant-core-before-444a1ff-${HOSTNAME_TAG}-$(date +%Y%m%d-%H%M%S).bundle"
log "Erstelle Backup-Bundle: ${BACKUP_BUNDLE}"
if ! git bundle create "${BACKUP_BUNDLE}" --all 2>/dev/null; then
  warn "Backup-Bundle konnte nicht erstellt werden; fahre trotzdem fort."
  warn "Risiko: Rollback ist dann nur via 'git reflog' moeglich."
else
  log "Backup erstellt. Rollback: git fetch ${BACKUP_BUNDLE} && git checkout ${CURRENT_HEAD}"
fi

# --- 5. Switch remote to SSH --------------------------------------------------
if [[ "$CURRENT_REMOTE" != "$REMOTE_SSH" ]]; then
  log "Setze remote auf SSH: ${REMOTE_SSH}"
  git remote set-url origin "$REMOTE_SSH"
else
  log "Remote ist bereits SSH."
fi

# --- 6. Fetch and checkout pin ------------------------------------------------
log "Fetch origin ..."
GIT_TERMINAL_PROMPT=0 git fetch origin

log "Checkout Pin ${TARGET_PIN} ..."
git checkout "$TARGET_PIN"

# --- 7. Verify HEAD -----------------------------------------------------------
HEAD_SHORT="$(git rev-parse --short HEAD)"
if [[ "$HEAD_SHORT" != "$TARGET_SHORT" ]]; then
  err "HEAD ist ${HEAD_SHORT}, erwartet ${TARGET_SHORT}."
  exit 1
fi
log "HEAD = ${HEAD_SHORT} (OK)."

# --- 8. Run BACH pytest -------------------------------------------------------
log "Starte pytest system/tests/test_notify_via_assistant_core.py ..."
cd "${BACH_DIR}"
if [[ ! -x "${VENV_PYTHON}" ]]; then
  err "Venv-Python nicht gefunden: ${VENV_PYTHON}"
  err "Bitte zuerst venv anlegen/aktivieren."
  exit 1
fi

if [[ ! -f "system/tests/test_notify_via_assistant_core.py" ]]; then
  err "Test-Datei nicht gefunden: system/tests/test_notify_via_assistant_core.py"
  err "BACH-Installation scheint unvollstaendig."
  exit 1
fi

"${VENV_PYTHON}" -m pytest system/tests/test_notify_via_assistant_core.py -q

log "Transfer auf ${HOSTNAME_TAG} erfolgreich abgeschlossen."
log ""
log "ZUSAMMENFASSUNG:"
log "  Remote:  ${REMOTE_SSH}"
log "  HEAD:    ${HEAD_SHORT}"
log "  Backup:  ${BACKUP_BUNDLE}"
log ""
log "NAECHSTER SCHRITT:"
log "  Auf allen 3 Hosts (MacStudio / WORKSTATION-LG / ASUS-GEI) GRUEN, dann:"
log "    bach task done 1236"
