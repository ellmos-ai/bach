# E06 Altpfad-Stilllegung — Vorbereitungs-Checkliste (BACH20-10)

> **Task:** #1568 `[TO-DECIDE] E06 Altpfad stilllegen + BACH20-10 Pin-Klärung`  
> **Zugehörig:** #1424 (E06 Altpfad stilllegen), #1357 (Pin-Klärung), #1358 (BACH20-09 Haltefrist-/Removal-Gate)  
> **Dokumentenstatus:** Korrigierte Fassung mit 9er Mapping, 5 Treffer-Kategorien, Sonderfällen, Risiken und 4 Entscheidungsoptionen A–D.  
> **Quellen:** `tools/doc_update_checker.py:60–77`, `tools/skill_export.py:640–760,1190–1220`, `ARCHITECTURE.md`, `CHANGELOG.md`, `tools/injectors.py`, `tools/fs_protection.py`, `system/wiki/synthese_workflow.txt`, DB-/Log-Historie, `tests/*`.

---

## 1. Ausgangslage und Ziel

- **#1424** (P2 pending): "E06 Altpfad stilllegen nach Nutzer-Briefing und Desktop-Durchsicht".  
  Blockiert, weil kein autonomer P2-Kandidat frei und Nutzer-Input fehlt.
- **#1357** (P2 in_progress): Pin-Klärung, abhängig von #1340 (P3 in_progress bis 2026-10-12) und #1341 (completed).
- **#1358** (P2 pending): BACH20-09 Haltefrist-/Nullreferenz-/Removal-Gate, depends_on #1356, #1357 und Haltefrist.
- **BACH20-10** (noch nicht als eigener Task angelegt): "unabhängige Modulupdates" mit Pin/Hash, staged Update, konsistenter Rollback (ROADMAP.md Z. 533).

**Ziel dieses Dokuments:**  
1. Ein einheitliches, korrigiertes 9er Mapping aller Alt-Pfade festhalten.  
2. Alle bekannten Treffer nach fünf Kategorien klassifizieren.  
3. Sonderfälle, Risiken und Handlungsempfehlungen pro Kategorie beschreiben.  
4. Vier Entscheidungsoptionen A–D präzise formulieren, damit der Nutzer in #1568 entscheiden kann.  
5. Als Arbeitsgrundlage für Nullreferenznachweis, Haltefrist und spätere Archivierung/Removal dienen.

---

## 2. Korrigiertes 9er Mapping

Quelle: `tools/doc_update_checker.py:60–77` (8 Paare) + realer Alt-Pfad `skills/_services/` → `hub/_services/` (ergänzt).

| # | Altpfad (Unix) | Altpfad (Windows) | Neuer Pfad | Status | Bemerkung |
|---|---|---|---|---|---|
| 1 | `scripts/` | `scripts\` | `tools/` | Mapping aktiv | Anthropic-Legacy-Export-Ziel; physisch existiert `system/scripts/` weiterhin |
| 2 | `skills/_connectors/` | `skills\_connectors\` | `connectors/` | Mapping aktiv | Nur noch Mapping-Eintrag + historische DB-/Log-Einträge |
| 3 | `skills/_agents/ati/` | `skills\_agents\ati\` | `agents/ati/` | Mapping aktiv | Spezifischer Subpfad vor `skills/_agents/` abarbeiten |
| 4 | `skills/_agents/` | `skills\_agents\` | `agents/` | Mapping aktiv | Genereller Agenten-Pfad |
| 5 | `skills/_experts/` | `skills\_experts\` | `agents/_experts/` | Mapping aktiv | Experten-Submodul wandert unter `agents/` |
| 6 | `skills/_workflows/` | `skills\_workflows\` | `skills/workflows/` | Mapping aktiv | Unterstrich entfällt innerhalb `skills/` |
| 7 | `skills/_partners/` | `skills\_partners\` | `partners/` | Mapping aktiv | Partners wird Top-Level |
| 8 | `system/help/wiki/` | `system\help\wiki\` | `system/wiki/` | Mapping aktiv | `help`-Ebene entfällt; physisch existiert `system/wiki/` |
| 9 | `skills/_services/` | `skills\_services\` | `hub/_services/` | **Neu / realer Alt-Pfad** | Nicht im `STATIC_PATH_MIGRATIONS`; physisch aktiv mit 25+ Dateien |

**Wichtige Reihenfolgeregel:**  
`skills/_agents/ati/` (#3) vor `skills/_agents/` (#4) abarbeiten, damit spezifischere Mappings nicht von allgemeineren überschrieben werden.

---

## 3. Fünf Treffer-Kategorien

Alle im `system/`-Baum gefundenen Referenzen auf Alt-Pfade lassen sich einer von fünf Klassen zuordnen:

| Kategorie | Beschreibung | Beispiele aus dem Repo | Behandlung |
|---|---|---|---|
| **K1 — Doku / SKILL-MD** | Markdown-, Architektur- oder Changelog-Zeilen, die Alt-Pfade beschreiben oder dokumentieren. | `ARCHITECTURE.md:525`, `CHANGELOG.md:79`, `system/wiki/synthese_workflow.txt:32`, alte Checkliste selbst | Inhalte prüfen; falls historisch belassen, explizit als Legacy markieren. Aktive Install-/Konfig-Doku muss aktualisiert werden. |
| **K2 — Logs / DB-historisch** | Zeitstempel-Reports, JSON-Health-Checks, SQLite-Historie, Task-Notizen. | `logs/Doc_Update_Report_2026-09-15_23-39.md`, `logs/registry_health_*.json/.txt`, `data/bach-ASUS-GEI.db`, `data/bach.db:1834761` (Task-Notiz mit alter 8er Liste) | **Nicht ändern.** Historische Daten dürfen nicht überschrieben werden. Sie dienen als Beweismittel für den Nullreferenznachweis *vor* der Haltefrist. |
| **K3 — Test-Assertions / Test-Fixtures** | Unit-Tests, Integrationstests oder Mock-Daten, die Alt-Pfade erwarten. | `tests/test_tuev_handler.py:95–132`, `tests/test_context_injector_db.py:85–86`, `tests/test_skills_integrity.py:33,40`, `tests/test_fs_protection.py:48`, `tests/test_self_heal_handlers.py:1659,1673,1695,1707` | Tests müssen mit dem neuen Pfad synchronisiert werden, **bevor** der Alt-Pfad archiviert/entfernt wird. Sonst rotieren Tests. |
| **K4 — Funktionaler Code / Import** | Wirkliche Pfadangaben, Importe, Kopieroperationen, Service-Scan-Logik oder Export-Ziele. | `tools/skill_export.py:664,681,690,694,748,760,762,771,774,776,785,788` (Anthropic-Export-Ziel), `tools/injectors.py`, `tools/fs_protection.py:105`, `tools/doc_update_checker.py:61,308` (Mapping + Service-Scan), `bin/harvest-local-commits.sh:41–43` (externer OneDrive-Pfad) | **Hohe Priorität.** Code-Pfade müssen auf neuen Pfad umgestellt werden. Bei Export-Zielen (`scripts/` für Anthropic) muss sichergestellt werden, dass der neue Pfad existiert und konsumierbar ist. |
| **K5 — .pyc / .git / index** | Kompilierte Python-Bytecode, Git-Index, IDE-Indizes, Caches. | `system/scripts/__pycache__/`, `.git/index`, `.pyc`-Dateien | Keine manuelle Code-Änderung nötig. Nach Code-Umstellung: `git rm -r --cached` für entfernte Verzeichnisse, Cache bereinigen, Neustart der Umgebung. |

---

## 4. Sonderfälle

### 4.1 `scripts/` — physisches `system/scripts/` vs. Anthropic-Legacy-Export

- **Befund:** `tools/skill_export.py` verwendet `scripts/` als **Zielpfad für den Anthropic-Export** (funktionaler Code, K4).  
  Gleichzeitig existiert physisch `system/scripts/` mit 13 Dateien + `__pycache__` (K5).
- **Risiko:** Eine naive Umbenennung von `system/scripts/` würde den Anthropic-Export brechen, falls das Tool weiterhin in `scripts/` schreiben will.
- **Empfehlung:**
  1. `tools/skill_export.py` so anpassen, dass es in `tools/` exportiert (oder konfigurierbar machen).
  2. Prüfen, ob `system/scripts/` danach noch aktiv genutzt wird (außer Caches).
  3. Falls `system/scripts/` leer/nur Cache ist: `__pycache__` entfernen, Verzeichnis archivieren.

### 4.2 `system/help/wiki/` — Mapping korrekt, aber DB-/Logs zeigen Varianten

- **Befund:** `STATIC_PATH_MIGRATIONS` listet `system/help/wiki/` → `system/wiki/` (Mapping korrekt).  
  DB-/Log-Einträge enthalten aber auch `docs/help/wiki*` und `skills/help/wiki`.
- **Risiko:** False-Positives beim Scan; Mapping-Logik könnte `system/help/wiki/` nicht erfassen, wenn historische Einträge andere Präfixe haben.
- **Empfehlung:**
  1. In `doc_update_checker.py` prüfen, ob die Mapping-Suche auch `docs/help/wiki` und `skills/help/wiki` abdeckt, falls diese tatsächlich existierten.
  2. Historische Varianten in K2 belassen, aber im Nullreferenznachweis dokumentieren.
  3. Aktive Dokumentation auf `system/wiki/` angleichen.

### 4.3 `skills/_services/` — realer Alt-Pfad, nicht im Mapping

- **Befund:** `tools/doc_update_checker.py` scannt sowohl `hub/_services` als auch `skills/_services` (`DOC_SCAN_SPECS`), aber `STATIC_PATH_MIGRATIONS` enthält kein Mapping `skills/_services/` → `hub/_services/`.  
  Physisch existiert `system/skills/_services/` mit 25+ Dateien; Treffer in Code, Tests und Doku.
- **Risiko:** Stilllegungs-Logik übersieht diesen Pfad, weil er nicht im Heiler-Mapping steht. Längerfristig entsteht ein Split-Brain zwischen `skills/_services/` und `hub/_services/`.
- **Empfehlung:**
  1. Mapping in `doc_update_checker.py:STATIC_PATH_MIGRATIONS` ergänzen: `skills/_services/` → `hub/_services/` (Unix + Windows).
  2. Inhalt von `system/skills/_services/` auf `system/hub/_services/` migrieren oder konsolidieren.
  3. Alle Code-/Test-Referenzen (K3/K4) aktualisieren.
  4. Erst danach Archivierung/Removal.

---

## 5. Risiken und Handlungsempfehlungen pro Treffer-Kategorie

| Kategorie | Risiken | Handlungsempfehlung |
|---|---|---|
| **K1 — Doku / SKILL-MD** | Veraltete Installations-/Konfig-Anleitungen; Contributor verwenden Alt-Pfad; inkonsistente Architekturbeschreibung. | 1. Alle aktiven `.md`/`.txt`-Dateien auf Alt-Pfad scannen. 2. Aktive Doku umschreiben. 3. Historische Changelog-/Architektur-Einträge mit Hinweis versehen: `<!-- LEGACY-PATH: ... -->`. |
| **K2 — Logs / DB-historisch** | Nachträgliche Manipulation von Logs/DB zerstört Audit-Trail; Beweismittel für Haltefrist/Removal geht verloren. | **Keine Änderung.** Stattdessen: Snapshot der DB und Logs vor Migration, separate `legacy-path-audit/`-Datei mit Zeitstempel und Treffer-Hash anlegen. |
| **K3 — Test-Assertions** | Rotierende Tests nach Pfad-Änderung; Testabdeckung für Migration fehlt; Stilllegung ohne Tests führt zu Regressionen. | 1. Test-Änderungen in separaten Commit. 2. Neuer Test `test_altpfad_nullreferenz` einführen, der garantiert, dass kein Alt-Pfad mehr aktiv referenziert wird. 3. CI-Pipeline vor Archivierung grün. |
| **K4 — Funktionaler Code / Import** | Laufzeitfehler (ModuleNotFoundError, FileNotFoundError); Export- / Service-Scan bricht ab; Datenverlust bei Kopieroperationen. | 1. Code-Pfade schrittweise umstellen (nicht blind ersetzen). 2. Für jeden Pfad existiert/erreichbar-Check einbauen. 3. Fallback-Logik für Übergangsfrist dokumentieren. 4. `skill_export.py`-Anthropic-Ziel explizit testen. |
| **K5 — .pyc / .git / index** | Veraltete Bytecode-Caches liefern alte Import-Pfade; Git-Index enthält gelöschte Verzeichnisse; Build-Artefakte verfälschen den Nullreferenznachweis. | 1. `pyclean` / `find . -type d -name __pycache__ -exec rm -rf {} +`. 2. `git rm -r --cached` für archivierte Alt-Verzeichnisse. 3. `.gitignore` prüfen/ergänzen. 4. Neustart/Neuimport der Umgebung. |

---

## 6. Vier Entscheidungsoptionen A–D

| Option | Name | Beschreibung | Kosten/Risiko | Empfohlener Einsatz |
|---|---|---|---|---|
| **A** | **Vollständige Migration + Stilllegung** | Alle 9 Alt-Pfade werden migriert, Mapping in `doc_update_checker.py` ergänzt, Code/Tests/Doku aktualisiert, nach Haltefrist in `system/hub/_archive/` archiviert und Alt-Verzeichnisse entfernt. | Hoch (viele Dateien, Abhängigkeiten, Testläufe); Nutzer muss aktiv freigeben. | Wenn Migration strategisch gewollt und Kapazität vorhanden. |
| **B** | **Mapping-Only / Heiler-Modus** | `STATIC_PATH_MIGRATIONS` um `skills/_services/` → `hub/_services/` ergänzt; `doc_update_checker.py` berichtet Alt-Pfade konsistent; Code und physische Verzeichnisse bleiben unverändert. | Gering; Pfad-Split bleibt bestehen; technische Schuld wächst. | Kurzfristige Stabilisierung, wenn Option A zeitlich nicht durchführbar. |
| **C** | **Archivierung ohne Löschung** | Alt-Verzeichnisse werden nach erfolgreichem Migrationstest in `system/hub/_archive/` kopiert (Snapshot), aber am Originalort belassen; Nullreferenznachweis wird geführt. | Mittel; doppelter Speicher; klare Trennung von "aktiv" und "archiviert" nötig. | Wenn Haltefrist/Beweispflicht erfordert, die Original-Pfade länger vorzuhalten. |
| **D** | **Abbruch / Aufschub** | Keine Änderung; Task bleibt pending; keine Mapping-Erweiterung, keine Migration, keine Archivierung. | Niedrig kurzfristig; wachsende Inkonsistenz, insbesondere bei `skills/_services/` vs. `hub/_services/`. | Nur wenn andere P2-Abhängigkeiten (#1357, #1340) zuerst geklärt werden müssen. |

**Empfehlung des Vorbereitungsdokuments:**  
- **Sofort (kein Nutzer-Input nötig):** Option B anwenden, um `skills/_services/` → `hub/_services/` im Heiler zu ergänzen und den Scan konsistent zu machen.  
- **Kurzfristig (nach #1357 / #1340):** Option A für alle 9 Pfade umsetzen, sofern der Nutzer freigibt.  
- **Falls Beweishaltefrist verlangt wird:** Option C als Zwischenschritt vor Option A.

---

## 7. Arbeitsanweisung / Next Steps

1. [ ] **Mapping-Erweiterung:** `tools/doc_update_checker.py:STATIC_PATH_MIGRATIONS` um `skills/_services/` → `hub/_services/` (Unix + Windows) erweitern.
2. [ ] **Re-Scan:** `search_text` / `grep` für alle 9 Patterns wiederholen und Treffer nach K1–K5 klassifizieren.
3. [ ] **Code-Migration (K4):**
   - `tools/skill_export.py`: Anthropic-Export-Ziel von `scripts/` auf `tools/` umstellen.
   - `tools/injectors.py`, `tools/fs_protection.py:105`, `tools/doc_update_checker.py:308`: Pfadangaben prüfen/aktualisieren.
   - `bin/harvest-local-commits.sh:41–43`: prüfen, ob OneDrive-Pfad außerhalb von BACH relevant ist.
4. [ ] **Test-Migration (K3):** Alle Test-Dateien mit Alt-Pfad-Assertions anpassen; neuen `test_altpfad_nullreferenz`-Test hinzufügen.
5. [ ] **Doku-Migration (K1):** `ARCHITECTURE.md:525`, `CHANGELOG.md:79`, `system/wiki/synthese_workflow.txt:32`, diese Checkliste und weitere aktive `.md`/`.txt` aktualisieren.
6. [ ] **Audit-Snapshot (K2):** DB + Logs vor jeder Migration kopieren/sichern, separate `legacy-path-audit/YYYY-MM-DD_TREFFER.md` anlegen.
7. [ ] **Cache-Bereinigung (K5):** `__pycache__`, `.pyc`, Git-Cache bereinigen.
8. [ ] **Nullreferenznachweis:** Nach Schritt 3–5 erneuter Scan; dokumentieren, dass keine Alt-Pfade mehr funktional referenziert werden.
9. [ ] **Haltefrist + Archivierung:** Nach erfolgreichem Update-/Rollback-Zyklus Alt-Verzeichnisse in `system/hub/_archive/` ablegen und gemäß BACH20-09 stilllegen.
10. [ ] **Task-Update:** #1568 auf "in_progress" setzen und auf diese Checkliste verweisen; bei Option D auf pending belassen.

---

## 8. Nullreferenznachweis — Pro-Alt-Pfad-Checkliste

Jeder der 9 Pfade muss vor Stilllegung/Removal die folgenden Kriterien erfüllen:

| # | Alt-Pfad | Kein K4-Treffer | Kein K3-Treffer | K1 markiert/aktualisiert | K2 audit-snapshotted | K5 bereinigt | Freigabe |
|---|---|---|---|---|---|---|---|
| 1 | `scripts/` | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ |
| 2 | `skills/_connectors/` | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ |
| 3 | `skills/_agents/ati/` | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ |
| 4 | `skills/_agents/` | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ |
| 5 | `skills/_experts/` | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ |
| 6 | `skills/_workflows/` | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ |
| 7 | `skills/_partners/` | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ |
| 8 | `system/help/wiki/` | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ |
| 9 | `skills/_services/` | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ |

**Definitionen:**
- **Kein K4-Treffer:** Kein funktionaler Code/Import/Export-Ziel referenziert den Alt-Pfad mehr.
- **Kein K3-Treffer:** Kein Unit-/Integrationstest erwartet den Alt-Pfad mehr.
- **K1 markiert/aktualisiert:** Aktive Doku verwendet nur noch den neuen Pfad; historische Einträge sind als Legacy gekennzeichnet.
- **K2 audit-snapshotted:** DB/Logs vor Migration gesichert; Snapshot liegt in `system/hub/_archive/legacy-path-audit/`.
- **K5 bereinigt:** Bytecode-Caches und Git-Index enthalten keine Alt-Pfad-Reste mehr.

---

## 9. Änderungshistorie dieser Checkliste

| Version | Datum | Änderung |
|---|---|---|
| 0.1 | 2026-09-15 | Erste unvollständige Fassung mit 8 Mapping-Paaren. |
| 1.0 | siehe File-Mtime | Korrigierte Fassung: 9er Mapping, 5 Treffer-Kategorien, Sonderfälle, Risiken, Optionen A–D, Arbeitsanweisung und Nullreferenznachweis. |
