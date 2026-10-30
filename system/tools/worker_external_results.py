# SPDX-License-Identifier: MIT
"""Explicit operator CLI for the remote result service, with private file I/O."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hub._services.worker_external_client import (
    MAX_ARTIFACT_BYTES,
    MAX_BODY_BYTES,
    ExternalResultError,
    WorkerExternalResultClient,
)


def _read(path, limit):
    with Path(path).open("rb") as handle:
        content = handle.read(limit + 1)
    if len(content) > limit:
        raise ValueError("Eingabedatei ist zu groß")
    return content


def _private_output(path):
    """Create with restrictive access from the first instant, before any bytes."""
    if os.name != "nt":
        return os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    import ctypes
    import msvcrt
    from ctypes import wintypes

    class SecurityAttributes(ctypes.Structure):
        _fields_ = [("length", wintypes.DWORD), ("descriptor", wintypes.LPVOID),
                    ("inherit", wintypes.BOOL)]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    convert = advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW
    convert.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(wintypes.LPVOID),
                        ctypes.POINTER(wintypes.DWORD)]
    convert.restype = wintypes.BOOL
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                       ctypes.POINTER(SecurityAttributes), wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    kernel.LocalFree.argtypes = [wintypes.LPVOID]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    descriptor = wintypes.LPVOID()
    # Protected DACL: Owner Rights and SYSTEM only; no inherited directory ACEs.
    # Passing this at CREATE_NEW prevents a readable empty-file race before ACL setup.
    if not convert("D:P(A;;FA;;;SY)(A;;FA;;;OW)", 1, ctypes.byref(descriptor), None):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        attrs = SecurityAttributes(ctypes.sizeof(SecurityAttributes), descriptor, False)
        handle = create(str(Path(path).absolute()), 0x40000000, 0, ctypes.byref(attrs),
                        1, 0x80 | 0x00200000, None)
        if handle == wintypes.HANDLE(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return msvcrt.open_osfhandle(handle, os.O_WRONLY | os.O_BINARY)
        except BaseException:
            kernel.CloseHandle(handle)
            raise
    finally:
        kernel.LocalFree(descriptor)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Externe Ergebnisbelege über den nativen BACH-Dienst")
    parser.add_argument("--lead-url", default=os.environ.get("BACH_LEAD_URL"))
    parser.add_argument("--credentials-file", help="Private JSON-Datei mit device_token und operator_token")
    parser.add_argument("--trusted-tailnet-http", action="store_true",
                        help="HTTP zur Tailnet-IP nur bei separat geprüfter verschlüsselter Route erlauben")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("catalog", "sources"):
        command = commands.add_parser(name)
        command.add_argument("--payload", help="Expliziter CAS-Schreibauftrag; ohne diese Option nur lesen")
    store = commands.add_parser("artifact-store")
    store.add_argument("file")
    store.add_argument("--media-type", required=True,
                       choices=["application/json", "application/x-ndjson", "text/plain"])
    read = commands.add_parser("artifact-read")
    read.add_argument("artifact_id")
    read.add_argument("--output", required=True, help="Neue private Datei; vorhandene Dateien bleiben erhalten")
    for name in ("attest", "review"):
        command = commands.add_parser(name)
        command.add_argument("task_id", type=int)
        command.add_argument("--payload", required=True)
    args = parser.parse_args(argv)
    try:
        credentials = {"device_token": os.environ.get("BACH_DEVICE_TOKEN"),
                       "operator_token": os.environ.get("BACH_RESULT_OPERATOR_TOKEN")}
        if args.credentials_file:
            credentials = json.loads(_read(args.credentials_file, 4096))
            if type(credentials) is not dict or set(credentials) != {"device_token", "operator_token"}:
                raise ValueError("Ungültige private Berechtigungsdatei")
        client = WorkerExternalResultClient(lead_url=args.lead_url,
            trusted_tailnet_http=args.trusted_tailnet_http, **credentials)
        payload = json.loads(_read(args.payload, MAX_BODY_BYTES)) if getattr(args, "payload", None) else None
        if args.command in {"catalog", "sources"}:
            result = getattr(client, ("write_" if payload is not None else "read_") + args.command)(
                *([payload] if payload is not None else []))
        elif args.command == "artifact-store":
            result = client.store_artifact(_read(args.file, MAX_ARTIFACT_BYTES), media_type=args.media_type)
        elif args.command == "artifact-read":
            result = client.read_artifact(args.artifact_id)
            content = result.pop("content")
            # Exclusive creation: no accidental overwrite or symlink following.
            fd = _private_output(args.output)
            with os.fdopen(fd, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
        else:
            result = getattr(client, "attest" if args.command == "attest" else "prepare_review")(
                args.task_id, payload)
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0
    except (ExternalResultError, ValueError, OSError, TypeError, KeyError):
        print("Externer Ergebnisauftrag fehlgeschlagen; keine automatische Wiederholung.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
