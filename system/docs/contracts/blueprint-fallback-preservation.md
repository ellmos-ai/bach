# Blueprint → Living: Modell-Fallbacks

## SOLL

GUI-Auswahl, Materialisierung und unabhängiger Profil-Readback erhalten dieselbe
geordnete Modellkette. Eine Vorlage, eine gespeicherte Instanz und ein tatsächlicher
Lauf bleiben unterschiedliche Zustände. Der kombinierte GUI-/Backendnachweis und
die installierte Hostabnahme stehen noch aus.

## IST: bestehender Vertrag im Backend

`execution.model_fallbacks` ist eine geordnete JSON-Liste. Jedes Ziel enthält genau
`backend` und `model`. Die vorhandenen Validatoren in `slots_config` prüfen
Anbieter, Modellformat, Duplikate, Wiederholung des Primärziels sowie die bestehenden
Ollama-Cloud- und OpenRouter-Free-Grenzen. Die Materialisierung verwendet diese
Validatoren; sie erfindet keine neue Auswahl- oder Modellpolicy.

- Bei einer neuen Instanz bedeutet ein ausgelassenes Feld die native leere Kette.
- Bei einer bestehenden Instanz behält ein ausgelassenes Feld die gespeicherte Kette.
- Eine ausdrücklich übergebene leere Liste löscht die Kette bewusst.
- Eine übergebene Liste behält ihre Reihenfolge. Es gibt keine stille Sortierung,
  Deduplizierung oder Ersetzung durch andere Defaults.

Auch wenn nur das Primärziel geändert wird, validiert der native Materialisierer
das vollständige resultierende Profil unter seiner bestehenden Eigentümersperre
und Konfigurations-CAS. Die vom vorhandenen Profilvalidator zurückgegebene Kette
wird vor Reconciliation und Speicherung gesetzt. Ungültige Kombinationen werden
abgewiesen, bevor Profilbytes oder Modellbindungen verändert werden.

Blueprint-Version, Konfigurationsversion und Terminalprüfung bestehender Instanzen
bleiben unverändert erforderlich. CAS- und Validierungsfehler behalten ihre
bisherige Bedeutung. Eine Materialisierung startet keinen Provider und bestätigt
weiterhin `worker_started: false`.

## Readback und Liefergrenze

Der native `core_system_agents_snapshot` liefert `backend`, `model` und die gesamte
`model_fallbacks`-Liste. Die vorhandene Materialisierungs-HTTP-Route liest die
Instanz danach erneut und liefert sie in `instance`; ein unabhängiger GET über
den bestehenden Core-Agentenvertrag kann dieselbe Konfigurationsversion und die
vollständige Kette prüfen. Das Antwortschema wird dafür nicht erweitert.

Die synthetischen Backendtests decken lokale, Cloud-, Subscription- und API-Profile,
Neuinstanz, Aktualisierung, Auslassung, bewusstes Leeren, ungültige Ketten,
Primärwechsel und bestehende CAS-/Terminalfehler ab. Sie verwenden ausschließlich
temporäre Stores und starten keine Modelle. Das ist keine Bestätigung realer
Anbieterwechsel, kein vollständiger Agentendispatch und keine Gesamt-P10-Abnahme.
