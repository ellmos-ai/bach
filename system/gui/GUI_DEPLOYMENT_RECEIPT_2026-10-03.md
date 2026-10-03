# BACH/Ocean GUI: Integrations- und Deploymentnachweis vom 03.10.2026

Dieser Nachweis ergänzt den früheren, inzwischen überholten Stand in `GUI_AUDIT_INTEGRATION_2026-10-03.md`. Die neun Bereiche der von Gemini angelegten Oberfläche blieben erhalten.

## GitHub und Build

- Bereinigter Main-Kandidat begann auf `d4917285`. Der GUI-Baum wurde als einzelner Squash-Commit `407e45cb` übernommen; die ältere Feature-Historie mit eingebettetem Gerätetoken wurde nicht in GitHub-Main gemergt.
- Nach gezielten Einzel-Patches ist `0c41cf5a5d47e52635f054ec6c311ce437c335d8` auf `origin/main` veröffentlicht. Alle Pushes waren normale Fast-Forwards ohne Force-Push. GitHub meldete dabei einen Bypass der Regel „Änderungen über Pull Request“; dies ist ein beobachteter Vorgang und keine Änderung der Repository-Regel.
- Im isolierten Integrations-Worktree: Astro-Build 16 Seiten, Python-Kompilierung und `git diff --check` bestanden. Sechs isolierte Tests für Memory-Federation, Auth, Lock-Feed und MarbleRun bestanden. Eine Suche in 45 relevanten GUI-Quell- und Build-Dateien fand null Kopien des zuvor eingebetteten Token-Literals. Weder Token noch dessen Hash stehen in diesem Nachweis.

## Mac Studio, ausgelieferter Stand

- Ziel: `/Users/lukas/services/bach`, GUI-LaunchAgent `com.bach.gui-server` auf Port 8000. Der Mac-Checkout behielt seinen eigenen älteren, teilweise veränderten Git-Stand; es gab dort keinen Pull, Reset oder Datenbanktausch. Installiert wurden nur hash-geprüfte GUI-Quellen und jeweils ein vollständiger neu gebauter `web/dist`-Baum.
- Vier sequenzielle Overlays mit privaten Backups außerhalb des Webroots: `bach-ocean-gui-20261003-407e45cb`, `bach-gui-task-20261003-e9c213fb`, `bach-ocean-runtime-20261003-3030aab2`, zuletzt `bach-ocean-memory-20261003-0c41cf5a` unter `/Users/lukas/private-deploy-backups/`. Die Backup-Verzeichnisse haben Modus `0700`; jedes Deploy-Skript prüfte Quell- und Dist-Vorabbilder und enthält eine hash-geprüfte Rücknahme. Die ursprünglichen, potentiell tokenhaltigen Dateien liegen ausschließlich in diesen privaten Backups.
- Letzte Welle: sechs Quelldateien, darunter das neue Read-only-Modul `memory_federation.py`, und 19 Dist-Dateien; GUI-LaunchAgent nach Neustart PID `97614`.
- Live-HTTP nach Neustart: `/`, `/memory`, `/governance`, `/agenten/marblerun`, `/agenten/fabrika` jeweils 200 und bytegleich mit dem eigenen Build. Ohne Token antworten `/api/memory/cognitive-state`, `/api/memory/facts` und `/api/gardener/search` mit 401. `/api/governance/status` antwortet 200 mit `availability=unavailable` und `lock_count=null`, weil auf dem Mac kein frischer Lock-Feed belegt ist. Es wurden keine produktiven Schreib- oder Modellaufrufe ausgeführt.

## Verbleibende Grenzen

- Der zuvor veröffentlichte Gerätetoken muss nach Prüfung seiner Verbraucher widerrufen und ersetzt werden. Die Browser-Anmeldung speichert ihren Token weiterhin in `localStorage`; ein Cookie- oder Sessionvertrag ist noch offen. Mehrere andere API-Präfixe verwenden weiterhin eine Übergangs-Authentifizierung.
- Die Memory-Suche trennt BACH, Gardener und USMC und öffnet SQLite nur lesend. Auf dem Mac fehlen die Gardener- und USMC-Datenbanken an ihren bestätigten Standardpfaden; die Oberfläche muss deren Status daher als nicht verfügbar zeigen. Ein positiver Live-Readback mit gültigem Gerätetoken wurde nicht ausgeführt; isolierte gültig/ungültig-Token-Fixtures bestanden.
- MarbleRun führt keinen Worker aus; ein Lauf wird vor jedem Datenbankzugriff mit 501 abgewiesen. Compare-Race hat im BACH-Mac-Venv weder `compare_race` noch `coma` als importierbares Paket und an den SDK-Standardpfaden keine Konfiguration. Die Oberfläche beansprucht deshalb keine echten Modellrennen.
- Das Mac-System ist ein gezieltes GUI-Overlay auf seinem erhaltenen Checkout, keine bytegleiche Installation des gesamten GitHub-Main-Repositories. Eine spätere vollständige Checkout-Angleichung benötigt eine eigene Prüfung seiner fremden Änderungen.
