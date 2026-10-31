# GUI-Kit 0.2.29 — Lieferbeschreibung

Dieses Verzeichnis (`system/gui/web`) enthaelt das ausgelieferte GUI-Kit
**0.2.29** als Release-Pin-Fassung. Es besteht aus:

- `gui-consumer.v1.json` — Consumer-Vertrag (Version 1) fuer die GUI-Konfiguration
- `kit_manifest.json` — Manifest mit den Pin-Angaben des Release

## Lieferangaben (aus kit_manifest.json)

| Angabe | Wert |
| --- | --- |
| Version | 0.2.29 |
| Commit | `a42adda6a9fe8d892578db3f7a09f7c1bef653ef` |
| Archiv | `ellmos-system-gui-0.2.29-a42adda6a9fe.zip` |
| archive_sha256 | `037516b1af6e658e06eee8aa57adaf81309bc430219198deeb6492ab816f29e1` |
| expected_page_count | 39 |

## Provenienz

Die Herkunftsangaben sind maschinenlesbar in `SOURCE_PROVENANCE`
(alle Felder als `schluessel=wert`) dokumentiert; sie entsprechen 1:1 den
Werten in `kit_manifest.json`.

## Verifizierung durch den Hub

Der Hub-Service `get_pinned_kit_manifest`
(`system/hub/_services/gui_contract_service.py`, Zeilen 37–70) prueft bei
Lesen der Pin-Referenz alle Manifest-Felder:

- `commit`: 40 Hex-Zeichen
- `archive_sha256`: 64 Hex-Zeichen
- `dist`-Schema
- `expected_page_count`: Ganzzahl >= 1
- `version`: nicht-leerer Text
- Archivname: `.zip` und ohne Pfadanteil

Bei gueltiger Identitaet setzt der Service `data["verified"] = true`
(Zeile 69). Die Integritaets-Assertion `kit["verified"] is True` ist damit
code-seitig abgedeckt.