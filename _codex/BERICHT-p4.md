# Abschlussbericht: Startseite (index.html) bereinigen — Punkt 4 (T-20260913-660268706)

**Worktree:** `C:/_Local_DEV/wt/bach-660268706-p4`  
**Branch:** `fix/T-20260913-660268706-p4-startseite-cleanup`  
**Datum:** 2026-09-13  

---

## 1. Übersicht der Umsetzungen

### 1) Chatfeld („AI Console“) entfernt
- In [system/gui/templates/index.html](file:///C:/_Local_DEV/wt/bach-660268706-p4/system/gui/templates/index.html) wurde die gesamte AI-Console-Box (Partner-Buttons Claude/Gemini/Ollama/Planner, Textarea `#headless-prompt`, Senden-Button und Link „Buddha Chat öffnen“) vollständig entfernt.
- Die dahinterliegenden JS-Funktionen in [system/gui/static/js/app.js](file:///C:/_Local_DEV/wt/bach-660268706-p4/system/gui/static/js/app.js) (`sendHeadlessPrompt`, `selectPartner`) blieben unangetastet.

### 2) Tab-Leiste, Tokens-Tab und Dateien-Tab entfernt, Verbindungen migriert
- Die Tab-Leiste (Buttons Startseite/Tokens/Dateien) und das Alpine-Attribut `x-data` am `<body>` wurden entfernt. Die Startseite ist nun eine direkte, einheitliche Übersichtsseite ohne Untertabs.
- Der Tokens-Tab (`id="tab-tokens"`) samt toter Script-Logik (`tokenConfig`, `loadTokenData`, `updateTokenUI`, `calculateCost`) wurde ersatzlos aus `index.html` entfernt, da der volle Funktionsumfang in [system/gui/templates/tokens.html](file:///C:/_Local_DEV/wt/bach-660268706-p4/system/gui/templates/tokens.html) (`/tokens`) bereitgestellt wird.
- Der Dateien-Tab (`id="tab-files"`) samt Review-Modal (`#process-modal`) und toter Script-Logik wurde aus `index.html` entfernt.
- **Migration des Verbindungen-Features (Mounts):**
  - In [system/gui/templates/inbox.html](file:///C:/_Local_DEV/wt/bach-660268706-p4/system/gui/templates/inbox.html) wurde ein dritter Tab hinzugefügt: Button `🔗 Verbindungen` (`id="tab-btn-connections"`, ruft `showTab(event, 'connections')` auf).
  - Tab-Content `tab-connections` enthält die Mounts-Tabelle (`#mounts-list-body`) und das Formular „Neuen Ordner anbinden“ im nativen CSS-Design von `inbox.html` (inkl. passender `.table-container`- und `.data-table`-Klassen).
  - Script-Funktionen `loadMounts()`, `addMount()`, `removeMount(alias)` und `restoreMounts()` wurden in `inbox.html` integriert und werden beim Wechsel auf den Tab `connections` via `showTab()` automatisch ausgeführt.
  - Das Backend (`/api/mounts` in `server.py`) blieb unverändert.

### 3) Sinnvolle Übersicht: Aktive Agenten ergänzt
- Auf der Startseite wurde eine neue Kachel **Aktive Agenten** in das Grid integriert (gleicher Tailwind-Kartenstil, Zähler `#stat-agents-active` und `#stat-agents-total`, Link zu `/agents`).
- In [system/gui/static/js/app.js](file:///C:/_Local_DEV/wt/bach-660268706-p4/system/gui/static/js/app.js) wurde die Funktion `loadActiveAgents()` implementiert, die `/api/agents` abfragt und in `loadDashboard()` aufgerufen wird. Der Zugriff auf Stat-Elemente in `loadStatus()` wurde zudem defensiv abgesichert.

### 4) Ausbaustufen-Sektion nach „System“ verschoben
- Der Abschnitt `<!-- Ausbaustufen Badges -->` wurde aus `index.html` entfernt.
- Die drei Stufen (Stufe 1: USMC, Stufe 2: Rinnsal, Stufe 3: BACH) wurden an das Ende von [system/gui/templates/settings.html](file:///C:/_Local_DEV/wt/bach-660268706-p4/system/gui/templates/settings.html) verschoben und an das dortige Theme/CSS (`.custom-panel`, `.theme-card`) angepasst.

---

## 2. Geänderte Dateien

| Datei | Status | Beschreibung |
|---|---|---|
| [system/gui/templates/index.html](file:///C:/_Local_DEV/wt/bach-660268706-p4/system/gui/templates/index.html) | Geändert | Startseite bereinigt (Chatfeld, Tab-Leiste, Tokens, Dateien, Ausbaustufen entfernt; Aktive-Agenten-Kachel ergänzt; tote Script-Funktionen aufgeräumt) |
| [system/gui/templates/inbox.html](file:///C:/_Local_DEV/wt/bach-660268706-p4/system/gui/templates/inbox.html) | Geändert | Tab „Verbindungen“ (🔗) inkl. Mounts-Tabelle, Anbinden-Formular, CSS-Styles und JS-Logik ergänzt |
| [system/gui/templates/settings.html](file:///C:/_Local_DEV/wt/bach-660268706-p4/system/gui/templates/settings.html) | Geändert | Sektion „Ausbaustufen“ (USMC, Rinnsal, BACH) am Seitenende vor `</main>` im nativen Settings-Design ergänzt |
| [system/gui/static/js/app.js](file:///C:/_Local_DEV/wt/bach-660268706-p4/system/gui/static/js/app.js) | Geändert | `loadActiveAgents()` ergänzt, in `loadDashboard()` integriert; DOM-Zugriffe in `loadStatus()` defensiv abgesichert |
| [system/tests/test_startseite_cleanup.py](file:///C:/_Local_DEV/wt/bach-660268706-p4/system/tests/test_startseite_cleanup.py) | Neu | Gezielte Testsuite für Bereinigung der Startseite, Verbindungen-Tab in `/inbox` und Ausbaustufen in `/settings` |

---

## 3. Testergebnisse

1. **Syntax-Prüfung `app.js`:**
   ```powershell
   node -c system/gui/static/js/app.js
   # Exit code 0, keine Fehler
   ```

2. **BeautifulSoup Parse Sanity Check:**
   ```powershell
   python -c "from bs4 import BeautifulSoup; from pathlib import Path; [BeautifulSoup(Path(f'system/gui/templates/{f}').read_text(encoding='utf-8'), 'html.parser') for f in ['index.html', 'inbox.html', 'settings.html']]; print('All HTML templates parsed successfully with BeautifulSoup')"
   # All HTML templates parsed successfully with BeautifulSoup
   ```

3. **Gezielte Testsuite `test_startseite_cleanup.py`:**
   ```powershell
   pytest system/tests/test_startseite_cleanup.py -q
   # 3 passed, 1 warning in 7.09s
   ```
   - `test_startseite_cleanup_get_index`: PASSED (bestätigt Status 200, kein `tab-tokens`, kein `tab-files`, kein `headless-prompt`, kein `Ausbaustufen`, `Aktive Agenten` vorhanden)
   - `test_inbox_has_verbindungen_tab`: PASSED (bestätigt Status 200, `Verbindungen`, `tab-btn-connections`, `tab-connections`, `mounts-list-body` vorhanden)
   - `test_settings_has_ausbaustufen`: PASSED (bestätigt Status 200, `Ausbaustufen`, `USMC`, `Rinnsal`, `BACH` vorhanden)

4. **Smoke-Testsuite `test_gui_server_smoke.py`:**
   ```powershell
   pytest system/tests/test_gui_server_smoke.py -q
   # 42 passed, 2 warnings in 39.83s
   ```

---

## 4. Git Diff Stat

```
 system/gui/static/js/app.js             |  39 +-
 system/gui/templates/inbox.html         | 147 +++++++
 system/gui/templates/index.html         | 763 +++----------------------------------
 system/gui/templates/settings.html      |  22 ++
 system/tests/test_startseite_cleanup.py |  88 +++++
 5 files changed, 344 insertions(+), 715 deletions(-)
```

---

## 5. Modell

Gemini 3.8 Flash (High)
