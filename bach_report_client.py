# SPDX-License-Identifier: MIT
"""Root-level report client shim for BACH's source-backed editable install."""
from __future__ import annotations

from pathlib import Path
import sys


def create_report_control_client():
    """Use this installed checkout's system module; never infer an external path."""
    system_dir = Path(__file__).resolve().parent / "system"
    client_file = system_dir / "hub" / "_services" / "document" / "report_operator_client.py"
    if not client_file.is_file():
        raise RuntimeError("control_report_client_not_installed")
    system_path = str(system_dir)
    if system_path not in sys.path:
        sys.path.insert(0, system_path)
    from hub._services.document.report_operator_client import create_report_control_client as create

    return create()
