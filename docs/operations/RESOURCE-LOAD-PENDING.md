# Modell-Kaltstart im Ressourcenbroker: vorbereitet, aktuell nicht aktivierbar

Der optionale Ocean-Zustand `LOAD_PENDING` trennt einen exklusiven Ladeversuch
vom regulären Modellturn. BACH fordert ihn nur aus seiner vorhandenen, an Task,
Backend, Modell, Chat und Laufzeitprüfung gebundenen Warmup-Berechtigung an. Ein
normaler Chat- oder Compute-Auftrag bekommt dadurch keine zusätzliche RAM-Freigabe.
Der bisherige Betrieb ohne `BACH_RESOURCE_BROKER_CONFIG` bleibt bestehen.

Eine gespeicherte `MAY_LOAD`-Antwort reicht vor dem POST nicht aus. Unter dem
tatsächlichen Inferenzowner liest BACH das aktuelle private Hostjournal erneut:
derselbe exklusiv belegte Inode, lebender Writer mit PID/Erstellzeit/Bootkennung,
aktuelle Writer-Epoche, exakter Grant, Request, Versuch, Execution, Clientlease
und frisches Profil müssen übereinstimmen. Nach der Profilprüfung folgt ein
weiterer Journalreadback. Teilweise geschriebene, ersetzte, abgelaufene oder
terminale Belege blockieren. Diese Prüfung verwendet keinen Controller-HTTP-Aufruf
unter dem Inferenzowner. Ein neuer Writer bewahrt ungeklärte Reservierungen,
erhält aber auch beim Wiederöffnen im selben Prozess eine neue Epoche.

## Aktuelle Aktivierungsgrenze

`GuardedModelPort.supports_load_pending` ist absichtlich `False`. Ollama 0.33.3
liefert in `/api/ps` Modellname, Digest, Kontext und API-/Metal-Größe, aber damit
keinen geprüften Nachweis über dem Modell zurechenbare private physische Seiten,
die aus derselben verfügbaren Host-RAM-Messung ausgeschlossen sind. Eine
Konfiguration mit `load_policy_sha256` wird deshalb schon beim Aufbau des
Hostdienstes abgelehnt. Das ist eine feste Adaptergrenze und kein abschaltbarer
JSON-Schalter. Ein ungeprüfter eigener Port darf sie nicht ersetzen.

Insbesondere gilt: API-Größe, Prozess-RSS, USS und `phys_footprint` sind keine
austauschbaren Zahlen. Apple beschreibt den Footprint als Abrechnung, die auch
komprimierte und ausgelagerte Seiten umfasst. Daraus folgt keine sichere
Untergrenze aktuell belegten physischen RAMs. Reclaimable oder gemeinsam genutzte
Seiten dürfen nicht gleichzeitig als verfügbar und als bereits belegter
Modellspeicher angerechnet werden.

Primärquelle zur Semantik:
[Apple WWDC22: Profile and optimize your game's memory](https://developer.apple.com/videos/play/wwdc2022/10106/),
insbesondere die Abschnitte zu dirty/compressed/clean memory und
`proc_pid_rusage`. Es wird weder eine Xcode-Lizenz akzeptiert noch eine solche
Zugriffsschranke umgangen, um Messdaten zu gewinnen.

Eine spätere Aktivierung braucht einen unabhängig geprüften Kernel-/Providervertrag
für die physische Zuordnung sowie ein frisches vollständiges Kontext-/Lastprofil.
Ein alter Lade- oder Idlewert reicht nicht. Das Profil wird weder verkleinert
noch durch die 6-GiB-Kaltstartschwelle ersetzt. Die Änderung an `chat_runtime.py`
gehört zum Control-Fingerprint und benötigt ein eigenes kontrolliertes
Aktivierungsfenster.

## Vorbereiteter Ablauf

1. Der einzige Hostbroker akzeptiert eine ausdrücklich berechtigte, begrenzte
   Modellanforderung. Ein zweiter lebender Ladeauftrag für denselben Socket wird
   abgewiesen. Andere Verbraucher behalten ihre normale vollständige Zulassung.
2. Die ursprüngliche Policy wird unverändert gelesen und per SHA gebunden:
   Minimum 6 GiB verfügbar, Floor 2 GiB, Druck höchstens 2, höchstens 8 GiB
   Swapwachstum und 300 Sekunden Ladezeit. Native CPU-/Diskreserve bleibt Pflicht.
3. Der Broker persistiert `MAY_LOAD` mit Authority-, Grant-, Profil-, Spec-,
   Policy-, Prozess- und Versuchsbinding, bevor BACH einen POST ausführen darf.
4. BACH prüft diese Bindung erneut unter dem vorhandenen `HostInferenceGate` und
   verwendet seinen überwachten Warmup. Ein fremder/zweiter Resident, geänderter
   Prozess, andere Policy oder eine veränderte Laufzeitberechtigung blockiert.
5. Erst nach terminalem Transport und Verlassen des BACH-Inferenzowners prüft der
   Hostport das Ergebnis unabhängig unter einem eigenen Inferenzowner. Er schreibt
   `RUNNING` unter demselben Owner, der die Abschlussmessung schützt. Vollprofil,
   exakter Kontext, normaler Druck, native Daten und KV-/Overheadreserve bleiben
   erforderlich. Ohne belegten ResidentCredit gibt es keine RAM-Gutschrift.

Native Probe-Callbacks laufen außerhalb des Controller-Zustandsmutex. Unter dem
Inferenzowner erfolgen nur kurze lokale Arbiter-/Journaloperationen, niemals
Controller-HTTP. BACH betritt den Ressourcenvertrag vor `inference.lock` und
beendet ihn nach Rückgabe dieses Locks. Damit warten die beiden Autoritäten
nicht gegenseitig aufeinander.

## Abbruch und ungeklärte Wirkung

Im neuen gestuften Pfad wird der alte Warmup-Entladehelfer nicht verwendet.
`GuardedModelPort` bindet die Entladung an denselben nativen Prozess, schreibt
den bestehenden `unload-pending`-Intent, sendet höchstens einen POST, verlangt
`done=true` und `done_reason=unload`, beobachtet die exakte Abwesenheit und prüft
die Prozessidentität erneut. Erst dann wird der Intent dauerhaft entfernt.

Nach den Metadaten und dem dauerhaften Intent wird die Prozessidentität noch vor
dem POST frisch geprüft. Der Host schreibt auch bei bereits bewiesener Abwesenheit
`ABORTED` über einen verpflichtenden lokalen Callback, während derselbe
Inferenzowner noch gehalten wird. Eine verzögerte alte Ladeerlaubnis kann dadurch
nicht zwischen Abwesenheitsbeleg und Abschluss erneut ausgeführt werden.
Gewöhnliches `end_turn` darf einen gestuften Ladeversuch nicht abschließen.

Ein unbeendeter Inferenz-Dispatch blockiert diesen Ablauf. Fehlender ACK,
Prozesswechsel, ungültige Messung, Deadline-/Leaseablauf nach möglichem POST oder
Crash führen zu `RECOVERY_HOLD`. Fristablauf ist keine RAM-Rückgabe. Der Controller
behält den Grant und das Journal; ein neuer Writer darf diese nicht automatisch
übernehmen oder löschen. Authentifizierter Status und Request-Readback zeigen
Phase und Versuchsbinding zur gezielten nativen Klärung. Ein vor POST noch rein
vorbereiteter Auftrag kann erst nach geprüfter Abwesenheit und dem normalen
Rückgabeprotokoll beendet werden.

Die Clienttransporte bleiben auch über wiederholte Coroutine-Cancellation hinweg
erhalten. Submit und Begin werden vor Cleanup abgeschlossen; verlorene Antworten
werden mit derselben bekannten Request-/Versuchsidentität abgeglichen. Es gibt
keinen Ersatzauftrag und keine ungebundene Freigabebehauptung.

## Abnahme vor produktivem Einsatz

Der Ocean-Vertrag wird mit nativen Fixture-Ports und echter Loopback-HTTP getestet.
Diese Tests starten kein produktives Modell und pausieren keine fremden Prozesse.
Sie beweisen das Protokoll, nicht die noch fehlende physische Metal-Zuordnung.
Die Freigabe erfordert zusätzlich unabhängigen Review, einen belegten Sensor,
ein aktuelles Peakprofil, kontrollierte Einbindung sämtlicher Modellkonsumenten
und überprüfte kooperative Compute-Checkpoint-/Resume-Abläufe. Ein paralleler
CPU-Broker neben einem unbrokered Modell löst die Kapazitätsfrage nicht.
