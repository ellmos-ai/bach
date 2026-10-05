import json
import subprocess
import urllib.error
import urllib.request

BRANCH = "feat/T-20260920-823767362-s8-skills-projection"
TITLE = "S8 (T-20260920-823767362): Skills- und Workflow-Projektionen aus Registern"
API = "https://api.github.com/repos/ellmos-ai/open-ocean"

proc = subprocess.run(
    ["git", "credential", "fill"],
    input="protocol=https\nhost=github.com\n\n",
    capture_output=True,
    text=True,
)
token = None
for line in proc.stdout.splitlines():
    if line.startswith("password="):
        token = line.split("=", 1)[1]
if not token:
    print("ERROR: no token from git credential fill")
    print("stdout:", proc.stdout)
    print("stderr:", proc.stderr)
    raise SystemExit(1)
print("token acquired (len=%d)" % len(token))


def api_request(url, method="GET", body=None):
    data = None
    headers = {
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "User-Agent": "s8-pr-script",
    }
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req) as resp:
            payload = resp.read().decode("utf-8")
            return resp.status, (json.loads(payload) if payload.strip() else {})
    except urllib.error.HTTPError as e:
        payload = e.read().decode("utf-8")
        try:
            parsed = json.loads(payload)
        except Exception:
            parsed = {"raw": payload}
        return e.code, parsed


status, pulls = api_request(API + "/pulls?state=open&per_page=50")
if status != 200:
    print("ERROR listing open PRs: %s %s" % (status, pulls))
    raise SystemExit(1)

print("open PRs: %d" % len(pulls))
base = "main"
for pr in pulls:
    head_ref = pr["head"]["ref"]
    print("PR #%s: %s -> %s" % (pr["number"], head_ref, pr["base"]["ref"]))
    if base == "main" and "s7-memory-transit" in head_ref:
        base = head_ref
print("selected base: " + base)

body = (
    "S8 (T-20260920-823767362): read-only projection of skills/tools from BACH "
    "ControlCenter registries. No live cutover, no registry write path. "
    "Parity not-accepted.\n\n"
    "Counts (contract-recorded):\n"
    "- tool_registry: 45\n"
    "- ati_tool_registry: 137\n"
    "- skills: 128\n"
    "- toolchain_runs: 6\n"
    "- tool_patterns: 5\n"
    "- agents: 6\n\n"
    "Toolchain verdict:\n"
    "- workflowhooker v0.2.1: no toolchain strings, workflow_tuev not present "
    "(provides: workflow.hook, workflow.check; tuev: false)\n"
    "- MarbleRun HEAD 938f3d5 (main): no toolchain strings, workflow_tuev not "
    "present\n"
    "- marblerun carrier use_cases [chain, recurring, routine]: not-evidenced\n\n"
    "Files:\n"
    "- architecture/bach-skills-workflow-projection-contract.v1.json\n"
    "- tools/check_skills_workflow_projection.py\n"
    "- tests/test_check_skills_workflow_projection.py\n"
    "- tests/fixtures/skills_workflow_projection/marblerun-chain-skill.json\n"
    "- tests/fixtures/skills_workflow_projection/taskmaster-ati-tool.json\n"
    "- tests/fixtures/skills_workflow_projection/connectors-msg-pattern.json\n"
    "- tests/fixtures/skills_workflow_projection/expected.json\n\n"
    "Checks: checker exit 0 (PASSED, schema+fixture conformance, not equivalence "
    "with a live BACH ControlCenter registry); 12 new S8 tests plus S7 regression "
    "suite, 23 passed total."
)

payload = {"title": TITLE, "head": BRANCH, "base": base, "body": body}
status, created = api_request(API + "/pulls", method="POST", body=payload)
if status not in (200, 201):
    print("POST with head=%s failed: %s %s" % (BRANCH, status, created))
    print("retrying with fork-qualified head")
    payload["head"] = "lukisch:" + BRANCH
    status, created = api_request(API + "/pulls", method="POST", body=payload)

if status not in (200, 201):
    print("ERROR creating PR: %s %s" % (status, created))
    raise SystemExit(1)

print("PR #%s" % created["number"])
print("PR URL: %s" % created["html_url"])