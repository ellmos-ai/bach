# Bericht zu Auftrag 2 — :8081 Control-API "/activity"-Design ins BACH-GUI-Design überführen (T-20260913-660268706, Punkt 7)

## 1. Geänderte Datei(en)

- `system/hub/_services/chat/telegram_chat.py`
  - Ausschließlich der `<style>`-Block innerhalb der Python-String-Variable `WEB_DASHBOARD` sowie die Farbangaben im Inline-`style`-Attribut des Activity-Links (`<a href="/activity">`).
  - Keine HTML-Struktur, keine Klassen-/ID-Namen, keine Scripts, keine Fetch-URLs/Endpunkte verändert.
  - Alles außerhalb von `WEB_DASHBOARD` (einschließlich `WEB_ACTIVITY_DASHBOARD`, `system/gui/server.py`, `system/hub/routine.py` und `system/tests/`) blieb vollständig unberührt.

> **Hinweis zur Architektur / Scope:**
> `WEB_DASHBOARD` wird unter `http://<host>:8081/` ausgeliefert. Der Endpunkt `http://<host>:8081/activity` wird in derselben Datei über die separate String-Variable `WEB_ACTIVITY_DASHBOARD` ausgeliefert. Gemäß strikter Vorgabe ("*NICHT anfassen: alles außerhalb der WEB_DASHBOARD-Variable in dieser Datei*") wurde `WEB_ACTIVITY_DASHBOARD` nicht berührt. Falls das Worker-Dashboard auf `/activity` ebenfalls an die neuen Tokens angeglichen werden soll, steht dies für einen Folgeauftrag bereit.

---

## 2. Vorher/Nachher-Kurzbeschreibung der Farbpalette

### Vorher (Alte "Cyan auf Navy"-Palette)
- **Hintergrund:** `#1a1a2e` (Body), `#16213e` (Cards)
- **Rahmen:** `#0f3460`
- **Primär-/Akzentfarbe:** `#00d4ff` (Cyan) für Titel, Werte, Rahmen, Hover, Toast und aktive Buttons
- **Text:** `#e0e0e0` / `#888`
- **Buttons:** `#0f3460` mit Cyan-Rahmen `#00d4ff`
- **Dots:** `#00ff88` (Grün), `#ff4444` (Rot), `#ffcc00` (Gelb)
- **Typografie:** Generische Systemschrift (`-apple-system, BlinkMacSystemFont, sans-serif`)

### Nachher (Kanonische BACH-GUI-Palette aus `main.css`)
- **Design-Tokens (`:root`):** Vollständig eingebettet mit identischen Werten wie in `system/gui/static/css/main.css`:
  - `--bg-dark`: `#0b0d14`
  - `--bg-panel`: `#111420`
  - `--bg-card`: `#171b28`
  - `--bg-elevated`: `#1c2033`
  - `--accent`: `#d4485a` (BACH Refined Red)
  - `--accent-light`: `#e06b7e`
  - `--accent-blue`: `#5b8def`
  - `--accent-glow`: `rgba(212, 72, 90, 0.12)`
  - `--text`: `#e2ded8`
  - `--text-muted`: `#6e7386`
  - `--text-dim`: `#454a5c`
  - `--border`: `#1e2236`
  - `--border-hover`: `#2a3048`
  - `--success`: `#4ade80`
  - `--warning`: `#f5c542`
  - `--error`: `#ef5350`
  - `--radius-sm`: `8px`, `--radius-md`: `14px`, `--radius-lg`: `18px`
  - `--ease`: `cubic-bezier(0.4, 0, 0.2, 1)`, `--duration`: `200ms`
- **Typografie:** Google Fonts `@import` für `Plus Jakarta Sans` (wie in `main.css` Z. 6) im Body gesetzt.
- **Header (`h1`):** Subtiler Text-zu-Akzent-Verlauf (`linear-gradient(135deg, var(--text) 40%, var(--accent) 100%)`) mit `-webkit-background-clip: text` analog zum BACH-Brand-Logo in `main.css`.
- **Cards (`.card`, `.card h2`):** `background: var(--bg-panel)`, `border-radius: var(--radius-md)`, `border: 1px solid var(--border)` mit sanftem Hover-Übergang zu `var(--border-hover)`. Überschrift in `var(--text)` mit `gap: 0.5rem` und Ausrichtung am Status-Dot.
- **Buttons (`.btn`, `.btn:hover`, `.btn.active`, `.btn:disabled`):**
  - Basis (`.btn`): Wie `.btn-secondary` in `main.css` (`background: var(--bg-card)`, `color: var(--text)`, `border: 1px solid var(--border)`).
  - Hover (`.btn:hover`): `background: var(--bg-elevated)`, `border-color: var(--border-hover)`.
  - Klick (`.btn:active`): `transform: scale(0.97)`.
  - Aktiv (`.btn.active`): Wie `.btn-primary` in `main.css` (`background: var(--accent)`, dunkler Text `var(--bg-dark)`, `box-shadow: 0 2px 12px var(--accent-glow)`).
  - Deaktiviert (`.btn:disabled`): `opacity: 0.4`, `cursor: not-allowed`.
- **Status-Reihen (`.status-row`, `.label`, `.value`):** Rahmen in `var(--border)`, Labels in `var(--text-muted)`, Werte in `var(--accent-light)` (`#e06b7e`, Semi-Bold).
- **Status-Dots (`.dot`, `.dot.green`, `.dot.red`, `.dot.yellow`):** Auf `var(--success)`, `var(--error)` und `var(--warning)` umgestellt mit jeweils weichem Glowing-Schatten.
- **Toast (`#toast`):** `background: var(--accent)`, Text in `var(--bg-dark)`, Schatten `0 4px 16px rgba(0,0,0,0.4)`.
- **Activity-Link:** Inline-Styles auf `var(--bg-card)`, `var(--text)`, `var(--border)` und `var(--radius-sm)` angepasst sowie globales `a:hover` definiert.

---

## 3. Ergebnis der Verifikationsschritte

### A. Pytest Check
Befehl:
```powershell
python -m pytest system/tests/test_gui_server_smoke.py -q --collect-only 2>&1 | Select-String -Pattern "telegram" -SimpleMatch
```
Ergebnis:
- Keine passenden Tests gefunden, Verifikation über Syntax-Check + manuelle Sichtprüfung.

### B. Python AST-Syntax-Check
Befehl:
```powershell
python -c "import ast; ast.parse(open('system/hub/_services/chat/telegram_chat.py', encoding='utf-8').read())"
```
Ergebnis:
- **Exit 0** (fehlerfrei durchgelaufen).

### C. Manuelle HTML-Sichtprüfung
- Der extrahierte HTML/CSS-String von `WEB_DASHBOARD` wurde in einer temporären Datei auf Syntax, Farbwerte und Token-Konsistenz geprüft.
- Plausibilitätsbefund:
  - Saubere CSS-Struktur ohne Syntaxfehler.
  - Farbwerte und Variablen entsprechen exakt der kanonischen Palette aus `system/gui/static/css/main.css`.
  - Alle von JavaScript genutzten Selektoren (`.btn`, `.btn.active`, `.dot.green`, `.dot.yellow`, `.dot.red`, `#toast`, `.status-row`, `.label`, `.value`) sind 1:1 intakt.
- Die temporäre Prüfdatei wurde anschließend wieder gelöscht.

---

## 4. `git diff --stat`

```
 system/hub/_services/chat/telegram_chat.py | 219 ++++++++++++++++++++++++++---
 1 file changed, 200 insertions(+), 19 deletions(-)
```

---

## 5. Selbstauskunft Modell

Ich bin Modell **Gemini 3.8 Flash (High)**.
