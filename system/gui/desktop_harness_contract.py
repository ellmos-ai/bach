# coding: utf-8
"""Desktop-Harness nach Plan #2053 (#2337):
- Gemeinsamer Träger: ellmos-system-gui (kein separates Desktop-Repo)
- Tauri-2 Remote-Attach mit strikter Origin-Grenze und ohne Remote-IPC-Rechte
- Lokale Anschlussseite darf ausschließlich asynchronen Capabilities-Probe ausführen
  (keine impliziten Prozess-, Worker-, Modell- oder Git-Starts)
- Erhalt bestehender Ocean-Session / BACH-Geräteanmeldung im Remote-Webview
- Lease/Fence-Prüfung und Ausführungsreceipt für Geräteabnahme
"""
from __future__ import annotations
import hashlib
import json
from typing import Any
from urllib.parse import urlparse

ALLOWED_SCHEMES = frozenset({"http", "https"})


def validate_remote_attach_origin(origin_url: str, allowed_origins: list[str] | set[str]) -> dict[str, Any]:
    """Prüft die exakte Origin-Grenze für das Tauri-Remote-Webview."""
    parsed = urlparse(origin_url.strip())
    if parsed.scheme not in ALLOWED_SCHEMES or not parsed.netloc:
        raise ValueError(f"Ungültige Origin-URL: {origin_url}")
    normalized = f"{parsed.scheme}://{parsed.netloc}".lower()
    allowed_norm = {u.rstrip("/").lower() for u in allowed_origins}
    if normalized not in allowed_norm:
        raise PermissionError(f"Origin nicht freigegeben: {normalized}")
    return {
        "origin": normalized,
        "remote_ipc_enabled": False,
        "spawns_local_processes": False,
        "preserves_device_cookie": True,
    }


def build_desktop_attach_receipt(
    *,
    host: str,
    platform_name: str,
    origin_url: str,
    allowed_origins: list[str],
    capabilities_status: int,
    fence: int,
    bundle_embeds_legacy_astro: bool = False,
) -> dict[str, Any]:
    """Erzeugt den verifizierten Geräteabnahme-Beleg für den Tauri-Desktop-Harness."""
    if bundle_embeds_legacy_astro:
        raise ValueError("Desktop-Shell darf keine veraltete Astro-Kopie bündeln")
    if capabilities_status != 200:
        raise RuntimeError(f"Capabilities-Probe fehlgeschlagen: HTTP {capabilities_status}")
    if fence <= 0:
        raise ValueError("Fence muss positiv sein")

    attach = validate_remote_attach_origin(origin_url, allowed_origins)
    payload = {
        "carrier_repo": "ellmos-system-gui",
        "process_supervisor": "open-ocean",
        "host": host,
        "platform": platform_name,
        "origin": attach["origin"],
        "remote_ipc_enabled": False,
        "spawns_local_processes": False,
        "windows_subsystem": "GUI",
        "capabilities_probe_http": capabilities_status,
        "fence": fence,
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    return {**payload, "receipt_sha256": digest}
