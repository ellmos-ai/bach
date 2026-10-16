# Begrenzte Wiederaufnahme für lokale Always-On-Reservefehler

Diese Quelle beschreibt die Recovery-Änderung für den bestehenden Hintergrundworker. Sie aktiviert keinen Worker, ändert keine Produktivkonfiguration und belegt keinen laufenden Modellbetrieb.

## Zustimmung und Profilbindung

Der Core-Worker buddha_always_on darf die Reserve-Wiederaufnahme nur nach einer ausdrücklichen, versionierten persistent_opt_in-Änderung nutzen. Die Freigabe wird an einen Hash des ausführungsrelevanten Profils gebunden. Änderungen an diesem Profil über die Core-Slot- oder Core-Agent-Schreibpfade widerrufen die Freigabe und ihren Prüfcheckpoint. Änderungen an Status, Aktivität oder aktueller Aufgabenbindung ändern den Profilhash nicht und widerrufen die Freigabe daher nicht.

Die Wiederaufnahme nach local_reserve_reserve_wait_expired gilt nur für den laufenden, aktivierten buddha_always_on mit gültiger Freigabe, unverändertem Profilhash und lokalem Ollama-Ziel. Ein automatischer Modell-Fallback oder Downgrade ist für diese Recovery ausgeschlossen. Andere Worker, Cloud-Antworten und andere Fehlercodes erhalten diese lokale Wartebehandlung nicht.

## Ablauf und Grenzen

- Ein Reservefehler darf nur dann einen neuen Versuch auslösen, wenn die Werkzeugdispatch-Zahl eindeutig null ist. Bei unbekannter oder bereits erfolgter Werkzeugwirkung greift der bestehende Quarantänepfad.
- Ein vollständig verifiziertes erstes Reserve-Warte-Receipt des persistenten Core-Workers (local_reserve_reserve_wait_lease_return_required) kehrt direkt an der Modellgrenze zurück. Der Controller prüft dabei dieselbe aktuelle Task-Binding-Instanz, die Null Werkzeugdispatches, Opt-in, Profil und Stopgeneration. Erst nach bestätigter Lease-Rückgabe und geschlossenem Assignment beginnt die leasefreie Kapazitätswarte; vor neuer Task-Lease und Modellwirkung werden Kapazität und Policy erneut geprüft.
- Der bestehende Poll bis zur Reservefrist bleibt für Legacy-, unbekannte, nicht verifizierte und nach einem Dispatch auftretende Fälle erhalten. Diese Fälle werden nicht als früher sicherer Rückgabepunkt umgedeutet. Nach Fristablauf führt nur ein bestätigter, werkzeugfreier Lauf in den vorhandenen Return-/Kapazitätswartepfad; eine ungeklärte oder bereits erfolgte Wirkung wird nicht wiederholt. Damit ist weiterhin keine vollständig leasefreie Vorab-Admission belegt.
- Während der leasefreien Wartephase werden keine neuen Tasks beansprucht. Nach einer bestätigten Bereitschaft prüft der Worker die aktuelle Profil- und Reservebindung erneut und erwirbt für den nächsten Versuch eine frische Task-Lease.
- Die Wartezeit ist begrenzt: höchstens drei Wiederaufnahmeversuche mit exponentiellen Intervallen ab 60 Sekunden und einem Gesamtbudget von 900 Sekunden. Die bestehende Controller-Überwachung hält einen sichtbaren Warte-/Blockstatus; Zeitablauf allein setzt das Budget nicht zurück. Nach erschöpftem Budget bleibt der Worker wartend, bis eine frische, aktuelle Beobachtung unter derselben Policy einen echten Übergang von blockiert zu bereit belegt.
- Der vorhandene Startup-Monitor darf den Core-Worker nur bei gültigem persistent_opt_in und unverändertem Profilhash wieder aufnehmen. Stop, Opt-out und Profiländerungen gewinnen; ein unbestätigter Start oder eine ungeklärte Werkzeugwirkung wird nicht automatisch wiederholt. Das belegt keinen nativen Live-Start oder dauerhaften 27B-Betrieb.
- Beim persistenten Cloud-Startup ist admission_pending ausschließlich Vorbereitung und öffnet das Startgate nicht. Das Gate öffnet erst, wenn derselbe Checkpoint als admitted persistiert und frisch zurückgelesen wurde und die Bestätigung unter dem Konfigurations-CAS-Lock den weiterhin gültigen Opt-in-Intent und Profilhash belegt. Der Assignment-Eintrag entsteht erst nach bestätigtem Gate; Task-Claim, Modell- und Werkzeugpfade prüfen die gebundene Freigabe erneut.
- Die finale Modellzulassung bleibt am vorhandenen HostInferenceGate: Reserve, Modellbindung und Vordergrundwarte werden unmittelbar vor dem Dispatch erneut geprüft. Die Kapazitätsbeobachtung ist ein vom lokalen Controller validierter Read-only-Proof unter der aktuellen Policy, keine signierte Messung oder Zusicherung nativer Modellverfügbarkeit.
- Während der Wartezeit beendet ein Stop, eine deaktivierte oder abgelaufene Aufgabe, ein Statuswechsel, eine nicht lesbare Richtlinie oder eine Änderung der gebundenen Zustimmung die Wiederaufnahme.
- Fehler werden über eine endliche Liste neutraler reason_code-Werte projiziert. Roh-Ausnahmetexte und interne Pfade werden für lokale Reservefehler nicht als Aktivität gespeichert.
- resolved_model wird nur aus einer erfolgreichen aktuellen Antwort übernommen. Ein Slotwert oder Backendcache eines früheren Laufs ist kein Nachweis für das Modell dieses Laufs.

## Prüfgrenze

Die Regressionen verwenden isolierte synthetische Fixtures. Sie belegen weder eine native Aktivierung noch einen Modellstart, einen Pull oder eine reale Ressourcenfreigabe. Profil-, Reserve- und Laufzeitkonfigurationen bleiben außerhalb dieses Quellpakets unverändert.
