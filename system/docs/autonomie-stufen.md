# Autonomiestufen je Bereich

Stand: Task #2559. Das Autoritätssystem von BACH/Ocean trägt die Autonomiestufe
je Bereich als *einstellbare Regel* und setzt sie durch. Es gibt kein
Parallelsystem: `delegation_authority`, `agents_heart` und `automation_master`
greifen auf dieselben Daten zu.

## Stufen

| Stufe | Verhalten | Rueckfrage | Ticket | `direct_order` | `inform` |
|---|---|---|---|---|---|
| `manuell` (Default) | Jede Aktion braucht Freigabe | ja | ja | nein | ja |
| `teilautomatisch` | Handeln erlaubt, Grenze bei Aussenwirkung; bei direktem Auftrag ohne Rueckfrage | nein | nein | ja | nein |
| `vollautomatisch` | Handeln und informieren statt Genehmigung | nein | nein | ja | ja |

Unbekannte oder fehlende Werte werden auf `manuell` normalisiert
(`DEFAULT_AUTONOMY_LEVEL`). Eine unbekannte Stufe fuehrt nie zu mehr Rechten.

## Bausteine

- `system/delegation_authority.py`
  - `AUTONOMY_LEVELS`, `DEFAULT_AUTONOMY_LEVEL`
  - `evaluate_permission(...)` – Entscheidung inkl. Ticket-/Informationsbedarf
- `system/agents_heart.py`
  - laedt Bereiche aus dem Dateisystem, registriert sie und setzt `manuell` als Default
  - `effective_autonomy_levels()` – effektive Stufe je Bereich
  - `evaluate_permission_for_area(area, ...)` – bereichsbezogene Rechtepruefung
- `system/automation_master.py`
  - persistente Konfiguration `system/_state/areas_autonomy.json`
  - `register_areas` (idempotent), `set_autonomy` (validiert Bereich und Stufe),
    `get_autonomy`, `enable_test_mode`, `record_metric`, `set_budget`, `use_budget`

## Testmodus und Messung

`test_mode` erlaubt das Durchspielen von Stufen ohne Aussenwirkung. `metrics`
zaehlt Qualitaet, Fehler und Eingriffe je Bereich; `budgets` /
`spending_areas` begrenzen Bereiche, in denen Geld fliesst (z. B. Marketing).

## Rangfolge

Der Chat mit Lukas hat hoehere Autoritaet als diese Testregeln. Das
Autoritaetssystem wird durch Autonomiestufen nicht untergraben: eine Stufe wird
nur wirksam, wenn sie als Einstellung eingetragen und durchgesetzt wird.

## Tests

`system/tests/test_delegation_autonomy.py` prueft alle drei Stufen in
`evaluate_permission`, die Bereichsermittlung in `agents_heart` sowie
Registrierung, Validierung und Persistenz in `automation_master`
(Temp-Konfiguration je Test, keine Schreibzugriffe auf den Live-Zustand).
