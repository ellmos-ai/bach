"""BACH #2231: device-bound GET/PUT for the creator-priority setting."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from system.tests.test_worker_policy_settings import ACTOR, _auth, _connect, api, db_path  # noqa: F401

PATH = "/api/system/task-lease-settings"


def test_put_is_observed_by_an_independent_get_and_rejects_stale_versions(api):
    before = api.client.get(PATH, headers=_auth(api))
    assert before.status_code == 200
    assert (before.json()["enabled"], before.json()["window_seconds"]) == (False, 120)
    payload = {"configuration_version": before.json()["configuration_version"],
               "enabled": True, "window_seconds": 120}
    written = api.client.put(PATH, headers=_auth(api), json=payload)
    assert written.status_code == 200 and written.json()["updated"] is True
    after = api.client.get(PATH, headers=_auth(api)).json()
    assert (after["enabled"], after["source"]) == (True, "user_override")
    assert api.client.put(PATH, headers=_auth(api), json=payload).status_code == 409
    bad = {**payload, "configuration_version": after["configuration_version"], "window_seconds": 0}
    assert api.client.put(PATH, headers=_auth(api), json=bad).status_code == 400


@pytest.mark.parametrize("method", ["GET", "PUT"])
@pytest.mark.parametrize("revoked", [False, True], ids=["missing-token", "revoked-token"])
def test_real_device_auth_protects_get_and_put(api, method, revoked):
    headers = _auth(api) if revoked else {}
    if revoked:
        with _connect(api.path) as conn:
            assert api.auth.revoke_device(ACTOR, connection=conn)
    response = api.client.request(method, PATH, headers=headers, json={} if method == "PUT" else None)
    assert response.status_code == (403 if revoked else 401)
