#!/usr/bin/env bash
# Push local BACH worker commits to a stable review branch and open one draft PR.
# This script never updates or pushes the remote main branch.
set -euo pipefail

MODE="${1:---status}"
BACH_DIR="${BACH_HARVEST_ROOT:-${HOME}/services/bach}"
REMOTE="${BACH_HARVEST_REMOTE:-origin}"
REPO_SLUG="${BACH_HARVEST_REPO:-ellmos-ai/bach}"
GIT_BIN="${BACH_HARVEST_GIT_BIN:-git}"
GH_BIN="${BACH_HARVEST_GH_BIN:-gh}"
PYTHON_BIN="${BACH_HARVEST_PYTHON:-python3}"
LOCK_SCAN="${BACH_HARVEST_LOCK_SCAN:-}"
RECEIPT_FILE="${BACH_HARVEST_RECEIPT:-${HOME}/Library/Logs/bach/git-harvester.jsonl}"

case "${MODE}" in
  --status|--dry-run|--run) ;;
  *) echo "Usage: $0 [--status|--dry-run|--run]" >&2; exit 2 ;;
esac

timestamp() { date -u "+%Y-%m-%dT%H:%M:%SZ"; }

receipt() {
  local action="$1" detail="$2"
  mkdir -p "$(dirname "${RECEIPT_FILE}")"
  printf '{"ts":"%s","action":"%s","detail":"%s"}\n' \
    "$(timestamp)" "${action}" "${detail}" >> "${RECEIPT_FILE}"
}

fail() {
  local message="$1"
  receipt "blocked" "${message//\"/}" || true
  echo "[BLOCKED] ${message}" >&2
  exit 1
}

[[ -d "${BACH_DIR}/.git" || -f "${BACH_DIR}/.git" ]] || fail "Kein Git-Checkout: ${BACH_DIR}"

if [[ -z "${LOCK_SCAN}" ]]; then
  for candidate in \
    "${HOME}/Library/CloudStorage/OneDrive-Personal/_scripts/lock_scan.py" \
    "${HOME}/Library/CloudStorage/OneDrive/_scripts/lock_scan.py" \
    "${HOME}/OneDrive/_scripts/lock_scan.py"
  do
    if [[ -f "${candidate}" ]]; then
      LOCK_SCAN="${candidate}"
      break
    fi
  done
fi
[[ -n "${LOCK_SCAN}" && -f "${LOCK_SCAN}" ]] \
  || fail "Kanonisches lock_scan.py nicht gefunden"
command -v "${PYTHON_BIN}" >/dev/null 2>&1 \
  || fail "Python für kanonische Lock-Prüfung nicht gefunden: ${PYTHON_BIN}"

BACH_DIR="$(cd "${BACH_DIR}" && pwd -P)"
home_dir="$(cd "${HOME}" && pwd -P)"
case "${BACH_DIR}/" in
  "${home_dir}/"*) ;;
  *) fail "Checkout liegt außerhalb von HOME; Parent-Lock-Prüfung ist unbestimmt" ;;
esac

# Der kanonische Scanner prueft Worktree/Main-Clone/Zwilling. Zusaetzlich werden
# alle Eltern bis HOME geprueft, damit projektuebergreifende User-/Condition-
# Locks nicht durch den unbeaufsichtigten Fetch oder Push umgangen werden.
check_dir="${BACH_DIR}"
while :; do
  if ! lock_output="$("${PYTHON_BIN}" "${LOCK_SCAN}" --check-dir "${check_dir}" --strict 2>&1)"; then
    fail "Lock-Prüfung blockiert ${check_dir}: ${lock_output//$'\n'/ }"
  fi
  [[ "${check_dir}" == "${home_dir}" ]] && break
  parent_dir="$(dirname "${check_dir}")"
  [[ "${parent_dir}" != "${check_dir}" ]] \
    || fail "Parent-Lock-Prüfung erreichte HOME nicht"
  check_dir="${parent_dir}"
done

cd "${BACH_DIR}"

branch="$(${GIT_BIN} symbolic-ref --quiet --short HEAD 2>/dev/null || true)"
[[ "${branch}" == "main" ]] || fail "Harvester erwartet den lokalen Branch main, gefunden: ${branch:-detached}"
[[ ! -e "$(${GIT_BIN} rev-parse --git-path MERGE_HEAD)" ]] || fail "Merge ist noch nicht abgeschlossen"

remote_url="$(${GIT_BIN} remote get-url "${REMOTE}" 2>/dev/null || true)"
case "${remote_url}" in
  "https://github.com/${REPO_SLUG}"|"https://github.com/${REPO_SLUG}.git"|\
  "git@github.com:${REPO_SLUG}.git"|"ssh://git@github.com/${REPO_SLUG}.git") ;;
  *) fail "Remote ${REMOTE} zeigt nicht auf github.com/${REPO_SLUG}" ;;
esac

${GIT_BIN} fetch --prune "${REMOTE}" main
remote_main="refs/remotes/${REMOTE}/main"
${GIT_BIN} rev-parse --verify "${remote_main}^{commit}" >/dev/null \
  || fail "${remote_main} fehlt nach fetch"

head_sha="$(${GIT_BIN} rev-parse HEAD)"
[[ "${head_sha}" =~ ^[0-9a-f]{40}$ ]] || fail "Lokaler HEAD ist keine vollständige Commit-ID"
ahead="$(${GIT_BIN} rev-list --count "${remote_main}..${head_sha}")"
behind="$(${GIT_BIN} rev-list --count "${head_sha}..${remote_main}")"
short_sha="${head_sha:0:12}"
host_raw="${BACH_HARVEST_HOST:-$(hostname -s)}"
host="$(printf '%s' "${host_raw}" | tr '[:upper:]_' '[:lower:]-' | tr -cd 'a-z0-9.-')"
day="${BACH_HARVEST_DATE:-$(date -u +%Y%m%d)}"
review_branch="mac/${host:-host}-${head_sha}"

echo "[HARVEST] HEAD=${head_sha} ahead=${ahead} behind=${behind} branch=${review_branch}"

# Uncommitted live changes (e.g. interim deploys copied into the tree) are
# captured as a snapshot commit built from a temporary index. HEAD, the real
# index and the working tree stay untouched; nothing is merged.
dirty="$(${GIT_BIN} status --porcelain --untracked-files=all)"
dirty_count=0
[[ -z "${dirty}" ]] || dirty_count="$(printf '%s\n' "${dirty}" | grep -c .)"
[[ "${dirty_count}" == "0" ]] || echo "[DIRTY] ${dirty_count} uncommittete Pfade im Live-Baum"

if [[ "${ahead}" == "0" && "${dirty_count}" == "0" ]]; then
  receipt "noop" "head=${short_sha};ahead=0;behind=${behind}"
  exit 0
fi

if [[ "${MODE}" == "--status" || "${MODE}" == "--dry-run" ]]; then
  receipt "status" "head=${short_sha};ahead=${ahead};behind=${behind};dirty=${dirty_count};target=${review_branch}"
  exit 0
fi

${GH_BIN} auth status --hostname github.com >/dev/null 2>&1 \
  || fail "gh ist für github.com nicht authentifiziert"

push_sha="${head_sha}"
pr_title="harvest(${host}): lokale BACH-Worker-Commits ${day}"
pr_summary="Automatisch abgeholte lokale BACH-Worker-Commits vom Host ${host}."
if [[ "${dirty_count}" != "0" ]]; then
  index_file="$(mktemp)"
  trap 'rm -f "${index_file:-}" "${body_file:-}"' EXIT
  GIT_INDEX_FILE="${index_file}" ${GIT_BIN} read-tree "${head_sha}"
  GIT_INDEX_FILE="${index_file}" ${GIT_BIN} add -A
  tree_sha="$(GIT_INDEX_FILE="${index_file}" ${GIT_BIN} write-tree)"
  [[ "${tree_sha}" =~ ^[0-9a-f]{40}$ ]] || fail "Snapshot-Tree ist keine vollständige ID"
  while IFS= read -r path; do
    [[ -f "${path}" ]] || continue
    (( $(wc -c < "${path}") <= 5242880 )) || fail "Snapshot enthält Datei über 5 MB: ${path}"
  done < <(GIT_INDEX_FILE="${index_file}" ${GIT_BIN} diff --cached --name-only --diff-filter=AM "${head_sha}")
  if GIT_INDEX_FILE="${index_file}" ${GIT_BIN} diff --cached -U0 "${head_sha}" \
      | grep -qE '^\+.*(ghp_[A-Za-z0-9]{20}|github_pat_|sk-or-v1-|-----BEGIN [A-Z ]*PRIVATE KEY|AKIA[0-9A-Z]{16})'; then
    fail "Snapshot enthält mögliche Zugangsdaten; Live-Baum manuell prüfen"
  fi
  # Same tree on the same base gives the same commit ID, so later runs reuse it.
  base_date="$(${GIT_BIN} show -s --format=%cI "${head_sha}")"
  push_sha="$(GIT_AUTHOR_DATE="${base_date}" GIT_COMMITTER_DATE="${base_date}" \
    ${GIT_BIN} commit-tree "${tree_sha}" -p "${head_sha}" \
    -m "snapshot(${host}): uncommittete Live-Änderungen auf ${short_sha}")"
  [[ "${push_sha}" =~ ^[0-9a-f]{40}$ ]] || fail "Snapshot-Commit ist keine vollständige ID"
  review_branch="mac/${host:-host}-live-${tree_sha:0:12}"
  pr_title="snapshot(${host}): uncommittete Live-Änderungen ${day}"
  pr_summary="Automatisch gesicherte uncommittete Änderungen (${dirty_count} Pfade) aus dem Live-Baum von ${host}, gebaut über einen temporären Index; der Live-Baum blieb unverändert."
  echo "[SNAPSHOT] tree=${tree_sha} commit=${push_sha} branch=${review_branch}"
fi

pr_number="$(${GH_BIN} pr list --repo "${REPO_SLUG}" --head "${review_branch}" \
  --base main --state all --limit 1 --json number --jq '.[0].number // empty')"

read_pr() {
  local number="$1"
  ${GH_BIN} pr view "${number}" --repo "${REPO_SLUG}" \
    --json number,url,state,isDraft,headRefName,headRefOid,baseRefName,mergedAt \
    --jq '[.number,.url,.state,.isDraft,.headRefName,.headRefOid,.baseRefName,.mergedAt] | map(if . == null then "" else tostring end) | join("|")'
}

validate_pr_identity() {
  [[ "${rb_number}" == "${pr_number}" && "${rb_head}" == "${review_branch}" \
      && "${rb_oid}" == "${push_sha}" && "${rb_base}" == "main" ]] \
    || fail "PR-Readback stimmt nicht mit Commit, Branch und Basis überein"
}

if [[ -n "${pr_number}" ]]; then
  readback="$(read_pr "${pr_number}")"
  IFS='|' read -r rb_number rb_url rb_state rb_draft rb_head rb_oid rb_base rb_merged <<< "${readback}"
  validate_pr_identity
  case "${rb_state}" in
    MERGED)
      receipt "noop" "head=${push_sha};branch=${review_branch};pr=${rb_number};state=MERGED;url=${rb_url}"
      echo "[OK] Commit bereits über PR #${rb_number} gemergt: ${rb_url}"
      exit 0
      ;;
    CLOSED)
      fail "PR #${rb_number} ist ungemergt geschlossen; automatisches Neuerstellen blockiert"
      ;;
    OPEN)
      [[ "${rb_draft}" == "true" ]] || fail "PR #${rb_number} ist nicht mehr Draft"
      receipt "pr" "head=${push_sha};branch=${review_branch};pr=${rb_number};state=OPEN;draft=true;url=${rb_url}"
      echo "[OK] Bestehender Draft-PR #${rb_number}: ${rb_url}"
      exit 0
      ;;
    *) fail "Unbekannter PR-Status für #${rb_number}: ${rb_state}" ;;
  esac
fi

# Exakter, zuvor gepruefter Commit als Quellref; ein spaeter bewegtes lokales
# HEAD kann weder Branch noch Receipt veraendern. Kein Force, niemals main.
${GIT_BIN} push --porcelain "${REMOTE}" "${push_sha}:refs/heads/${review_branch}"

if [[ -z "${pr_number}" ]]; then
  body_file="$(mktemp)"
  trap 'rm -f "${index_file:-}" "${body_file:-}"' EXIT
  cat > "${body_file}" <<EOF
${pr_summary}

- Ausgangs-HEAD: ${head_sha}
- Gepushter Commit: ${push_sha}
- Commits vor origin/main: ${ahead}
- Commits hinter origin/main: ${behind}
- Uncommittete Pfade: ${dirty_count}
- Ziel: Review nach D-20260902-002

Dieser PR darf erst nach unabhängiger Prüfung gemergt werden. Der Harvester pusht niemals auf main.
EOF
  created_url="$(${GH_BIN} pr create --repo "${REPO_SLUG}" --base main \
    --head "${review_branch}" --draft \
    --title "${pr_title}" \
    --body-file "${body_file}")"
  pr_number="${created_url##*/}"
  [[ "${pr_number}" =~ ^[0-9]+$ ]] || fail "PR-Erstellung lieferte keine lesbare PR-Nummer"
fi

readback="$(read_pr "${pr_number}")"
IFS='|' read -r rb_number rb_url rb_state rb_draft rb_head rb_oid rb_base rb_merged <<< "${readback}"
validate_pr_identity
[[ "${rb_state}" == "OPEN" ]] || fail "Neu erstellter PR #${rb_number} ist nicht OPEN"
[[ "${rb_draft}" == "true" ]] || fail "Neu erstellter PR #${rb_number} ist nicht Draft"

receipt "pr" "head=${push_sha};branch=${review_branch};pr=${rb_number};state=${rb_state};draft=${rb_draft};url=${rb_url}"
echo "[OK] PR #${rb_number}: ${rb_url} (${rb_state}, draft=${rb_draft})"
