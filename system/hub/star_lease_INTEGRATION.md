# Star Lease Integration

## Grundregel
Die Stern-Lease-Integration folgt einer Kern-Grundregel, die sicherstellt, dass Sperren korrekt angewendet werden und freigegeben werden, auch wenn Operationen fehlschlagen.

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
- Dient als indikation eines Konflikts; das System sollte die Operation erneut versuchen oder ablehnen, ohne die Lease zu ändern.

### LeaseUnavailableError (`[UNAVAILABLE]`)
- Sollte **nicht** mutiert oder in der ersten Acquisition-Methode abgebrochen werden.
- Kann bei Bedarf wiederholt werden (z.新しい BACH-Scan oder erneute Versuche), bis die Lease verfügbar wird.

### LeaseViolation (`[VIOLATION]`)
- Sollte **nur geloggt** werden und nicht mutiert oder abgebrochen.
- Zeigt an, dass eine bereits bestehende Lease verletzt wurde; das System sollte die Lease protokollieren und möglicherweise die Operation ablehnen, ohne den Zustand zu ändern.

## Integration in `writer.py` (bc57916)

Die Integration wählt die folgenden Punkte aus `writer.py` aus (Positionen in der Quelle):

- `:31` – **Behalte `MUTATION_LOCK` als `threading.RLock`** bei, um eine erneute Acquisition durch denselben Thread zu ermöglichen.
- **Stern-Lease** wird als **zweite, prozessübergreifende Schicht** hinzugefügt. Die Reihenfolge ist **zuerst `MUTATION_LOCK` und dann die Stern-Lease** (um sicherzustellen, dass die Prozess-Sperre nach der Thread-Ebene gehalten wird).
- **`:753-776` – `write_lock` / `release_lock` Methoden verwenden den **globalen `_ACTIVE_LEASE`**, um die Lease-Akquisition zu koordinieren.**
- **`:568` – `decide_entry`** und **`:369` – `undo_decision`** berücksichtigen die Lease-Zuordnung und kehren zurück / rollen back, wenn die Lease nicht gehalten wird.
- **`:778-783` – `_guard`** führt die endgültige Lease-Validierung durch, bevor die Mutation erlaubt wird.

### Modul-Parameter
Die Konfiguration für die Integration lautet:

```python
DEFAULT_TTL = 30.0          # Standardgültigkeitsdauer der Lease in Sekunden
MAX_ACQUIRE_ATTEMPTS = 3    # Maximale Versuche, um eine Lease zu erwerben (mit Exponential Backoff)
```

## Hinweise für Polarstern-Freigabe
Diese Integration ist **blockiert**, bis Polarstern seine Freigabe bestätigt hat. Nach der Freigabe:

1. Stelle sicher, dass die `star_lease_INTEGRATION.md`-Datei im `system/hub/`-Verzeichnis vorhanden ist.
2. Führe den vollständigen Test-Satz (`system/tests/test_star_lease.py`) aus, um sicherzustellen, dass alle 12 Tests grün sind.
3. Führe einen endgültigen `pytest`-Lauf über `system/tests/test_star_lease.py` aus und behalte die Ergebnisse bei.
4. Wenn die Tests erfolgreich sind, vervollständige den Task mit `finish_task` und hinterlasse eine PR-Beschreibung, die auf diese Integration verweist.

## Haftungsausschluss
Alle Änderungen, die in `writer.py` vorgenommen werden, müssen in der Reihenfolge vorgenommen werden, die `MUTATATION_LOCK` vor der Lease-Anwendung respektiert. Das Ignorieren dieser Reihenfolge kann zu Deadlocks oder inkonsistenten Zuständen führen.

---
*Erstellt gemäß der Aufgabenbeschreibung für Task #3746*.
