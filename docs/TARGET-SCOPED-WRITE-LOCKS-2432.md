# Zielbezogene Konfigurations-Schreibsperren — Task #2432

## Ursache und Änderung

Der kanonische `--check-dir`-Scanner prüft bereits Zielverzeichnis, relevante Vorfahren, Worktree-Hauptclone und Twins. Zusätzliche rekursive Scans jedes Vorfahren bis zum Dateisystemroot bezogen fremde Geschwister-Unterbäume ein. Am 22.10.2026 um 10:29 UTC waren `~/.bach/chat` und `~/.bach` vollständig frei; `/Users/lukas` war ohne Locktreffer unvollständig. Dadurch konnte Buddha seine alte Taskbindung nicht über den vorgesehenen SDK-Schreibweg lösen.

Der Consumer prüft jetzt das vorhandene Zielverzeichnis einmal. Erfolg verlangt Exit 0, genau dieses geprüfte Verzeichnis, leere Locks und Hookguards, vollständige Descendants sowie bestätigten Twinstatus. `-S` bleibt erhalten. Tatsächliche Sperren und unvollständige relevante Scans bleiben blockierend. Kein neuer Scanner, keine Whitelist und keine Guardabschaltung. Der Parent-Scan bleibt konservativ für dessen Unterbäume.

## Grenzen und weitere Schritte

Der konkrete Operator-Clear muss den originalen absoluten Slotpfad vor SDK-Aufruf auf Symlinks/Reparse und `..` prüfen und denselben Pfad übergeben: vorhandene Slotaufrufer lösen ihren Pfad bereits vor dem Guard auf. Diese Änderung behauptet keine allgemeine Behebung jener vorhandenen Aliasgrenze.

Quellenprüfung: Python-AST und `git diff --check`; keine neuen oder manuell ausgeführten Tests. Veröffentlichung, unabhängiger Review, Mac-Aktivierung, Freigabe der alten Taskbindung und neue Buddha-Ausführung werden separat belegt. Die verbleibende Ressourcen-/Fackelarbeit bleibt in #2330/#2333/#2334 offen. Keine RAM-, Kontext- oder Modelländerung.
