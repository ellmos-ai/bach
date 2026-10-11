# SPDX-License-Identifier: MIT
"""Installed operator client factory for the existing authenticated Control RPC."""


def create_report_control_client():
    """Construct a client without transport, inference, or approval side effects.

    Empty device_token requests the existing local Control credential resolver.
    Each RPC still checks configured target identity and write authentication.
    """
    from gui.api.report_provider import _ControlReportProvider

    return _ControlReportProvider("")
