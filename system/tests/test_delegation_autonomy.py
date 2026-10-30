"""Tests für Autonomiestufen in delegation-authority und agents-heart."""

import importlib.util
import sys
import unittest
from pathlib import Path


def _load(name, relpath):
    path = Path(__file__).resolve().parents[2] / ".MODULES" / ".CONTROL" / relpath
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


delegation = _load(
    "ellmos-delegation-authority",
    "ellmos-delegation-authority/delegation_authority.py",
)
heart = _load("ellmos-agents-heart", "agents-heart/agents_heart.py")


class DelegationAutonomyTests(unittest.TestCase):
    """evaluate_permission mit Autonomiestufen (EINE Entscheidungsebene)."""

    def test_default_manuell_bleibt_rueckfrage(self):
        events = []
        decision = delegation.evaluate_permission(
            "linkedin", "codex", event_recorder=events.append
        )
        self.assertEqual(decision.decision, "rueckfrage")
        self.assertTrue(decision.needs_ticket)
        self.assertFalse(decision.inform)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["autonomy_level"], "manuell")
        self.assertIn("direct_order", events[0])
        self.assertIn("inform", events[0])

    def test_vollautomatisch_ueberfuehrt_und_informiert(self):
        decision = delegation.evaluate_permission(
            "linkedin", "codex", autonomy_level="vollautomatisch"
        )
        self.assertEqual(decision.decision, "erlaubt")
        self.assertTrue(decision.inform)
        self.assertFalse(decision.needs_ticket)
        self.assertIn("vollautomatisch", decision.reason)

    def test_vollautomatisch_laesst_nie_unveraendert(self):
        decision = delegation.evaluate_permission(
            "linkedin", "hintergrundworker", autonomy_level="vollautomatisch"
        )
        self.assertEqual(decision.decision, "nie")

    def test_teilautomatisch_intern_erlaubt(self):
        decision = delegation.evaluate_permission(
            "bildschirmsteuerung", "codex", autonomy_level="teilautomatisch"
        )
        self.assertEqual(decision.decision, "erlaubt")
        self.assertFalse(decision.inform)

    def test_teilautomatisch_extern_bleibt_rueckfrage(self):
        decision = delegation.evaluate_permission(
            "linkedin", "codex", autonomy_level="teilautomatisch"
        )
        self.assertEqual(decision.decision, "rueckfrage")
        self.assertFalse(decision.inform)

    def test_teilautomatisch_extern_mit_auftrag_erlaubt(self):
        decision = delegation.evaluate_permission(
            "linkedin",
            "codex",
            autonomy_level="teilautomatisch",
            direct_order=True,
        )
        self.assertEqual(decision.decision, "erlaubt")
        self.assertFalse(decision.inform)

    def test_unbekannte_stufe_loest_value_error_aus(self):
        with self.assertRaises(ValueError):
            delegation.evaluate_permission(
                "linkedin", "codex", autonomy_level="turbo"
            )

    def test_explicitite_matrix_bleibt_massgebend(self):
        matrix = {"cells": {"linkedin": {"buddha": "erlaubt"}}}
        decision = delegation.evaluate_permission("linkedin", "buddha", matrix=matrix)
        self.assertEqual(decision.decision, "erlaubt")

    def test_permission_decision_inform_standard_false(self):
        decision = delegation.PermissionDecision(
            action="mail",
            actor="buddha",
            decision="erlaubt",
            reason="Test",
            source="matrix",
            needs_ticket=False,
            escalation_hint="",
            revision="v1",
        )
        self.assertFalse(decision.inform)


class AgentsHeartAutonomyTests(unittest.TestCase):
    """effective_autonomy_levels und begin_assignment mit Autonomie."""

    def test_safe_kappt_vollautomatisch(self):
        self.assertEqual(
            heart.effective_autonomy_levels({"linkedin": "vollautomatisch"}, "safe"),
            {"linkedin": "teilautomatisch"},
        )

    def test_full_laesst_vollautomatisch_stehen(self):
        self.assertEqual(
            heart.effective_autonomy_levels({"linkedin": "vollautomatisch"}, "full"),
            {"linkedin": "vollautomatisch"},
        )

    def test_none_geht_durch(self):
        self.assertIsNone(heart.effective_autonomy_levels(None, "safe"))

    def test_unbekannter_modus_loest_value_error_aus(self):
        with self.assertRaises(ValueError):
            heart.effective_autonomy_levels({"linkedin": "voll"}, "test")

    def test_kein_mapping_loest_value_error_aus(self):
        with self.assertRaises(ValueError):
            heart.effective_autonomy_levels(["linkedin"], "safe")

    def test_begin_assignment_kappt_in_safe(self):
        events = []
        assignment = heart.begin_assignment(
            role_id="task_worker",
            mode="safe",
            agent_instance_id="a",
            backend_id="b",
            model_id="m",
            slot_id="s",
            task_id=1,
            autonomy_levels={"linkedin": "vollautomatisch"},
            event_recorder=events.append,
        )
        self.assertEqual(assignment.autonomy_levels, {"linkedin": "teilautomatisch"})
        self.assertEqual(events[0]["autonomy_levels"], {"linkedin": "teilautomatisch"})

    def test_begin_assignment_ohne_autonomie_ohne_event_feld(self):
        events = []
        assignment = heart.begin_assignment(
            role_id="task_worker",
            mode="safe",
            agent_instance_id="a",
            backend_id="b",
            model_id="m",
            slot_id="s",
            task_id=1,
            event_recorder=events.append,
        )
        self.assertIsNone(assignment.autonomy_levels)
        self.assertNotIn("autonomy_levels", events[0])


if __name__ == "__main__":
    unittest.main()