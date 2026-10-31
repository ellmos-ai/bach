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