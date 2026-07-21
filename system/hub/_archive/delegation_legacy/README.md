# Legacy delegation fallback

Diese Module sind der archivierte BACH-interne Clutch-Fork. Der produktive
Einstiegspunkt bleibt `hub/_services/delegation/__init__.py`; er nutzt das
externe `clutch`-Package und greift nur bei explizit deaktivierter oder nicht
verfügbarer externer Anbindung auf diese archivierten Module zurück.

Archiviert am 2026-07-21 nach mindestens einer Woche grünem Parallelbetrieb
und grünen BACH-Clutch-/Partner-Regressionssuiten. Nicht als neue
Implementierungsquelle weiterentwickeln.
