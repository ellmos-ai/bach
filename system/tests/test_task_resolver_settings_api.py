"""#2661: device-bound GET/PUT for the resolver task owner."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from system.tests.test_worker_policy_settings import _auth, api, db_path  # noqa: F401

PATH = "/api/system/task-resolver-settings"


def test_put_is_observed_by_get_rejects_stale_versions_and_needs_a_device(api):
    before = api.client.get(PATH, headers=_auth(api))
    assert before.status_code == 200 and before.json()["assignee"] == "BACH"
    payload = {"configuration_version": before.json()["configuration_version"], "assignee": "CODEX"}
    assert api.client.put(PATH, headers=_auth(api), json=payload).status_code == 200
    after = api.client.get(PATH, headers=_auth(api)).json()
    assert (after["assignee"], after["source"]) == ("CODEX", "user_override")
    assert api.client.put(PATH, headers=_auth(api), json=payload).status_code == 409
    bad = {"configuration_version": after["configuration_version"], "assignee": "zwei Wörter"}
    assert api.client.put(PATH, headers=_auth(api), json=bad).status_code == 400
    assert api.client.get(PATH).status_code == 401
