#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BACH Claude Bridge -- FastAPI REST Layer
==========================================
Provides a REST API for the Bridge Daemon in server mode.

Endpoints:
  POST /api/message  -- Send a message to BACH
  GET  /api/status   -- Bridge status (uptime, mode, last_message, active_workers)
  POST /api/control  -- Control commands (pause, resume, reload_config)

Auth: Bearer token from config["server"]["auth_token"]
"""

import time
from datetime import date, datetime
from pathlib import Path
from typing import Optional

try:
    from fastapi import FastAPI, HTTPException, Depends, Request
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse
    from pydantic import BaseModel
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

# Lazy imports from bridge_daemon (avoids circular imports at module level)
_bridge_daemon = None


def _get_bridge():
    global _bridge_daemon
    if _bridge_daemon is None:
        from . import bridge_daemon as bd
        _bridge_daemon = bd
    return _bridge_daemon


# ============ PYDANTIC MODELS ============

if HAS_FASTAPI:

    class MessageRequest(BaseModel):
        text: str
        sender: str = "api"

    class ControlRequest(BaseModel):
        action: str  # "pause", "resume", "reload_config"

    class MessageResponse(BaseModel):
        ok: bool
        message: str

    class StatusResponse(BaseModel):
        running: bool
        pid: Optional[int] = None
        mode: str
        uptime_seconds: Optional[float] = None
        permission_mode: str
        session_active: bool
        daily_spent: float
        daily_limit: float
        active_workers: int
        total_workers: int
        last_message_at: Optional[str] = None


# ============ APP FACTORY ============

def create_app(config: dict) -> "FastAPI":
    """Creates and configures the FastAPI application."""
    if not HAS_FASTAPI:
        raise ImportError(
            "FastAPI ist nicht installiert. "
            "Installiere mit: pip install fastapi uvicorn"
        )

    server_cfg = config.get("server", {})
    auth_token = server_cfg.get("auth_token", "")
    cors_origins = server_cfg.get("cors_origins", [])

    app = FastAPI(
        title="BACH Claude Bridge API",
        version="1.0.0",
        docs_url="/docs",
    )

    # CORS
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # Startup time for uptime calculation
    _start_time = time.time()

    # Store daemon reference (set by start_server_mode)
    app.state.daemon = None
    app.state.config = config

    # ============ AUTH ============

    async def verify_token(request: Request):
        if not auth_token:
            return  # No auth configured
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing Bearer token")
        token = header[len("Bearer "):]
        if token != auth_token:
            raise HTTPException(status_code=403, detail="Invalid token")

    # ============ ENDPOINTS ============

    @app.post("/api/message", response_model=MessageResponse, dependencies=[Depends(verify_token)])
    async def send_message(req: MessageRequest):
        """Send a message to BACH via the bridge."""
        bd = _get_bridge()
        config = bd.load_config()
        connector = config.get("connector_name", "api")
        chat_id = req.sender

        try:
            bd.db_execute(
                "INSERT INTO connector_messages "
                "(connector_name, direction, sender, recipient, content, status, bridge_processed, created_at) "
                "VALUES (?, 'in', ?, '', ?, 'pending', 0, ?)",
                (connector, chat_id, req.text, datetime.now().isoformat())
            )
            return MessageResponse(ok=True, message="Message queued for processing")
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/api/status", response_model=StatusResponse, dependencies=[Depends(verify_token)])
    async def get_status():
        """Get bridge status."""
        bd = _get_bridge()
        config = bd.load_config()
        state = bd.load_state()
        pid = bd.get_running_pid()

        # Worker counts
        active_workers = 0
        total_workers = 0
        try:
            conn = bd.db_connect()
            active_workers = conn.execute(
                "SELECT COUNT(*) FROM claude_bridge_workers WHERE status = 'running'"
            ).fetchone()[0]
            total_workers = conn.execute(
                "SELECT COUNT(*) FROM claude_bridge_workers"
            ).fetchone()[0]
            conn.close()
        except Exception:
            pass

        uptime = time.time() - _start_time if pid else None

        return StatusResponse(
            running=pid is not None and pid > 0,
            pid=pid,
            mode=config.get("mode", "local"),
            uptime_seconds=uptime,
            permission_mode=state.get("permission_mode", "restricted"),
            session_active=state.get("has_active_session", False),
            daily_spent=state.get("daily_spent", 0.0),
            daily_limit=config.get("budget", {}).get("daily_limit_usd", 5.0),
            active_workers=active_workers,
            total_workers=total_workers,
            last_message_at=state.get("last_message_at"),
        )

    @app.post("/api/control", response_model=MessageResponse, dependencies=[Depends(verify_token)])
    async def control(req: ControlRequest):
        """Control the bridge daemon."""
        daemon = app.state.daemon
        if daemon is None:
            raise HTTPException(status_code=503, detail="Daemon not available in API-only mode")

        if req.action == "pause":
            daemon.stop_event.set()
            return MessageResponse(ok=True, message="Daemon paused")
        elif req.action == "resume":
            daemon.stop_event.clear()
            return MessageResponse(ok=True, message="Daemon resumed")
        elif req.action == "reload_config":
            daemon.config = _get_bridge().load_config()
            return MessageResponse(ok=True, message="Config reloaded")
        else:
            raise HTTPException(status_code=400, detail=f"Unknown action: {req.action}")

    return app
