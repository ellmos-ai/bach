# Operator-Runbook: assistant-core auf Pin `444a1ff` transferieren

**Task:** `#1241` / `#1236`  
**Ziel:** Den lokalen `assistant-core`-Checkout von `ccadcf9` (v0.1.0) auf den gepinnten Commit `444a1fffd56236078988d088f6237f706c3e15a9` bringen.  
**Blocker:** SSH-Authentifizierung gegen `github.com` funktioniert noch nicht, weil die Host-SSH-Keys noch nicht bei GitHub registriert sind.

---

## Betroffene Hosts

Der Transfer muss auf allen drei Hosts erfolgen:

1. **MacStudio** (Primary)
2. **WORKSTATION-LG**
3. **ASUS-GEI**

> Hinweis: Die Hosts sind nicht über SSH voneinander erreichbar. Das Skript muss auf jedem Host lokal ausgeführt werden.

---

## Voraussetzung auf jedem Host

### 1. SSH-Key erstellen (falls noch nicht vorhanden)

```bash
ls ~/.ssh/id_ed25519.pub
```

Falls die Datei fehlt:

```bash
ssh-keygen -t ed25519 -C "$(hostname -s)-transfer" -f ~/.ssh/id_ed25519 -N ""
```

### 2. SSH-Key bei GitHub registrieren

Den Public-Key anzeigen:

```bash
cat ~/.ssh/id_ed25519.pub
```

Dann unter folgender URL einfügen:  
**https://github.com/settings/ssh/new**

Titel-Vorschlag: `BACH <Hostname> transfer assistant-core`.

### 3. SSH-Auth testen

```bash
ssh -T git@github.com
```

Erwartete Ausgabe:

```
Hi <username>! You've successfully authenticated, but GitHub does not provide shell access.
```

---

## Transfer durchführen

Sobald die SSH-Authentifizierung funktioniert, auf **jedem Host** ausführen:

```bash
cd ~/services/bach
bash system/bin/transfer-assistant-core-444a1ff.sh
```

### Was macht das Skript?

1. Prüft SSH-Auth gegen `github.com` (fail-fast).
2. Zeigt verfügbare SSH-Public-Keys an.
3. Erstellt ein Backup-Bundle von `assistant-core` unter `~/services/bach/data/assistant-core-backups/`.
4. Setzt den Git-Remote auf `git@github.com:ellmos-ai/assistant-core.git`.
5. Fetched den Ziel-Pin und checkt ihn aus.
6. Verifiziert HEAD = `444a1ff`.
7. Führt `pytest system/tests/test_notify_via_assistant_core.py` aus.

### Dry-Run (ohne Änderungen)

```bash
cd ~/services/bach
bash system/bin/transfer-assistant-core-444a1ff.sh --dry-run
```

---

## Fehlerbehebung

### `Permission denied (publickey)`

- Ist der Key tatsächlich bei GitHub registriert?
- Läuft `ssh-agent` und ist der private Key geladen?
  ```bash
  eval "$(ssh-agent -s)"
  ssh-add ~/.ssh/id_ed25519
  ```
- Kein Tippfehler im Key auf GitHub?
- Korrekte `~/.ssh/config`?

### `HEAD ist ..., erwartet 444a1ff`

- Prüfe, ob der Pin tatsächlich im Repo verfügbar ist:
  ```bash
  cd ~/services/assistant-core
  git fetch origin
  git log --oneline origin/HEAD | head -20
  ```

### pytest schlägt fehl

- Zuerst das venv prüfen:
  ```bash
  ls -l ~/.venvs/bach/bin/python
  ```
- Falls der Test fehlt:
  ```bash
  ls -l ~/services/bach/system/tests/test_notify_via_assistant_core.py
  ```

---

## Rollback

Falls nach dem Checkout etwas schiefgeht, kann zum vorherigen Zustand zurückgekehrt werden:

```bash
cd ~/services/assistant-core
git checkout ccadcf9
```

Oder über das Backup-Bundle:

```bash
cd ~/services/assistant-core
BACKUP=~/services/bach/data/assistant-core-backups/assistant-core-before-444a1ff-<HOST>-<ZEITSTEMPEL>.bundle
git fetch "${BACKUP}" 'refs/*:refs/backups/*'
git checkout ccadcf9
```

---

## Abnahme

**NUR** wenn das Skript auf **allen 3 Hosts** erfolgreich (GRÜN) durchgelaufen ist:

```bash
bach task done 1236
bach task done 1241
```

---

## Alternative ohne SSH (nicht empfohlen)

Falls SSH nicht möglich ist, kann stattdessen ein GitHub-Personal-Access-Token (PAT) mit `repo`-Recht verwendet werden:

```bash
cd ~/services/assistant-core
git remote set-url origin https://<TOKEN>@github.com/ellmos-ai/assistant-core.git
GIT_TERMINAL_PROMPT=0 git fetch origin 444a1fffd56236078988d088f6237f706c3e15a9
git checkout 444a1fffd56236078988d088f6237f706c3e15a9
```

Das PAT muss anschließend sicher verwahrt werden. Das SSH-Verfahren ist vorzuziehen.
