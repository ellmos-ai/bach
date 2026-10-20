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

## Noch zu integrierender Abschlussweg

1. Aktuelle Task-/Result-ID, Hash, Fence, Generation, Taskversion,
   Statusrevision, Submissionrevision und Ereignis-ID vollständig binden.
2. Scope über den vorhandenen vertrauenswürdigen Git-/Lock-Scanner außerhalb
   der DB-Schreibtransaktion neu prüfen. Keine Clientpfade oder fingierten
   historischen Snapshots übernehmen.
3. Operatorberechtigung, Identitätsbindung, Task-/Result-CAS und freie Lease
   unter `BEGIN IMMEDIATE` erneut prüfen; eigene externe Herkunfts- und
   Scope-Ereignisse unveränderlich aufzeichnen. BACH setzt die heutige Zeit;
   eine Quellzeit bleibt separat ausgewiesen.
4. Plattform/Tenant/Account/Run/Turn global gegen Wiederverwendung sperren.
   Identische unveränderte Wiederholung ist idempotent, ein abweichender
   Zweitbeleg ein Konflikt.
5. Eine eigene externe Ergebnisrevision aus Submission, externem Beleg und
   Scope berechnen; aktuelles Git erneut projizieren. Die native
   `execution_revision` bleibt davon getrennt.
6. Result-Readback, Completion-Policy und unabhängigen Review explizit um
   diese Herkunft erweitern. Reviewer-Child führt weiter eine tatsächliche
   belegte Modellausführung aus; Modellunabhängigkeit nutzt globale Principals.
7. API/SDK/CLI und Ergebnisanzeige integrieren, einschließlich Operatorauth,
   strikter Payloads, Replay-/CAS-/Revokationsfällen und echter Live-Abnahme.

Frühere Ergebnisse lassen sich nur mit real vorhandenen, nachvollziehbar zum
Result passenden Artefakten neu revalidieren. Die neue Revision ist heute
attestiert; sie erfindet weder einen früheren Modelllauf noch einen früheren
Scope-Beleg. Unabhängiger Review und normale Akzeptanzentscheidung bleiben nötig.
