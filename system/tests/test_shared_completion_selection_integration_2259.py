from gui.api.shared_completion_selection_integration import build_shared_completion_selection_contract


def test_shared_completion_selection_contract_guards_and_identity():
    c1 = build_shared_completion_selection_contract(
        consumer="bach",
        gui_version="0.2.30",
        host="mac-studio",
        device="operator-mac",
        provider="anthropic",
        foreign_lease_active=True,
    )
    assert c1["carrier_product"] == "ellmos-system-gui"
    assert c1["legacy_web_copy_revived"] is False
    assert c1["guards"]["action_allowed"] is False
    assert c1["identity"]["host"] == "mac-studio"
    assert c1["identity"]["device"] == "operator-mac"
    assert c1["identity"]["provider"] == "anthropic"
