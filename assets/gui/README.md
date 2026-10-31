# Bildvertrag: Screenshots der BACH-GUI 0.2.29

Status: Bildvertrag v1, Stand 2026-10-26. Echte Screenshots der BACH-GUI 0.2.29 stehen noch aus; dieses Dokument legt Namensschema, Mindestumfang und Belegzusammenhang verbindlich fest. Verwendung: [README.md](../../README.md), [docs/video/ANLEITUNGSVIDEO-GUI-0.2.29-v1.md](../../docs/video/ANLEITUNGSVIDEO-GUI-0.2.29-v1.md), [docs/WETTBEWERBSANALYSE-GUI-v1.md](../../docs/WETTBEWERBSANALYSE-GUI-v1.md).

## Namensschema

```
assets/gui/v0.2.29-<seitenname>.png
```

`<seitenname>` ist der HTML-Dateiname der GUI-Seite ohne Endung; Beispiel: `ki-center.html` → `assets/gui/v0.2.29-ki-center.png`. Der Source-Pin v0.2.29 erwartet 39 HTML-Seiten ([../../system/gui/kit_manifest.json](../../system/gui/kit_manifest.json):7).

## Mindestumfang

| PNG (geplant) | GUI-Seite als Beleg |
| --- | --- |
| `assets/gui/v0.2.29-unified_dashboard.png` | `../../system/gui/unified_dashboard.html` |
| `assets/gui/v0.2.29-ki-center.png` | `../../system/gui/ki-center.html` |
| `assets/gui/v0.2.29-token-dashboard.png` | `../../system/gui/token-dashboard.html` |

## Belegzusammenhang (Source-Pin v0.2.29)

- Commit: a42adda6a9fe8d892578db3f7a09f7c1bef653ef
- ZIP-Archiv: ellmos-system-gui-0.2.29-a42adda6a9fe.zip
- SHA-256-Prüfsumme: 037516b1af6e658e06eee8aa57adaf81309bc430219198deeb6492ab816f29e1
- pinned_at: 2026-10-26T05:41:35Z
- Kernrouten der GUI: /api/gui/brand, /api/gui/backend-origin, /api/gui/capabilities ([../../system/gui/gui-consumer.v1.json](../../system/gui/gui-consumer.v1.json):12–16)
- Ein Pin belegt keine laufende Installation: „A pin alone does not prove a live installation." ([../../system/gui/gui-consumer.v1.json](../../system/gui/gui-consumer.v1.json):17)

## Bestandsvermerk

Derzeit liegen KEINE echten PNGs vor. Das Verzeichnis assets/ enthält neben diesem Unterverzeichnis assets/gui/ nur die Dateien `bach-demo-preview.png`, `banner.svg` und `banner_v2.png`. Jede oben gelistete PNG-Datei ist geplant und noch nicht erzeugt; die Erzeugung echter Screenshots bleibt als offene Restaufgabe dokumentiert.

## Aufnahme-Werkzeug (Anforderungen, nicht in BACH)

Die Aufnahme ist bewusst **nicht** Teil dieses Repos ([DECISION-20261030 Lukas (D2)]: kein Screenshot-Code in BACH). Das Werkzeug entsteht wiederverwendbar außerhalb, in `ellmos-tests` oder im privaten Repo `gui-testing`; dieses Dokument beschreibt nur den Vertrag, den es erfüllen muss, damit die PNGs hier ablegbar sind.

Soll-Aufruf (Vorschlag, Namen bindend für die Ablage):

```
gui-shot --base-url <GUI-Origin> --out assets/gui --version 0.2.29 \
         --pages unified_dashboard,ki-center,token-dashboard
```

Pflichtanforderungen:

1. **Viewport fix**: 1440x900, `device_scale_factor 1`, damit Wiederholungsläufe diffbar bleiben.
2. **Bereitschaft statt Timeout**: warten, bis die Seite gerendert ist; erst danach `page.screenshot({ fullPage: false })` (nur Viewport, keine Scroll-Crops).
3. **Live-Nachweis**: vor der Aufnahme die Kernrouten `/api/gui/brand`, `/api/gui/backend-origin`, `/api/gui/capabilities` abrufen und die Antwort-Hashes neben den PNGs als `<seitenname>.json` protokollieren — ein Pin allein belegt keine laufende Installation (siehe Belegzusammenhang).
4. **Versionssiegel**: Dateiname MUSS dem Namensschema `v0.2.29-<seitenname>.png` folgen; abweichende GUI-Version bricht den Lauf ab, statt falsch benannte Bilder zu schreiben.
5. **Nur PNGs ohne Personenbezug**: keine Logins, keine Token-Werte, keine Klartext-Pfade im Bild; vor Ablage Sichtprüfung.
6. **Deterministisch**: keine Mauszeiger-, Fokus- oder Hover-Artefakte; identische Eingabe soll identische Bildgröße erzeugen.

Abnahmekriterium für dieses Verzeichnis: die drei PNGs aus „Mindestumfang" existieren, `file` meldet PNG mit 1440x900, und die zugehörigen `<seitenname>.json`-Protokolle liegen bei. Danach wird der Platzhalter in [README.md](../../README.md) durch die echte Einbindung ersetzt und der Bestandsvermerk oben auf „vorhanden" umgestellt.

### Abnahmeprüfung im Repo (ohne Bilderzeugung)

Das Abnahmekriterium oben ist maschinell prüfbar: [`../../system/tools/gui_asset_contract.py`](../../system/tools/gui_asset_contract.py) verifiziert genau diese Bedingungen in diesem Verzeichnis — die drei PNGs aus „Mindestumfang", PNG-Signatur und Abmessung 1440x900, die zugehörigen `<seitenname>.json`-Protokolle samt Kernrouten-Nachweis und das Versionssiegel im Dateinamen. Das Werkzeug **erzeugt selbst keine Bilder** und ersetzt die Aufnahme nicht; es meldet nur, ob eine vorgefundene Ablage vertragskonform ist (Exit 0 = vertragskonform, Exit 1 = Befundliste).