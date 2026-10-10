# DEPRICATED – Register ersetzter BACH-Teile

Stand: 8. Oktober 2026. Der Dateiname bleibt für vorhandene Plan- und Taskverweise erhalten. Ein Eintrag bedeutet keine endgültige Löschung.

| Teil | Seit | Ersatz | Endpunkte und Zustand | Rollback / Entfernung |
|---|---|---|---|---|
| Navigation zum Agents-Board | 2026-10-08 | Blueprints, MarbleRun, Task-Zuweisung und vier Capability-Boards der gemeinsamen GUI | Navigationsverweis entfernt; `/agents-board` leitet auf `/agenten/blueprints`, `/skills-board` auf `/skills` weiter. Produktions- und Geräteabnahme des neuen Releases stehen beim Schreiben noch aus. | Alte Renderer und Templates bleiben zunächst für einen Code-Rollback erhalten. Endgültige Entfernung gesondert prüfen. |
| Separater Fabrika/Werkstatt-Editor | 2026-10-08 | Blueprint-Editor mit Vorlagen, Rollen und Instanzen | Die gemeinsame Fabrika-Seite führt zum Editor. Erstellung und Änderungen bleiben an die nativen APIs gebunden; kein zweiter Editor wird als kanonisch geführt. | Bestehende Altendpunkte erst nach Prüfung ihrer weiteren Konsumenten entfernen. |
| Feste Policy- und Decision-Beispiellisten im Governance-Adapter | 2026-10-08 | Gepinnter nativer `policy-registry`-Reader | Lesepfade sind angebunden; fehlende Quelle ist nicht verfügbar. Registry- und Quellenprüfung sind keine bestätigte Durchsetzung. DecisionClicker-Schreiben bleibt nicht verfügbar. | Adapter kann explizit deaktiviert werden. Kein stiller Rückfall auf Beispielpolicies. |
| SentinelFleet-Bezeichnung der Skill-Versionierung | 2026-10-08 | BACH-Skillquelle mit CAS und Versionshistorie | Bezeichnung im betroffenen API-Kommentar und Kontextanker ersetzt. Native Skillbearbeitung bleibt erhalten. | Keine Datenmigration oder Entfernung von Versionshistorie. |
| Skills-Board: Schreibweg `PUT /api/skills-board/item-file` | 2026-10-11 | `PUT /api/capabilities/skills/{id}/source` (CAS-Revision und Verlauf in der Skill-Zentrale `/skills`) | HTTP 410 mit Hinweis auf den Ersatz. Der Weg schrieb `.md`, `.txt` und `.py` unter `BACH_DIR`. Einziger Caller: `gui/static/js/skills-board.js` (Board ist verwaist: `/skills-board` und `/agents-board` leiten um). Der Lesepfad `GET /api/skills-board/item-file` bleibt, gibt aber keinen `absolute_path` mehr aus | Commit zurücknehmen; kein Datenbestand betroffen |
| Skills-Board: Speicher `data/skills_hierarchy.json` | 2026-10-11 | Tabelle `hierarchy_assignments` als einziger Speicher (liest die CLI `hub/skills.py` und der Server) | `GET /api/skills-board/hierarchy` liest nur noch die Datenbank; `PUT` validiert strikt (Typen, Größe 1 MB, Listen bis 5000, bekannte Agenten und Elemente), speichert nur Zuordnungen in einer Transaktion und speichert Items nicht. Die vorhandene JSON-Datei wird weder gelesen noch geschrieben noch gelöscht. Entscheidung Lukas 2026-10-11: Die Zuordnung wird künftig primär in der Agenten-Werkstatt (Blueprints) gepflegt, zusätzlich bleibt eine Board-Zuordnung; ein `/skills`-Tab folgt erst nach Klärung des Speichervertrags mit dem Hauptworker (Blueprint `skills_json` = ausführbare Laufzeitbindung mit Pins, `hierarchy_assignments` = Organisationsbaum, verschiedene Konzepte). Unterschiede zeigt `tools/migration/skills_hierarchy_dryrun.py` (nur Bericht, keine Übernahme; die Entscheidung über eine Datenübernahme liegt beim Nutzer) | Commit zurücknehmen; die JSON-Datei bleibt unverändert erhalten |

## Probleme und Grenzen

- Quelländerung, Testabnahme, Installation und menschliche Geräteabnahme sind verschiedene Zustände.
- Die erste Registryintegration umfasst lesende Metadaten. Mac-Policy-Adoption und menschlicher Writer benötigen eigene Abnahme.
- Die BACH-Frontendquelle bleibt zunächst im Repository. Sie ist nach dem Wechsel auf das gepinnte gemeinsame GUI-Paket kein zweiter Veröffentlichungsort. Ihr endgültiger Rückbau erfolgt nach bestätigter Build- und Konsumentenparität.

## Pflege je künftigem Transfer

Ergänzen: Modul/Altteil, tatsächliches Datum, Ersatz und Pin, alle betroffenen Endpunkte, offene Lücken, Abnahmen, Probleme, Rollbackereignisse und endgültige Entfernung. Keine geplanten Schritte als erledigt eintragen.
