"""Live evidence rules for the Running hardware-fackel readout."""

import sqlite3

from gui.api import cluster_status


def _install_observations(monkeypatch, active, compute_lock=None):
    from hub import compute_lock as compute_lock_module

    monkeypatch.setattr(compute_lock_module, "get_fackel_preference", lambda **_kwargs: "ollama")
    monkeypatch.setattr(cluster_status, "_compute_lock", lambda: compute_lock or {
        "state": "none_reported", "reported_jobs": 0,
    })
    monkeypatch.setattr(cluster_status, "_capacity", lambda: {
        "state": "measured", "loaded_model_count": 1, "used_gib": 12.0,
        "occupied_units": 4, "loaded_models": ["qwen"],
    })
    monkeypatch.setattr(cluster_status, "_task_counts", lambda _path: (4, 1))
    monkeypatch.setattr(cluster_status, "_runtime_compute_turn", lambda: {
        "state": "owned_by_this_system" if active else "idle",
        "active": active,
        "observed_at": "2026-10-05T10:00:00+00:00",
        "reason_code": "local_inference_gate_active" if active else "no_local_inference_active",
        "priority": "background" if active else None,
        "foreground_waiters": 0,
    })


def test_flame_is_lit_only_for_a_live_local_inference(monkeypatch, tmp_path):
    _install_observations(monkeypatch, True)

    data = cluster_status.build_cluster_cockpit(tmp_path / "bach.db")

    assert data["fackel"]["ownership"]["state"] == "owned_by_this_system"
    assert data["fackel"]["ownership"]["holder"] == "BACH"
    assert data["fackel"]["ownership"]["flame"] is True
    assert data["fackel"]["flame_animated"] is True


def test_preference_and_loaded_model_do_not_light_idle_fackel(monkeypatch, tmp_path):
    _install_observations(monkeypatch, False)

    data = cluster_status.build_cluster_cockpit(tmp_path / "bach.db")

    assert data["fackel"]["preference"] == "ollama"
    assert data["fackel"]["capacity"]["loaded_model_count"] == 1
    assert data["fackel"]["ownership"]["state"] == "idle"
    assert data["fackel"]["ownership"]["flame"] is False
    assert data["fackel"]["flame_animated"] is False


def test_reported_competing_compute_job_keeps_fackel_unlit(monkeypatch, tmp_path):
    _install_observations(monkeypatch, True, {
        "state": "reported_unverified", "reported_jobs": 1,
    })

    data = cluster_status.build_cluster_cockpit(tmp_path / "bach.db")

    assert data["fackel"]["ownership"]["state"] == "competing_compute_reported"
    assert data["fackel"]["ownership"]["holder"] is None
    assert data["fackel"]["ownership"]["flame"] is False
    assert data["fackel"]["flame_animated"] is False


def test_unavailable_compute_lock_keeps_fackel_unlit(monkeypatch, tmp_path):
    _install_observations(monkeypatch, True, {
        "state": "unknown", "reported_jobs": None,
    })

    data = cluster_status.build_cluster_cockpit(tmp_path / "bach.db")

    assert data["fackel"]["ownership"]["state"] == "unknown"
    assert data["fackel"]["ownership"]["holder"] is None
    assert data["fackel"]["ownership"]["flame"] is False
    assert data["fackel"]["flame_animated"] is False


def test_task_counts_remain_available_for_existing_database(tmp_path):
    db_path = tmp_path / "bach.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE tasks (assigned_to TEXT)")
        conn.executemany("INSERT INTO tasks (assigned_to) VALUES (?)", [("user",), ("worker",)])

    assert cluster_status._task_counts(db_path) == (2, 1)
