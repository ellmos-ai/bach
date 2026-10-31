# Task 2230 – Empirische Dokuprüfung help_forensic: Analyse & Vorschläge

## Prüfumfang
- `system/hub/_services/recurring/config.json` (Z78–87)
- `system/hub/_services/recurring/recurring_tasks.py` (vollständig)
- `system/skills/workflows/help-forensic.md` (Z1–137, Z200–371)
- `system/docs/help/practices.txt` (Z104–106)
- `system/docs/help/bach_paths.txt` (Z14)
- `system/hub/bach_paths.py` (Z1–82)

Keine Codeänderungen vorgenommen.

---

## 1. Routine help_forensic: korrekte technische Verkabelung

| Konfiguration (`config.json`) | Verhalten in `recurring_tasks.py` | Bewertung |
|---|---|---|
| `interval_days: 14` | `trigger_recurring_task()` prüft `last_run + interval_days` gegen aktuelles Datum | ✅ korrekt |
| `target: tasks` | `ensure_recurring_task()` legt Task in `ati_tasks/tasks/` an | ✅ korrekt |
| `priority: P2`, `project: BACH`, `aufwand: mittel` | Werden 1:1 in den Task übernommen | ✅ korrekt |
| `last_run: 2026-05-29T13:08:49.019791` | `trigger_recurring_task()` setzt `last_run` nach Anlage zurück; Doppel-Anlage wird verhindert | ✅ korrekt |

**Fazit:** Die `help_forensic`-Recurring-Routine ist technisch korrekt mit `recurring_tasks.py` verdrahtet. Der nächste Lauf wäre ca. 2026-06-12 fällig.

---

## 2. Wahrheitskonflikt: help-forensic.md vs. practices.txt

### Feststellung
- `help-forensic.md` Z16 behauptet:
  > `skills/docs/help/*.txt ist die WAHRHEIT`
- `system/docs/help/practices.txt` Z104–106 besagt:
  > `7. HELP ALS WAHRHEIT / docs/help/*.txt ist die primaere Dokumentation. / Bei Widerspruch: docs/help/ gewinnt.`

### Probleme
1. **Widerspruch in der Wahrheitsinstanz:** help-forensic.md sagt `skills/docs/help/`, practices.txt sagt `docs/help/` (kanonisch: `system/docs/help/`).
2. **Pfad existiert nicht:** `skills/docs/help/` ist im Worktree nicht vorhanden; die tatsächliche Wahrheitsdoku liegt unter `system/docs/help/`.
3. **Hierarchischer Konflikt:** help-forensic.md selbst ist ein Workflow unter `system/skills/workflows/`. Seine eigene Wahrheitsregel verweist auf einen anderen, nicht existierenden Pfad.

### Regelanwendung
Gemäß `practices.txt` Z106 gewinnt `system/docs/help/` den Widerspruch. Daher ist help-forensic.md Z16 in seinem eigenen Geltungsbereich falsch.

---

## 3. Weitere Pfad-Inkonsistenzen in help-forensic.md

| help-forensic.md | Angabe | Tatsächlicher Stand | Bewertung |
|---|---|---|---|
| Z368 | `skills/_services/skills/docs/help/SKILL.md` | Doppelt verschachtelt, nicht existent | ❌ fehlerhaft |
| Z369 | `skills/docs/help/practices.txt` | Existiert als `system/docs/help/practices.txt` | ❌ Pfad falsch |
| (implizit) | `skills/docs/help/*.txt` als Wahrheit | `system/docs/help/*.txt` | ❌ Pfad falsch |

`bach_paths.txt` Z14 und `bach_paths.py` Z1–82 stimmen überein: `bach_paths.py` liegt unter `system/hub/bach_paths.py`. Dies ist ein positives Beispiel für Pfad-Konsistenz.

---

## 4. Konkrete Vorschläge (nur Analyse, keine Änderung)

1. **Wahrheitsregel korrigieren**
   help-forensic.md Z16: ersetze `skills/docs/help/*.txt ist die WAHRHEIT` durch `system/docs/help/*.txt ist die WAHRHEIT`. Dadurch wird die Aussage konsistent mit `practices.txt` und der tatsächlichen Verzeichnisstruktur.

2. **Referenz auf practices.txt korrigieren**
   help-forensic.md Z369: `skills/docs/help/practices.txt` → `system/docs/help/practices.txt`.

3. **Doppelt verschachtelten Pfad auflösen**
   help-forensic.md Z368: `skills/_services/skills/docs/help/SKILL.md` ist wahrscheinlich entweder
   - `system/docs/help/SKILL.md` (falls ein Skill-Template gemeint ist), oder
   - `system/skills/_services/SKILL.md` (falls der Service-Workflow gemeint ist).
   Vorschlag: im Workflow die beabsichtigte Kanonik prüfen und auf einen existierenden Pfad normalisieren.

4. **Einmalige kanonische Pfadvariable einführen**
   Zukünftig könnte `bach_paths.py` einen Schlüssel `DOCS_HELP_ROOT = "system/docs/help"` erhalten, sodass Workflows diesen Wert referenzieren statt Pfad-Literale zu wiederholen. Das reduziert die Wahrscheinlichkeit inkonsistenter Verweise.

5. **help_forensic-Routine um Pfad-Konsistenz-Check erweitern**
   Bei der nächsten Ausführung (ca. 2026-06-12) könnte der generierte Task neben dem Text-Review auch prüfen, ob alle in `help-forensic.md` genannten Pfade existieren und ob sie mit `practices.txt` konform sind.

---

## Zusammenfassung

Die technische Recurring-Infrastruktur für `help_forensic` funktioniert korrekt. Die Dokumentation `help-forensic.md` enthält jedoch mindestens drei inkonsistente Pfadangaben, die im Widerspruch zur kanonischen Wahrheitsregel in `system/docs/help/practices.txt` stehen. Empfohlen wird eine reine Textkorrektur in `system/skills/workflows/help-forensic.md` (Vorschläge 1–3), ohne Code oder Konfiguration zu ändern.
