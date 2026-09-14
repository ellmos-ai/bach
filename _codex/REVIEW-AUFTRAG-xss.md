# Security-Review-Auftrag — Stored-XSS-Fix agents-board.js (T-20260913-304635102)

Du bist Security-Reviewer für den Branch `fix/T-20260913-304635102-xss-agents-board`
(BACH-Repo) gegen `origin/main`. Lies `git diff origin/main..HEAD -- system/gui/static/js/agents-board.js`
vollständig sowie den Auftrag `_codex/AUFTRAG-xss.md` und den Autorenbericht
`_codex/BERICHT-xss.md`.

## Hintergrund

[HIGH] Stored-XSS-Befund: ungeschützte innerHTML-Interpolation von
`item.name`/`displayName`/`item.description` und onclick-JS-String-Zusammenbau
in 8 Funktionen (`renderTreeItem`, `renderDetailView`, `renderNestedAssignments`,
`renderAgentAssignments`, `renderItemUsage`, `renderFlowNodes`,
`renderExpertSkillsSelector`, `renderTaskForm`).

Vorgegebener Fix: `escapeHtml` auf Text-Interpolation, eine neue `escapeAttr`-
Funktion (escaped zusätzlich Anführungszeichen) auf Attribut-Interpolation,
Entfernung aller onclick-Strings mit interpolierten Datenwerten zugunsten
delegierter `addEventListener` + `data-`-Attribute.

## Prüfe gezielt und gründlich (Sicherheitsfix, kein interpoliertes Feld darf durchrutschen)

1. Suche selbst per grep nach jedem verbliebenen Template-Literal-Ausdruck
   (Dollarzeichen gefolgt von geschweifter Klammer) innerhalb eines
   `onclick=`/`onchange=`/`oninput=`-Attributs in der geänderten Datei — jeder
   Treffer mit einem Datenwert (nicht nur festem String wie `'info'`) ist ein
   CHANGES-NEEDED.
2. Prüfe, ob `escapeAttr()` korrekt vor jedem Attributwert benutzt wird, der
   aus item/agent/skill/node-Daten stammt (`data-id`, `data-type`,
   `data-name`, `value`, `title`, `href`, `data-agent`, `data-drop-zone`).
3. Prüfe, ob `escapeHtml()` bei jeder Text-Interpolation aus Daten in den 8
   genannten Funktionen greift (nicht nur an den schon vorher vorhandenen
   Stellen).
4. Führe `node -c system/gui/static/js/agents-board.js` und
   `python -m pytest system/tests/test_agents_board_xss.py -q` SELBST aus und
   berichte Exit-Codes/Ergebnisse.
5. Prüfe, ob die delegierten Listener (`setupTreeDelegation`,
   `setupDetailDelegation`) tatsächlich die ursprüngliche Funktionalität
   erhalten (`selectItem`, `toggleAgentChildren`, `editItem`,
   `createTaskForAgent`, `switchTab` etc. werden weiterhin mit den richtigen
   Argumenten aufgerufen).
6. Baue selbst einen konkreten XSS-Payload-Test: ein Objekt mit einem Namen,
   der ein Bild-Tag mit einem onerror-Handler enthält (klassischer
   Stored-XSS-Payload), durch die Render-Logik laufen lassen (Node-Skript,
   kein Browser nötig — extrahiere die relevante Interpolationslogik oder
   simuliere sie direkt) und bestätige, dass kein ausführbares
   onerror-Attribut im Ergebnis-String vorkommt.

Urteil als APPROVE oder CHANGES-NEEDED mit konkreten Zeilenangaben bei
Befunden. Schreibe dein Ergebnis nach `_codex/REVIEW-xss.md`. Nenne am Ende
exakt dein Modell.
