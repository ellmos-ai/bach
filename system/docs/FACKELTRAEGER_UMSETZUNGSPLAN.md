# Fackelträger-System – Umsetzungsplan

> Stand: 2026-10-01 · Task #1583 · abgeleitet aus Telegram #965–#974
>
> **Kernidee:** Eine einzige 24h-Claude-Bridge-Instanz dient als „Herz“ für alle Connectoren (Telegram, WhatsApp, …). Sie übernimmt die Rolle des persönlichen Assistenten und läuft nur auf **einem** System gleichzeitig. Wechselt der User das Gerät, wird die Fackel (Kontext + Zustand) sauber übergeben.

---

## 1. Ziel & Vision

- **Eine** Langzeit-Session (24h) pro Benutzer-Kontext.
- Alle Connectoren (Telegram, WhatsApp, zukünftige) melden an dieselbe Bridge.
- Die Bridge startet automatisch, sobald mindestens ein Connector konfiguriert ist.
- Die Bridge ist **auch ohne Connector** manuell startbar (`start/bridge.sh`).
- Wechsel zwischen Geräten = **Fackelübergabe**: alte Instanz beenden, neue startet mit Kontextpaket.
- Worker-Aufgaben über Tage hinweg persistieren und werden automatisch fortgesetzt.

---

## 2. Grundsätze

| # | Grundsatz | Konsequenz |
|---|-----------|------------|
| 1 | **Ein Herz pro Benutzer.** | Nur eine 24h-Bridgeinstanz ist aktiv. |
| 2 | **Maximal 2× 24h-Instanzen systemweit.** | (1) Bridge/Assistent + optional (2) persönlicher Assistent. Alle anderen Agenten sind temporär. |
| 3 | **Multiuser: nur ein 24h-Privileg.** | Pro System darf zu einem Zeitpunkt nur ein User das 24h-Privileg besitzen. |
| 4 | **Fackel ist ortsgebunden.** | Eine 24h-Session läuft nur auf einem System. Start auf anderem System löst Handover aus. |
| 5 | **Komprimierung = Standard-Claude-Code.** | Kein eigener Kontext-Aufbau; laufende Claude-Code-Session wird komprimiert. |
| 6 | **Bridge immer startbar.** | Auch ohne Connectoren kann die Bridge manuell aus `start/` gestartet werden. |
| 7 | **Logisch konsistent statt aufwändig.** | Entscheidungen (z. B. GUI-Sessions) werden so getroffen, dass das Gesamtkonzept stimmig bleibt. |

---

## 3. Architekturkomponenten

```text
┌─────────────────────────────────────────────────────────────┐
│                         BACH-System                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │   Telegram   │  │  WhatsApp    │  │   Weitere        │  │
│  │  Connector   │  │  Connector   │  │   Connectoren    │  │
│  └──────┬───────┘  └──────┬───────┘  └─────────┬────────┘  │
│         │                 │                    │           │
│         └─────────────────┼────────────────────┘           │
│                           ▼                                │
│              ┌─────────────────────────┐                   │
│              │   Fackelträger-Bridge   │                   │
│              │  (24h Claude-Bridge)    │                   │
│              │  - persönlicher Assistent│                  │
│              │  - StartSkill laden      │                  │
│              │  - UserSkill laden       │                  │
│              └───────────┬─────────────┘                   │
│                          │                                  │
│              ┌───────────▼───────────┐                    │
│              │  Fackel-Manager         │                   │
│              │  - Regeln prüfen        │                   │
│              │  - Handover orchestrieren│                  │
│              │  - State persistieren    │                   │
│              └───────────┬─────────────┘                   │
│                          │                                  │
│              ┌───────────▼───────────┐                    │
│              │   GUI / Tray            │                   │
│              │  - Autostart-Steuerung  │                   │
│              │  - Handover-Dialog      │                   │
│              │  - Session-Übersicht    │                   │
│              └─────────────────────────┘                   │
└─────────────────────────────────────────────────────────────┘
```

### 3.1 Bridge (`hub/_services/claude_bridge/bridge_daemon.py`)

- Lädt beim Start:
  1. `root-SKILL.md` (StartSkill / System-Kontext).
  2. Persönlichen-Assistenten-Skill (pro Benutzer).
- Hält eine Langzeit-Session offen.
- Empfängt Nachrichten von allen Connectoren über ein einheitliches API.

### 3.2 Fackel-Manager (neu)

Neuer Service, z. B. `hub/_services/fackeltraeger.py`:

- **Regel-Engine:** Prüft, ob eine neue 24h-Instanz erlaubt ist.
- **State-Store:** Persistiert minimalen Handover-Kontext (letzte Zustände, offene Todos, aktive Projekte).
- **Handover-Orchestrierung:**
  1. Erkennt laufende Fackel auf anderem System.
  2. Fordert Kontextpaket an.
  3. Beendet alte Instanz nach Bestätigung.
  4. Startet neue Instanz und spielt Kontext ein.
- **Komprimierung:** Delegiert an Claude-Code-Standardmechanismus; speichert nur Metadaten.

### 3.3 Tray / GUI

- `bridge_tray.py` übernimmt Autostart-Logik.
- GUI zeigt an, ob die Fackel aktiv ist und auf welchem System.
- Erlaubt manuelles „Fackel übergeben“ und „Fackel beenden“.

### 3.4 Connectoren

- Melden sich beim Fackel-Manager an.
- Leiten eingehende Nachrichten an die aktive Bridge weiter.
- Sind Connector-unabhängig: die Bridge ist auch ohne sie startbar.

---

## 4. Regeln (Enforcement)

### 4.1 Maximal 2× 24h-Instanzen

- **Instanz A:** Bridge/Assistent (Connector-gesteuert oder manuell).
- **Instanz B (optional):** persönlicher Assistent (explizit vom User gestartet).
- Jede weitere Agenten-Anfrage wird als **temporäre Session** behandelt (max. Laufzeit z. B. 4h).
- Prüfung durch Fackel-Manager vor Start.

### 4.2 Multiuser: Single-24h-Privileg

- Pro System darf nur ein Benutzer das 24h-Privileg haben.
- Wechsel = Handover oder Beendigung der aktiven Session.
- Nicht-Fackelträger-Systeme dürfen **eigene** GUI-24h-Sessions führen (kein zentrales 24h-Privileg, aber lokal maximal eine).

### 4.3 Fackel-Handover

- Eindeutige Fackel-ID = `(user_id, system_id, session_id, timestamp)`.
- Handover-Trigger:
  - Bridge-Start auf anderem System.
  - Manuelle „Übergeben“-Aktion in GUI.
- Ablauf:
  1. Neue Instanz sendet Handover-Request an State-Store.
  2. State-Store prüft Regeln und bereitet Kontextpaket vor.
  3. Alte Instanz komprimiert Session (Claude-Code-Standard) und sendet Paket.
  4. Neue Instanz startet mit Paket; alte beendet sich nach Bestätigung.

---

## 5. Datenmodell / State

### 5.1 Persistente Dateien

| Datei | Inhalt | Ort |
|-------|--------|-----|
| `fackel_state.json` | Aktive Fackeln, System-Zuordnung, User-Privileg | `BACH_RUNTIME_DIR/fackel/` |
| `handover_<id>.json` | Kontextpaket für Übertragung | `BACH_RUNTIME_DIR/fackel/handover/` |
| `worker_todos.json` | Offene Worker-Aufgaben über Tage | `BACH_RUNTIME_DIR/fackel/worker/` |
| `session_meta.json` | Letzte Session-Metadaten (Projekte, Kontakte, Shortcuts) | `BACH_RUNTIME_DIR/fackel/meta/` |

### 5.2 `fackel_state.json` (Schema)

```json
{
  "version": 1,
  "owner_system_id": "mac-studio-lukas",
  "owner_user_id": "lukas",
  "fackeln": [
    {
      "id": "fackel-bridge-001",
      "type": "bridge_assistant",
      "system_id": "mac-studio-lukas",
      "user_id": "lukas",
      "started_at": "2026-10-01T08:00:00Z",
      "last_seen": "2026-10-01T12:00:00Z",
      "status": "active"
    },
    {
      "id": "fackel-personal-001",
      "type": "personal_assistant",
      "system_id": "mac-studio-lukas",
      "user_id": "lukas",
      "started_at": "2026-10-01T09:00:00Z",
      "last_seen": "2026-10-01T11:30:00Z",
      "status": "active"
    }
  ]
}
```

### 5.3 Handover-Paket (Schema)

```json
{
  "handover_id": "...",
  "from": { "system_id": "...", "session_id": "..." },
  "to": { "system_id": "...", "requested_at": "..." },
  "context": {
    "compressed_session_url": "file://...",
    "open_todos": ["..."],
    "active_projects": ["..."],
    "recent_contacts": ["..."],
    "custom_shortcuts": {}
  },
  "expires_at": "2026-10-01T12:15:00Z"
}
```

---

## 6. Schnittstellen & Ereignisse

### 6.1 Interne API (Fackel-Manager)

| Methode | Zweck |
|---------|-------|
| `POST /fackel/request` | Neue Fackel anfordern |
| `POST /fackel/handover` | Handover einleiten |
| `GET  /fackel/status` | Aktive Fackeln abfragen |
| `POST /fackel/release` | Fackel freigeben |
| `POST /worker/todo` | Todo für Worker über Tage anlegen |
| `GET  /worker/todo/next` | Nächstes offenes Todo abrufen |

### 6.2 Ereignisse (Event-Stream / Log)

- `fackel.started`
- `fackel.handover.requested`
- `fackel.handover.completed`
- `fackel.handover.failed`
- `fackel.released`
- `worker.todo.created`
- `worker.todo.completed`

---

## 7. Roadmap & Subtasks

| Phase | Subtask | Inhalt | Status |
|-------|---------|--------|--------|
| 1 | **#1583** | Umsetzungsplan erstellen (dieses Dokument) | ✅ erledigt |
| 2 | **#1591** | S2: Fackel-Handover-Mechanismus zwischen Systemen | offen |
| 3 | **#1593** | S4: 24h-Regeln durchsetzen (max 2 Instanzen, Multiuser-Single-Privileg) | offen |
| 4 | **#1594** | S5: GUI-Konzept entscheiden + dokumentieren („logisch konsistent“) | offen |
| 5 | **#1596** | S7: Worker über Tage (Plan + Todos aufschreiben und abarbeiten lassen) | offen |
| 6 | n. N. | Integrationstests & Rollout-Dokumentation | noch offen |

### Abhängigkeiten

- #1591, #1593, #1594, #1596 hängen von #1583 ab (Plan vorhanden).
- #1591 (Handover) sollte vor #1593 (Regeln) umgesetzt werden, da die Regeln den Handover als Ausnahme/Trigger kennen müssen.
- #1594 (GUI) kann parallel zu #1591/#1593 laufen, sollte aber deren Ergebnisse integrieren.
- #1596 (Worker) kann weitgehend unabhängig implementiert werden, liest/schreibt jedoch denselben State-Store.

---

## 8. Offene Fragen & Risiken

| # | Frage / Risiko | Vorschlag |
|---|----------------|-----------|
| 1 | Wie wird `system_id` eindeutig und stabil vergeben? | Hash aus Hostname + User + Hardware-Fingerprint; konfigurierbar via `BACH_SYSTEM_ID`. |
| 2 | Wie synchronisiert sich State über Systeme? | Primär lokal + optional Mirror/Cloud-Sync (OneDrive/iCloud). Keine zentrale Infrastruktur erforderlich. |
| 3 | Was passiert bei gleichzeitigem Handover-Request? | Lock-Mechanismus im State-Store; erst anfragendes System gewinnt, anderes erhält „Fackel bereits aktiv“. |
| 4 | Wie groß darf ein Handover-Paket werden? | Max. 50 MB; größere Sessions werden vor Komprimierung aufgeräumt (alte Chunks verwerfen). |
| 5 | Backwards-Kompatibilität mit bestehender Bridge? | Schrittweise Migration; alte Bridge läuft weiter, Fackel-Manager wird optional eingeschaltet. |
| 6 | Sicherheit: Wer darf Handover anfordern? | Nur lokaler User + ggf. device_auth; keine externe Handover-Anforderung erlaubt. |

---

## 9. Nächste Schritte

1. **#1591** umsetzen: State-Store + Handover-API + Bridge-Anpassung.
2. **#1593** umsetzen: Regel-Engine in Fackel-Manager integrieren.
3. **#1594** entscheiden: GUI-Entwurf dokumentieren und mit #1591/#1593 abstimmen.
4. **#1596** umsetzen: Worker-Todo-Persistenz + Fortsetzungslogik.
5. Nach Abschluss der Subtasks: Integrationstests und `CHANGELOG.md` aktualisieren.

---

*Dokument erstellt von Buddha (BACH-Hintergrundworker) im Rahmen von Task #1583.*
