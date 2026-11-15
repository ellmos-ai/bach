# Star Lease Integration

## Grundregel
Die Stern-Lease-Integration folgt einer Kern-Grundregel: Sperren werden in fester Reihenfolge erworben und in jedem Fall wieder freigegeben, auch wenn die Operation fehlschlägt.

```python
acquire():
    try:
        # Warten auf einen Fence (Vorschub) VOR der Mutation
        check_fence()
        # Führe die Mutation durch
        mutate()
    finally:
        # Freigabe der Lease nach der Mutation (oder bei einem Fehler)
        release()
```

## Fehlerklassen

### LeaseDeniedError (`[CONFLICT]`)
- Sollte **nicht** mutiert oder abgebrochen werden.
- Dient als Indikation eines Konflikts; das System sollte die Operation erneut versuchen oder ablehnen, ohne die Lease zu ändern.

### LeaseUnavailableError (`[UNAVAILABLE]`)
- Sollte **nicht** mutiert oder in der ersten Acquisition-Methode abgebrochen werden.
- Kann bei Bedarf wiederholt werden (erneuter BACH-Scan oder erneute Versuche), bis die Lease verfügbar wird.

### LeaseViolation (`[VIOLATION]`)
- Sollte **nur geloggt** werden und nicht mutiert oder abgebrochen.
- Zeigt an, dass eine bereits bestehende Lease verletzt wurde; das System sollte die Lease protokollieren und möglicherweise die Operation ablehnen, ohne den Zustand zu ändern.

## Reale Lease-API: `system/hub/lease.py`

Die verbindliche Implementierung liegt in `system/hub/lease.py` (Polaris-Lease, CLI-basiert). Verfügbare Aktionen:

| Aktion | Aufruf |
| --- | --- |
| Status | `status` |
| Erwerb | `acquire --by <agent@host> [--ttl POLARIS] [--intent T] [--version <sha256>] [--show-capability]` |
| Verlängern | `renew --lease-id <uuid> --fence <n> [--version]` |
| Freigeben | `release --lease-id <uuid> --fence <n> [--version]` |
| Registrieren | `register` (nur Lead-Authority) |

Belegstellen in `system/hub/lease.py`:
- `:105` – Erfolgsausgabe `[OWN POLARIS STAR CONFIRMED]` nach bestätigtem Erwerb.
- `:115-117` – Acquire-Antwort enthält Fence, Profil und `renew_after_seconds`.
- `:137` – `from hub._services.resource_lease import register_resource` (Registrierung der Resource-Lease).

Ein `LeaseManager` als Python-Klasse existiert in diesem Baum **nicht**; die Lease wird ausschließlich über die oben genannten CLI-Aktionen angesprochen.

## Einbindung in einen schreibenden Prozess

Die Einbindung folgt zwei Schichten, in dieser Reihenfolge:

1. **`MUTATION_LOCK` als `threading.RLock`** – prozessintern, erlaubt erneuten Erwerb durch denselben Thread.
2. **Stern-Lease** – prozessübergreifend, wird **nach** dem `MUTATION_LOCK` erworben.

Damit ist die Prozess-Sperre erst nach der Thread-Ebene gehalten. Empfohlenes Muster:

```python
with MUTATION_LOCK:                 # Ebene 1: Thread
    lease = acquire(...)            # Ebene 2: Prozess (lease.py acquire)
    try:
        check_fence()               # Fence VOR der Mutation prüfen
        mutate()
    finally:
        release(lease)              # immer freigeben, auch im Fehlerfall
```

### Modul-Parameter
```python
DEFAULT_TTL = 30.0          # Standardgültigkeitsdauer der Lease in Sekunden
MAX_ACQUIRE_ATTEMPTS = 3    # Maximale Versuche, um eine Lease zu erwerben (mit Exponential Backoff)
```

## Abgrenzung: nicht Bestandteil dieses Baums

Die folgenden Artefakte existieren im BACH-Baum **nicht** und werden hier nicht vorausgesetzt:

- `system/hub/star_lease.py` – nicht vorhanden. Ein Import wie `from star_lease import LeaseManager` ist damit nicht lauffähig.
- `system/tests/test_star_lease.py` – nicht vorhanden; ein `pytest`-Lauf auf dieser Datei ist derzeit nicht möglich.
- `writer.py` im Wurzelverzeichnis des Arbeitsbaums – kein Bestandteil des BACH-Baums (kein Pfad unter `system/hub/`). Die dortigen Zeilenverweise (`:31`, `:369`, `:568`, `:753-776`, `:778-783`) sind externe, hier nicht verifizierbare Angaben und daher nur als Orientierung zu lesen.

## Freigabestatus

Eine formale Freigabe durch Polarstern steht aus; sie ist **nicht Teil dieses Tasks**. Diese Dokumentation ist inhaltlich eigenständig nutzbar und blockiert keine weitere Arbeit.

## Haftungsausschluss

Alle Änderungen an schreibenden Komponenten müssen die Reihenfolge einhalten, die `MUTATION_LOCK` vor der Lease-Anwendung respektiert. Das Ignorieren dieser Reihenfolge kann zu Deadlocks oder inkonsistenten Zuständen führen.

---
*Erstellt gemäß der Aufgabenbeschreibung für Task #3746*
