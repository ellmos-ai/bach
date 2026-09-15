# OC-B: Verifizierter Start- und Stop-Vertrag

Stand: 2026-09-15. Entwurf für `BACH-AGENT-PID-01` und den eigenständigen `agent-launcher`-Seam. **Kein erfülltes Release-Gate.**

## Bestätigter Fehlerpfad

`system/hub/agent_launcher.py::_start_agent` startet den Runner mit `subprocess.Popen`, liest erst danach `process_create_time` und schreibt bei fehlender Erfassung eine PID-Datei mit `null`. Das Ergebnis meldet `running=false`, obwohl der Runner bereits laufen kann. Windows startet zunächst `cmd /c start.bat`; dieser kann den eigentlichen Provider schon als Kind gestartet haben. Unix startet den Provider direkt. Der bestehende Test `test_agent_start_reports_unverified_if_birth_time_capture_fails` beweist nur die Fehlermeldung und den erhaltenen Beleg, **nicht** das Ausbleiben eines laufenden Providers.

## Invarianten vor Opt-in

1. **Gesperrter Spawn:** Der Provider darf erst nach erfolgreichem exklusivem Namens-Claim, erfasstem Prozessanker und dauerhaft geschriebenem Startbeleg ausgeführt werden. Ein eindeutiger, einmaliger Freigabe-Handshake verhindert einen vorzeitigen Provider-Start. Fehlschlag oder Timeout vor der Freigabe beendet den noch providerlosen Starter; der Beleg bleibt zur Nachzertifizierung erhalten, falls dessen Ende nicht bestätigt ist.
2. **Eigentum statt nackter PID:** Jede Stop-Aktion benötigt einen vom Betriebssystem gehaltenen Bezug zum ursprünglichen Prozess oder einen nachweisbar kontrollierten Supervisor. Eine bloße Kombination aus PID und Geburtszeit, gefolgt von einem numerischen Signal, schließt die Wiederverwendungs-Race nicht aus. Auf Windows muss ein Prozess-Handle beziehungsweise ein Job-Objekt die Zielidentität und den Prozessbaum halten; für Unix sind die jeweiligen Plattformprimitive oder ein Supervisor-Protokoll zu belegen. Nicht unterstützte Hosts bleiben fail-closed.
3. **Baum-Abschluss:** Stop erfasst nicht nur eine Kind-Momentaufnahme. Kein Beleg darf als erfolgreich gestoppt entfernt werden, bis Supervisor/Job und alle zugeordneten Prozesse nachweislich beendet sind. Detached/reparented Kinder sind als expliziter Testfall zu behandeln; wenn sie nicht kontrolliert werden können, bleibt der Stop unbestätigt.
4. **Status ist read-only:** Ungültige, alte oder abweichende Belege werden weder durch Status noch Dry-run gelöscht. Dateiname, technischer Name, PID und Prozessanker müssen übereinstimmen. Parallele Start-/Stop-Versuche müssen unter demselben Claim serialisiert sein.

## Prüfmatrix

| Fall | Erwarteter Nachweis |
| --- | --- |
| Birth-Erfassung schlägt fehl | Kein Provider startet; Starter-Ende wird bestätigt oder Beleg bleibt `unverified` und Opt-in gesperrt. |
| Start gegen Start / Start gegen Stop | Höchstens ein Besitzer und kein Beleg-Overwrite; reproduzierbarer Nebenläufigkeitstest. |
| PID wiederverwendet / Altbeleg | Weder Status noch Dry-run noch Stop senden ein Signal; Beleg bleibt sichtbar. |
| Provider erzeugt Kinder, auch verzögert/detached | Stop-Abschluss erst nach belegtem Baum-Ende, sonst Fehler mit erhaltenem Beleg. |
| Windows, Linux, macOS | Host-spezifischer Test des tatsächlichen OS-Bezugs; Mock-Tests allein reichen nicht für den Sicherheitsclaim. |
| BACH ↔ eigenständiges Modul ↔ Ocean | Gleicher Start-/Stop-Vertrag; echter Host-Smoke und Paritätsprüfung vor Merge/Release. |

Die Umsetzung muss den gegenwärtigen direkten Provider-Spawn ersetzen, nicht nur den Zeitraum zwischen `Popen` und Birth-Abfrage verkürzen. Lokale Ollama-Modelle sind kein Prüfmittel für dieses Gate.
