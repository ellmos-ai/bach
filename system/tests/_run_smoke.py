# -*- coding: utf-8 -*-
import urllib.request, json, sys

BASE = "http://localhost:18765"

PAGES = [
    "/", "/tasks", "/tasks-board", "/memory", "/agents", "/ati",
    "/tools", "/prompt-generator", "/skills-board", "/kontakte",
    "/agents/steuer", "/agents/gesundheit", "/agents/persoenlich",
    "/agents/foerderplaner", "/partners", "/help", "/inbox",
    "/daemon", "/messages", "/maintenance", "/logs", "/wiki",
    "/denkarium", "/tokens", "/financial", "/usecases", "/routinen",
    "/anonymization",
]

APIS = [
    "/api/status", "/api/tasks", "/api/agents", "/api/bach-agents",
    "/api/tools", "/api/skills", "/api/skills/categories",
    "/api/contacts", "/api/help", "/api/prompt-generator/templates",
    "/api/prompt-generator/daemon/status",
    "/api/memory/overview", "/api/memory/working",
    "/api/memory/lessons", "/api/memory/sessions", "/api/memory/facts",
    "/api/memory/stats/db", "/api/messages", "/api/partners",
    "/api/daemon/jobs", "/api/daemon/runs", "/api/daemon/status",
    "/api/daemon/chains", "/api/wartung/status",
    "/api/tokens/usage", "/api/scanner/status",
    "/api/scanner/tools", "/api/scanner/config",
    "/api/ati/stats", "/api/ati/tasks", "/api/ati/sessions",
    "/api/scanned-tasks", "/api/assignees",
    "/api/system/logs", "/api/denkarium",
    "/api/inbox/config", "/api/inbox/status",
    "/api/inbox/folders", "/api/inbox/rules",
    "/api/bericht/status", "/api/bericht/clients",
    "/api/mounts", "/api/session/activities",
    "/api/recurring", "/api/financial/status",
    "/api/financial/config", "/api/financial/categories",
    "/api/financial/accounts", "/api/financial/imap-presets",
    "/api/financial/profiles", "/api/financial/false-positives",
    "/api/financial/contracts", "/api/financial/insurances",
    "/api/financial/deadlines", "/api/financial/bank-accounts",
    "/api/financial/credits", "/api/usecases", "/api/routines",
    "/api/steuer/dokumente/unlinked", "/api/ws/status",
    "/api/anonymization/clients", "/api/skills-board/hierarchy",
]


def fetch(url):
    try:
        r = urllib.request.urlopen(url, timeout=10)
        c = r.getcode()
        b = r.read()
        return c, len(b), b
    except urllib.error.HTTPError as e:
        return e.code, 0, b""
    except Exception as e:
        return 0, 0, str(e).encode()


print("=" * 70)
print("BACH GUI SMOKE TEST")
print("=" * 70)

print("\n--- HTML Pages ---")
pok = pfail = 0
for p in PAGES:
    c, s, _ = fetch(BASE + p)
    if c == 200:
        pok += 1
    else:
        pfail += 1
    mark = "OK" if c == 200 else "FAIL"
    print("  %-30s %3d %8d bytes  %s" % (p, c, s, mark))
print("Pages: %d OK, %d FAIL" % (pok, pfail))

print("\n--- API Endpoints ---")
aok = afail = 0
errors = []
for ep in APIS:
    c, s, body = fetch(BASE + ep)
    if c == 200:
        aok += 1
        try:
            d = json.loads(body)
            if isinstance(d, list):
                detail = "%d items" % len(d)
            elif isinstance(d, dict):
                detail = "%d keys" % len(d)
            else:
                detail = type(d).__name__
        except Exception:
            detail = "%d bytes" % s
        print("  %-45s %3d  %s" % (ep, c, detail))
    else:
        afail += 1
        errors.append((ep, c))
        print("  %-45s %3d  FAIL" % (ep, c))
print("API: %d OK, %d FAIL" % (aok, afail))

if errors:
    print("\n--- Failed ---")
    for ep, c in errors:
        print("  %s -> %d" % (ep, c))

print("\n--- PromptManager ---")
c, s, body = fetch(BASE + "/api/prompt-generator/templates")
if c == 200:
    try:
        d = json.loads(body)
        if isinstance(d, dict):
            for k, v in d.items():
                if isinstance(v, list):
                    print("  %s: %d items" % (k, len(v)))
                elif isinstance(v, dict):
                    print("  %s: %d keys" % (k, len(v)))
                else:
                    print("  %s: %s" % (k, v))
    except Exception as e:
        print("  error: %s" % e)

total = pok + pfail + aok + afail
ok = pok + aok
fail = pfail + afail
print("\n" + "=" * 70)
print("TOTAL: %d OK, %d FAIL (of %d)" % (ok, fail, total))
sys.exit(1 if fail > 0 else 0)
