# Cloud429 nach interner Retry-Erschöpfung — Task #2433

Der bestehende ChatRuntime-Pfad meldet nach internen 429-Versuchen `cloud_call_retry_exhausted` an FailedAnswer. Die äußere Cloud-Warte verlangte einen leeren Reason-Code und beendete deshalb den Worker, obwohl HTTP429 und Anbieteridentität erhalten blieben.

Die äußere Warte akzeptiert jetzt zusätzlich genau diesen Reason-Code. Die vorhandenen Bedingungen bleiben: normalisierter 429-/rate_limited-Fehler, Cloudprovider, continuous/persistent-Profil. Andere Fehlercodes und lokale Ressourcenregeln bleiben unverändert. Der bestehende Supervisor-Close und bestätigte native Lease-Return vor der Wartephase bleiben verpflichtend. Keine zusätzlichen Toolreplays, feste Taskzuweisung oder Prüfquarantäne.

Quellenprüfung: Python-AST und git diff --check, keine Tests hinzugefügt oder manuell ausgeführt. Exakte unabhängige Review, Veröffentlichung, Mac-Aktivierung und tatsächlicher leasefreier Cooldown werden separat belegt. Gestapelt auf dem aktiven 9f481597-Stand einschließlich des zielbezogenen Konfigurationsguards. Ressourcen-/Fackelarbeit für Buddha bleibt in #2330/#2333/#2334 offen.
