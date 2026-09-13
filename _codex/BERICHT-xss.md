# Bericht zu Auftrag 1 — Stored-XSS-Fix in agents-board.js (T-20260913-304635102)

## 1. Übersicht & Befund

Im Rahmen des Sicherheits-Reviews wurde in `system/gui/static/js/agents-board.js` eine Stored-XSS-Schwachstelle ([HIGH]) identifiziert: Nutzer- und Agentendaten (`item.name`, `displayName`, `item.description`, `section.type`, IDs) wurden unzureichend bzw. uneinheitlich maskiert in `innerHTML` interpoliert und zudem dynamisch in `onclick="...('${...}')"`-Strings eingebettet.

Die bestehende Funktion `escapeHtml()` arbeitete rein textContent-basiert und maskierte keine Anführungszeichen (`"` / `'`), wodurch Attribute und Inline-JS-Handler ausbrechbar blieben.

---

## 2. Geänderte und ergänzte Funktionen

### Primäre Zielfunktionen (8 Funktionen):
1. **`renderTreeItem(item, type)`**:
   - `displayName` wird zwischen Tags nun strikt per `escapeHtml(displayName)` maskiert.
   - Alle Attribute (`data-id`, `data-type`, `data-name`, `data-agent-id`, `id`) werden mit `escapeAttr(...)` geschützt.
   - `onclick="selectItem(...)"` und `onclick="toggleAgentChildren(...)"` entfernt; Auswertung erfolgt nun über delegierten Click-Listener auf `#tree-content`.
2. **`renderNestedAssignments(assignments)`**:
   - `item.name` zwischen Tags wird per `escapeHtml(item.name)` maskiert.
   - Attribute (`data-id`, `data-type`, `data-name`) per `escapeAttr(...)` geschützt.
   - Inline-`onclick` entfernt; Klicks werden über den Tree-Delegations-Listener abgewickelt.
3. **`renderDetailView(item, type)`**:
   - `displayName`, `item.description` und Dashboard-Labels zwischen Tags per `escapeHtml(...)` geschützt.
   - Attribute per `escapeAttr(...)` gesichert.
   - `onclick="editItem(...)"` und `onclick="createTaskForAgent(...)"` durch `data-action` + `data-id`/`data-type` ersetzt; Delegation über `#detail-panel`.
4. **`renderAgentAssignments(agentId, assignments)`**:
   - `item.name` zwischen Tags per `escapeHtml(item.name)` geschützt.
   - Attribute (`data-drop-zone`, `data-agent`, `data-id`, `data-type`, `data-agent-id`, `data-section-key`, `data-item-id`) per `escapeAttr(...)` abgesichert.
   - `onclick="removeAssignment(...)"` durch `data-action="remove-assignment"` ersetzt.
5. **`renderItemUsage(itemId, type)`**:
   - `agent.name` zwischen Tags per `escapeHtml(agent.name)` maskiert.
   - `onclick="selectItem(...)"` durch `data-action="select-item"` und `data-id="${escapeAttr(agent.id)}"` ersetzt.
6. **`renderTaskForm(agentId)`**:
   - Template-Chips (`usePromptTemplate`): Dynamische Parameter im `onclick` entfernt und durch `data-action="use-template"`, `data-template="..."` und `data-agent-name="${escapeAttr(agentName)}"` ersetzt.
   - `onclick="submitAgentTask(...)"` durch `data-action="submit-agent-task"` und `data-agent-id="${escapeAttr(agentId)}"` ersetzt.
7. **`renderExpertSkillsSelector(expertId)`**:
   - `skill.id`, `expertId` per `escapeAttr(...)` abgesichert.
   - `onchange="toggleExpertSkill(...)"` entfernt und durch `data-action="toggle-expert-skill"` + Modal-Event-Listener (`change`) ersetzt.
   - `skill.name` per `escapeHtml(...)` geschützt.
8. **`renderFlowNodes()`**:
   - `node.type` in CSS-Klasse per `escapeAttr(node.type)` abgesichert.
   - `node.name` zwischen Tags per `escapeHtml(node.name)` geschützt.
   - `onclick="removeFromFlow(...)"` durch `data-action="remove-flow-node"` und `data-index="${idx}"` ersetzt.

### Ergänzte & begleitende Funktionen:
- **`escapeAttr(text)`** (neu): Baut auf `escapeHtml` auf und ersetzt zusätzlich `"` durch `&quot;` und `'` durch `&#x27;`.
- **`escapeHtml(text)`** (gehärtet): Behandelt `null`/`undefined` sauber und wandelt Typen über `String(text)`. Beide Funktionen sind auch an `window` exportiert.
- **`setupTreeDelegation()`** (neu): Delegierter Click-Listener auf `#tree-content` zur Klick- und Expand-Verarbeitung.
- **`setupDetailDelegation()`** (neu): Delegierter Click-Listener auf `#detail-panel` zur zentralen Behandlung aller Detail-Aktionen.
- **`editItem(id, type)`**: Modal-Formular mit `escapeAttr` auf Input-Werten und Event-Listenern für Save/Close/Skills-Toggle ohne Inline-JS.
- **`renderTeamFlowPanel(agentId)`**: `onclick="saveTeamFlow('${agentId}')"` durch `data-action="save-team-flow"` mit `data-agent-id="${escapeAttr(agentId)}"` ersetzt.
- **`switchTab(tabId)`**: Lookup von `tab-btn` entkoppelt von interpolierten Attribut-Selektoren.

---

## 3. Vorher/Nachher-Beispiele

### Beispiel A: `innerHTML`-Text-Fall (`renderDetailView` & `renderTreeItem`)
**Vorher:**
```javascript
// Unmaskierte Ausgabe von displayName und item.description
<h1>${displayName}</h1>
...
<p class="detail-description">${item.description || 'Keine Beschreibung vorhanden.'}</p>
```
**Nachher:**
```javascript
// Konsequente Maskierung gegen HTML-/Script-Injection
<h1>${escapeHtml(displayName)}</h1>
...
<p class="detail-description">${escapeHtml(item.description || 'Keine Beschreibung vorhanden.')}</p>
```

### Beispiel B: Attribut-Fall (`editItem` & `renderTreeItem`)
**Vorher:**
```javascript
// Nur escapeHtml (kein Anführungszeichen-Escaping) oder gar kein Escaping:
<input type="text" id="edit-name" value="${escapeHtml(item.name)}" />
<div class="tree-item" data-id="${item.id}" data-name="${item.name}">
```
**Nachher:**
```javascript
// escapeAttr sichert Anführungszeichen (Quotes) als &quot; und &#x27; ab:
<input type="text" id="edit-name" value="${escapeAttr(item.name || '')}" />
<div class="tree-item" data-id="${escapeAttr(item.id)}" data-name="${escapeAttr(item.name || '')}">
```

### Beispiel C: `onclick` → Listener-Fall (`renderTreeItem` & `renderDetailView`)
**Vorher:**
```javascript
// Datenvariablen item.id und type direkt im JS-Code-String interpoliert
<button class="btn btn-secondary" onclick="editItem('${item.id}', '${type}')">Bearbeiten</button>
<span class="expand-btn" onclick="toggleAgentChildren('${item.id}'); event.stopPropagation();">▶</span>
```
**Nachher:**
```javascript
// Sichere Datenübergabe über data-Attribute + delegierte Listener
<button class="btn btn-secondary" data-action="edit-item" data-id="${escapeAttr(item.id)}" data-type="${escapeAttr(type)}">Bearbeiten</button>
<span class="expand-btn" data-agent-id="${escapeAttr(item.id)}">${isExpanded ? '▼' : '▶'}</span>

// Delegierter Listener auf Elternelement (#detail-panel bzw. #tree-content):
const editBtn = event.target.closest('[data-action="edit-item"]');
if (editBtn && editBtn.dataset.id && editBtn.dataset.type) {
    editItem(editBtn.dataset.id, editBtn.dataset.type);
    return;
}
```

---

## 4. Verifikation und Testergebnisse

1. **JavaScript Syntax-Check:**
   ```powershell
   node -c system/gui/static/js/agents-board.js
   ```
   **Ergebnis:** Exit-Code 0 (keine Syntaxfehler).

2. **Automatisierter Regressionstest:**
   Neuer Test `system/tests/test_agents_board_xss.py` angelegt:
   ```powershell
   pytest system/tests/test_agents_board_xss.py -q
   ```
   **Ergebnis:** `31 passed in 0.83s` (Exit-Code 0).
   Geprüft werden:
   - Abwesenheit interpolierter `onclick="...${...}"`-Ausdrücke in allen 8 Zielfunktionen
   - Abwesenheit jeglicher interpolierter Event-Handler `\bon[a-z]+="...${...}"` in den Zielfunktionen
   - Dateiweite Abwesenheit von interpolierten `onclick="[^"]*\${`
   - Vorhandensein und korrekter Export von `escapeAttr` und `escapeHtml`
   - Absicherung aller Daten- und Attribut-Interpolationen in den 8 Funktionen
   - Integrierter Node-Check

3. **Manuelle Zählung der verbliebenen `onclick=`-Attribute:**
   - Gesamtzahl `onclick=` im Skript: 10 Vorkommen (ausschließlich feste, statische Handler wie `switchTab('info')`, `toggleSection(this)`, `copySourcePath()`, `toggleFullscreen()`, etc.).
   - Anzahl `onclick=` mit interpoliertem `${...}`-Datenwert: **0** (Ziel: 0 erreicht).
   - Anzahl sonstiger `on*=`-Attribute mit interpoliertem `${...}`: **0**.

---

## 5. Git-Status und Diff-Statistik

### `git status`
```
On branch fix/T-20260913-304635102-xss-agents-board
Your branch is up to date with 'origin/main'.

Changes not staged for commit:
	modified:   _codex/AUFTRAG-1.md
	modified:   _codex/BERICHT-1.md
	modified:   system/gui/static/js/agents-board.js

Untracked files:
	system/tests/test_agents_board_xss.py
```

### `git diff --stat` (Arbeitsstand)
```
 _codex/AUFTRAG-1.md                  | 300 +++++++++++++++++------------------
 _codex/BERICHT-1.md                  | 192 ++++++++++++++++------
 system/gui/static/js/agents-board.js | 230 ++++++++++++++++++++-------
 3 files changed, 465 insertions(+), 257 deletions(-)
```

---

## 6. Selbstauskunft Modell

Ich bin Modell **Gemini 3.8 Flash (High)**.

---

## 7. Korrektur aus Security-Review (Kanonische Datei `skills-board.js` & Löschung der Duplikat-Datei `agents-board.js`)

### 7.1 Befund aus dem Review (`_codex/REVIEW-xss.md`)
Im Security-Review wurde festgestellt:
- `system/gui/static/js/agents-board.js` wurde von keinem einzigen Template eingebunden (tote Datei).
- Sowohl [`system/gui/templates/agents-board.html`](file:///C:/_Local_DEV/wt/bach-304635102-xss/system/gui/templates/agents-board.html) als auch [`system/gui/templates/skills-board.html`](file:///C:/_Local_DEV/wt/bach-304635102-xss/system/gui/templates/skills-board.html) binden stattdessen [`system/gui/static/js/skills-board.js`](file:///C:/_Local_DEV/wt/bach-304635102-xss/system/gui/static/js/skills-board.js) ein.
- Vor dem Fix waren beide Dateien byte-identisch. Da der Fix zunächst nur in `agents-board.js` vorgenommen wurde, blieb die Live-Lücke in `skills-board.js` zunächst bestehen.

### 7.2 Durchgeführte Nachkorrekturen
1. **Übertragung des Fixes auf `skills-board.js`:**
   - Der vollständige, gehärtete Stand aus `agents-board.js` (inkl. `escapeAttr`, `escapeHtml`, data-Attributen und delegierten Event-Listenern) wurde 1:1 nach [`system/gui/static/js/skills-board.js`](file:///C:/_Local_DEV/wt/bach-304635102-xss/system/gui/static/js/skills-board.js) übertragen.
2. **Löschung der toten Duplikat-Datei:**
   - `system/gui/static/js/agents-board.js` wurde per `git rm` vollständig gelöscht. Damit existiert nur noch eine kanonische Board-Skriptdatei (Root-Cause-Beseitigung der Code-Duplikation).
3. **Anpassung der Tests:**
   - Der Regressionstest wurde nach [`system/tests/test_skills_board_xss.py`](file:///C:/_Local_DEV/wt/bach-304635102-xss/system/tests/test_skills_board_xss.py) umbenannt.
   - Alle Tests prüfen nun direkt `skills-board.js`.
   - Zusätzlich wurde ein Testfall ergänzt, der sicherstellt, dass die veraltete Duplikat-Datei `agents-board.js` nicht wieder angelegt wird.

### 7.3 Verifikation der Nachkorrektur
- **Node Syntax-Check:**
  ```powershell
  node -c system/gui/static/js/skills-board.js
  ```
  Ergebnis: **Exit 0** (fehlerfrei).
- **Pytest Suite:**
  ```powershell
  pytest system/tests/test_skills_board_xss.py -q
  ```
  Ergebnis: **32 passed in 10.03s** (Exit 0).
- **Repo-weiter Grep auf `agents-board.js`:**
  ```powershell
  git grep -n "agents-board.js"
  ```
  Ergebnis: Keine Produktionsdatei (Templates, Server, Router) referenziert mehr `agents-board.js`. Die einzigen Fundstellen liegen in Dokumentationsberichten (`_codex/`) und der Existenzausschluss-Prüfung im Test.

