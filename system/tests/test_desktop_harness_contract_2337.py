import pytest
from gui.desktop_harness_contract import (
    build_desktop_attach_receipt,
    validate_remote_attach_origin,
)


def test_desktop_harness_remote_attach_and_device_receipt():
    allowed = ["http://127.0.0.1:8000", "http://100.119.69.90:8000"]
    attach = validate_remote_attach_origin("http://127.0.0.1:8000/agenten/living", allowed)
    assert attach["origin"] == "http://127.0.0.1:8000"
    assert attach["remote_ipc_enabled"] is False
    assert attach["spawns_local_processes"] is False

    with pytest.raises(PermissionError):
        validate_remote_attach_origin("https://evil.example.com", allowed)

    receipt = build_desktop_attach_receipt(
        host="mac-studio",
        platform_name="macos-aarch64",
        origin_url="http://127.0.0.1:8000",
        allowed_origins=allowed,
        capabilities_status=200,
        fence=3,
    )
    assert receipt["carrier_repo"] == "ellmos-system-gui"
    assert receipt["remote_ipc_enabled"] is False
    assert len(receipt["receipt_sha256"]) == 64
