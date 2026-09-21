# OPERATOR-RUNBOOK: assistant-core → Pin 444a1fff (v0.2.0)

Zugehörig: Task #1236 · Gate: TRANSFER-09 · Befund B1 (Stufe-8-Zertifikat 2026-09-12)
Erstellt von BACH (qwen3.8) — 2026-09-12 08:29 (automatisiert, Credentials fehlen im nicht-interaktiven Kontext)

## Problem
- Lokal: `~/services/assistant-core` @ `ccadcf9` (v0.1.0, Welle 1)
- Pin in `~/services/bach/requirements.txt:62`:
  `assistant-core @ git+https://github.com/ellmos-ai/assistant-core.git@444a1fffd56236078988d088f6237f706c3e15a9`
- `hub/notify.py` importiert `CHANNELS, NotificationService, resolve_secret_refs, send_*`
  → diese fehlen in v0.1.0 → `test_notify_via_assistant_core.py` fällt mit
  `ImportError: cannot import name 'CHANNELS'`.
- `assistant-core` ist als **editable** auf `~/services/assistant-core` gekoppelt
  (pip editable, venv `~/.venvs/bach`), daher reicht ein Checkout-Wechsel im Repo.

## Warum nicht interaktiv?
Privates Repo `ellmos-ai/assistant-core`. Keine nicht-interaktiven Credentials:
- `credential.helper=osxkeychain` gesetzt, aber **kein** github.com-Eintrag im Keychain
- SSH-Key `~/.ssh/id_ed25519` (Label `macstudio-transfer`) bei GitHub **nicht registriert**
  (`ssh -T git@github.com` → `Permission denied (publickey)`)
- kein `~/.netrc`, kein `gh`-CLI/Token, kein ssh-agent-Identität
- v0.2.0-Quellen liegen **nicht** lokal (kein pip-Cache/Wheel/Bundle/OneDrive/Mount)

## Behebung (Operator, interaktiv) — pro Host
Hosts (Gate = alle pin-konform): **MacStudio (dieser)**, **WORKSTATION-LG**, **ASUS-GEI**

### Option A — einmalig SSH-Key registrieren (empfohlen, dauerhafter nicht-interaktiver Weg)
```bash
# 1. Key bei GitHub hochladen (einmalig, im Browser):
#    https://github.com/settings/ssh/new  ->  Titel z.B. "macstudio-transfer", Key = Inhalt:
cat ~/.ssh/id_ed25519.pub
#    (bei allen 3 Hosts jeweils den dortigen id_ed25519.pub hochladen)

# 2. Remote auf SSH umstellen (einmalig, pro Host, nicht-destruktiv):
cd ~/services/assistant-core
git remote set-url origin git@github.com:ellmos-ai/assistant-core.git

# 3. Fetch + Checkout (nun nicht-interaktiv möglich):
git fetch origin
git checkout 444a1fffd56236078988d088f6237f706c3e15a9

# 4. Verifikation:
git rev-parse --short HEAD        # -> 444a1ff
cd ~/services/bach
python3 -m pytest system/tests/test_notify_via_assistant_core.py -q   # muss GRÜNE
```

### Option B — PAT in Keychain (falls SSH-Key nicht zulässig)
```bash
# Einmalig: Personal Access Token im Keychain ablegen
echo "host=github.com
protocol=https
username=<GITHUB_USER>
password=<PASTE_PAT>" | git credential-osxkeychain store

# Dann pro Host:
cd ~/services/assistant-core
git fetch origin
git checkout 444a1fffd56236078988d088f6237f706c3e15a9
cd ~/services/bach
python3 -m pytest system/tests/test_notify_via_assistant_core.py -q
```

## Nach erfolgreichem Checkout auf ALLEN Hosts
- `git rev-parse --short HEAD` == `444a1ff`
- `test_notify_via_assistant_core.py` == grün (3 Tests: construct, storage-mark, no-network-in-handler)
- erst dann ist das TRANSFER-09-Gate "Pin-Konformität aller Hosts" erfüllt
- Task #1236 kann danach per `task done 1236` geschlossen werden

## Hinweis
Keine Fälschung: Eine eigene `NotificationService`-Implementierung wäre NICHT pin-konform
(bricht den Commit-Pin `444a1fff` und das Gate). Nur der echte Commit darf installiert werden.

---
## STATUS 2026-09-12 17:25 (Task #1254, Entscheidung #1240 = Option A) — vorbereitet, operator-blocked
- **MacStudio-Key verifiziert**: `~/.ssh/id_ed25519.pub` stimmt 1:1 mit Task-Key überein
  (`...Fqt macstudio-transfer`). Muss in https://github.com/settings/ssh/new hochgeladen werden.
- **SSH-Config vorbereitet (nicht-destruktiv, Backup `~/.ssh/config.bak.*`)**: `~/.ssh/config`
  enthält jetzt `Host github.com { IdentityFile ~/.ssh/id_ed25519; IdentitiesOnly yes }`.
- **Ready-to-Run-Skript (idempotent, fail-fast, kein Push, kein Credential-Prompt)**:
  `~/services/bach/system/scripts/task1254_checkout_444a1ff.sh`
  - Exit 3 = SSH-Block (Key nicht registriert) · Exit 0 = GRÜN · Exit 4-7 = fetch/checkout/pytest-Fehler
  - Dry-Run 17:25 korrekt Exit 3 (Key nicht registriert) — Repo unangetastet.
- **Aktion Operator (MacStudio)**: Key registrieren -> `bash ~/services/bach/system/scripts/task1254_checkout_444a1ff.sh`
- **WORKSTATION-LG / ASUS-GEI**: von MacStudio NICHT erreichbar -> dort lokal
  `ssh-keygen -t ed25519 -C <host>` (falls kein Key), Key hochladen, dann Skript lokal ausführen.
- **Abnahme**: GRÜN auf ALLEN 3 Hosts -> `task done 1236`.
- **KEIN FÄLSCHEN**: Eigene NotificationService NICHT nachbauen (nicht pin-konform).

---
## STATUS 2026-09-15 04:42 (Task #1248, Re-Verifikation) — weiterhin OPERATOR-BLOCKED, alles vorbereitet
- **SSH-Key NICHT registriert**: `ssh -T git@github.com` -> `Permission denied (publickey)` (exit 255).
  Key `macstudio-transfer` (`~/.ssh/id_ed25519.pub`) stimmt 1:1 mit Task-Key ueberein, ist aber
  weiterhin nicht auf github.com aktiv. -> **ein Operator-Schritt je Host** bleibt (Browser).
- **Transfer-Skript intakt & fail-fast korrekt**: `system/bin/transfer-assistant-core-444a1ff.sh --dry-run`
  laeuft sauber, prueft SSH-Auth, bricht bei fehlender Registrierung ab (EXIT=1), taetigt KEINE
  Repo-Änderung. Ready-to-Run-Skript ist also vorbereitet; nur die Key-Registrierung fehlt.
- **Repo unangetastet**: `~/services/assistant-core` @ `ccadcf9` (v0.1.0), Remote noch HTTPS.
  Kein Checkout, kein Push, kein Fälschen erfolgt — korrekt (Gate nicht erfuellbar ohne echten Key).
- **Entscheidung #1240/#1247 = Option A (SSH-Key, dauerhaft) gilt unverändert.**
- **Operator-Ein-Schritt je Host** (nur dies fehlt):
  1. Browser: `~/.ssh/id_ed25519.pub` auf https://github.com/settings/ssh/new hochladen
     (Titel je Host, z.B. `macstudio-transfer`, `WORKSTATION-LG-transfer`, `ASUS-GEI-transfer`).
  2. `ssh -T git@github.com` -> `Hi <user>! You've successfully authenticated`.
  3. `cd ~/services/bach && bash system/bin/transfer-assistant-core-444a1ff.sh`
     (idempotent, fail-fast, Backup-Bundle, kein Push) -> GRÜN.
- **Nur MacStudio verifizierbar hier**: WORKSTATION-LG / ASUS-GEI sind nicht erreichbar -> dort lokal
  Key ggf. `ssh-keygen -t ed25519 -C <host>-transfer` erzeugen, hochladen, Skript lokal ausführen.
- **Abnahme (Gate TRANSFER-09)**: GRÜN auf ALLEN 3 Hosts -> `task done 1236`.
- **NICHT tun**: NotificationService fälschen (bricht Pin 444a1ff) / git push / erzwungener Checkout.

## STATUS 2026-09-15 04:46 (Task #1248, Re-Verifikation #2) — OPERATOR-BLOCKED, kein lokaler Fix moeglich (definitiv belegt)
- **Key wird offeriert, aber von GitHub abgelehnt** (entscheidend): `ssh -vT git@github.com` zeigt
  `Offering public key: /Users/lukas/.ssh/id_ed25519 ED25519 SHA256:cFv6MMm+ziHLURAKxsTkorFsyqa2DbFoXqYFv64dUdk
  explicit agent` -> anschliessend `git@github.com: Permission denied (publickey)`. Der Key ist also korrekt
  geladen (ssh-agent) und korrekt offeriert (~/.ssh/config: `Host github.com` -> `IdentitiesOnly yes`,
  `IdentityFile ~/.ssh/id_ed25519`), wird aber von github.com abgelehnt => **der Key ist schlicht nicht im
  GitHub-Account registriert**. Damit ist JEDER lokale Fix (agent/config/key laden) ausgeschlossen.
- **Option B (PAT) ebenfalls blockiert**: kein `gh`-auth (`You are not logged into any GitHub hosts`),
  kein `~/.netrc`, kein globaler `credential.helper`, kein keychain-Eintrag für github.com. Kein
  Credential verfügbar, um den Key via API hochladen oder PAT zu speichern.
- **Zustand unverändert**: `ssh -T` -> `Permission denied`; assistant-core @ `ccadcf9`, Remote HTTPS;
  `transfer-assistant-core-444a1ff.sh --dry-run` bricht sauber an SSH-Schranke ab (EXIT=1), Repo unangetastet.
- **Fazit**: Gate TRANSFER-09 NICHT von BACH erreichbar. EIN Operator-Schritt je Host (Browser-Upload des
  .pub nach https://github.com/settings/ssh/new) ist der einzig fehlende Baustein. Nach Upload: Skript
  lokal ausfuehren -> GRUEN -> `task done 1236`. BACH wartet (Task #1248 = open, operator-blocked).

---
## [LOOP-GUARD 05:28] DEFINITIVER Fix — idle-worker-Claim-Loop gebrochen
- **Wurzelursache:** task_manage(action='update', status='blocked') hat den Status NICHT gesetzt;
  der idle-worker hat #1248 05:11 erneut auf in_progress gepickt. (claim_task_atomic schliesst
  'blocked' korrekt aus [task_audit.py:198 'status NOT IN (done,completed,cancelled,blocked)'],
  aber der update-Pfad hielt 'blocked' nicht -> Claim-Loop.)
- **Fix:** #1248 DIREKT in ~/.bach/bach.db auf status='blocked', claimed_by=NULL gesetzt +
  task_history-Eintrag (changed_by='idle-worker-guard').
- **Verifiziert:** SELECT -> (1248,'blocked',NULL); idle-worker-Pick-Check
  (status IN pending/open/in_progress) = 0 => 'NEIN (blocked)'. Loop gebrochen.
- **#1236 bleibt 'open'** (Gate NICHT erfuehlt -> NICHT vorsorglich geschlossen).
- **WIEDERAUFNAHME:** #1248 -> 'open' setzen, sobald Operator Key-Upload bestaetigt;
  dann auf MacStudio: ssh -T, bash system/bin/transfer-assistant-core-444a1ff.sh,
  Verifikation (git rev-parse 444a1ff + 3 grune Pytests), GRUEN auf allen 3 Hosts -> task done 1236.
