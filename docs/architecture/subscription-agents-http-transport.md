# HTTP-Transport für Subscription-Agent-Vorschauen

## Vertrag

Der neue Router stellt `POST /api/agent-studio/subscription-agents/compose`
bereit. Er verwendet denselben `SubscriptionAgentsComposer` wie der vorhandene
`bach subscription_agents compose <Request-JSON-Datei>`-Handler. Der HTTP-Adapter
legt weder einen zweiten Composer noch einen zusätzlichen Speicher an.

Die Anfrage muss das vorhandene Schema
`bach.subscription-agent-onboarding.request.v1` verwenden. Der Adapter akzeptiert
nur `application/json`, liest den Request gestreamt bis zum vorhandenen Limit von
256 KiB, lehnt doppelte JSON-Felder ab und übergibt das Objekt anschließend an
die bestehende Composer-Validierung.

Vor dem Body-Read und vor jedem Quellreader prüft der Adapter mit dem vorhandenen
read-only Device-Token-Helper, ob ein aktives Gerät registriert ist. Fehlende,
ungültige oder widerrufene Tokens erhalten keine Vorschau. Das Token wird weder
in Antworten noch in Fehlertexten ausgegeben. Die Capability-Projektion ist eine
Beschreibung von Routenmetadaten und keine Autorisierungsquelle.

Composer- und Parserfehler werden auf feste Fehlercodes abgebildet. Interne
Ausnahmen, Request-Inhalte, Secrets und Rohtexte gelangen nicht in HTTP-Fehler.
Ein unbekanntes, syntaktisch gültiges `target_client` bleibt ausschließlich
angezeigte Eingabe. Es wird dadurch kein vertrauenswürdiger oder ausführbarer
Client registriert.

## Grenzen

Die Antwort enthält einen Promptentwurf, Quellenprojektionen und den
`ready_for_review`- oder `needs_sources`-Status des vorhandenen Composers.
Governance-Durchsetzung ist nicht bestätigt. Der Transport startet keinen Agenten,
claimt keine Aufgabe, durchsucht keine Queue und schreibt nicht in die
Zwischenablage. Die aktive Geräteanmeldung gibt nur Zugang zu dieser Vorschau;
Prompt- oder Capabilitytexte vergeben keine zusätzlichen Rechte.

Die Regressionen verwenden eine temporäre SQLite-Datei mit synthetischen
Device- und Blueprint-Zeilen. Blueprint- und Skillreader sowie der Composer sind
die bestehenden Implementierungen; die Policy-Registry ist in den Tests
ausdrücklich deaktiviert, sodass ihre fehlenden Einträge als `needs_sources`
erscheinen. Die Tests belegen keine produktive Geräte-, Browser- oder
Governance-Aktivierung.

Der bestehende Device-Helper akzeptiert neben einem Bearer-Token auch das
`bach_device_token`-Cookie. Ob Browser dieses Cookie beim tatsächlich
gemounteten Router mitsenden und wie Origin-/Middleware-Regeln wirken, ist hier
nicht geprüft. Cookie- und Origin-Verhalten bleiben bis zum echten Mount offen.

## Integrations-Handoff

Der Router ist bewusst noch nicht in `system/gui/server.py` eingebunden. Der
zuständige Server-Writer kann nach eigener Scope- und Lockprüfung im statischen
Routerblock ergänzen:

```python
from gui.api.subscription_agents_transport import router as subscription_agents_transport_router
app.include_router(subscription_agents_transport_router)
```

Bis zu dieser Integration ist die Route nicht über den produktiven GUI-Server
erreichbar. Für den späteren Browseraufruf bleiben Mount, Middleware-/Origin-
Verhalten und echte Geräteabnahme separat zu prüfen.

Der Adapter ist auf PR #318 mit dem Composer-Head
`2d0838f55f349e13cc09d540792792b377c555a6` gestapelt. Dieser Folge-PR benötigt
den vorhandenen Composer-Vertrag; er enthält keine Kopie seiner Implementierung.
