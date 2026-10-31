# Wettbewerbsanalyse: BACH-GUI 0.2.29 gegen OpenClaw und Hermes (v1)

- **Bezugsrelease:** BACH-GUI 0.2.29, Source-Pin a42adda6a9fe8d892578db3f7a09f7c1bef653ef (system/gui/kit_manifest.json:4–5)
- **Anlass:** Task #2627 — Bildvertrag für Screenshots, Anleitungsvideo-Doku und Wettbewerbsabgleich zur neuen GUI
- **Quellenbasis:** ausschließlich Belege aus dem eigenen Repository, immer als Pfad:Zeile. Für OpenClaw existiert im Repo keine URL, keine Lizenz- und keine Produktdokumentation (siehe Abschnitt 5).
- **Verwandte Doku:** [video/ANLEITUNGSVIDEO-GUI-0.2.29-v1.md](video/ANLEITUNGSVIDEO-GUI-0.2.29-v1.md), [GUI_SOFTWARE_OCEAN_CATALOG.md](GUI_SOFTWARE_OCEAN_CATALOG.md), [../assets/gui/README.md](../assets/gui/README.md)

## 1. Bezugsrahmen: BACH-GUI 0.2.29

Der maßgebliche GUI-Kit-Pin steht in [../system/gui/kit_manifest.json](../system/gui/kit_manifest.json) (Schema `ellmos-system-gui.kit-manifest.v1`, :2):

| Fakt | Wert | Beleg |
|---|---|---|
| Repository | github.com/ellmos-ai/ellmos-system-gui | kit_manifest.json:3 |
| Source-Commit (Pin) | a42adda6a9fe8d892578db3f7a09f7c1bef653ef | kit_manifest.json:4 |
| Version | 0.2.29 | kit_manifest.json:5 |
| Manifest-Schema | ellmos-system-gui.dist.v1 | kit_manifest.json:6 |
| Erwartete Seiten | 39 HTML-Seiten | kit_manifest.json:7 |
| Release-Archiv | ellmos-system-gui-0.2.29-a42adda6a9fe.zip | kit_manifest.json:8 |
| SHA-256 | 037516b1af6e658e06eee8aa57adaf81309bc430219198deeb6492ab816f29e1 | kit_manifest.json:9 |
| Pinned at | 2026-10-26T05:41:35Z | kit_manifest.json:10 |

Der Konsumvertrag [../system/gui/gui-consumer.v1.json](../system/gui/gui-consumer.v1.json) (Schema `ellmos.bach.gui-consumer.v1`, :2; Version 0.2.29, :4; Status `pinned_release`, :5) verlangt die Kernrouten `/api/gui/brand`, `/api/gui/backend-origin` und `/api/gui/capabilities` (:12–16) und hält fest: „A pin alone does not prove a live installation." (:17). Der Pin belegt also die Distribution, nicht eine laufende Installation.

Marktabgrenzung zu Terminal-/Editor-Tools ([architecture/BACH-vs-Claude-Code.md](architecture/BACH-vs-Claude-Code.md):41): Die lokale Betriebsoberfläche — FastAPI-GUI, Control API, Chat-/Daemon-Dienste — ist ein Alleinstellungsmerkmal („Nur BACH").

Zur Vertragshistorie: Der ältere Kit-Vertrag ([architecture/SHARED-GUI-KIT-AND-ORIGIN-CONTRACT-v1.md](architecture/SHARED-GUI-KIT-AND-ORIGIN-CONTRACT-v1.md), Stand 2026-10-05, :6) beschreibt noch einen Astro-5-Static-Build mit 16 Seiten (:17), Routen inklusive `/api/gui/kit-manifest` (:22) und die Themes dark/light/ocean/warm (:51). Für diese Analyse ist ausschließlich der aktuelle Pin 0.2.29 mit 39 erwarteten HTML-Seiten maßgeblich (kit_manifest.json:7).

## 2. Steckbrief OpenClaw (externes Konkurrenzprodukt)

OpenClaw ist das einzige im Repository beobachtete externe Konkurrenzprodukt. Die Quellenlage ist schmal: Alle Angaben stammen aus dem „OpenClaw-Abgleich" bzw. „Competitive Watch" des eigenen Root-CHANGELOG ([../CHANGELOG.md](../CHANGELOG.md)); eine URL, Lizenz oder Produktdokumentation liegt nicht vor. Die folgenden Punkte sind daher Beobachtungen aus dem eigenen CHANGELOG, keine eigene Prüfung des Produkts.

### OpenClaw v2026.9.8 (8. Oktober 2026, CHANGELOG.md:71)

Beobachtet: Inter-Agent-Reply-Stabilität, Session-Zuweisungs-Bereinigung, Speicheroptimierung für Multi-Codex-Läufe, Windows-Updater-Retry, Hilfetexte in 20 Sprachen.

Relevanz für BACH: Boss-Expert-Orchestrierung (Reply-Stabilität zwischen Agenten), Session-Continuation-Snapshots, atomare Release-/Rollback-Grenzen (distribution_releases v3.14.0), Task #1118 (OPS-RUN-001).

### OpenClaw v2026.9.7 (30. September 2026, CHANGELOG.md:79 und :87 — Einträge inhaltlich identisch)

Beobachtet: Stabilität bei langen Konversationen, OpenAI Agents API, „Sign in with ChatGPT"-Beta, Update-Backups mit Rollback-Schutz, Desktop-/Mobile-Kontinuität.

### OpenClaw v2026.9.6 (September 2026, CHANGELOG.md:94, :100, :106)

Beobachtet: Modelle Claude Opus 5.5, GPT-6 Sol/Luna und Grok 4.7; GitHub Reader; Managed Updates & Work Recovery; Befehlsguardrails gegen Shell-Injections; 30-Tage-Usage-Reporting.

Relevanz für BACH: Guardrails gegen Shell-Injections vergleichen mit safe_exec.py; das 30-Tage-Usage-Reporting berührt die geplante Telemetrie (Task #1315).

### OpenClaw v2026.9.5 LTS (Release 2026-09-19, CHANGELOG.md:112 und :118)

Beobachtet: „gateway-only extended-stable", Docker Image Pinning, Channel-Plugin-Härtungen, Rolling Updates, Atomic Updates mit Background-Staging und automatischem Rollback, Plugin Hot-Reloading, Conversation Sharing/Archives, Specialist Guided Setup.

Relevanz für BACH: Die Update-Mechanik (Atomic Updates mit automatischem Rollback) entspricht dem Härtungsziel der eigenen atomaren Release-/Rollback-Grenzen (distribution_releases v3.14.0).

Ein älterer OpenClaw-Abgleich zur 2026.7.x-Reihe (CHANGELOG.md:745) wird hier nur am Rand geführt.

## 3. Steckbrief Hermes (intern, kein Wettbewerber)

Hermes ist die interne Skill-Destillation von BACH — kein externes Produkt und kein Wettbewerber. Es wird hier aufgenommen, um Verwechslungen im GUI-/Ocean-Kontext auszuschließen.

- Rauschfilter 65–85 % ([architecture/HERMES-SKILL-DISTILLATION-v1.md](architecture/HERMES-SKILL-DISTILLATION-v1.md):58)
- SKILL.md-Format für destillierte Skills (:64–96)
- API: `POST /api/learning/hermes/distill`, `GET /candidates`, `GET /candidates/{id}`, `POST approve`, `POST reject`, `GET /stats` (:111–116)
- Ocean-Map-Subsystem „Hermes"/Skill-Destillation/active; Metriken: 12 Runs, 3 pending, 8 approved, 45 lessons; Ø 76,2 % (:122–138, :132)
- „Hermes (Skill-Learner)" als verknüpfter Agent ([architecture/DOMAINS-DASHBOARDS-PLAN-v1.md](architecture/DOMAINS-DASHBOARDS-PLAN-v1.md):217)

## 4. Abgrenzungen

- **BACH-GUI gegen OpenClaw:** OpenClaw zeigt nach eigener CHANGELOG-Beobachtung Stärken bei Agenten-Orchestrierung, Update-Mechanik und Update-Härtung. BACH setzt demgegenüber auf die lokale Betriebsoberfläche (FastAPI-GUI, Control API, Chat-/Daemon-Dienste; architecture/BACH-vs-Claude-Code.md:41) und auf einen versionierten, prüfsummenbelegten GUI-Kit-Pin (kit_manifest.json:3–10).
- **BACH-GUI gegen Hermes:** intern, keine Konkurrenzsituation. Wettbewerblicher Bezug besteht nur zu OpenClaw.
- **BACH-GUI gegen Terminal-/Editor-Tools:** dort existiert keine BACH-äquivalente lokale Betriebsoberfläche (architecture/BACH-vs-Claude-Code.md:41).
- **Charakter des Pins:** Der Pin 0.2.29 belegt Distribution, nicht Installation (gui-consumer.v1.json:17). Der Bildvertrag [../assets/gui/README.md](../assets/gui/README.md) soll die Oberfläche zusätzlich visuell belegen, sobald echte Screenshots vorliegen.

## 5. Lückenliste

1. **OpenClaw-Quellenlage:** Nur Beobachtungen im eigenen CHANGELOG; keine URL, keine Versionsdokumentation, keine Lizenzangabe im Repository.
2. **Gesamtdateizahl für 0.2.29 unbelegt:** Belegt ist nur die erwartete Seitenzahl 39 (kit_manifest.json:7). Eine Gesamtdateizahl existiert nur für den historischen Pin 0.2.23 mit 197 Dateien und 26 HTML-Seiten ([GUI_SOFTWARE_OCEAN_CATALOG.md](GUI_SOFTWARE_OCEAN_CATALOG.md), Abschnitt „Historischer Source-Pin: GUI 0.2.23").
3. **Keine echten Screenshots:** Die GUI 0.2.29 ist noch nicht bildlich belegt. Namensschema und Mindestumfang regelt der Bildvertrag [../assets/gui/README.md](../assets/gui/README.md); die Aufnahmen selbst sind offene Arbeit. Prüfbar ist bis dahin nur die *Ablage*, nicht die Aufnahme: `system/tools/gui_asset_contract.py` prüft ein vorhandenes Verzeichnis gegen den Bildvertrag (Exit 0 = vertragskonform, Exit 1 = Befundliste) und erzeugt selbst keine Bilder. Ist-Stand: `assets/gui/` enthält ausschließlich `README.md`, der Prüfer meldet daher korrekt Exit 1. Die Aufnahme scheitert derzeit an der Umgebung (kein Browser/Playwright, kein Netzwerkzugang) — sie ist damit nicht nur offen, sondern in dieser Umgebung nicht erbringbar.
4. **Unbelegte Richtlinien:** P-015 (Stimme), P-016 (Musik) und die Pipeline „HyperFrames" sind im Repository nicht belegt (keine Treffer in docs/) und werden ausschließlich als Auftragsbindung geführt (Details: [video/ANLEITUNGSVIDEO-GUI-0.2.29-v1.md](video/ANLEITUNGSVIDEO-GUI-0.2.29-v1.md)). Für diese Punkte existiert keine Belegquelle im Repository; sie dürfen in Video und Analyse nicht als belegte Fakten dargestellt werden. Das Anleitungsvideo bleibt bis zur Freigabe durch Lukas zurückgestellt.

## 6. Quellenverzeichnis (Pfad:Zeile)

- system/gui/kit_manifest.json:2–10 — Kit-Manifest: Schema, Repository, Commit a42adda6a9fe8d892578db3f7a09f7c1bef653ef, Version 0.2.29, 39 Seiten, ZIP, SHA-256, pinned_at
- system/gui/gui-consumer.v1.json:2, :4–5, :12–16, :17 — Konsumvertrag, pinned_release, Kernrouten, „A pin alone does not prove a live installation."
- docs/architecture/BACH-vs-Claude-Code.md:41 — Abgrenzung GUI/lokale Services, „Nur BACH"
- docs/architecture/SHARED-GUI-KIT-AND-ORIGIN-CONTRACT-v1.md:6, :17, :22, :51 — älterer Kit-Vertrag (Stand 2026-10-05): 16 Seiten, Routen, Themes
- CHANGELOG.md:71 — OpenClaw v2026.9.8
- CHANGELOG.md:79, :87 — OpenClaw v2026.9.7 (identische Einträge)
- CHANGELOG.md:94, :100, :106 — OpenClaw v2026.9.6
- CHANGELOG.md:112, :118 — OpenClaw v2026.9.5 LTS
- CHANGELOG.md:745 — älterer OpenClaw-Abgleich (2026.7.x)
- docs/architecture/HERMES-SKILL-DISTILLATION-v1.md:58, :64–96, :111–116, :122–138, :132 — Hermes Skill-Destillation
- docs/architecture/DOMAINS-DASHBOARDS-PLAN-v1.md:217 — Hermes (Skill-Learner)
- docs/GUI_SOFTWARE_OCEAN_CATALOG.md — Pin-Historie: 0.2.29 (aktuell), 0.2.23 und 0.2.22 (historisch)
- README.md:22 — Demo-Video-Referenz (youtu.be/Gv5nxF8HssU, 2:22) und Screenshot-Abschnitt
- assets/gui/README.md — Bildvertrag Screenshots BACH-GUI 0.2.29
- docs/video/ANLEITUNGSVIDEO-GUI-0.2.29-v1.md — Szenenplan Anleitungsvideo