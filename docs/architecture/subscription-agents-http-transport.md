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

Der BACH-Server bindet den bestehenden Router im Quellstand ein. Der statische
Seitenpfad `/agenten/subscription-agents` liefert ausschließlich die installierte
gemeinsame GUI-Seite; fehlende oder verlinkte Seiten bleiben mit 503 gesperrt.
Die Quellintegration verwendet:

```python
from gui.api.subscription_agents_transport import router as subscription_agents_transport_router
app.include_router(subscription_agents_transport_router)
```

Die fokussierten Mounttests verwenden die tatsächliche BACH-ASGI-App samt
Host-, Origin- und Geräte-Middleware mit temporären synthetischen Daten. Sie
prüfen Bearer- und Cookie-Zugriff, Ablehnungen vor Body-/Composer-Aufruf und
den statischen Seitenpfad ohne Legacy-Fallback. Der dienststartende Lifespan
läuft dabei nicht. Das belegt keinen produktiven Dienststart, keine echte
Geräteanmeldung, keine ASUS-Zwischenablage und keine Ocean-Anbindung.

Die Capability-Projektion verlangt für diese Seite den registrierten
`POST /api/agent-studio/subscription-agents/compose`, keinen erfundenen
GET-Endpunkt. Routepräsenz bleibt von Runtime- und Nutzerabnahme getrennt.

Composer und HTTP-Adapter aus PR #318 sind bereits in BACH-main enthalten.
Der Servermount verwendet diese vorhandenen Komponenten; er kopiert weder
Composer noch Blueprint- oder Skillbibliothek.
