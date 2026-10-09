# GUX-Abnahmeblatt (GUI-Ozean)

Angelegt: 09.10.2026, 01:34 Uhr (Task #1933/GUX-087)
Formatvorgabe: je GUX-Feld ein getrennter Nachweisabschnitt (Aussage=Quelle, keine Sammelaussage); Felder 087/089/091/093/094.

## GUX-087 – Tray-Readback + Endpoint-Nachweis (Task #1933)

### a) Prozess

- PID 57904, PPID 1 – Quelle: ps -p 57904, 08.10.2026.
- Start Do 08.10.2026 08:57:18 – Quelle: ps -p 57904, 08.10.2026.
- Kommando „…/Python -u hub/_services/chat/chat_tray.py --port 8081“ – Quelle: ps -p 57904, 08.10.2026.
- Kein --remote, kein --brand – Quelle: ps -p 57904, 08.10.2026.

### b) Endpoint-Readback (nur GET)

- GET http://127.0.0.1:8081/ → 200 OK, text/html, Titel „BACH Chat Control“ – Quelle: curl GET, 08.10.2026 23:29:44 GMT.
- GET /status → 404, JSON {"error":"Not found"} – Quelle: curl GET, 08.10.2026 23:29:44 GMT.
- Server: BaseHTTP/0.6 Python/3.12.13 – Quelle: curl GET (Server-Header), 08.10.2026 23:29:44 GMT.
- KEINE POSTs ausgeführt (toggle/delete verboten) – Quelle: Durchführungsprotokoll des Endpoint-Readbacks, 08.10.2026 (nur GET).

### c) Code-Belege chat_tray.py LIVE (mtime 2026-10-08 17:43:06)

- Docstring „--port 8081 [--host lead.example]“ – Quelle: chat_tray.py LIVE, Docstring.
- Docstring „BACH_IDLE_WORKER=0 -> Host startet keinen neuen Always-On-Lauf“ – Quelle: chat_tray.py LIVE, Docstring.
- control_auth #196 – Quelle: chat_tray.py LIVE, Z. 33.
- Auth-Header – Quelle: chat_tray.py LIVE, Z. 258.
- _api() – Quelle: chat_tray.py LIVE, Z. 317-323/337-341.
- GET /api/status – Quelle: chat_tray.py LIVE, Z. 370.
- POST /api/chat – Quelle: chat_tray.py LIVE, Z. 576.
- _toggle_worker_action → POST /api/workers/toggle – Quelle: chat_tray.py LIVE, Z. 1200ff.
- _delete_worker_action → POST /api/workers/delete (Icon-Notify) – Quelle: chat_tray.py LIVE, Z. 1200ff.
- _open_gui → gui_url – Quelle: chat_tray.py LIVE, Z. 1200ff.
- _open_webchat → gui_url/chat („standalone webchat :8080 went with retired claude_bridge; working chat is GUI page (plan item 1.1.6)“) – Quelle: chat_tray.py LIVE, Z. 1200ff.
- _open_promptboard (win32 startfile, sonst Popen cwd DEVNULL) – Quelle: chat_tray.py LIVE, Z. 1200ff.
- _open_telegram – Quelle: chat_tray.py LIVE, Z. 1200ff.
- „neither elapsed time, TaskDB status nor model text authorizes restart“ – Quelle: chat_tray.py LIVE, Z. 633.
- unconfirmed → kein Start – Quelle: chat_tray.py LIVE, Z. 672-674.

### c2) Code-Belege telegram_chat.py LIVE

- Import BaseHTTPRequestHandler/ThreadingHTTPServer – Quelle: telegram_chat.py LIVE, Z. 46.
- CONTROL_PORT=int(os.environ.get("BACH_CONTROL_PORT","8081")) – Quelle: telegram_chat.py LIVE, Z. 2298.
- QuietHTTPServer – Quelle: telegram_chat.py LIVE, Z. 3140.
- ControlHandler – Quelle: telegram_chat.py LIVE, Z. 3787.
- do_GET – Quelle: telegram_chat.py LIVE, Z. 3953.
- server=QuietHTTPServer((bind_host, CONTROL_PORT), ControlHandler) – Quelle: telegram_chat.py LIVE, Z. 4830.
- `<title>BACH Chat Control</title>` – Quelle: telegram_chat.py LIVE, Z. 2306.
- `<h1>BACH Chat Control</h1>` – Quelle: telegram_chat.py LIVE, Z. 2511.
- wt-t1710 dieselbe Struktur – Quelle: wt-t1710, Z. 46/3709/3717/3797/4642.

### c3) Schärf-Grep (Muster „BACH Chat Control“, Runde 10, 09.10.2026)

- Treffer nur in telegram_chat.py Z. 2306/2511 – Quelle: Schärf-Grep, 09.10.2026.
- Treffer in 4 Backups (.bak-20260904-114458, .bak-board_authz-20260927-2330, .bak-lock-20260907, .bak-auto-20260904-114651) – Quelle: Schärf-Grep, 09.10.2026.
- Treffer in __pycache__/telegram_chat.cpython-312.pyc – Quelle: Schärf-Grep, 09.10.2026.
- KEIN Treffer in chat_tray.py (LIVE, wt-t1710, bach.pre-git-2026-07-12) – Quelle: Schärf-Grep, 09.10.2026.

### d) Abweichung/Altstand-Risiko

- Prozess 57904 (Start 08.10.2026 08:57:18) bedient :8081 mit Titel „BACH Chat Control“ – Quelle: ps + curl, 08.10.2026.
- Live-chat_tray.py (mtime 2026-10-08 17:43:06, NACH Prozessstart) enthält weder HTTP-Server (kein do_GET/self.path/HTTPServer/server_address) noch Titel noch telegram_chat-Referenz – Quelle: grep do_GET/HTTPServer, 08./09.10.2026; Schärf-Grep, 09.10.2026.
- Kein telegram_chat-Prozess läuft – Quelle: pgrep telegram_chat leer, 08./09.10.2026.
- __pycache__/telegram_chat.cpython-312.pyc existiert (Python 3.12 passend) – Quelle: Dateisystem-Befund.
- :8081-Dienst dem Live-Stand nicht eindeutig zuordenbar, plausibel Code von VOR 17:43:06 (Indiz, gestärkt durch Schärf-Grep; KEINE Behauptung) – Quelle: Zusammenschau a)–c3).

### e) Offene Punkte

- Restart nur mit Nutzerfreigabe (nicht erfolgt) – Quelle: Vorgabe Task #1933/GUX-087.
- CWD PID 57904 nicht ermittelbar (lsof blockiert) → Prozesszuordnung :8081 offen – Quelle: lsof-Versuch blockiert.
- GUI-Browser-Kontrolle offen – Quelle: Verweis GUX-093/Task #1936.

## GUX-089 – offen → Task #1934 (Platzhalter)

## GUX-091 – offen → Task #1935 (Platzhalter)

## GUX-093 – offen → Task #1936 (Platzhalter)

## GUX-094 – offen → Task #1937 (Platzhalter; Task 1937 verbietet Restart/Merge/Deploy ohne Nutzerfreigabe)