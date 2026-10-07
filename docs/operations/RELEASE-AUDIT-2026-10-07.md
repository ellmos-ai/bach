# Release-Audit 2026-10-07

## Ausgangsstand

- Quelle: frischer Worktree von `origin/main` `9815de1b22e0f1b396a86b81cb6521afc96ebde7`, Repository `ellmos-ai/bach`.
- Version bleibt `3.14.0`; neuere Änderungen stehen unter `[Unreleased]`. Latest Release ist weiterhin `v3.14.0` vom 2026-09-11. Dieser Kandidat ist keine neue Releaseversion.
- PR #188 (Abhängigkeiten) und PR #190 (Privacy/GUI) wurden am 2026-10-04 integriert.

## Befunde und Korrekturen

- Manifest verlangte Astro 5, Lockfile enthielt Astro 7.3.5. Manifest auf den vorhandenen Lockfile-Stand abgeglichen; eine Neuauflösung auf Astro 5 brachte kritische Advisories zurück.
- Ein verbleibender Main-Dependabot-Alert #42 betraf `http-cache-semantics` 4.2.0. Update auf Registry-Version 4.3.0; nur Version, Registry-URL und Integrity dieses Lockfile-Eintrags geändert. Keine plattformspezifischen Optional-Metadaten entfernt.
- Unvollständiges Duplikat von `applyGovProfile` verhinderte das Kompilieren der Agenten-Werkstatt und machte das Inline-Skript syntaktisch ungültig. Die vorhandene vollständige Funktion bleibt erhalten. Regression prüft Skriptinitialisierung und read-only Toolauswahl.
- Persönlicher Modulpfad durch explizite Modul-/OneDrive-Konfiguration und aktuelles Home ersetzt. Private Lead-Fallbacks entfernt; nur der konfigurierte Server wird geprüft. Ein Offline-Lead führt zu `None`, keine Umleitung von Taskverkehr.
- Control-Origin-Liste nutzt den lokalen Hostnamen statt persönlicher Hostnamen; Same-Origin und generische lokale Netze bleiben unterstützt. Dokumentationsadressen redigiert und historische Befunde als solche gekennzeichnet.
- Ignore-Lücken geschlossen: SQLite-Begleitdateien, `.credentials/`, verschachtelte Lockdateien und weitere bekannte OneDrive-Konfliktkopien. Bereits versionierte Quell-/Testdateien werden weiterhin erfasst.

## Verifikation

- Node 24.13.1 auf Windows: `npm ci --no-audit --no-fund` erfolgreich; `npm test`: 8 bestanden; `npm run build`: 17 Seiten.
- `npm audit --json --package-lock-only`: Exit 0, 0 Advisories (aktueller Registry-Snapshot, keine dauerhafte Sicherheitsgarantie).
- Python 3.12: Domain-Katalog, Rheingold, Workerstatus und Slots: 159 bestanden. GUI-Privacy, Server, Tasksummary und Templates: 167 bestanden, 2 vorhandene Templatewarnungen (fehlendes CSS und nicht referenzierte Templates).
- Gitignore: 9 sensible Beispieldateien ignoriert, 3 Quell-/Manifestdateien nicht ignoriert; `git ls-files -ci --exclude-standard` leer.
- Credential-/Privatpfadscan über 3833 getrackte UTF-8-Dateien (3831 Ausgangsdateien plus zwei neue Regression-/Nachweisdateien): Treffer ausschließlich synthetische Security-Testwerte und eine Negativprüfung auf einen früheren Hostnamen nach Redigierung. Acht unveränderte Bild-/Icondateien wurden als Binärdateien getrennt erfasst, keine Inhaltsfreigabe behauptet. Kein Scanfehler.
- `git diff --check` erfolgreich. Domain-Regression in bestehende Python-CI aufgenommen; Fabrika-Regression läuft im GUI-Workflow.

## Offene Gates

- PR-Review, Integration und GitHub-Checks müssen den tatsächlich gepushten Commit prüfen. Lokale Tests ersetzen die unabhängige Freigabe nicht.
- `BACH-SEC-DEPS-01`: Dependabot-Alertstatus nach Integration erneut lesen; das aktuelle Main enthielt noch 4.2.0.
- `BACH-SEC-ROTATE-01`: Alt-Token-Widerruf und Verbraucher sind weiterhin nicht belegt. Keine produktiven Credentials oder Deployments verändert.
- Kein Release-Tag und kein Release-Upload; keine Änderung der fremden OneDrive-Projektion.
