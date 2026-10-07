# Native Worker: Sicherheitsgrenzen

## Autorität

Eine bestätigte Task-Lease erlaubt nur Operationen an der gebundenen Task und ihrer aktuellen Inhaltsversion. Sie ist keine Betriebssystem-Sandbox. Datei-, Shell- und Netzwerkwerkzeuge folgen zusätzlich dem vom Nutzer gewählten Werkzeugmodus.

Der private CLI-Transport öffnet ausschließlich eine zufällige Loopback-Adresse. Jeder Aufruf benötigt ein eigenes zufälliges Bearer-Token; Browser-Origin-Anfragen werden abgewiesen. Token und Lease-Daten erscheinen weder in CLI-Argumenten noch in Modellprompts. Der Modus wird beim Erzeugen der Bridge festgelegt und kann durch HTTP-Payloads nicht erweitert werden. Werkzeugname, aktuelle Freigabe und Taskbindung werden erneut im Dispatcher geprüft.

## Erreichbare Funktionen

| Familie | Grenze und Bewertung |
| --- | --- |
| Taskoperationen | Aktuelle Lead-Lease, Task-ID, Fence und Inhaltsversion; SQL-Werte parametrisiert und Feldnamen zugelassen. |
| Worktree und Veröffentlichung | Exakte gebundene ganzzahlige Task-ID, isolierter Taskpfad, Argumentlisten ohne Shell, erneute Lease-Prüfung vor Operationen und bestätigter Veröffentlichungsbeleg. |
| Legacy-Delegation und Cleanup | In jedem gebundenen Modus ausgeblendet und vor dem Dispatcher abgewiesen. Kein bezahlter Delegationsfallback und kein destruktiver Cleanup durch den Worker. |
| Lesen | Aufgelöste erlaubte Wurzeln und bestehende Secrets-Deny-Liste. Diese Liste beansprucht keine vollständige Erkennung aller vertraulichen Dateien. |
| Schreiben | Bestehende Modus- und Live-Pfad-Grenzen. Safe bedeutet Dateiwerkzeuge ohne beliebige Shell; Full erlaubt ausdrücklich Shell und Dateischreiben. Die Lease erzeugt keine zusätzliche globale Dateisystemisolation. |
| Textsuche | Regex mit Timeout pro Suche, Gesamtzeit-, Muster- und Leselimit. Kein unbegrenztes Backtracking auf Modellargumenten. |
| Webabruf | Bestehender Web-Scraper-Provider mit öffentlichen DNS-Zielen, DNS-Pinning, erneuter Redirect-Prüfung und Antwortlimit. Kein stiller Wechsel bei fehlendem kanonischem Provider. |

Eine statische Meldung an einer Datei- oder Shellfunktion muss anhand dieses tatsächlichen Aufrufpfads bewertet werden. Die absichtliche Full-Funktion darf nicht als unauthentifizierte Webausführung beschrieben werden. Ebenso beweist die Authentifizierung allein keine Sicherheit eines erreichbaren Regex- oder Web-Fetch-Werkzeugs. Alarmfamilien werden nicht pauschal verworfen.

## Ausführung und Ende

Fehler bei der Backendauflösung stoppen den Start. Der globale Chatanbieter ist weder Ersatzanbieter noch Ollama-Cache-Eintrag.

Ein privater POSIX-CLI-Aufruf besitzt eine neue Prozessgruppe. Der Aufruf kehrt erst zurück, wenn der Elternprozess und seine Gruppe beendet sind; Kill- oder Wait-Fehler erzeugen keinen Endbeleg. Dies gilt auch für unerwartete Fehler nach dem Spawn. Der private Windows-CLI-Pfad bleibt bis zur Abnahme eines entsprechenden Prozessschutzes gesperrt.

Übergabe und Zerlegungsanfragen während eines laufenden Blocks stehen nur Backends mit tatsächlich angebundener Aktionsgrenze zur Verfügung. Managed CLI-Backends lehnen diese Anfragen ab. Ein Anbieterwechsel mit bereits ausstehender Blockaktion stoppt vor dem CLI-Start.

## Getrennte Abnahmen

Unit-Tests und ein Prozessgruppen-Test mit eigenen Python-Prozessen belegen die geprüften Grenzen. Sie ersetzen weder die Abnahme einer installierten Agenten-CLI noch den tatsächlichen Always-On-Tasklauf oder die Windows-Tray-Abnahme.
