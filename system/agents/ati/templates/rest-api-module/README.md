# REST-API + CLI Template

ATI Standard-Module fuer API/CLI-Steuerbarkeit in Desktop-Apps.

## Dateien

| Datei | Funktion |
|-------|----------|
| `api_server.py` | Threaded REST-API Server (stdlib, keine Dependencies) |
| `cli_interface.py` | CLI mit argparse Subcommands + Tabellenausgabe |

## Integration

1. Dateien in das Projekt kopieren (`src/api/` oder `src/cli/`)
2. Routes / Commands projektspezifisch anpassen
3. In `main.py` einbinden (CLI-Modus oder API-Start)

## API-Server Features

- Threaded (laeuft neben GUI)
- Bearer-Token Auth (optional)
- CORS-Support
- JSON Request/Response
- Health-Endpoint automatisch (`GET /api/health`)

## CLI Features

- argparse-basierte Subcommands
- JSON- und Tabellenausgabe
- Headless-Modus (ohne GUI)
