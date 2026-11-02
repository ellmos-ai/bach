"""Private in-memory auth-owner fixtures; no production credentials or DB."""
import contextlib
import io
import json
import os
import secrets
import sqlite3
import tempfile
import unittest
import uuid
from pathlib import Path

from gui import device_auth
from hub._services import task_result_operator_rotation as owner
from hub._services.task_result_service import ResultConflict, ResultPermissionDenied, _operator_capabilities


class RotationTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.actor = device_auth.create_task_result_operator(
            "private-maintainer", connection=self.conn, can_request_correction=True)
        self.old = device_auth.create_task_result_operator(
            "ticket-master-review-luna-session01a176e7", connection=self.conn, can_request_correction=True)
        self.conn.execute("UPDATE devices SET id=45 WHERE name='private-maintainer'")
        self.conn.execute("UPDATE devices SET id=47 WHERE name='ticket-master-review-luna-session01a176e7'")
        self.conn.execute("UPDATE task_result_operators SET device_id=45 WHERE device_id=1")
        self.conn.execute("UPDATE task_result_operators SET device_id=47 WHERE device_id=2")
        self.conn.commit()
        self.assertTrue(device_auth.revoke_device("ticket-master-review-luna-session01a176e7", connection=self.conn))
        self.expected = owner.rotation_snapshot(self.conn, 47, operator_token=self.actor, expected_actor_device_id=45)
        self.temp = tempfile.TemporaryDirectory(prefix="private-operator-rotation-")
        self.root = Path(self.temp.name)
        os.chmod(self.root, 0o700)
        self.credential = self.root / "ticket-master-review-luna-session01a176e7.txt"
        self.credential.write_text(self.old + "\n", encoding="utf-8")
        os.chmod(self.credential, 0o600)
        self.request_id = str(uuid.uuid4())
        self.output = io.StringIO()
        self.capture = contextlib.redirect_stdout(self.output)
        self.capture.__enter__()

    def tearDown(self):
        self.capture.__exit__(None, None, None)
        self.assertFalse(self.old in self.output.getvalue())
        self.assertFalse(self.actor in self.output.getvalue())
        self.conn.close()
        self.temp.cleanup()

    def prepare(self):
        return owner.prepare_private_stage(self.credential, root=self.root,
                                          expected=self.expected, request_id=self.request_id, expected_actor_device_id=45)

    def rotate(self, stage):
        return owner.rotate_staged_operator_credential(
            self.conn, stage["intent_path"], root=self.root, operator_token=self.actor)

    def test_stage_before_effect_same_identity_capability_old_deny_new_allow(self):
        before = self.conn.total_changes
        stage = self.prepare()
        self.assertTrue(self.conn.total_changes == before)
        for key in ("intent_path", "stage_path", "backup_path"):
            if owner._POSIX_DIR_FD:
                self.assertTrue(Path(stage[key]).stat().st_mode & 0o777 == 0o600)
            else:
                self.assertTrue(Path(stage[key]).is_file())
        ack = self.rotate(stage)
        self.assertTrue(ack["device_id"] == 47 and ack["metadata"]["capability"] == self.expected["capability"])
        self.assertTrue(ack["metadata"]["device"]["name"] == self.expected["device"]["name"])
        self.assertTrue(device_auth.validate_token(self.old, connection=self.conn) is None)
        installed = owner.install_confirmed_stage(self.conn, stage["intent_path"], root=self.root,
                                                  operator_token=self.actor)
        new = self.credential.read_text().strip()
        self.assertTrue(installed["file_installed"] and device_auth.validate_token(new, connection=self.conn)["id"] == 47)
        self.assertTrue(_operator_capabilities(self.conn, new) == {"accept_result": True, "request_correction": True})
        self.assertFalse(new in self.output.getvalue())
        audit = " ".join(str(tuple(row)) for row in self.conn.execute(f"SELECT * FROM {owner._AUDIT}"))
        self.assertFalse(any(value in audit for value in (new, self.old, self.actor)))
        self.assertFalse(device_auth._hash_token(new) in audit)

    def test_ack_loss_read_recovery_and_install_are_forward_only(self):
        stage = self.prepare()
        first = self.rotate(stage)
        changes = self.conn.total_changes
        value = Path(stage["stage_path"]).read_text().strip()
        recovered = owner.rotation_receipt(self.conn, 47, expected=self.expected,
            request_id=self.request_id, replacement_token=value, operator_token=self.actor, expected_actor_device_id=45)
        self.assertTrue(recovered["event_id"] == first["event_id"] and recovered["current_credential_confirmed"])
        self.assertTrue(self.conn.total_changes == changes)
        owner.install_confirmed_stage(self.conn, stage["intent_path"], root=self.root, operator_token=self.actor)
        owner.install_confirmed_stage(self.conn, stage["intent_path"], root=self.root, operator_token=self.actor)
        self.assertTrue(self.conn.total_changes == changes)
        self.assertTrue(self.conn.execute(f"SELECT count(*) FROM {owner._AUDIT}").fetchone()[0] == 1)

    def test_unknown_not_applied_does_not_install_or_rotate(self):
        stage = self.prepare()
        changes = self.conn.total_changes
        result = owner.install_confirmed_stage(self.conn, stage["intent_path"], root=self.root,
                                               operator_token=self.actor)
        self.assertTrue(result["state"] == "unconfirmed" and not result["file_installed"])
        self.assertTrue(self.conn.total_changes == changes and self.credential.read_text().strip() == self.old)
        self.assertTrue(Path(stage["stage_path"]).exists())

    def test_existing_intent_never_generates_second_stage(self):
        self.prepare()
        with self.assertRaises(ResultConflict):
            self.prepare()

    def test_wrong_original_credential_is_not_rotated(self):
        self.credential.write_text(self.actor + "\n")
        stage = self.prepare()
        with self.assertRaises(ResultConflict):
            self.rotate(stage)
        self.assertTrue(self.conn.execute("SELECT status FROM devices WHERE id=47").fetchone()[0] == "revoked")

    def test_target_identity_and_capability_races_deny(self):
        for statement in ("UPDATE devices SET name='private-changed' WHERE id=47",
                          "UPDATE task_result_operators SET can_request_correction=0 WHERE device_id=47"):
            with self.subTest(case=statement.split()[1]):
                old_device = dict(self.conn.execute("SELECT * FROM devices WHERE id=47").fetchone())
                old_cap = self.conn.execute("SELECT can_request_correction FROM task_result_operators WHERE device_id=47").fetchone()[0]
                self.conn.execute(statement)
                self.conn.commit()
                with self.assertRaises(ResultConflict):
                    owner._rotate_operator_credential(self.conn, 47, expected=self.expected,
                        request_id=str(uuid.uuid4()), replacement_token=secrets.token_urlsafe(32), operator_token=self.actor, expected_actor_device_id=45)
                self.conn.execute("UPDATE devices SET name=? WHERE id=47", (old_device["name"],))
                self.conn.execute("UPDATE task_result_operators SET can_request_correction=? WHERE device_id=47", (old_cap,))
                self.conn.commit()

    def test_wrong_or_revoked_authorizer_denied(self):
        for token in ("private-invalid", self.old):
            with self.assertRaises(ResultPermissionDenied):
                owner.rotation_snapshot(self.conn, 47, operator_token=token, expected_actor_device_id=45)
        with self.assertRaises(ResultPermissionDenied):
            owner.rotation_snapshot(self.conn, 45, operator_token=self.actor, expected_actor_device_id=45)

    def test_other_active_correction_operator_cannot_choose_actor_policy(self):
        other = device_auth.create_task_result_operator(
            "private-other-correction-operator", connection=self.conn, can_request_correction=True)
        stage = self.prepare()
        changes = self.conn.total_changes
        for expected_actor in (45, 48):
            with self.assertRaises(ResultPermissionDenied):
                owner.rotation_snapshot(self.conn, 47, operator_token=other,
                                        expected_actor_device_id=expected_actor)
        with self.assertRaises(ResultPermissionDenied):
            owner.rotate_staged_operator_credential(self.conn, stage["intent_path"],
                                                   root=self.root, operator_token=other)
        with self.assertRaises(ResultPermissionDenied):
            owner.install_confirmed_stage(self.conn, stage["intent_path"],
                                          root=self.root, operator_token=other)
        self.assertTrue(self.conn.total_changes == changes)
        self.assertTrue(self.conn.execute("SELECT status FROM devices WHERE id=47").fetchone()[0] == "revoked")
        self.assertFalse(other in self.output.getvalue())

    def test_actor_metadata_race_and_intent_policy_forgery_deny(self):
        stage = self.prepare()
        intent = json.loads(Path(stage["intent_path"]).read_text())
        self.assertTrue(intent["expected_actor_device_id"] == 45)
        self.assertTrue(intent["expected"]["actor_preimage"]["device"]["id"] == 45)
        self.conn.execute("UPDATE devices SET name='private-maintainer-changed' WHERE id=45")
        self.conn.commit()
        with self.assertRaises(ResultConflict):
            self.rotate(stage)
        intent["expected_actor_device_id"] = 48
        Path(stage["intent_path"]).write_text(json.dumps(intent))
        with self.assertRaises(ResultPermissionDenied):
            self.rotate(stage)
        self.assertTrue(self.conn.execute("SELECT status FROM devices WHERE id=47").fetchone()[0] == "revoked")

    def test_audit_failure_rolls_back_token_and_activation(self):
        stage = self.prepare()
        self.conn.execute("BEGIN")
        owner._ensure_audit(self.conn)
        self.conn.execute(f"CREATE TRIGGER fail_private_audit BEFORE INSERT ON {owner._AUDIT} BEGIN SELECT RAISE(ABORT,'private audit failure'); END")
        self.conn.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            self.rotate(stage)
        self.assertTrue(self.conn.execute("SELECT status FROM devices WHERE id=47").fetchone()[0] == "revoked")
        self.assertTrue(device_auth.validate_token(self.old, connection=self.conn) is None)
        self.assertTrue(Path(stage["stage_path"]).exists())

    def test_actor_mutation_during_target_update_rolls_back_back_both_devices(self):
        stage = self.prepare()
        self.conn.execute("CREATE TRIGGER private_actor_race AFTER UPDATE OF token_hash ON devices "
                          "WHEN NEW.id=47 BEGIN UPDATE devices SET name='private-actor-raced' WHERE id=45; END")
        self.conn.commit()
        with self.assertRaises(ResultConflict):
            self.rotate(stage)
        self.assertTrue(self.conn.execute("SELECT status FROM devices WHERE id=47").fetchone()[0] == "revoked")
        self.assertTrue(self.conn.execute("SELECT name FROM devices WHERE id=45").fetchone()[0] == "private-maintainer")
        self.assertTrue(Path(stage["stage_path"]).exists())

    def test_symlink_and_file_drift_deny(self):
        stage = self.prepare()
        self.rotate(stage)
        self.credential.write_text("private-drift\n")
        with self.assertRaises(ResultConflict):
            owner.install_confirmed_stage(self.conn, stage["intent_path"], root=self.root, operator_token=self.actor)
        other = self.root / "private-symlink.txt"
        try:
            other.symlink_to(self.credential.name)
        except OSError:
            return
        with self.assertRaises((OSError, ResultConflict)):
            owner.prepare_private_stage(other, root=self.root, expected=self.expected, request_id=str(uuid.uuid4()), expected_actor_device_id=45)


if __name__ == "__main__":
    unittest.main()
