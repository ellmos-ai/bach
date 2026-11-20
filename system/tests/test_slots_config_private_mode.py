import os
import stat

import pytest
from hub._services.chat import slots_config as slots


@pytest.mark.skipif(os.name != "posix", reason="POSIX file modes")
def test_slots_config_is_private_after_every_write(tmp_path):
    path = str(tmp_path / "slots.json")
    slots.initialize_slots_config(path)
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    # A pre-existing world-readable file is replaced by a private one on the next save.
    os.chmod(path, 0o644)
    config = slots.load_slots_config(path, strict=True)
    slots.save_slots_config(config, path)
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    slots.save_slots_config(config, path, durable=True)
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert not [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
