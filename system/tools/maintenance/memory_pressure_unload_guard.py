#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
memory_pressure_unload_guard.py — Sensor/Aktor-Waechter fuer racefreien Modell-Unload.

Zweck
    Reiner Sensor (Ist-Bestand abfragen) + Aktor (ein benanntes Modell freigeben).
    Diese Datei enthaelt bewusst KEINE Policy: sie entscheidet nicht, *wann*
    entladen wird. Die Entscheidung trifft der Aufrufer — der Adapter im
    Host-Inferenz-Gate ruft den Waechter ausschliesslich im gehaltenen
    exklusiven Inferenz-Lock auf (siehe docs/operations/watchdog-inference-unload.md).

Hintergrund
    `POST /api/generate {"keep_alive": 0}` quittiert mit `done_reason=unload`,
    bevor der Speicher tatsaechlich frei ist (beobachtet mit Ollama 0.33.3).
    `done_reason` ist also nur ein ACK, kein Nachweis. Verlaesslich ist
    ausschliesslich das Polling auf `GET /api/ps`: erst wenn das Modell dort
    nicht mehr auftaucht, gilt es als entladen.

Abhaengigkeiten
    Ausschliesslich Python-Standardbibliothek (urllib, json, time, argparse).

CLI
    python memory_pressure_unload_guard.py ps
    python memory_pressure_unload_guard.py wait --model qwen3:8b --timeout 30
    python memory_pressure_unload_guard.py unload --model qwen3:8b --timeout 30
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

__version__ = "1.0.0"

DEFAULT_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_REQUEST_TIMEOUT_S = 10.0
DEFAULT_POLL_S = 0.25
DEFAULT_UNLOAD_TIMEOUT_S = 30.0

__all__ = [
    "OllamaUnavailable",
    "OllamaResponseError",
    "list_running",
    "loaded_entries",
    "is_unloaded",
    "wait_until_unloaded",
    "unload",
]


class OllamaUnavailable(RuntimeError):
    """Ollama ist nicht erreichbar — der Speicherzustand ist unbekannt."""


class OllamaResponseError(RuntimeError):
    """Ollama antwortet, aber nicht mit der erwarteten Struktur."""


def _base_url(base_url=None):
    if base_url:
        return str(base_url).rstrip("/")
    raw = (os.environ.get("BACH_OLLAMA_HOST") or os.environ.get("OLLAMA_HOST") or "").strip()
    if not raw:
        return DEFAULT_BASE_URL
    if "://" not in raw:
        raw = "http://" + raw
    return raw.rstrip("/")


def _normalize_digest(value):
    if not value:
        return None
    text = str(value).strip().lower()
    if text.startswith("sha256:"):
        text = text[len("sha256:"):]
    return text or None


def _request(path, *, base_url=None, payload=None, timeout_s=DEFAULT_REQUEST_TIMEOUT_S):
    """Ein einzelner HTTP-Aufruf gegen die Ollama-API; liefert geparstes JSON."""
    url = _base_url(base_url) + path
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    method = "POST" if payload is not None else "GET"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            body = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:400]
        raise OllamaResponseError(f"Ollama antwortet {exc.code} auf {path}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise OllamaUnavailable(f"Ollama nicht erreichbar ({url}): {exc.reason}") from exc
    except OSError as exc:
        raise OllamaUnavailable(f"Ollama nicht erreichbar ({url}): {exc}") from exc
    if not body.strip():
        return {}
    try:
        return json.loads(body)
    except ValueError as exc:
        raise OllamaResponseError(f"Antwort auf {path} ist kein JSON") from exc


def list_running(*, base_url=None, timeout_s=DEFAULT_REQUEST_TIMEOUT_S):
    """Sensor: aktuell im Speicher gehaltene Modelle laut `GET /api/ps`."""
    payload = _request("/api/ps", base_url=base_url, timeout_s=timeout_s)
    models = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(models, list):
        raise OllamaResponseError("GET /api/ps liefert keine Modellliste")
    running = []
    for entry in models:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name") or entry.get("model")
        if not isinstance(name, str) or not name.strip():
            continue
        model = entry.get("model") if isinstance(entry.get("model"), str) else name
        running.append({
            "name": name,
            "model": model,
            "digest": _normalize_digest(entry.get("digest")),
            "size": entry.get("size"),
            "size_vram": entry.get("size_vram"),
            "expires_at": entry.get("expires_at"),
        })
    return running


def _matches(entry, name, digest=None):
    """Ein Bestandseintrag passt zu Name **oder** Digest (ODER-Verknuepfung).

    Bewusst konservativ: Ein Namens-Treffer bleibt auch dann ein Treffer, wenn
    der erwartete Digest abweicht. So meldet `is_unloaded()` niemals vorschnell
    "entladen", solange noch ein Modell unter demselben Namen laeuft.
    """
    if digest and entry.get("digest") and entry["digest"] == _normalize_digest(digest):
        return True
    if not name:
        return False
    wanted = str(name).strip().lower()
    for candidate in (entry.get("name"), entry.get("model")):
        if not isinstance(candidate, str) or not candidate.strip():
            continue
        candidate = candidate.strip().lower()
        if candidate == wanted or candidate.split(":")[0] == wanted.split(":")[0]:
            return True
    return False


def loaded_entries(name=None, digest=None, *, base_url=None, timeout_s=DEFAULT_REQUEST_TIMEOUT_S):
    """Sensor: alle laufenden Eintraege, die zu Name/Digest passen."""
    return [
        entry for entry in list_running(base_url=base_url, timeout_s=timeout_s)
        if _matches(entry, name, digest)
    ]


def is_unloaded(name=None, digest=None, *, base_url=None, timeout_s=DEFAULT_REQUEST_TIMEOUT_S):
    """Sensor/Verifikation: True, wenn kein passendes Modell mehr im Speicher liegt."""
    return not loaded_entries(name, digest, base_url=base_url, timeout_s=timeout_s)


def wait_until_unloaded(
    name=None,
    digest=None,
    *,
    timeout_s=DEFAULT_UNLOAD_TIMEOUT_S,
    poll_s=DEFAULT_POLL_S,
    base_url=None,
    request_timeout_s=DEFAULT_REQUEST_TIMEOUT_S,
):
    """Pollt `GET /api/ps`, bis das Modell verschwunden ist. True = entladen."""
    deadline = time.monotonic() + max(float(timeout_s), 0.0)
    interval = max(float(poll_s), 0.01)
    while True:
        if is_unloaded(name, digest, base_url=base_url, timeout_s=request_timeout_s):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(interval)


def unload(
    model,
    *,
    digest=None,
    base_url=None,
    timeout_s=DEFAULT_UNLOAD_TIMEOUT_S,
    poll_s=DEFAULT_POLL_S,
    request_timeout_s=DEFAULT_REQUEST_TIMEOUT_S,
    wait=True,
):
    """Aktor: Modell freigeben (`keep_alive=0`) und den ACK per Poll verifizieren.

    Rueckgabe: Report-Dict mit `unloaded` (True/False, bei wait=False None),
    `done_reason` (nur ACK, kein Nachweis!), `elapsed_s` und ggf. `warning`.
    """
    if not isinstance(model, str) or not model.strip():
        raise ValueError("Modellname fuer Unload fehlt")
    started = time.monotonic()
    ack = _request(
        "/api/generate",
        base_url=base_url,
        payload={"model": model, "keep_alive": 0},
        timeout_s=request_timeout_s,
    )
    done_reason = ack.get("done_reason") if isinstance(ack, dict) else None
    report = {
        "model": model,
        "digest": _normalize_digest(digest),
        "done_reason": done_reason,
        "unloaded": None,
        "elapsed_s": None,
    }
    if done_reason is not None and done_reason != "unload":
        report["warning"] = f"unerwartetes done_reason={done_reason!r} (nur ACK, kein Nachweis)"
    if not wait:
        return report
    report["unloaded"] = wait_until_unloaded(
        model,
        digest,
        timeout_s=timeout_s,
        poll_s=poll_s,
        base_url=base_url,
        request_timeout_s=request_timeout_s,
    )
    report["elapsed_s"] = round(time.monotonic() - started, 3)
    return report


def _main(argv=None):
    parser = argparse.ArgumentParser(
        description="Sensor/Aktor-Waechter fuer racefreien Ollama-Modell-Unload (stdlib-only)."
    )
    parser.add_argument("--base-url", default=None, help="Ollama-Basis-URL (Default: OLLAMA_HOST)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("ps", help="Laufende Modelle anzeigen")

    for name, help_text in (("wait", "Auf Unload warten"), ("unload", "Modell freigeben")):
        node = sub.add_parser(name, help=help_text)
        node.add_argument("--model", required=True, help="Modellname, z.B. qwen3:8b")
        node.add_argument("--digest", default=None, help="Optionaler Digest (sha256)")
        node.add_argument("--timeout", type=float, default=DEFAULT_UNLOAD_TIMEOUT_S)
        node.add_argument("--poll", type=float, default=DEFAULT_POLL_S)

    args = parser.parse_args(argv)
    try:
        if args.command == "ps":
            print(json.dumps(list_running(base_url=args.base_url), indent=2, ensure_ascii=False))
            return 0
        if args.command == "wait":
            gone = wait_until_unloaded(
                args.model, args.digest,
                timeout_s=args.timeout, poll_s=args.poll, base_url=args.base_url,
            )
            print(json.dumps({"model": args.model, "unloaded": gone}, ensure_ascii=False))
            return 0 if gone else 1
        report = unload(
            args.model, digest=args.digest,
            timeout_s=args.timeout, poll_s=args.poll, base_url=args.base_url,
        )
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0 if report.get("unloaded") else 1
    except OllamaUnavailable as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 2
    except OllamaResponseError as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(_main())
