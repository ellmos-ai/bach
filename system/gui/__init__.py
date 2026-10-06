# SPDX-License-Identifier: MIT
"""
BACH GUI Module
===============
Web-Dashboard fuer BACH v1.1
"""

from pathlib import Path

GUI_DIR = Path(__file__).parent
TEMPLATES_DIR = GUI_DIR / "templates"
STATIC_DIR = GUI_DIR / "static"

from gui.activity_dashboard import (
    DEFAULT_BRANDING,
    get_activity_dashboard_template,
    render_activity_dashboard,
)

__all__ = [
    'DEFAULT_BRANDING',
    'GUI_DIR',
    'STATIC_DIR',
    'TEMPLATES_DIR',
    'get_activity_dashboard_template',
    'render_activity_dashboard',
]
