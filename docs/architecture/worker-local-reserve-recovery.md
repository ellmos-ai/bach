# Begrenzte Wiederaufnahme für lokale Always-On-Reservefehler

Diese Quelle beschreibt die Recovery-Änderung für den bestehenden Hintergrundworker. Sie aktiviert keinen Worker, ändert keine Produktivkonfiguration und belegt keinen laufenden Modellbetrieb.

## Zustimmung und Profilbindung

Der Core-Worker buddha_always_on darf die Reserve-Wiederaufnahme nur nach einer ausdrücklichen, versionierten persistent_opt_in-Änderung nutzen. Die Freigabe wird an einen Hash des ausführungsrelevanten Profils gebunden. Änderungen an diesem Profil über die Core-Slot- oder Core-Agent-Schreibpfade widerrufen die Freigabe und ihren Prüfcheckpoint. Änderungen an Status, Aktivität oder aktueller Aufgabenbindung ändern den Profilhash nicht und widerrufen die Freigabe daher nicht.

Die Wiederaufnahme nach local_reserve_reserve_wait_expired gilt nur für den laufenden, aktivierten buddha_always_on mit gültiger Freigabe, unverändertem Profilhash und lokalem Ollama-Ziel. Ein automatischer Modell-Fallback oder Downgrade ist für diese Recovery ausgeschlossen. Andere Worker, Cloud-Antworten und andere Fehlercodes erhalten diese lokale Wartebehandlung nicht.

## Ablauf und Grenzen

- Ein Reservefehler darf nur dann einen neuen Versuch auslösen, wenn die Werkzeugdispatch-Zahl eindeutig null ist. Bei unbekannter oder bereits erfolgter Werkzeugwirkung greift der bestehende Quarantänepfad.
- Der Task-Lease wird vor dem Warten zurückgegeben. Nach dem Warten muss die nächste Ausführung die aktuellen Richtlinien prüfen und einen frischen Task-Lease erwerben.
- Die Wartezeit ist begrenzt: höchstens drei Wiederaufnahmeversuche mit exponentiellen Intervallen ab 60 Sekunden und einem Gesamtbudget von 900 Sekunden.
- Dieses begrenzte Retry ist kein dauerhafter Always-On-Betrieb und startet den Worker nach einem Dienstneustart nicht automatisch neu; dieses Elternziel bleibt offen.
- Während der Wartezeit beendet ein Stop, eine deaktivierte oder abgelaufene Aufgabe, ein Statuswechsel, eine nicht lesbare Richtlinie oder eine Änderung der gebundenen Zustimmung die Wiederaufnahme.
- Fehler werden über eine endliche Liste neutraler reason_code-Werte projiziert. Roh-Ausnahmetexte und interne Pfade werden für lokale Reservefehler nicht als Aktivität gespeichert.
- resolved_model wird nur aus einer erfolgreichen aktuellen Antwort übernommen. Ein Slotwert oder Backendcache eines früheren Laufs ist kein Nachweis für das Modell dieses Laufs.

## Prüfgrenze

Die Regressionen verwenden isolierte synthetische Fixtures. Sie belegen weder eine native Aktivierung noch einen Modellstart, einen Pull oder eine reale Ressourcenfreigabe. Profil-, Reserve- und Laufzeitkonfigurationen bleiben außerhalb dieses Quellpakets unverändert.
