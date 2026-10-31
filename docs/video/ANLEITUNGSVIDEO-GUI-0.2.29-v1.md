# Anleitungsvideo BACH-GUI 0.2.29 — Szenenplan v1

Status: Szenenplan v1 (Drehbuchgerüst), Stand 2026-10-26, bezogen auf den Source-Pin v0.2.29. Ziel ist ein kurzes Anleitungsvideo mit einer Gesamtlänge von etwa 2:20–2:30 Minuten. Echte Screenshots existieren noch nicht; Namensschema und Mindestumfang stehen im Bildvertrag [assets/gui/README.md](../../assets/gui/README.md). Wettbewerbskontext: [WETTBEWERBSANALYSE-GUI-v1.md](../WETTBEWERBSANALYSE-GUI-v1.md).

## 1 Szenenplan (Ziellänge ca. 2:20–2:30)

| Nr. | Szene | Zeitfenster | Inhalt und Belege |
| --- | --- | --- | --- |
| 1 | Intro/Hausstil | 0:00–0:15 | Titelkarte und Hausstil-Montage aus [banner.svg](../../assets/banner.svg), [banner_v2.png](../../assets/banner_v2.png) und [bach-demo-preview.png](../../assets/bach-demo-preview.png); Ansage: „Anleitung BACH-GUI 0.2.29". |
| 2 | unified_dashboard | 0:15–0:45 | Dashboard-Überblick über unified_dashboard.html: Startseite, Statusfelder und Navigation. |
| 3 | ki-center | 0:45–1:25 | Führung durch ki-center.html: Agenten- und Skill-Übersicht sowie zentrale Einstiege. |
| 4 | token-dashboard | 1:25–1:55 | Führung durch token-dashboard.html: Verbrauchsanzeige und Kennzahlen. |
| 5 | Source-Pin/Fakten | 1:55–2:10 | Faktenkarte: Version 0.2.29, Commit a42adda6a9fe8d892578db3f7a09f7c1bef653ef, 39 erwartete HTML-Seiten, Kernrouten /api/gui/brand, /api/gui/backend-origin, /api/gui/capabilities. |
| 6 | Outro | 2:10–2:20 | Einblendung: „Ein Pin belegt keine laufende Installation." Verweis auf [README.md](../../README.md). |

## 2 Faktengrundlage

- Source-Pin: [system/gui/kit_manifest.json](../../system/gui/kit_manifest.json):4–10 — Version 0.2.29, Commit a42adda6a9fe8d892578db3f7a09f7c1bef653ef, ZIP ellmos-system-gui-0.2.29-a42adda6a9fe.zip, SHA-256 037516b1af6e658e06eee8aa57adaf81309bc430219198deeb6492ab816f29e1, pinned_at 2026-10-26T05:41:35Z.
- Seitenumfang: 39 erwartete HTML-Seiten ([system/gui/kit_manifest.json](../../system/gui/kit_manifest.json):7).
- Kernrouten: /api/gui/brand, /api/gui/backend-origin, /api/gui/capabilities ([system/gui/gui-consumer.v1.json](../../system/gui/gui-consumer.v1.json):12–16).
- Warnhinweis, wörtlich zu übernehmen: „A pin alone does not prove a live installation." ([system/gui/gui-consumer.v1.json](../../system/gui/gui-consumer.v1.json):17).
- Demo-Referenz mit Länge 2:22: [README.md](../../README.md):22.

## 3 Produktionsrichtlinien (Auftragsbindung, im Repo nicht belegt)

Die folgenden Vorgaben beruhen auf Auftragsbindung und sind im Repository nicht belegt (vgl. [WETTBEWERBSANALYSE-GUI-v1.md](../WETTBEWERBSANALYSE-GUI-v1.md):79); sie sind als Arbeitskonvention kenntlich gemacht:

- Stimme: en-US-AndrewNeural (P-015).
- Musik: P-016 (Auswahl nach Auftragsbindung, im Repo nicht belegt).
- Produktions-Pipeline: HyperFrames.
- Freigabe-Gate: Lukas (Review und Freigabe vor Veröffentlichung).

## 4 Offene Arbeit

- Screenshots erzeugen: die im Bildvertrag [assets/gui/README.md](../../assets/gui/README.md) gelisteten PNGs (mindestens unified_dashboard, ki-center, token-dashboard) existieren noch nicht.
- Szenen belegen: je Szene mindestens ein Belegbild aus der jeweiligen GUI-Seite (Szenen 2–4).
- Video-Link nachtragen: nach Veröffentlichung Ziellänge und Link in [README.md](../../README.md) ergänzen.