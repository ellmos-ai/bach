# SPDX-License-Identifier: MIT
"""Backend-free shell resources extracted from BACH; safe to import alone."""
from .activity import (
    TEMPLATE_PATH,
    get_activity_dashboard_template,
    render_activity_dashboard,
)

__version__ = "0.1.0"
__all__ = ["TEMPLATE_PATH", "get_activity_dashboard_template", "render_activity_dashboard"]
