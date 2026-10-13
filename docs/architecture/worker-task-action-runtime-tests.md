# Runtime-/Trace-Tests für Taskaktionen

Die deterministischen Lease-Unit-Fixtures verwenden eine eingefrorene Uhr. Der echte Tool-Trace-Start validiert dagegen an der kanonischen Authority mit deren aktueller UTC-Uhr. Ein alter Unit-Lease belegt daher keinen aktuellen Runtime-Durchlauf.

Der Runtime-/Handoff-Test verwendet eine separate, vollständig isolierte In-Memory-TaskDB und erwirbt seine Lease ohne eingefrorene Uhr. Die bisherigen Unit-Fixtures bleiben erhalten. Es werden weder produktive Daten noch Runtime-Zeitprüfungen geändert.

Eine zusätzliche Negativkontrolle simuliert eine abgelaufene Lease an der Trace-Authority: Kein Trace-Start, keine Taskmutation, kein Tooldispatch und keine Ergebnisabgabe dürfen daraus entstehen. Die Fähigkeit des lokalen Callers ersetzt den kanonischen Nachweis nicht.

Dieser Testvertrag belegt die isolierten Runtime-/Binding-Pfade. Native Providerinferenz, Installation und produktive Ergebnisqualität benötigen eigene Belege.

## Adapter- und Runtime-Seam

Die Runtime erhält normalisierte Dictionaries in tool_calls[*].function.arguments. Die ursprüngliche Wire-Antwort kann in raw_message weiterhin JSON-Strings enthalten. Der Runtime-Test trennt beide Formen; ein zusätzlicher Test führt die echte OpenAI-Adapter-Normalisierung mit einem isolierten HTTP-Double aus. Die strikte Dictionary-Prüfung am Trace-Dispatch bleibt erhalten. Ein synthetisches Backend darf Wire-JSON nicht als bereits normalisierten Runtime-Aufruf ausgeben.
