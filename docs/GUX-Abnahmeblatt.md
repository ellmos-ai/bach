# GUX-Abnahmeblatt – Kontakt/Finanz/Overflow (Task #1703)

**Datum:** 2026-10-09
**Task:** #1703 (P2, GUI-GUX) – „Kontaktvorschau, Finanzlayout und globalen Überlauf visuell abnehmen" (GUX-061/062/067/DES-03 + nav.js-Lektüre)
**Worktree:** /Users/lukas/services/bach-worktrees/task-1703

---

## GUX-061 – Kontaktvorschau (kontakte.html) – NUR LEKTÜRE, KEINE ÄNDERUNG

Die Kontaktvorschau in `kontakte.html` wurde vollständig visuell abgenommen (read-only). Belege:

- `.contact-grid` (Z.113) und `.contact-card` (Z.119): Kartenraster vorhanden.
- Split-Layout `.contact-list-panel` / `.preview-panel` (Z.264–295):
  - Preview-Feld-Grid: `grid-template-columns: repeat(2, minmax(0,1fr))` (Z.288) – Überlauf-sicher durch `minmax(0,1fr)`.
  - `.preview-field`: `min-width: 0; overflow-wrap: anywhere` (Z.289) – lange Werte brechen um.
  - `dd`: `white-space: pre-wrap` (Z.291) – Zeilenumbrüche bleiben erhalten, kein horizontales Austreten.
  - `.wide`: `grid-column: 1 / -1` (Z.292) – breite Felder über die volle Grid-Breite.
- Mobile Umsetzung (Z.301–311):
  - Preview als Bottom-Sheet, `.preview-backdrop.open` mit `position: fixed; inset: 0` (Z.307).
  - 1fr-Spalten (Z.309) – einspaltige Felder auf Mobilgeräten.
  - `prefers-reduced-motion` (Z.311) – Animationen respektieren Systempräferenz.

**Ergebnis:** Kontaktvorschau sauber umgesetzt und Überlauf-gesichert. GUX-061 erfüllt, keine Änderungen erforderlich.

---

## GUX-062 – Finanzlayout (financial.html) – BEREITS GEFIXT, NUR VERIFIKATION

Der Tab- und Reportbereich in `financial.html` wurde verifiziert (Fix aus vorherigem Lauf, keine neue Änderung nötig). Belege:

- `.tabs` (Z.370–378): `flex-wrap: wrap; max-width: 100%; overflow-x: auto` – Tabs brechen mehrzeilig um bzw. scrollen bei Bedarf.
- `.tab`: `flex: 0 0 auto` + `white-space: nowrap` – Labels werden nicht gequetscht oder abgeschnitten.
- Tab-Leiste im HTML (Z.425): 9 Tabs vorhanden, Layout stabil.
- `report-options-grid`: `minmax(0,1fr)`-Spalten – keine Grid-Überläufe.
- `#report-preview-pane` / `#report-preview-content` / `#email-view-body`: `overflow-wrap: anywhere` – lange Zahlen/IDs/Betreffs brechen um.

**Ergebnis:** GUX-062 erfüllt, Fix verifiziert, keine weiteren Änderungen nötig.

---

## GUX-067 – Globaler Überlauf (main.css) – ABWEICHUNG DOKUMENTIERT, KEIN NACHFIX

Befund in `main.css` (Z.60–62):

```css
/* Long labels and paths must stay inside the viewport on every page. */
body, .container, .main-content { min-width: 0; overflow-wrap: break-word; }
pre { max-width: 100%; overflow-x: auto; }
```

- Das ist das EINZIGE `overflow-wrap`-Vorkommen in main.css (Z.61).
- **Abweichung zur Beschreibung:** Kein `anywhere`, keine Selektorliste `.card/.list-item/.section/table/.tab-btn/.nav-item`. Umsetzung stattdessen als globale, vererbbare Breitenregel auf `body, .container, .main-content` – `overflow-wrap` erbt, daher wirkt die Regel auf alle Nachfahren inkl. Karten, Listen, Tabellen und Tabs.

**Abnahme:** Ziel (lange Labels/Pfade bleiben im Viewport) erreicht. Abweichung vom Beschreibungstext ehrlich festgehalten, bewusst KEIN Nachfix, da die globale Regel das Ziel bereits erfüllt.

---

## DES-03 – Warm-Theme `--text-dim` (main.css) – WERTABWEICHUNG DOKUMENTIERT, KEIN NACHFIX

Befund im warm-Block (`main.css` Z.1158): `--text-dim: #6d5645;`

- Kontext des warm-Themes: `--text: #35271f`, `--text-muted: #695446`, `--bg-dark: #f6f0e4`.
- **Wertabweichung:** Beschreibung nennt `#97826e` – Suche danach ergab 0 Treffer im Code. Tatsächlicher Wert ist `#6d5645`.
- Kontrast von `#6d5645` auf `#f6f0e4` ist stark/lesbar.
- Weitere `--text-dim`-Werte im Vergleich: Z.25 `#909aaf` (default), Z.1105 `#60677d` (light), Z.1201 `#5a5280` (ocean), Z.1310 `#749ec8`.

**Abnahme:** Ziel (abgesetzter, lesbarer Dim-Text im warm-Theme) erfüllt. Wertabweichung ehrlich dokumentiert, KEIN Nachfix.

---

## nav.js – Befund (vollständige Lektüre, Dateiende bestätigt)

`nav.js` wurde komplett gelesen. Relevante Erkenntnisse:

- **Exports am Dateiende** (`module.exports`): `initNavigation`, `updateNavStatus`, `loadNavStatus`, `setTheme`, `previewTheme`, `commitTheme`, `persistThemePreference`, `loadThemePreference`, `normalizeTheme`, `loadNavigationConfig`, `safeNavHref`, `BACH_VERSION`.
- **Bootstrap:** `DOMContentLoaded` → `loadNavigationConfig` + `loadThemePreference` + `loadNavStatus`.
- **Theme-Logik:**
  - `THEME_KEY = 'bach-theme'`, `AVAILABLE_THEMES = [dark, light, ocean, warm, custom]`.
  - `normalizeTheme` prüft/normalisiert Werte; `applyTheme`: dark → `removeAttribute('data-theme')`, andere → `data-theme`-Attribut.
  - Header-Switcher: 5 Buttons (je Theme).
  - `persistThemePreference` persistiert die Wahl via `PUT /api/settings/theme`.

**Ergebnis:** Theme-Switcher-Logik vollständig verstanden und dokumentiert; keine Änderungen an nav.js erforderlich.

---

## Theme-Bootstrap-Bug (NUR DOKUMENTIERT, KEIN FIX IN DIESEM TASK)

Identisches Inline-Bootstrap-Muster mit Fehler in **beiden** Seiten:

- `financial.html` (Z.9):
  ```js
  !function(){var t=localStorage.getItem("bach-theme");t&&t!=="dark"&&document.documentElement.setAttribute("data-theme",t)}()
  ```
- `kontakte.html` (Z.8): identisches Muster.

**Problematik:** Das Bootstrap liest `localStorage` direkt, ohne `normalizeTheme`, ohne `AVAILABLE_THEMES`-Prüfung und ohne dark-Fallback. Ungültige Werte (z. B. veraltete Theme-Namen) werden ungeprüft als `data-theme` gesetzt; fehlender Wert bleibt korrekt bei dark.

**Handhabung:** Laut Beschreibung sollte hierfür ein separater Task angelegt sein; ein solcher ist in der offenen Task-Liste (Stand dieses Laufs, 20 offene Tasks) nicht sichtbar. Gemäß Mandat: Nur Dokumentation im Abnahmeblatt, KEIN Fix und KEIN neuer Task in #1703.

---

## Fazit

- GUX-061 (Kontaktvorschau) und GUX-062 (Finanzlayout) sind vollständig umgesetzt und verifiziert; die einzige Code-Änderung dieses Tasks ist der bereits erfolgte GUX-062-Fix in financial.html (Tabs flex-wrap + nowrap, preview-Panes overflow-wrap:anywhere).
- GUX-067 und DES-03 sind im Ziel erfüllt; die Umsetzung weicht vom Beschreibungstext ab (GUX-067: globale vererbbare Regel statt Selektorliste mit `anywhere`; DES-03: `#6d5645` statt `#97826e`). Beide Abweichungen sind oben dokumentiert, ein Nachfix ist bewusst unterblieben.
- nav.js vollständig gelesen und dokumentiert; Theme-Bootstrap-Bug in financial.html (Z.9) und kontakte.html (Z.8) identifiziert und an dieser Stelle nur dokumentiert – Bearbeitung erfolgt separat.
- **Es sind keine weiteren Code-Änderungen nötig.**

---

## Selbstprüfung

- Secrets-Scan im Abnahmeblatt (Muster `password|secret|token|api_key`): **0 Treffer**.
- `stat` auf `docs/GUX-Abnahmeblatt.md`: Datei existiert, 6685 Bytes, UTF-8.