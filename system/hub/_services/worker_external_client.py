# SPDX-License-Identifier: MIT
"""Remote-only operator SDK. No retries, redirects or local database fallback."""
from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import math
import re
import urllib.error
import urllib.parse
import urllib.request

MAX_ARTIFACT_BYTES = 2 * 1024 * 1024
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_BODY_BYTES = 3 * 1024 * 1024


class ExternalResultError(RuntimeError):
    def __init__(self, status=None):
        self.status = status
        super().__init__(f"Externer Ergebnisdienst nicht verfügbar (HTTP {status})" if status
                         else "Externer Ergebnisdienst nicht verfügbar")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _task_id(value):
    if type(value) is not int or value <= 0:
        raise ValueError("Positive Task-ID erforderlich")
    return value


def _artifact_id(value):
    if type(value) is not str or re.fullmatch(r"[a-f0-9]{32}", value) is None:
        raise ValueError("Gültige private Artefakt-ID erforderlich")
    return value


class WorkerExternalResultClient:
    """Use existing enrolled credentials; this client cannot enroll operators."""

    def __init__(self, *, lead_url, device_token, operator_token, timeout=15, trusted_tailnet_http=False):
        if type(trusted_tailnet_http) is not bool:
            raise ValueError("Explizite Transportentscheidung erforderlich")
        if type(lead_url) is not str:
            raise ValueError("Fester Lead erforderlich")
        try:
            parts = urllib.parse.urlsplit(lead_url)
            port = parts.port
        except (ValueError, TypeError):
            raise ValueError("Fester Lead erforderlich") from None
        if (parts.scheme not in {"http", "https"} or not parts.hostname
                or parts.username or parts.password or parts.query or parts.fragment
                or parts.path not in {"", "/"} or port == 0):
            raise ValueError("Fester Lead erforderlich")
        if parts.scheme == "http":
            try:
                address = ipaddress.ip_address(parts.hostname)
                trusted_transport = (address.is_loopback or trusted_tailnet_http and (
                    address in ipaddress.ip_network("100.64.0.0/10")
                    or address in ipaddress.ip_network("fd7a:115c:a1e0::/48")))
            except ValueError:
                trusted_transport = parts.hostname == "localhost"
            if not trusted_transport:
                raise ValueError("HTTPS oder eine lokale beziehungsweise Tailscale-IP erforderlich")
        for token in (device_token, operator_token):
            if (type(token) is not str or not 1 <= len(token) <= 256
                    or token != token.strip() or any(ord(c) < 33 or ord(c) > 126 for c in token)):
                raise ValueError("Bestehende Geräte- und Operatorberechtigung erforderlich")
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 120:
            raise ValueError("Begrenztes Timeout erforderlich")
        self._url = lead_url.rstrip("/")
        self._device = device_token
        self._operator = operator_token
        self._timeout = timeout
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())

    def _request(self, method, path, schema, payload=None):
        headers = {"Authorization": "Bearer " + self._device,
                   "X-BACH-Result-Operator": self._operator, "Accept": "application/json"}
        data = None
        if payload is not None:
            if type(payload) is not dict:
                raise ValueError("JSON-Objekt erforderlich")
            data = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
            if len(data) > MAX_BODY_BYTES:
                raise ValueError("Ergebnisauftrag ist zu groß")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self._url + path, data=data, headers=headers, method=method)
        try:
            with self._opener.open(req, timeout=self._timeout) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise ExternalResultError()
                result = json.loads(raw)
        except urllib.error.HTTPError as exc:
            exc.close()
            raise ExternalResultError(exc.code) from None
        except (urllib.error.URLError, OSError, TimeoutError, ValueError, RecursionError):
            # Never return a server's potentially private error body or URL.
            raise ExternalResultError() from None
        if type(result) is not dict or result.get("schema") != schema:
            raise ExternalResultError()
        return result

    def read_catalog(self):
        return self._request("GET", "/api/system/worker-model-principal-catalog",
                             "bach.worker-model-principal-catalog.v1")

    def write_catalog(self, payload):
        return self._request("PUT", "/api/system/worker-model-principal-catalog",
                             "bach.worker-model-principal-catalog.v1", payload)

    def read_sources(self):
        return self._request("GET", "/api/system/worker-external-principals",
                             "bach.worker-external-principals.v1")

    def write_sources(self, payload):
        return self._request("PUT", "/api/system/worker-external-principals",
                             "bach.worker-external-principals.v1", payload)

    def store_artifact(self, content, *, media_type):
        if type(content) is not bytes or not 0 < len(content) <= MAX_ARTIFACT_BYTES:
            raise ValueError("Artefakt muss 1 bis 2097152 Bytes enthalten")
        result = self._request("POST", "/api/system/worker-external-artifacts",
            "bach.worker-external-artifact.v1", {"media_type": media_type,
                "content_base64": base64.b64encode(content).decode("ascii")})
        if (result.get("sha256") != hashlib.sha256(content).hexdigest()
                or result.get("size_bytes") != len(content) or result.get("media_type") != media_type):
            raise ExternalResultError()
        _artifact_id(result.get("artifact_id"))
        return result

    def read_artifact(self, artifact_id):
        result = self._request("GET", "/api/system/worker-external-artifacts/" + _artifact_id(artifact_id),
                               "bach.worker-external-artifact.v1")
        try:
            content = base64.b64decode(result["content_base64"], validate=True)
            if (not 0 < len(content) <= MAX_ARTIFACT_BYTES
                    or result.get("artifact_id") != artifact_id
                    or result.get("sha256") != hashlib.sha256(content).hexdigest()
                    or result.get("size_bytes") != len(content)):
                raise ValueError("Invalid artifact")
        except (ValueError, KeyError, TypeError):
            raise ExternalResultError() from None
        return {key: value for key, value in result.items() if key != "content_base64"} | {"content": content}

    def attest(self, task_id, payload):
        result = self._request("POST", f"/api/tasks/{_task_id(task_id)}/result/external-attestation",
                               "bach.worker-external-attestation-ack.v1", payload)
        readback = result.get("readback")
        record = readback.get("result") if isinstance(readback, dict) else None
        scope = record.get("scope") if isinstance(record, dict) else None
        provenance = record.get("external_provenance") if isinstance(record, dict) else None
        if (type(result.get("task_id")) is not int or result["task_id"] != task_id
                or type(result.get("created")) is not bool
                or type(result.get("attested_result_id")) is not int
                or result["attested_result_id"] != payload.get("result_id")
                or type(readback) is not dict or type(readback.get("task_id")) is not int
                or readback["task_id"] != task_id
                or readback.get("schema") != "bach.task-result-readback.v1"
                or readback.get("verified") is not True or readback.get("status") != "review"
                or type(record) is not dict or type(record.get("result_id")) is not int
                or record["result_id"] != payload.get("result_id")
                or record.get("result_sha256") != payload.get("result_sha256")
                or record.get("source_kind") != "external_attested" or record.get("accepted") is not False
                or type(scope) is not dict or scope.get("availability") != "available"
                or type(provenance) is not dict or provenance.get("availability") != "available"
                or type(record.get("result_revision")) is not str
                or re.fullmatch(r"[a-f0-9]{64}", record["result_revision"]) is None
                or scope.get("result_revision") != record["result_revision"]
                or provenance.get("result_revision") != record["result_revision"]):
            raise ExternalResultError()
        return result

    def prepare_review(self, task_id, payload):
        result = self._request("POST", f"/api/tasks/{_task_id(task_id)}/result/external-review",
                               "bach.worker-external-review-ack.v1", payload)
        review = result.get("review")
        if (result.get("worker_started") is not False or result.get("accepted") is not False
                or type(review) is not dict or type(review.get("target_task_id")) is not int
                or review["target_task_id"] != task_id
                or type(review.get("target_result_id")) is not int
                or review["target_result_id"] != payload.get("result_id")
                or review.get("target_revision") != payload.get("result_revision")):
            raise ExternalResultError()
        return result
