---
name: webseiten-lesen
version: 1.0.0
type: protocol
author: Claude Opus 4.6
created: 2026-03-12
updated: 2026-03-12
anthropic_compatible: true

dependencies:
  tools: []
  services: []
  protocols: []

description: >
  Verfahren zum Lesen und Extrahieren von Webseiten-Inhalten ueber BACH.
  Entscheidungsbaum fuer die Wahl des richtigen Handlers (web_parse vs web_scrape).
---

# Webseiten lesen -- Verfahren

> Verfahren zum Lesen und Extrahieren von Webseiten-Inhalten ueber BACH; Entscheidungsbaum fuer die Wahl des richtigen Handlers (web_parse vs web_scrape).

## Entscheidungsbaum

```
Was brauchst du von der Webseite?
│
├── Textinhalt / Artikel / Dokumentation
│   └── bach web-parse clean <url>
│       (Hauptinhalt als Markdown, Nav/Header/Footer entfernt)
│
├── Vollstaendiger Seiteninhalt als Markdown
│   └── bach web-parse url <url>
│       (Alles als Markdown, inkl. Navigation und Links)
│
├── Alle Links einer Seite
│   └── bach web-scrape links <url>
│       (Liste aller <a href> mit Linktext, max 50, dedupliziert)
│
├── Formulare analysieren
│   └── bach web-scrape forms <url>
│       (Formular-Felder, Actions, Methods)
│
├── HTTP-Header pruefen
│   └── bach web-scrape headers <url>
│       (Response-Headers, Status-Code, Content-Type)
│
├── Roher HTML-Body
│   └── bach web-scrape get <url>
│       (HTTP GET, truncated bei >10.000 Zeichen)
│
└── Screenshot einer Seite
    └── bach web-scrape screenshot <url>
        (PNG via Selenium, braucht Chrome-Driver)
```

## Handler-Uebersicht

| Handler | Befehl | Technik | Ergebnis |
|---------|--------|---------|----------|
| `web_parse` | `bach web-parse url/clean <url>` | trafilatura / html2text | Markdown |
| `web_scrape` | `bach web-scrape get/links/forms/headers/screenshot <url>` | requests + Regex | Text/PNG |

## Typischer Workflow

### 1. Content einer Webseite extrahieren

```bash
# Empfohlen: Clean-Modus (nur Hauptinhalt)
bach web-parse clean https://example.com/artikel

# Alternative: Voller Inhalt mit Links
bach web-parse url https://example.com/artikel
```

### 2. Seite analysieren (Links, Formulare)

```bash
# Alle Links
bach web-scrape links https://example.com

# Formulare erkennen
bach web-scrape forms https://example.com/login
```

### 3. API ueber Python

```python
from bach_api import app
a = app()

# Content extrahieren
ok, md = a.execute('web-parse', 'clean', ['https://example.com'])

# Links auflisten
ok, links = a.execute('web-scrape', 'links', ['https://example.com'])
```

## Einschraenkungen

- **Kein JavaScript-Rendering:** Beide Handler nutzen HTTP-Requests (kein Browser). Seiten die Inhalte per JavaScript laden (React, Next.js, Angular) liefern nur den serverseitig gerenderten Anteil.
- **Workaround fuer JS-Seiten:** `web-parse clean` nutzt trafilatura, das auch bei JS-lastigen Seiten oft den Textinhalt extrahieren kann (wie bei lobehub.com/pricing gezeigt).
- **Screenshot:** `web-scrape screenshot` nutzt Selenium mit headless Chrome -- das rendert JS, braucht aber Chrome-Driver.
- **Timeout:** 20 Sekunden pro Request.
- **Cache:** `web-parse` cached Ergebnisse in `data/cache/web/` (MD5-basiert). Cache pruefen/leeren: `bach web-parse cache list/clear`.

## Dateien

- `hub/web_parse.py` -- WebParseHandler (Content-Extraktion)
- `hub/web_scrape.py` -- WebScrapeHandler (Struktur-Analyse)
- `docs/help/web_parse.txt` -- Help-Datei fuer web_parse
- `docs/help/web_scrape.txt` -- Help-Datei fuer web_scrape
- `data/cache/web/` -- Cache fuer web_parse
- `data/cache/scrape/` -- Screenshots fuer web_scrape

## Siehe auch

- `bach help web_parse` -- Detaillierte Handler-Dokumentation
- `bach help web_scrape` -- Detaillierte Handler-Dokumentation
