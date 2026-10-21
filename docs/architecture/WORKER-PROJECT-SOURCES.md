# Projektquellen für gebundene Worker

## Zweck und Stand

Aufgaben sollen in ihrem registrierten Repository bearbeitet werden. Die Projektkennung ist Teil der nativen Taskversion. Ein Modell darf weder einen lokalen Quellpfad noch eine Clone-URL als Autorität vorgeben.

Dieser Abschnitt ist eine Umsetzung zu BACH #2358. Er ist noch kein Deployment- oder Abnahmebeleg. Insbesondere müssen der vollständige Reviewpfad, die Operator-Bereinigung, die Übernahme bestehender Aufgaben und die tatsächliche Mac-Installation vor der Freigabe separat geprüft werden.

## Autorität

Das lokale Operatorregister liegt unter `~/.bach/worker-project-sources.json`:

```json
{
  "schema": "bach.worker-project-sources.v1",
  "entries": {
    "example-r1": {
      "repository": "owner/repository",
      "origin": "https://github.com/owner/repository",
      "repo_root": "/absolute/registered/checkout",
      "worktrees_root": "/absolute/separate/task-worktrees",
      "lock_scope": "/absolute/registered/checkout",
      "source_ref": "refs/heads/main",
      "source_sha": "EXAKTER_40_STELLIGER_COMMIT",
      "source_class": "public",
      "retired": false
    }
  },
  "legacy_bach_tasks": {}
}
```

Das Beispiel enthält Platzhalter und ist keine installierbare Freigabe. Repository und Commit werden mit anonymen öffentlichen Metadaten gegengeprüft. Der Commit muss bereits im registrierten lokalen Checkout vorliegen. Es gibt keinen automatischen Clone, Fetch oder privaten Fallback. Verschiedene Repositories erhalten getrennte Arbeitsbaumverzeichnisse.

Zusätzlich wird der exakte öffentliche Branch über GitHubs einzelnen Ref-Endpunkt aufgelöst. Der gepinnte Commit muss mit dem beobachteten Branch-Tip identisch oder dessen Vorläufer sein; der Vergleich verwendet beide unveränderlichen SHAs. Fehlende Branches und abweichende Abstammung sperren die Zulassung. Der Herkunftsbeleg speichert den tatsächlich beobachteten Tip. API-Verträge: [einzelne Referenz](https://docs.github.com/en/rest/git/refs#get-a-reference), [Commitvergleich](https://docs.github.com/en/rest/commits/commits#compare-two-commits).

Fremde registrierte Repositories benötigen keinen erfundenen BACH-Twin. Sie benötigen weiterhin vollständige Sperrscans, einen bestätigten Twinstatus und leere Listen für Locks und Hook-Sperren; der kanonische BACH-Pfad verlangt weiterhin seinen bestätigten Twin. Fehlende oder unlesbare Prüfergebnisse gelten nicht als Freigabe. Auch beim Aufgabenabschluss darf eine unlesbare explizite Quelle nicht als unverändert gelten.

Projektkennungen werden über die CLI nie ersetzt oder wiederverwendet. Eine neue Quellrevision erhält eine neue Kennung. `retire` markiert den bisherigen Eintrag dauerhaft als widerrufen; der Eintrag bleibt als Tombstone erhalten. Eine Registeränderung an einer anderen Kennung widerruft einen laufenden Auftrag nicht. Änderungen an der gebundenen Kennung stoppen dagegen den nächsten Modell- oder Werkzeugaufruf. Die CLI entfernt keine Tombstones; eine manuelle Entfernung oder Ersetzung der gesamten lokalen Operator-Konfiguration gehört nicht zum unterstützten Änderungsverfahren.

Vier reservierte native Tags binden die Aufgabe:

- `worker-source:v1`
- `worker-project:<kennung>`
- `worker-commit:<40-stelliger Commit>`
- `worker-entry:<Base64url des SHA-256 des Registereintrags>`

Der letzte Tag verhindert, dass eine bereits zugeordnete Aufgabe nach einer Registeränderung eine andere Quelle erhält. Generische Task-Updates und Lease-Holder dürfen diese Tags nicht ändern. Die Tags beeinflussen weder die gewöhnlichen Auswahl-Tags noch deren Ausschlüsse. Der Operator-Setter prüft die aktuelle Taskversion und eine freie Lease und nutzt den bestehenden auditierten Task-Schreibpfad.

## Operator-CLI

Aus dem installierten BACH-`system`-Verzeichnis:

```sh
python -m hub._services.chat.worker_project_sources list
python -m hub._services.chat.worker_project_sources register example-r1 entry.json --expected-registry-sha256 AKTUELLER_REGISTERHASH
python -m hub._services.chat.worker_project_sources bind 123 example-r1 --task-version AKTUELLE_TASKVERSION
python -m hub._services.chat.worker_project_sources retire example-r1 --expected-registry-sha256 AKTUELLER_REGISTERHASH
```

Nur beim erstmaligen Anlegen eines noch nicht vorhandenen Registers entfällt der erwartete Registerhash. Alle Änderungen schreiben atomar mit exklusivem Konfigurationslock und anschließendem Byte-Readback. Unter POSIX werden Besitzer, Schreibrechte, regulärer Dateityp, Linkanzahl und physische Pfade geprüft. Eine zusätzliche Windows-DACL-Prüfung und eine GUI für diese Operator-Einstellungen sind noch offen.

## Bestehende BACH-Aufgaben

Solange noch kein Register installiert ist, bleibt der bisherige BACH-Modus kompatibel. **Mit der Installation des Registers endet die implizite Zuordnung unmarkierter Aufgaben zu BACH.** Bestehende Aufgaben benötigen entweder eine explizite Projektbindung oder eine einzelne, versionsgebundene Legacy-Klassifikation:

```sh
python -m hub._services.chat.worker_project_sources classify-legacy 123 --task-version AKTUELLE_TASKVERSION --expected-registry-sha256 AKTUELLER_REGISTERHASH
```

Diese Klassifikation gilt für genau diese Aufgabe und ihre anfängliche Inhaltsversion. Ein laufender, weiterhin gültig gebundener Worker behält diese Herkunft bei eigenen nativen Inhaltsupdates; ein neuer Claim benötigt die Klassifikation seiner aktuellen Taskversion. Neue Aufgaben erben sie nicht. Eine explizit fremde Projektangabe wird nie als Legacy-BACH klassifiziert. Die Klassifikation verändert weder den Taskstatus noch eine Lease oder die Taskversion. Historische v1-Ergebnisbelege behalten ihre bisherige Bedeutung und werden nicht nachträglich in v2 umgedeutet.

Die Aktivierung muss deshalb ein abgestimmtes Wartungsfenster mit vorab ausgewählten bestehenden Aufgaben und geprüften Registereinträgen verwenden. Ein leeres Register blind in einen laufenden Workerbetrieb zu stellen würde unmarkierte Aufgaben blockieren.

## Laufzeit und Ergebnis

Die private Taskbindung führt dasselbe Projekt durch Vorbereitung, registrierten Git-Arbeitsbaum, Lesen, Schreiben, gebundene Prüfkommandos und Finish/PR. Lokale Pfade gehören nicht in öffentliche Ergebnisbelege. Ein v2-Scope-Snapshot bindet Repository, Origin, Ref, Quellcommit, Registereintrag und beobachteten Git-Zustand. Er wird beim Ergebnis-Readback erneut aus der aufgezeichneten Quelle geprüft. Ein inzwischen geändertes BACH-Standardverzeichnis darf die Quelle nicht ersetzen.

Eine Review-Aufgabe liest den aktuell gültigen Scope des Parent-Ergebnisses. Eigene Child-Tags liefern dafür keine Quellenautorität. Der Parent bleibt ohne Schreibberechtigung für das Reviewkind. Diese Verknüpfung benötigt noch eine eigene Regression mit einem zweiten Repository.

Git-Scope-Leseprüfungen ignorieren ausführbare globale Filter. Für `status` werden ausschließlich validierte `core.autocrlf`-/`core.eol`-Werte übernommen, damit ein unveränderter Windows-Checkout korrekt als sauber erkannt wird. Repositorylokale ausführbare Filter bleiben ein Ausschlussgrund. Lease-, Lock-, Index-, Symlink-, Secret- und Worktree-Prüfungen bleiben eigenständige Voraussetzungen.

## Offene Abnahme

- Exakter unabhängiger Review des fertigen Diffs und der nativen Writer-Flächen.
- Reviewkind, Zerlegung und Operator-Bereinigung durchgängig für das zweite Repository prüfen.
- Windows-Fehlschläge von unverändertem Basisstand und neue Regressionen getrennt ausweisen; POSIX-Pfade auf dem Mac prüfen.
- Register und Legacy-Auswahl auf dem Mac geschützt installieren, tatsächlichen Quellenwechsel beobachten und Deploymentbeleg sichern.
- Benutzeroberfläche für die Operator-Zuordnung und zusätzliche Windows-DACL-Prüfung gesondert umsetzen.
