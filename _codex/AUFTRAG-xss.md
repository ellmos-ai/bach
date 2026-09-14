# Auftrag — Stored-XSS-Fix in agents-board.js (T-20260913-304635102)

Du arbeitest im Worktree `C:/_Local_DEV/wt/bach-304635102-xss` (Branch
`fix/T-20260913-304635102-xss-agents-board`, Basis `origin/main`, aktuell
`e3db932`). Committe auf DIESEM Branch. **NICHT pushen.**

Dies ist ein **Sicherheitsfix** — Gründlichkeit geht hier vor Kürze. Kein
Corner-Cutting bei Escaping/Sanitizing.

## Befund (aus automatisiertem Security-Review, [HIGH])

Datei: `system/gui/static/js/agents-board.js`. `container.innerHTML =` bzw.
`panel.innerHTML =` interpoliert Nutzer-/Agentendaten (`item.name`,
`displayName`, `item.description`, `section.type`, IDs) ungeschützt in
Markup UND baut `onclick="selectItem('${item.id}', ...)"` als JS-String
zusammen. Betroffene Funktionen (gefunden per `grep -n "^function"`):
- `renderTreeItem` (Zeile ~116)
- `renderNestedAssignments` (Zeile ~199)
- `renderDetailView` (Zeile ~269)
- `renderAgentAssignments` (Zeile ~460)
- `renderItemUsage` (Zeile ~496)
- `renderTaskForm` (Zeile ~523)
- `renderExpertSkillsSelector` (Zeile ~904)
- `renderFlowNodes` (Zeile ~1003)

Es gibt bereits `function escapeHtml(text)` (Zeile ~1121, textContent-basiert:
escaped `&`, `<`, `>`). Sie wird an einigen Stellen schon benutzt (z. B.
Zeile 533-536, 876, 880, 914, 1014), an den oben genannten Funktionen aber
NICHT konsequent.

**Wichtige Einschränkung von `escapeHtml()`:** Sie ist textContent-basiert
und escaped **keine Anführungszeichen** (`"`/`'`). Das reicht für Text
ZWISCHEN Tags (z. B. `<span>${escapeHtml(x)}</span>`), aber NICHT für Werte
INNERHALB eines HTML-Attributs (`data-name="${x}"`) oder innerhalb eines
`onclick="...('${x}')"`-JS-Strings — dort kann ein `"` oder `'` im Wert die
Anführungszeichen-Grenze durchbrechen. Deshalb reicht "escapeHtml drauf" bei
Attributen/onclick NICHT allein.

## Fix (in dieser Reihenfolge)

1. **Text-Interpolation (zwischen Tags):** Jede der o.g. 8 Funktionen
   durchgehen und JEDE interpolierte Variable, die aus Daten stammt
   (`item.name`, `displayName`, `item.description`, `section.type`/`.label`,
   `agent.name`, Namen/Beschreibungen aus verschachtelten Objekten in
   `renderNestedAssignments`/`renderAgentAssignments`/`renderItemUsage`/
   `renderFlowNodes`/`renderExpertSkillsSelector`), die als Text zwischen
   Tags landet, mit `escapeHtml(...)` umschließen — auch wenn es an anderer
   Stelle in derselben Funktion schon mal gemacht wurde, aber woanders in der
   Funktion fehlt. Feste, aus dem Code selbst stammende Strings (z. B.
   `typeConfig.icon`, `typeConfig.label` aus der lokalen `HIERARCHY_TYPES`-
   Konstante) brauchst du NICHT escapen — die kommen nicht von außen.
2. **Attribut-Interpolation:** Jede Stelle, an der eine Datenvariable in ein
   HTML-Attribut geschrieben wird (z. B. `data-name="${item.name}"`,
   `title="${x}"`, `value="${item.name}"` im Edit-Formular), zusätzlich zu
   `escapeHtml` auch Anführungszeichen absichern. Baue dafür EINE neue
   Hilfsfunktion `escapeAttr(text)` direkt neben `escapeHtml` (gleicher
   Stil), die zusätzlich `"` → `&quot;` und `'` → `&#x27;` ersetzt (auf dem
   Ergebnis von `escapeHtml` aufbauend), und benutze sie überall dort, wo der
   Wert in ein `"`-Attribut geschrieben wird.
3. **`onclick="...('${x}')"`-Strings entfernen (die 27 Vorkommen in den 8
   Funktionen, `grep -n "onclick=" system/gui/static/js/agents-board.js`):**
   Ersetze sie durch `data-`-Attribute (per `escapeAttr`) + EINEN delegierten
   `click`-Listener statt vieler Inline-Handler. Konkret:
   - Wo bereits `data-id`/`data-type` existieren (z. B. `renderTreeItem`s
     äußeres `.tree-item`-Div), das vorhandene `onclick="selectItem(...)"`
     entfernen — der Klick wird stattdessen über einen delegierten Listener
     auf einem stabilen Elternelement behandelt (z. B. dem Tree-Container;
     finde ihn über die Stelle, die `renderTreeItem`s Ergebnis einfügt, oder
     lege den Listener direkt nach der ersten Datenladung im
     `DOMContentLoaded`-Handler an, Zeile ~31). Im Listener:
     `event.target.closest('.tree-item')`, daraus `dataset.id`/`dataset.type`
     lesen, dann `selectItem(id, type)` aufrufen (Funktion bleibt
     unverändert). Für den `expand-btn` (`toggleAgentChildren`) genauso: ein
     `data-agent-id`-Attribut statt `onclick`, delegierter Listener auf
     `.expand-btn` prüft `event.target.closest('.expand-btn')` und ruft
     `event.stopPropagation()` + `toggleAgentChildren(id)` auf.
   - Für Buttons in `renderDetailView`/`renderTaskForm`/
     `renderExpertSkillsSelector`/`renderFlowNodes` (z. B.
     `onclick="editItem('${item.id}', '${type}')"`,
     `onclick="createTaskForAgent('${item.id}')"`,
     `onclick="switchTab('info')"` — bei LETZTEREM ist der Parameter ein
     fester String, kein Datenwert, DER darf als Ausnahme so bleiben, wenn
     dir das Umbauen an dieser einen Stelle unverhältnismäßig erscheint;
     wichtig ist ausschließlich, dass KEIN aus `item`/`agent`/Daten
     stammender Wert mehr in einem `onclick`-String landet): dasselbe Muster
     — `data-action="edit-item"` (o.ä.) + `data-id`/`data-type` per
     `escapeAttr`, ein delegierter Listener auf dem jeweiligen Container
     (z. B. `panel` in `renderDetailView`, direkt nach dem
     `panel.innerHTML = ...`-Aufruf per `panel.addEventListener('click', ...)`
     — das Panel wird bei jedem Render neu befüllt, ein Listener pro
     Render-Aufruf ist hier unproblematisch, da `panel.innerHTML` das alte
     Markup UND dessen Listener ohnehin ersetzt).
   - Halte das Muster pro Funktion konsistent, aber du musst nicht alle 8
     Funktionen identisch verdrahten — Hauptsache: am Ende steht in KEINER
     der 8 Funktionen mehr ein `onclick="...('${<Datenwert>}'...)"` mit
     interpoliertem Datenwert.
4. **Smoke-Test:** Lege (falls noch nicht vorhanden) in
   `system/tests/test_gui_templates_regression.py` einen Test an, der
   `system/gui/static/js/agents-board.js` einliest und per Regex/String-Suche
   sicherstellt, dass in den 8 genannten Funktionen KEIN
   `onclick="[^"]*\$\{` mehr vorkommt (d. h. kein Template-Literal-Ausdruck
   mehr innerhalb eines onclick-Attributs). Das ist ein reiner
   Static-Analysis-Test (kein Browser/JS-Runtime nötig) — Python `re` auf den
   Dateiinhalt reicht. Wenn diese Datei nicht existiert oder kein passendes
   Testmuster hat, prüfe zuerst `system/tests/` (nur lesen, NICHT
   umstrukturieren) und lege den Test dort ein, wo thematisch am ehesten
   passend (z. B. neue Datei `system/tests/test_agents_board_xss.py`, falls
   `test_gui_templates_regression.py` nicht passt).
5. **Funktion 1:1 erhalten:** Die sichtbare Funktionalität (Klick auf einen
   Tree-Eintrag wählt ihn aus, Expand/Collapse, Bearbeiten-Button,
   Task-erstellen-Button, Tab-Wechsel, Prompt-Templates, Flow-Nodes) darf
   sich NICHT ändern — nur der Übertragungsweg (onclick-String vs.
   Listener). Wenn du unsicher bist, ob ein Refactor eine Funktion bricht,
   bevorzuge die konservativere Variante (Listener zusätzlich zum
   bestehenden Code, statt große Teile umzuschreiben).
6. **NICHT anfassen:** `system/gui/templates/agents-board.html`, alle
   anderen `.js`-Dateien, `system/hub/routine.py`, Routinen-Endpunkte in
   `system/gui/server.py` (keine aktiven Locks mehr, aber außerhalb des
   Scopes).

## Verifikation

- `node -c system/gui/static/js/agents-board.js` → muss Exit 0 sein.
- Dein neuer/erweiterter Test unter `system/tests/` → `pytest <datei> -q`,
  Ergebnis berichten.
- Manuelle Kontrolle: `grep -n "onclick=" system/gui/static/js/agents-board.js`
  danach — zähle, wie viele der verbliebenen `onclick=`-Vorkommen (falls
  welche übrig sind, z. B. `switchTab('info')` mit festem String) noch einen
  interpolierten `${...}`-Datenwert enthalten. Ziel: 0.

## Selbstauskunft

Nenne am Ende deines Berichts EXAKT dein Modell.

## Bericht

Schreibe nach `_codex/BERICHT-1.md`: geänderte Funktionen, Vorher/Nachher an
2-3 Beispielen (ein `innerHTML`-Text-Fall, ein Attribut-Fall, ein
onclick→Listener-Fall), Testergebnis, `git diff --stat`, dein Modell.
Committe alles auf dem aktuellen Branch (Conventional Commits, z. B.
`fix(security): Stored-XSS in agents-board.js schliessen
(T-20260913-304635102)`). NICHT pushen.
