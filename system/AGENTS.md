# Bauort-Klassen (Bauort-Feld)

**Beschreibung:** Dieses Dokument definiert die standardisierten Bauort-Tags, die für die Zuordnung von Aufgaben zu Modul-Grenzen verwendet werden.

---

## 1. Kern-Modul (Kernbereich)

**Bauort:** `kern` oder `core`

**Verwendungszweck:** Alle Kernkomponenten von BACH (bach.py, Lead-HTTP, bach.db-Speicher, dünne Adapter).

**Pfade:** `system/core/**/*.py` (ausgenommen `system/core/gui/web/**`, `system/core/tests/**`)

**Berechtigung:** Nur Aufgaben mit `bauort:kern` sind für Kernentwicklungen autorisiert.

---

## 2. Modul-Gate (Steuerbereich)

**Bauort:** `module-gate` oder `gate`

**Verwendungszweck:** Die Modul-Gate-CI-Prüfung, verantwortet durch BACH-System.

**Pfade:** `system/hub/_services/module_gate/`, `.github/workflows/module_gate.yml`

**Berechtigung:** Nur Aufgaben mit `bauort:module-gate` sind für Gate-Aktivitäten autorisiert.

---

## 3. Adapter (Integrationsbereich)

**Bauort:** `adapter:<modul-id>` (z.B. `adapter:agents-heart`, `adapter:policy-registry`)

**Verwendungszweck:** Dünne Adapter für Ocean-Module, exportieren die neutrale Modul-API.

**Pfade:** `system/hub/_services/adapters/<modul-id>/*.py`

**Berechtigung:** Nur Aufgaben mit `bauort:adapter:<id>` sind für Adapter-Entwicklungen autorisiert.

---

## 4. Ausnahmen (Sonderfälle)

**Bauort:** `ausnahme:<Task>`

**Verwendungszweck:** Ausnahmen von der Regelbasierung, erforderlich für spezielle Aufgaben.

**Berechtigung:** Nur Aufgaben mit `bauort:ausnahme:<task-id>` sind für berechtigte Ausnahmen autorisiert.

---

## 5. GUI-Modul (Clientbereich)

**Bauort:** `gui`

**Verwendungszweck:** GUI- und Client-bezogene Komponenten (ausgenommen Web-FRP).

**Pfade:** `system/gui/*.py`, `system/gui/**/*.py` (ausgenommen `system/gui/web/**`)

**Berechtigung:** Nur Aufgaben mit `bauort:gui` sind für GUI-Entwicklungen autorisiert.

---

## 6. Test- und Hilfsmodule (Hilfsbereich)

**Bauort:** `test` oder `utils`

**Verwendungszweck:** Test-Dateien, Hilfs-Skripte und Dokumentskripte.

**Pfade:** `tests/`, `scripts/`, `tools/`, `docs/` (ausgenommen `tests/integration/`, `tools/**/*_integration*.py`)

**Berechtigung:** Nur Aufgaben mit `bauort:test` oder `bauort:utils` sind für Hilfsarbeiten autorisiert.

---

## 7. Ocean-Kern (externer Bereich)

**Bauort:** `ocean`

**Verwendungszweck:** Ocean-Kernmodule, unabhängige Repositorys.

**Pfade:** `open-ocean/`, `ellmos-*` (externe Repositorys)

**Berechtigung:** Nur Aufgaben mit `bauort:ocean` sind für Ocean-Entwicklungen autorisiert.

---

## 8. Leeres/Generisches Modul

**Bauort:** `generic`

**Verwendungszweck:** Wenn kein spezifischer Bauort angemessen ist (z.B. gemeinsame Hilfsbibliotheken, Dokumentation).

**Berechtigung:** Nur Aufgaben mit `bauort:generic` sind für generische Arbeiten autorisiert.

---

## Bauort-Semantik-Erklärung

**Format:** `bauort:<modul-id>` oder `bauort:ausnahme:<Task>`

**Verpflichtung:** Der Inhalt von `modul:<id>@<sha>` verweist auf den aktuellen Integrations-Commit für ein bestimmtes Modul. Das `adapter:<id>` Segment verweist auf den Adapter-ID für Ocean-Module.

**Enforcement:** Alle PRs müssen mindestens ein `bauort:`-Tag in ihrem Commit- oder PR-Titel enthalten. PRs ohne ein identifiziertes Bauort werden von GitHubBot als HOLD eingestuft und können nicht von den 24-stündigen Draft-Freigabe-Regeln ausgenommen werden.

**Configuration:** Die genaueste Karte der gültigen <modul-id>-Werte und ihrer erlaubten Verwendungen wird in dieser Datei gepflegt.

---

## 9. BACH als gebrandeter Teil-OS-Stack von Ocean (`@deprecated_legacy_bach`)

Seit Meilenstein `v3.15.0-ocean-stack-m1` (2026-10-31) gilt für jeden Anschluss eines Ocean-Moduls an BACH das verbindliche 3-Stufen-Verfahren:

1. **Ocean-Modul über `system/hub/_services/ocean_stack_bridge.py` bzw. dünnen Adapter einbinden** (`adapter:<modul-id>`).
2. **Ersetzte BACH-interne Klasse/Funktion mit `@deprecated_legacy_bach("<kanonisches-ocean-modul>")` dekorieren** und in `DEPRICATED.md` eintragen. Der Altcode bleibt nur als deprecated Rückfallpfad bestehen.
3. **Nach Paritäts- und Caller-Abnahme den deprecated Altcode in einem eigenen Aufräum-Schritt entfernen.**
