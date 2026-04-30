"""
REST-API Server Template -- ATI Standard-Modul
================================================
Wiederverwendbarer REST-API-Server fuer PySide6-Desktop-Apps.
Laeuft als separater Thread neben der GUI.

Verwendung:
    1. Diese Datei in das Projekt kopieren (z.B. src/api/api_server.py)
    2. ROUTES anpassen (siehe unten)
    3. In main.py / main_window.py einbinden:

        from api.api_server import APIServer
        self.api = APIServer(port=8080)
        self.api.start()

Abhaengigkeiten:
    Keine externen -- nutzt nur Python-stdlib (http.server, json, threading)

Lizenz: MIT (Teil des BACH ATI Systems)
"""

import json
import threading
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any, Callable, Dict, Optional
from functools import partial

logger = logging.getLogger(__name__)


class APIHandler(BaseHTTPRequestHandler):
    """HTTP Request Handler mit JSON-API."""

    # Wird vom Server gesetzt
    routes: Dict[str, Callable] = {}
    auth_token: Optional[str] = None

    def log_message(self, format, *args):
        """Leite HTTP-Logs an Python-Logger um."""
        logger.debug(format, *args)

    def _check_auth(self) -> bool:
        """Prueft Bearer-Token falls konfiguriert."""
        if not self.auth_token:
            return True
        auth = self.headers.get("Authorization", "")
        if auth == f"Bearer {self.auth_token}":
            return True
        self._respond(401, {"error": "Unauthorized"})
        return False

    def _respond(self, status: int, data: Any):
        """Sendet JSON-Antwort."""
        body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> Optional[dict]:
        """Liest JSON-Body aus dem Request."""
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        try:
            raw = self.rfile.read(length)
            return json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            self._respond(400, {"error": f"Invalid JSON: {e}"})
            return None

    def do_OPTIONS(self):
        """CORS Preflight."""
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_PUT(self):
        self._handle("PUT")

    def do_DELETE(self):
        self._handle("DELETE")

    def _handle(self, method: str):
        """Dispatcht Request an registrierte Route."""
        if not self._check_auth():
            return

        path = self.path.split("?")[0].rstrip("/") or "/"
        route_key = f"{method} {path}"

        # Exakter Match
        handler = self.routes.get(route_key)
        if not handler:
            # Fallback: nur Pfad (ohne Method)
            handler = self.routes.get(path)
        if not handler:
            self._respond(404, {"error": f"Route not found: {route_key}"})
            return

        try:
            body = self._read_body() if method in ("POST", "PUT") else {}
            if body is None:
                return  # Fehler wurde bereits gesendet
            result = handler(body=body, path=self.path, headers=dict(self.headers))
            self._respond(200, result)
        except Exception as e:
            logger.error(f"API Error on {route_key}: {e}", exc_info=True)
            self._respond(500, {"error": str(e)})


class APIServer:
    """
    Threaded REST-API Server.

    Beispiel:
        server = APIServer(port=8080, auth_token="geheim")
        server.add_route("GET /api/status", lambda **kw: {"status": "ok"})
        server.add_route("POST /api/action", my_handler)
        server.start()
        # ... spaeter:
        server.stop()
    """

    def __init__(self, port: int = 8080, host: str = "127.0.0.1",
                 auth_token: Optional[str] = None):
        self.port = port
        self.host = host
        self.auth_token = auth_token
        self._routes: Dict[str, Callable] = {}
        self._server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None

        # Standard-Route
        self.add_route("GET /api/health", lambda **kw: {
            "status": "ok",
            "port": self.port
        })

    def add_route(self, route: str, handler: Callable):
        """
        Registriert eine Route.

        Args:
            route: "METHOD /path" z.B. "GET /api/status" oder "POST /api/action"
            handler: Funktion(body=dict, path=str, headers=dict) -> dict
        """
        self._routes[route] = handler

    def start(self):
        """Startet den Server in einem Daemon-Thread."""
        if self._thread and self._thread.is_alive():
            logger.warning("API Server laeuft bereits auf Port %d", self.port)
            return

        handler_class = type("BoundHandler", (APIHandler,), {
            "routes": self._routes,
            "auth_token": self.auth_token,
        })

        self._server = HTTPServer((self.host, self.port), handler_class)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        logger.info("API Server gestartet: http://%s:%d", self.host, self.port)

    def stop(self):
        """Stoppt den Server."""
        if self._server:
            self._server.shutdown()
            self._server = None
            self._thread = None
            logger.info("API Server gestoppt")

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()
