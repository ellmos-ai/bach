"""Unsupported durable saves must reject without publishing partial admission state."""

import copy
import json
import os

import pytest
from hub._services.chat import slots_config


@pytest.mark.skipif(os.name != "nt", reason="Native Windows unsupported-durability boundary")
@pytest.mark.parametrize("existing", [False, True])
def test_unsupported_durable_save_preserves_config_and_filesystem(tmp_path, existing):
    target = tmp_path / "state" / "slots.json"
    if existing:
        target.parent.mkdir()
        target.write_bytes(b'{"marker":"before"}\n')
    payload = {"marker": "after"}
    original = copy.deepcopy(payload)

    with pytest.raises(OSError, match="POSIX-Verzeichnissync"):
        slots_config.save_slots_config(payload, str(target), durable=True)

    assert payload == original
    if existing:
        assert target.read_bytes() == b'{"marker":"before"}\n'
        assert sorted(item.name for item in target.parent.iterdir()) == ["slots.json"]
    else:
        assert not target.parent.exists()


@pytest.mark.parametrize("existing", [False, True])
def test_ordinary_slot_save_still_creates_and_replaces_files(tmp_path, existing):
    target = tmp_path / "ordinary" / "slots.json"
    if existing:
        target.parent.mkdir()
        target.write_text('{"marker":"before"}', encoding="utf-8")
    slots_config.save_slots_config({"marker": "ordinary"}, str(target))
    observed = json.loads(target.read_text(encoding="utf-8"))
    assert observed["marker"] == "ordinary"
    assert isinstance(observed["updated_at"], str)


@pytest.mark.skipif(os.name != "posix", reason="Native POSIX directory fsync boundary")
def test_posix_durable_slot_save_still_publishes(tmp_path):
    target = tmp_path / "durable" / "slots.json"
    slots_config.save_slots_config({"marker": "durable"}, str(target), durable=True)
    assert json.loads(target.read_text(encoding="utf-8"))["marker"] == "durable"
