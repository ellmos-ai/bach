# Worker-Taskkontext bei einem neuen Lease isolieren

## Zweck

Ein langlebiger Telegram-Worker verwendet eine Chat-Session, deren Schlüssel die Worker-ID ist. Ohne eine Grenze beim Aufgabenwechsel kann der nächste Task das Gespräch des vorherigen Tasks als Kontext erhalten. Der Worker muss den Verlauf des vorherigen Tasks archivieren und eine leere Session beginnen, bevor er einen neu geleasten Task an das Modell sendet.

## Vertrag

- Das aktive Task-Binding ist die Kontextgrenze. Ein neues Binding bedeutet eine neue Lease und verlangt vor dem ersten Inferenzaufruf einen persistenten Session-Reset.
- Der Reset läuft erst, nachdem Task-Binding und Assignment bestätigt und der Lease-Supervisor gestartet wurden. Vorherige Toolrunden, Wiederaufnahme nach Toolbudget und sonstige Folgeblöcke desselben offenen Bindings behalten ihren Verlauf.
- Der Reset verwendet ausschließlich ChatRuntimes vorhandenes `clear_session(..., archive_reason="Worker Taskwechsel")`. Der vorhandene `SQLiteChatSessionStore` archiviert den alten Verlauf und entfernt den aktuellen Snapshot, bevor `get_session` ihn wiederherstellen kann.
- Direkt danach werden Modell-, Profil-, Werkzeug- und Promptkonfiguration erneut auf die leere Session gebunden. Dafür wird derselbe Steckplatzsnapshot verwendet, der das Backend für diesen Aufgabenblock ausgewählt hat; die neue Session fällt so nicht auf Runtime-Standardwerte zurück.
- Ein fehlender persistenter Chatstore oder ein Fehler beim Archivieren/Löschen beendet den Lauf vor der Inferenz. Der bestehende Cleanup-Pfad schließt Supervisor und Assignment und gibt die neue Lease zurück; fehlende Rückbestätigung bleibt ein Cleanup-Fehler.
- Wenn keine Task-Lease verfügbar ist, wird kein Verlauf zurückgesetzt. Die leere Queue ist kein Taskwechsel.

## Grenzen

Der Vertrag ändert weder Task-Auswahl noch Lease-/Assignment-Autorität oder Ergebnisannahme. Er ersetzt keine Vertraulichkeitsprüfung des Prompts und erzwingt keinen Reset für andere Chat-Einstiegspunkte. Der Quellfix ist erst nach Root-Review und gezielter Mac-Testabnahme belegt; eine produktive Aktivierung oder Laufabnahme ist damit nicht verbunden.
