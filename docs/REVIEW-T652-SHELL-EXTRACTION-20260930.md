# T652 — neutrale Activity-Paketgrenze und offener Board-Port

session: 01a0f189-21d6-7851-a075-0aab0e3ebe77 | codex-gui-program@ASUS-GEI | 2026-09-30

Autorität: T-20260926-652455601, Root-Go für den nächsten kleinen Extraktionsschritt.
Richtung bleibt D-20260920-004/B: BACH-stämmige neutrale Vollschale, BACH als
Branding-Consumer, `ellmos-unified-gui` als eigenständig nutzbare Lite-Schale.
Die bereits abgenommenen PR13 und Doc/Auth174 werden nicht erneut umgesetzt.

Basen: BACH `113a6ad15a99f98aea9af33ee4b77941ac769f83`, GUI
`20003994637cadf5efead686c901bef5f18779b7`; beide Defaults frisch gefetcht.
Eigene Worktrees, kein Eingriff in fremde Änderungen oder PR164. Keine
Runtime-, Live-DB-, Service-, Remote-, Ticket- oder Workflow-Änderung.

## Implementierte Einheit

`system/ocean_gui_shell` ist eine separat baubare stdlib-Paketgrenze. Das
Activity-Template wurde verschoben und wird ausschließlich dort gepflegt.
`gui.activity_dashboard` delegiert Rendering und reicht BACH-Branding weiter.
Der optionale Lite-Consumer enthält keine Backend-Probes oder Proxyrouten;
er verwendet denselben Renderer für Standalone und Mount. Die normalen
Lite-Panels bleiben unabhängig und bekommen keine Pflichtabhängigkeit.
Backend-/Branding-Vertrag: `system/ocean_gui_shell/README.md`.

Die direkte BACH-URL `/activity` konsumiert über ihren unveränderten
ControlHandler den neuen Wrapper. Die neue Lite-Factory wird ausdrücklich
aufgerufen; die bestehende automatische `/control`-Einbindung wird dadurch
nicht stillschweigend zur Vollschale erweitert.

## PR164-Abgleich und konkret verbleibender Port

Gelesener Originalhead `6f2d5259e53dec9bc493071ef96740f98374b2e6`, Parent
`31579bdef6bb20a46ce4d627b3bbf4600e9797cd`. Der eigentliche Phase-2.3-Commit
ändert neun Dateien (520 Einfügungen, 40 Löschungen). Ein pauschaler Diff
gegen heutiges `main` enthält zusätzlich ältere Activity-Stände und darf
nicht als frischer Board-Port übernommen werden.

| Scope | Aktueller Befund | Noch erforderlicher Port |
|---|---|---|
| `board_renderers.py` | Nur im offenen PR; BACH-Defaults, JS-String-Ersetzung und unmaskiertes Icon | In neutrale Paketgrenze übernehmen, gemeinsames sicheres JSON-/HTML-/CSS-Rendering verwenden |
| agents-/skills-/tasks-Templates | Weiter unter BACH; PR parameterisiert einige Titel und Basen | Ressourcen und alle Assetreferenzen gemeinsam verschieben; kein paralleler Template-Fork |
| `api.js`, `skills-board.js` | PR ergänzt API-Basis und Tokenheader; GUI-API ist `:8000`, nicht Control `:8081` | Eigenen GUI-REST-Vertrag, Rechte und Fehler-/Offline-Gates belegen; Control-Authreceipt nicht als Board-Schreibrecht behandeln |
| `nav.js`, `main.css` | Im PR unverändert; Navigation/Version/Theme bleiben BACH-spezifisch | Konfigurierbare Navigation und Theme-Consumer, prefixsichere Assets/Links samt Doppel-Mount-Nachweis |
| `server.py` | PR überschreibt ältere Routehunks und fällt breit auf Rohdateien zurück | Kleine aktuelle Hunk-Ports ohne fremde Änderungen; keine stillen unsicheren Fallbacks auf ungerenderte Platzhalter |
| `test_board_renderers.py` | Acht PR-Tests ohne vollständigen Asset-/Browser-/Rechtenachweis | Hermetische API-/Asset-/XSS-/Offline- und Consumer-Parität für Boards ergänzen |

Auch Chat-/Settings-Templates sind weitere Vollschalen-Scopes. Tray und
Operator-Komposition bleiben eigenständige Folgetickets. Dieses Delta löst
T652 nicht vollständig und behauptet keine Gesamt- oder Geräteabnahme.

## Empirie

- BACH: 96 Shell-/Activity-/Template-/Skills-XSS-Regressionen bestanden,
  eine bestehende Warnung zu drei nicht referenzierten Alt-Templates.
- GUI: sieben Tests bestanden, einschließlich tatsächlich gleichem HTML für
  neutralen Renderer, Standalone, `/control`-Mount und BACH-Branding-Consumer.
  Eine bekannte Starlette-TestClient-Warnung.
- Ausgeführter gemeinsamer JavaScript-Client in einer deterministischen Node-VM:
  echte Clientfunktionen für RO, frischen Auth-Nachweis, ungültige Receipts,
  Reauth vor POST, Offline, HTTP-Fehler, Redirectverbot und dynamische XSS-Fälle.
  Dies ist keine vollständige Browser-/Geräteabnahme.
- Ruff für neue Paket-/Wrapper-/Testdateien und GUI-Delta sauber; Diffprüfung sauber.
- Unabhängiges Wheel ohne Dependencies offline aus einer temporären Quellkopie
  gebaut; Template im Wheel enthalten. Aus dem entpackten Wheel unter
  `python -I -S` importiert und gerendert, ohne `hub`, `gui`, `bach`, FastAPI
  oder Unified GUI zu importieren. Kein Host-Install oder Backendaufruf.
- Wheel-Receipt: `C:\_Local_DEV\test-tmp\ocean_shell_package_a06ce65t\receipt.json`,
  SHA256 `b955fdc6d509fc3943a8c33a8aaad029497c023c5ff4eae2de50e8d5f73f41ef`.
  Alle drei ausführbaren/resource Dateien stimmen bytegenau mit dem aktuellen
  Quellstand überein; die sieben Consumer-Tests bestehen auch mit diesem
  entpackten Wheel vor dem BACH-Quellpfad.

Vor Integration ist die unabhängige Abnahme durch die andere Modellklasse
Astra erforderlich. Deployment und Live-/Browser-Parität bleiben offen.
