# DEPRICATED – Register ersetzter BACH-Teile

Stand: 8. Oktober 2026. Der Dateiname bleibt für vorhandene Plan- und Taskverweise erhalten. Ein Eintrag bedeutet keine endgültige Löschung.

| Teil | Seit | Ersatz | Endpunkte und Zustand | Rollback / Entfernung |
|---|---|---|---|---|
| Navigation zum Agents-Board | 2026-10-08 | Blueprints, MarbleRun, Task-Zuweisung und vier Capability-Boards der gemeinsamen GUI | Navigationsverweis entfernt; `/agents-board` leitet auf `/agenten/blueprints`, `/skills-board` auf `/skills` weiter. Produktions- und Geräteabnahme des neuen Releases stehen beim Schreiben noch aus. | Alte Renderer und Templates bleiben zunächst für einen Code-Rollback erhalten. Endgültige Entfernung gesondert prüfen. |
| Separater Fabrika/Werkstatt-Editor | 2026-10-08 | Blueprint-Editor mit Vorlagen, Rollen und Instanzen | Die gemeinsame Fabrika-Seite führt zum Editor. Erstellung und Änderungen bleiben an die nativen APIs gebunden; kein zweiter Editor wird als kanonisch geführt. | Bestehende Altendpunkte erst nach Prüfung ihrer weiteren Konsumenten entfernen. |
| Feste Policy- und Decision-Beispiellisten im Governance-Adapter | 2026-10-08 | Gepinnter nativer `policy-registry`-Reader | Lesepfade sind angebunden; fehlende Quelle ist nicht verfügbar. Registry- und Quellenprüfung sind keine bestätigte Durchsetzung. DecisionClicker-Schreiben bleibt nicht verfügbar. | Adapter kann explizit deaktiviert werden. Kein stiller Rückfall auf Beispielpolicies. |
| SentinelFleet-Bezeichnung der Skill-Versionierung | 2026-10-08 | BACH-Skillquelle mit CAS und Versionshistorie | Bezeichnung im betroffenen API-Kommentar und Kontextanker ersetzt. Native Skillbearbeitung bleibt erhalten. | Keine Datenmigration oder Entfernung von Versionshistorie. |

## Probleme und Grenzen

- Quelländerung, Testabnahme, Installation und menschliche Geräteabnahme sind verschiedene Zustände.
- Die erste Registryintegration umfasst lesende Metadaten. Mac-Policy-Adoption und menschlicher Writer benötigen eigene Abnahme.
- Die BACH-Frontendquelle bleibt zunächst im Repository. Sie ist nach dem Wechsel auf das gepinnte gemeinsame GUI-Paket kein zweiter Veröffentlichungsort. Ihr endgültiger Rückbau erfolgt nach bestätigter Build- und Konsumentenparität.

## Pflege je künftigem Transfer

Ergänzen: Modul/Altteil, tatsächliches Datum, Ersatz und Pin, alle betroffenen Endpunkte, offene Lücken, Abnahmen, Probleme, Rollbackereignisse und endgültige Entfernung. Keine geplanten Schritte als erledigt eintragen.
