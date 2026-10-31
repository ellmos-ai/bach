# MemoryHook-Opt-in aus nativer Konfiguration (#2006)

## Konfigurationsvertrag

Diese Änderung speichert die ausdrückliche Einstellung `memory_hook_opt_in`. Der Standard ist `false`. Alte Core- und Workerprofile ohne das Feld werden als `false` gelesen. Ein gespeicherter Wert, der kein JSON-Boolean (`true` oder `false`) ist, wird abgelehnt.

Core-Agenten werden über `change_core_system_agent` mit `configuration_version` geändert. Der Reset setzt das Feld auf `false` zurück. Für dynamische Worker wird es nach der Erstellung über `change_worker_configuration` mit dessen Konfigurationsversion gesetzt. Der Workerstatus-Adapter projiziert das Feld als Boolean und übergibt Änderungen an denselben CAS-Vertrag. Der allgemeine Laufzeit-`update_slot`-Pfad und die Worker-Erstellung akzeptieren das Feld nicht; damit lässt es sich nicht aus einem Prompt, Tasktext, einer Persona oder einem Toolaufruf ableiten.

Die Konfigurationsversionen binden das Feld ein. CAS-Konflikte, Status- und Ablaufprüfungen sowie bestehende Werkzeugfreigaben und Rundenbudgets bleiben wirksam. Das Feld erteilt keine zusätzlichen Toolrechte.

## Laufzeitverhalten

Der bestehende MemoryHook bleibt die einzige Kontextquelle. Bei einem ausdrücklich aktivierten nativen Core- oder dynamischen Workerprofil fügt `chat_runtime.py` den Hook-Kontext genau einmal nach Persona und Systemprompt ein. Die Laufzeit liest dafür ausschließlich das verifizierte Slotprofil; Werte aus Usernachrichten, Persona, Tasktext, Toolausgaben oder beliebigen Requestfeldern können das Opt-in nicht setzen.

Für Profile und benutzerdefinierte Prompts ist das Opt-in standardmäßig aus. Fehlt das Opt-in-Feld in einem gültigen nativen Slotprofil, wird es aus Gründen der Rückwärtskompatibilität als `false` gelesen. Ein vorhandener Wert ohne Boolean-Typ sowie ein fehlender, nicht lesbarer, deaktivierter oder nicht zur Bindung passender nativer Slot stoppen den Turn fail-closed vor Hook und Modell. Chats ohne Profilbindung und ohne benutzerdefinierten Prompt behalten das bisherige Legacy-Verhalten des MemoryHooks.

Die Konfiguration gibt keine zusätzlichen Werkzeugrechte frei und ändert weder Taskbindung noch Rundenbudget. Sie führt keinen neuen Provider und keine zweite Memory- oder Taskdatenbank ein.

## Prüfgrenze

Die Konfigurations- und Laufzeitregressionen verwenden isolierte Konfigurationsdateien, Chatstores und Backend-Transporte. `test_memory_hook_runtime_opt_in.py` ersetzt den bestehenden Hook-Kontext-Seam durch einen Zähler, um Aufrufzahl und Position im Prompt zu prüfen; dabei starten weder MemoryHook-Provider noch Modell.

Der zusätzliche Testpfad in `test_learning_reuse_empirical.py` verwendet dagegen den echten `ExternalMemoryHook` mit einer synthetischen isolierten Datenbank und einem Recording-Backend. Er prüft den Transport einer synthetischen Erinnerung bis in den Prompt und ruft kein Modell auf. Der vorhandene Testaufbau allein belegt keinen erfolgreichen Lauf. Auch ein erfolgreicher isolierter Lauf wäre weder eine Produktionsaktivierung noch ein gemessener Modell- oder Qualitätsgewinn.

Schreibende Konfigurations- und Promotion-Fixtures benötigen einen konfigurierten kanonischen Lock-Scanner und einen bestätigten vollständigen Lock-Status. Fehlt dieser Nachweis, wird der Schreibzugriff verweigert; ein solcher Testabbruch ist kein erfolgreicher Anschlussnachweis.
