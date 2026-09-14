# TRANSFER-09 Gate1 — OPERATOR-HANDOFF (verifiziert)

Erstellt: 2026-09-12 ~11:35 · BACH (qwen3.8) · Task #1248 (Operator-Handoff) · bezieht #1236
Grundlage: `OPERATOR-RUNBOOK-ASSISTANT-CORE-444a1fff.md`

## Status: BEREIT FÜR OPERATOR — lokal nicht ausführbar (verifiziert)

### Warum lokal NICHT machbar (Beweis 2026-09-12 11:35, MacStudio)
- SSH-Auth: `ssh -i ~/.ssh/id_ed25519 -T git@github.com` → **`Permission denied (publickey)`**
- `git ls-remote git@github.com:ellmos-ai/assistant-core.git` (SSH) → **`Permission denied (publickey)`**
- Credential-Suche: **keine** nicht-interaktive Quelle
  - `gh auth status` → "not logged into any GitHub hosts"
  - kein `~/.netrc`, keine `GITHUB_TOKEN`/`GIT_*`-Envvars
  - `security find-internet-password -s github.com` → nicht gefunden
  - kein `~/.config/gh/hosts.yml`
- Reach: BACH erreicht nur **MacStudio**. WORKSTATION-LG & ASUS-GEI = separate Hosts (kein Zugriff).
- Delegation an Claude/Codex bringt **keine** Credentials (gleiche Umgebung) → nutzlos.
- **Verbot**: Keine eigene `NotificationService`-Fälschung (bricht Pin `444a1fff` + Gate). ✓ nicht getan.

### "Vorher"-Snapshot (MacStudio, 2026-09-12 11:35)
- `~/services/assistant-core` HEAD = `ccadcf9` (v0.1.0)
- Remote `origin` = `https://github.com/ellmos-ai/assistant-core.git`
- `test_notify_via_assistant_core.py` → **ROT**: `ImportError: cannot import name 'NotificationService' from 'assistant_core'`
- Ziel-Pin: `444a1fffd56236078988d088f6237f706c3e15a9` (v0.2.0, in `bach/requirements.txt:62`)

---

## Operator-Schritte pro Host (Option A — SSH-Key, empfohlen)

Hosts (alle müssen pin-konform sein): **MacStudio** · **WORKSTATION-LG** · **ASUS-GEI**

### 1) SSH-Key bei GitHub hochladen (einmalig, Browser)
Öffne https://github.com/settings/ssh/new und trage pro Host den dortigen `id_ed25519.pub` ein.

- **MacStudio** (bereits verfügbar, Titel `macstudio-transfer`):
  ```
  ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIAl8WNWzjtqo3G7r+InFdnwUDzsSBRo+eymcE7dcsFqt macstudio-transfer
  ```
- **WORKSTATION-LG**: auf diesem Host ausführen → `cat ~/.ssh/id_ed25519.pub` → Titel z.B. `workstation-lg-transfer`
- **ASUS-GEI**: auf diesem Host ausführen → `cat ~/.ssh/id_ed25519.pub` → Titel z.B. `asus-gei-transfer`

### 2) Remote auf SSH umstellen (pro Host, nicht-destruktiv)
```bash
cd ~/services/assistant-core
git remote set-url origin git@github.com:ellmos-ai/assistant-core.git
```

### 3) Fetch + Checkout (pro Host, nun nicht-interaktiv möglich)
```bash
git fetch origin
git checkout 444a1fffd56236078988d088f6237f706c3e15a9
```

### 4) Verifikation (pro Host)
```bash
git rev-parse --short HEAD
# -> muss 444a1ff liefern
cd ~/services/bach
~/.venvs/bach/bin/python -m pytest system/tests/test_notify_via_assistant_core.py -q
# -> 3 Tests GRÜN: construct, storage-mark, no-network-in-handler
```

### Fallback Option B (nur falls SSH-Key NICHT zulässig)
Einmalig PAT im Keychain ablegen, dann fetch+checkout:
```bash
printf "host=github.com\nprotocol=https\nusername=<GH_USER>\npassword=<PAT>\n" | git credential-osxkeychain store
cd ~/services/assistant-core && git fetch origin && git checkout 444a1fffd56236078988d088f6237f706c3e15a9
```

---

## Abschlusskriterien (Gate "Pin-Konformität aller Hosts")
- Auf **allen 3** Hosts: `git rev-parse --short HEAD` == `444a1ff`
- Auf **allen 3** Hosts: `test_notify_via_assistant_core.py` grün
- Erst danach: `task done 1236`
- **Bis dahin bleibt #1236 OPEN** (nicht vorzeitig schließen).
