# GUI-Konzept Fackelträger-System (#1594)

**Status:** ENTSCHIEDEN (Doku/Entscheidung, keine Codeänderung in diesem Task)
**Datum:** 2026-09-30
**Parent:** #1583 (Fackelträger-System Umsetzung, Telegram #965–#974)
**User-Vorgabe:** „mach es wie es logisch konsistenter ist"

---

## 1. Ausgangslage

Das Fackelträger-System (#1583) sieht vor:

- Eine **24h-Claude-Bridgeinstanz** als Herz des Systems, Agentenrolle „persönlicher Assistent",
  bedient alle Connectoren (Telegram/WhatsApp/GUI).
- **Max. 2 aktive 24h-Instanzen** gleichzeitig (`H24_SESSION_TYPES = ("bridge", "personal_assistant")`,
  `MAX_24H_ACTIVE = 2`, siehe `fackel.py` / `hub/_services/fackeltraeger.py`, Limit-Gate aus #1593).
- Die **Fackel** (24h-Privileg) läuft zu einem Zeitpunkt nur auf **einem** System;
  Start auf einem anderen System = Fackelübergabe (Handover).
- Alle anderen Agentenrollen sind **temporär** (zeitlich begrenzte Sessions).

Offen war bisher: Wie bildet die **GUI** (Sessionstart, Routing eingehender Anfragen) dieses
Modell ab? Diese Entscheidung wird hier getroffen und dokumentiert.

---

## 2. Entscheidung

### 2.1 Routing eingehender Anfragen

| Anfrage-Typ | Ziel |
|---|---|
| **Allgemeine Anfragen** (keine explizite Rolle adressiert) | 24h-Fackelträger-Claude |
| **Anfragen an den persönlichen Assistenten** | 24h-Fackelträger-Claude |
| **Alle anderen Anfragen** (spezialisierte Agentenrollen, Coding-Instanzen, Worker o.ä.) | Zeitlich begrenzte **Extrasessions** |

Der 24h-Fackelträger-Claude ist damit der **Default-Endpunkt** der GUI. Extrasessions sind
die Ausnahme und müssen **explizit** gewählt werden.

### 2.2 Sessionstart in der GUI (zu überarbeiten)

Der Sessionstart-Dialog wird auf das Fackelträger-Modell ausgerichtet:

1. **Default-Option: „Assistent (24h)"**
   - Startet bzw. attacht die Fackelträger-Bridge-Session (Session-Typ `bridge` /
     `personal_assistant`).
   - Läuft bereits ein Fackelträger auf **diesem** System → Attach an die laufende Session
     (kein zweiter 24h-Claim).
   - Läuft der Fackelträger auf einem **anderen** System → Hinweis auf Fackelübergabe;
     Start nur über den Handover-Mechanismus (‑`request_handover`/`accept_handover`),
     niemals stillschweigend als dritte 24h-Instanz.
2. **Explizite Extrasession-Auswahl** für alle anderen Rollen:
   - Frei wählbare Agentenrolle/Prompt, **immer mit Zeitlimit** (Timeout wie bisher bei
     ATI-Sessions, z. B. `work_time` in Minuten).
   - Extrasessions konsumieren **kein** 24h-Slot, sind aber hard-limitiert in der Laufzeit.
3. **Sichtbarkeit:** Die GUI zeigt an, welches System aktuell die Fackel hält
   (`get_fackel_holder_state()`), inkl. System-Name und verbleibender Zeit.

### 2.3 Nicht-Fackelträger-Systeme

Ein System, das **nicht** die Fackel hält, darf über die GUI trotzdem eine **eigene
lokale 24h-Session** führen — unter diesen Bedingungen:

- Es beansprucht **keinen** Fackel-Slot (kein `acquire_fackel`, kein Connector-Betrieb
  über diese Session).
- Die lokale GUI-24h-Session ist klar als **lokal** gekennzeichnet (UI-Badge o.ä.),
  damit kein scheinbarer Konflikt mit dem Fackelhalter entsteht.
- Das globale Limit (`MAX_24H_ACTIVE = 2`) gilt nur für **fackel-gebundene** 24h-Instanzen
  (`bridge`/`personal_assistant` mit Fackel-Claim). Lokale GUI-24h-Sessions ohne Claim
  zählen nicht darauf an.

> Hintergrund: Die 24h-Regel schützt die **Connectoren-Eindeutigkeit** (wer antwortet auf
> Telegram/WhatsApp) und die Kontext-Kontinuität — nicht die Frage, ob ein Entwickler lokal
> eine lange Claude-Session offen hat. Ein Verbot wäre inkonsistent restriktiv.

---

## 3. Begründung („logisch konsistent")

1. **Single-Point-Prinzip:** Es gibt genau ein „Herz" (24h-Fackelträger). Also muss der
   Default-Weg der GUI genau dorthin führen — alles andere erzeugt widersprüchliche
   Kontexte und Doppelantworten auf Connectoren.
2. **Limit-Abbildung:** `MAX_24H_ACTIVE = 2` ist in `fackel.py`/`fackeltraeger.py` bereits
   durchgesetzt (#1593, getestet in #1597). Die GUI darf daher niemals implizit eine
   zusätzliche 24h-Instanz erzeugen; der einzige legitime Weg zu einer zweiten 24h-Instanz
   ist die Fackelübergabe. Default „Assistent (24h)" + explizite Extrasession-Auswahl
   erzwingt genau das strukturell.
3. **Symmetrie der Rollen:** Der persönliche Assistent ist die einzige Rolle mit
   Dauer-Charakter (Kontext über Tage, Worker-Koordination). Alle anderen Rollen sind im
   Konzept seit #1583 ausdrücklich „temporär" — die GUI spiegelt das durch das
   Pflicht-Zeitlimit bei Extrasessions.
4. **Fackel-Regel ohne Over-Blocking:** Lokale 24h-Sessions auf Nicht-Fackelträger-Systemen
   widersprechen der Fackel-Regel nicht (die Fackel regelt Connector-Hoheit, nicht lokale
   Entwicklung). Sie zu verbieten, würde die GUI-Regeln von der eigentlichen Schutzfunktion
   entkoppeln.

---

## 4. Konsequenzen für die Umsetzung (Follow-ups, kein Code hier)

1. **GUI Sessionstart-UI umbauen** (api/gui): Default „Assistent (24h)" mit Attach-Logik,
   Extrasession-Auswahl mit Pflicht-Timeout, Fackelhalter-Anzeige.
2. **Routing-Layer** zwischen GUI und Bridge: Klassifikation „allgemein/PA vs. andere Rolle"
   — minimal: explizite Auswahl durch den User, keine Auto-Klassifikation.
3. **Multiuser:** Single-24h-Privileg (nur ein User gleichzeitig mit 24h-Privileg) ist in
   `acquire_fackel` noch nicht umgesetzt (user_id wird aktuell ignoriert) → eigener
   Follow-up-Task.
4. Bestehende ATI-Session-Endpunkte (`/api/ati/session/start*`) bleiben vorerst die
   technische Basis der Extrasessions; 24h-Start geht künftig über die Bridge/Fackel-API.

---

## 5. Explizit NICHT entschieden / offen

- Keine Auto-Klassifikation von Anfragen (Intent-Erkennung) — bewusst explizite Wahl.
- Kein GUI-Verbot lokaler 24h-Sessions (siehe 2.3).
- Keine Änderung am Handover-Protokoll selbst (aus #1592/#1595 bereits umgesetzt).
