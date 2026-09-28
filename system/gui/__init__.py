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
from gui.board_renderers import (
    DEFAULT_AGENTS_BOARD_BRANDING,
    DEFAULT_TASKS_BOARD_BRANDING,
    get_agents_board_template,
    get_tasks_board_template,
    render_agents_board,
    render_tasks_board,
)

__all__ = [
    'DEFAULT_AGENTS_BOARD_BRANDING',
    'DEFAULT_BRANDING',
    'DEFAULT_TASKS_BOARD_BRANDING',
    'GUI_DIR',
    'STATIC_DIR',
    'TEMPLATES_DIR',
    'get_activity_dashboard_template',
    'get_agents_board_template',
    'get_tasks_board_template',
    'render_activity_dashboard',
    'render_agents_board',
    'render_tasks_board',
]
