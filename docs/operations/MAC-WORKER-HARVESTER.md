# Mac-Worker-Commits sicher abholen

Der Live-Pfad `~/services/bach` konsumiert `origin/main` und darf lokale Worker-Commits erzeugen. Diese Commits verlassen den Mac ausschließlich über einen Review-Branch. Der Harvester pusht niemals auf `main`, führt keinen Merge aus und verändert keine laufenden Dienste.

## Ablauf

1. Vor jedem Fetch prüft der kanonische `lock_scan.py --check-dir --strict` den Checkout und alle Eltern bis `$HOME`. Ein fehlender Scanner, ein Lock, ein User-Hold oder ein unbekannter Zustand blockiert den Lauf.
2. `system/bin/harvest-local-commits.sh --status` holt danach `origin/main` und zeigt Divergenz sowie den deterministischen Zielbranch.
3. `--run` verlangt `main`, einen sauberen Arbeitsbaum, das erwartete GitHub-Repository und eine gültige `gh`-Anmeldung.
4. Bei lokalen Commits pusht das Skript ausschließlich die vorab erfasste vollständige Commit-ID ohne Force auf `mac/<host>-<vollständige-commit-id>`. Der Branch bleibt für denselben Commit auch an späteren Tagen gleich.
5. Ein vorhandener offener Draft-PR mit exakt dieser Head-ID wird wiederverwendet. Ein bereits gemergter PR ist ein erfolgreicher No-op; ein ungemergt geschlossener PR blockiert.
6. Der abschließende `gh pr view`-Readback muss `OPEN`, Draft-Status, Branch, Basis und Head-ID bestätigen. Das JSONL-Receipt liegt unter `~/Library/Logs/bach/git-harvester.jsonl`.

Der PR braucht die unabhängige Prüfung nach D-20260902-002. Merge, Dienstneustart und Rückführung des Mac auf `origin/main` bleiben getrennte Schritte.

## Launchd nach Review aktivieren

Die versionierte Vorlage `system/launchd/com.bach.git-harvester.plist` startet den Lauf täglich um 03:20 Uhr. Erst nach unabhängiger Prüfung und Mac-Rollout wird sie nach `~/Library/LaunchAgents/` kopiert und mit `launchctl bootstrap gui/$(id -u) ...` registriert. Die Vorlage nutzt `$HOME/services/bach`; bei einem anderen Live-Pfad muss der Program-Argument-Eintrag vor der Registrierung angepasst werden.

## Gerettete unversionierte Dateien vom 21. September 2026

- Übernommen: sechs fehlende Service-SKILLs, das tatsächlich archivierte `hq5-test-agent`-Paar und die Whitelist-Erweiterung des Anonymisierers samt Regressionstest.
- Ersetzt: `deploy-bach-services.sh`. Das unversionierte Skript holte nur neue Commits, aktualisierte den Checkout aber nicht und startete dennoch den GUI-Dienst neu. Der Harvester trennt Abholung und Deployment.
- Nur in der geprüften Rettungskopie aufbewahrt: `apply_helpdoc_review_patches.py` und weitere einmalige Übersetzungsreparaturen. Sie schrieben direkt in eine lokale Datenbank, waren an abgeschlossene Tasks gebunden und sind durch die versionierten Übersetzungsartefakte belegt.
- Nicht übernommen: Datenbank-Backups, Übersetzungsreports, Zustands-, Lock-, Cache-, Log- und doppelt verschachtelte Laufzeitdateien. Die Rettungskopie mit SHA-256-Manifest bleibt ihr Beleg.
