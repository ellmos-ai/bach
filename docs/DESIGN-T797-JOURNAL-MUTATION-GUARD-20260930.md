# T797: vorgeschlagene private Mutationsgrenzen für den Nemo-Consumer

**Entwurf für statischen unabhängigen Vertragsreview. Nicht implementiert.**
Iststand Journal `861a3ca51fa2462c22b31c020c699369aca116a9`, aktuelle lokale
Lease-Nachbesserung `409b7fa5` auf regulär integrierter Defaultbasis `7120cd1e`.
Alle vier Nemo-Quelldateien bleiben unverändert. Kein neuer Journaling-Algorithmus,
kein Hostlock-Erzeuger, keine Runtimeanbindung und keine CI-Änderung.

## Befund und vorgeschlagene Naht

Die unveränderten Nemo-Funktionen validieren Daten und Hashes. Die letzten
Dateimutationen erreichen aber native `Path.replace`/`unlink`, bevor der nächste
Hostcheck erfolgt. Ein während der letzten Hashprüfung verlorener Hostguard
wird erst nach der Mutation erkannt. Die drei unabhängigen Gegenfälle betreffen
Forward-Move, Undo-Move und Undo-Copy.

Der Consumer soll ausschließlich unveränderte, bereits importierte vertrauenswürdige
Python-Codeobjekte gegen eine **pro Instanz private** Umgebung binden. Dazu dient
`types.FunctionType`; keine Codekompilierung aus Text, kein `eval`/`exec`, kein
AST-Umschreiben und keine globalen Monkeypatches. Der Algorithmus/Bytecode kommt
weiter aus den vier geprüften Nemo-Dateien. Eine dokumentierte lokale Bindetabelle
und unveränderte Sourcehashes machen diese Grenze überprüfbar.

## Aufrufgraph und Bindung

```text
BachActionJournal.execute_actions / rollback
  -> vollständige Plan-, Root-, Alias-, Receipt- und Hash-Vorprüfung
  -> exklusiver vom Host gelieferter Guard-Kontext für ALLE Pfade/Eltern
  -> privater Nemo-Consumer
       ActionJournal.__init__, _load, plan, execute, undo,
       _planned_entries, _target_bytes, _receipt, controlled_paths,
       _write, _write_target
       -> privates apply_move / undo_move / file_sha256 / move_action_id
       -> private Path-Klasse / OS-Proxy / tempfile-Proxy / Stream-Proxy
       -> frischer Hostcheck unmittelbar vor JEDEM mutierenden Primitive
       -> unverändertes Standardbibliothek-Primitive
```

Pro Consumer entstehen eine private Globals-Dictionary, eine private
ActionJournal-Unterklasse und eine private Path-Unterklasse des tatsächlich
verwendeten Plattformtyps (`type(Path())`). Alle gebundenen Methoden referenzieren
diese Dictionary. Die Globals-Referenz `ActionJournal` verweist auf die private
Klasse, damit die statischen Querverweise `_planned_entries -> _target_bytes`
keine originale ungeschützte Variante erreichen. `staticmethod` bleibt explizit
`staticmethod`; reguläre Methoden behalten ihre Instanzbindung. Defaultargumente,
Keyworddefaults und notwendige Closure werden unverändert übernommen.

Die privaten Globals ersetzen ausschließlich `Path`, `os`, `tempfile`,
`ActionJournal`, `apply_move`, `undo_move`, `file_sha256` und `move_action_id`.
Dataclasses/Contracts, JSON, Hashlib und alle sonstigen Referenzen bleiben die
geprüften Originalreferenzen. Die fertige Umgebung wird nach dem Bau nicht
mehr umgebunden und nicht exportiert. Originalmodule und fremde Consumer
behalten ihre ursprünglichen Globals und Klassen.

Die Path-Klasse bindet ihren Owner in der privaten Klassenumgebung. Auch
`parent`, `resolve` und weitere von Path erzeugte Ableitungen müssen denselben
Owner behalten; kein verlorener Guard durch Path-Konstruktionshilfen.

## Vollständige Mutationsgrenzen

| Originaler Pfad | Primitive | Schutz unmittelbar vor dem Primitive |
| --- | --- | --- |
| `smart_inbox.apply_move` | `source.replace(target)` | Private Path: beide Pfade erneut validieren; Hostcheck; native Replace |
| `smart_inbox.undo_move` | `source.replace(target)` | Dieselbe private Path-Grenze nach der letzten Hashprüfung |
| `ActionJournal.undo`, Copy | `target.unlink()` | Private Path: kontrollierter Target; Hostcheck; native Unlink |
| `ActionJournal._write` | `self.path.parent.mkdir(parents=True, exist_ok=True)` | Private Path: Journalwurzel und Elternscope prüfen; Hostcheck vor jeder tatsächlichen Erstellung |
| `_write` / `_write_target` | `tempfile.mkstemp` | Privater tempfile-Proxy: ausschließlich im kontrollierten Journal-/Target-Elternscope; Hostcheck vor Erstellung |
| `_write` / `_write_target` | `os.fdopen` und `temporary.write` | Privater OS-/Stream-Proxy: nur registrierte eigene Temp-FDs; Hostcheck vor Datenwrite |
| `_write` / `_write_target` | `temporary.flush` / `os.fsync` | Privater Stream-/OS-Proxy: Eigentum und Hostcheck vor Datenpersistenz |
| `_write` / `_write_target` | `os.replace(temporary_name, final_path)` | Privater OS-Proxy: registrierter eigener Temp-Pfad und explizit kontrolliertes finales Ziel; Hostcheck vor Rename |
| `_write` / `_write_target`, finally | `os.unlink(temporary_name)` | Privater OS-Proxy: ausschließlich registrierter eigener Temp-Pfad; Hostcheck vor Cleanup |

Dateistreams müssen unbuffered arbeiten, damit ein späteres `close` keine
bereits abgewiesenen Pufferwrites ausführt. Das Schließen eigener FDs/Handles
ist auch nach Guardverlust nötig und darf keine neuen Pfad-/Datenmutationen
auslösen. Der Proxy darf keinen Schreibzugang zu beliebigen Fremd-FDs vermitteln.
Neue Tempfiles werden als eigene Ressourcen unter dem bereits exklusiv
gehaltenen Verzeichnisscope registriert. Ein Fehler nach Erstellung und vor
`fdopen` muss den FD zuverlässig schließen.

Bei Guardverlust ist auch ein Cleanup-Unlink verweigert. Ein eigener temporärer
Rest darf dann bestehen bleiben; er ist kein Erfolgsreceipt. Der Fehler muss
diesen begrenzten Tempzustand dem Aufrufer zugänglich machen. Es erfolgt keine
automatische spätere Cleanup-Arbeit und keine Pfadlöschung ohne neue gültige
Autorisierung. Bestehende Nutzerdateien und Journalzustände werden geschützt.

Jede Grenze prüft den gleichen expliziten Hostkontext erneut; Ergebnisse werden
nicht gecacht. Nur exakt `True` autorisiert. Unknown, Exception, NIL-/falsche
Lease oder Scopekonflikt bleiben fail-closed. Die Hostimplementation muss die
exklusive Lease während des gesamten Kontextes tatsächlich halten/erneuern.
Der Consumer erzeugt dafür keinen eigenen zweiten Lockstandard.

## Geplante deterministische Abnahme

1. Die drei originalen Astra-Repros bleiben unverändert rot vor dem Fix und
   müssen grün werden: Guardverlust während letzter Hashprüfung, anschließend
   keine Source-/Target-Mutation und kein neues Erfolgsreceipt.
2. Fault-Injection an jeder obigen Mutationsgrenze: Guard wechselt vor dem
   Primitive auf False/None/Exception; keine entsprechende Mutation. Erlaubte
   eigene Temp-Reste sind ausdrücklich messbar und Handles geschlossen.
3. Zwei gleichzeitig vorhandene Consumer mit gegensätzlichen Guards, darunter
   mehrere Threads: kein Zustands-/Globals-/Path-Owner-Leak. Ein Consumer darf
   niemals den Guard eines anderen autorisieren. Originalmodule bleiben identisch.
4. Statische Methoden und alle internen Querverweise werden nachweisbar auf
   private Consumer gebunden. Hash/Receipt/Plan/Undo-Algorithmus bleibt gleich.
5. Die bestehenden 35 Journalfälle bleiben unverändert grün: reale Datei-Bytes,
   Root-/Alias-/alte-Target-Schutz, explizite Crash-Retry-/Undo-Reopen-Fälle,
   keine fremde Hashdrift-Adoption, keine permissiven Defaultguards.
6. Alle vier Nemo-Dateien und die übernommene LICENSE müssen weiterhin exakt
   bytegleich dem unabhängig bestätigten `861a3ca5` sein.

## Entscheidungsgrenze

Diese Bindung ist komplexer als ein ausdrücklicher Guard-Hook in der Original-API.
Sie wird nur vorgeschlagen, weil der autorisierte Scope Originalcode unverändert
verlangt. Falls die Instanzisolation, vollständige Mutationsabdeckung oder sichere
FD-Behandlung im Vertragsreview nicht überzeugen, bleibt der Consumer ungeeignet
für Runtimeeinsatz. Dann braucht ein expliziter Guard-Hook eine neue abgestimmte
Quelländerungsautorität; der Scope darf nicht still erweitert werden.
