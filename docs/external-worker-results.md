# Externe Worker und kanonische Ergebnisabnahme

Status: Vertrag in Umsetzung. Der bestehende native Abschlussweg bleibt erhalten.
Die folgenden Grundlagen allein schließen noch keine externe Aufgabe ab.
Nativer Restauftrag: BACH #2339; Commit, Push, Integration und Live-Abnahme werden
jeweils gesondert belegt.

## Herkunft und Identität

Ein außerhalb von BACHs ChatRuntime ausgeführter Codex-/Claude-Turn ist keine
native BACH-Modellanfrage. Er erhält einen eigenen Belegtyp `external_attested`.
Plattform, Tenant, Account und Quellprincipal beschreiben die externe Herkunft.
Der **globale Modellprincipal** bleibt eine getrennte, ausdrücklich vom Operator
verwaltete Zuordnung. Ein weiteres Konto oder eine andere Plattform macht dasselbe
Modell nicht zu einem unabhängigen Reviewer. Native und externe Aliasse desselben
Modells müssen denselben globalen Modellprincipal verwenden.

`operator_checked_artifacts` bedeutet, dass ein authentisierter Operator reale
Herkunftsartefakte geprüft hat. Es behauptet keine kryptografische Bestätigung
durch den Modellanbieter. Ein vom Worker selbst geposteter Modellname oder Hash
reicht nicht. Die externe Zuordnung ist versioniert; Änderungen einer anderen
Quelle verändern die Bindung der eigenen unveränderten Quelle nicht.

Der globale Katalog umfasst bestehende native Principals und ausdrücklich
registrierte externe Modelle. `model_key` benennt das im Herkunftsartefakt
beobachtete Deployment; ein Anzeigename allein ist keine Identität. Wird ein
ausdrücklich registrierter Principal ohne verbleibende native Route entfernt,
bleibt seine ID dauerhaft stillgelegt. Weder erneutes Registrieren noch eine
neue native Aliaszuordnung darf alte externe Bindungen dadurch wiederbeleben.
Für ein anderes Modell ist eine neue globale Principal-ID erforderlich.
Auch das Entfernen der letzten nativen Route legt den Principal atomar still,
sofern er nicht ausdrücklich im globalen Katalog aktiv gehalten wird. Eine
vorübergehende Änderung der Routen muss deshalb die globale Identität erhalten.

## Private Artefakte

`worker_external_evidence` speichert tatsächliche Bytes in einem privaten,
unveränderlichen Datenbankbestand und berechnet den SHA-256 selbst. Maximal
2 MiB je Artefakt; unterstützt sind JSON, JSONL und Klartext. Die Speicherung
verlangt eine bestehende gesonderte Task-Result-Operatorberechtigung. Allgemeine
Geräteanmeldung oder Workerzugriff genügt nicht. Keine Zugangsdaten importieren.

Artefaktinhalt, Pfade und private Referenzen gehören nicht in öffentliche
Task-/Result-DTOs. Ein Inhaltsabruf verlangt erneut die Operatorberechtigung.
Speicherung eines Artefakts attestiert noch keine Herkunft und erteilt keine Abnahme.

## Implementierter Belegkern

`worker_external_attestation` bietet den gesonderten Writer, DB-/History-Reader
und die aktuelle Scope-Projektion. Der Writer bindet Task-/Result-ID, Hash,
Fence, Generation, Taskversion, Status-, Submissionrevision und beide
Submission-Ereignisse. Ein eigenes privates Ergebnisartefakt muss bytegenau
mit dem vollständigen Result übereinstimmen. Für die Operatorprüfung der
Herkunft werden getrennte private Quellartefakte verlangt.

Git und Sperren werden über `snapshot_task_scope` außerhalb der
SQLite-Transaktion geprüft. Unter `BEGIN IMMEDIATE` werden anschließend
Operator, freie Lease, aktuelle Task-/Resultrevision, Identitätsbindung und
die tatsächlichen Artefaktbytes erneut geprüft. Zwei eigene History-Ereignisse
binden den externen Herkunfts- und Scope-Beleg. BACH setzt die heutige
Attestierungszeit; eine externe Quellzeit bleibt separat ausgewiesen.

Die eindeutige Kombination Plattform/Tenant/Account/Run/Turn gilt über alle
Tasks hinweg. Identische Wiederholung erzeugt bei unverändertem Scope keine
weiteren Events; ein anderer Beleg für dasselbe Result oder dieselbe Run-/Turn-
Kombination ist ein Konflikt. Bereits verknüpfte native Modellbelege können
auch bei beschädigter nativer Receipt nicht extern überschrieben werden.

Der Reader prüft Identitätsbindung, Artefaktbytes, Hashes, Events und aktuelle
Operatorgültigkeit neu. Ein Widerruf erhält die Historie, sperrt aber ihre
Verwendung zur Abnahme. Die öffentliche Projektion zeigt keine privaten
Artefakt-, Account-, Tenant-, Run-/Turn-IDs oder Dateipfade. Erst ein erneuter
Git-Vergleich erzeugt die eigene externe Ergebnisrevision. Diese Projektion
ist ausschließlich mit Daten des vertrauenswürdigen DB-Readers aufzurufen.

Dieser Kern ist noch kein über API/SDK nutzbarer Abschlussweg und erteilt
keine Abnahme. Dafür fehlen die nachfolgenden Integrationsschritte.

## Noch zu integrierender Abschlussweg

1. Result-Readback, Completion-Policy und unabhängigen Review explizit um
   diese Herkunft erweitern. Reviewer-Child führt weiter eine tatsächliche
   belegte Modellausführung aus; Modellunabhängigkeit nutzt globale Principals.
   Vor jeder Abschlussentscheidung alle aktuellen DB-Abhängigkeiten per CAS
   erneut prüfen. Die native `execution_revision` bleibt getrennt.
2. API/SDK/CLI und Ergebnisanzeige integrieren, einschließlich Operatorauth,
   strikter Payloads, Replay-/CAS-/Revokationsfällen und echter Live-Abnahme.

Frühere Ergebnisse lassen sich nur mit real vorhandenen, nachvollziehbar zum
Result passenden Artefakten neu revalidieren. Die neue Revision ist heute
attestiert; sie erfindet weder einen früheren Modelllauf noch einen früheren
Scope-Beleg. Unabhängiger Review und normale Akzeptanzentscheidung bleiben nötig.
