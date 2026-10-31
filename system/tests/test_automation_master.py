"""Tests für automation-master: Stufen, Testmodus, Budget, Overrides, Messung."""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


def _load(name, relpath):
    path = Path(__file__).resolve().parents[2] / ".MODULES" / ".CONTROL" / relpath
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


automation = _load(
    "ellmos-automation-master", "automation-master/automation_master.py"
)
delegation = _load(
    "ellmos-delegation-authority",
    "ellmos-delegation-authority/delegation_authority.py",
)


class AutomationMasterSettingsTests(unittest.TestCase):
    """Stufen, Events, Testmodus, Persistenz."""

    def test_bereiche_matchen_delegation_actions(self):
        self.assertEqual(tuple(automation.AREAS), tuple(delegation.ACTIONS))

    def test_standard_manuell_ohne_testmodus(self):
        master = automation.AutomationMaster()
        for area in automation.AREAS:
            self.assertEqual(master.get_autonomy(area), "manuell")
        self.assertFalse(master.is_test_mode())

    def test_set_autonomy_loest_event_aus(self):
        events = []
        master = automation.AutomationMaster(event_recorder=events.append)
        master.set_autonomy(
            "mail", "teilautomatisch", actor="buddha", reason="Erweiterter Testlauf"
        )
        self.assertEqual(master.get_autonomy("mail"), "teilautomatisch")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["module"], "ellmos-automation-master")
        self.assertEqual(events[0]["event"], "autonomy.changed")
        self.assertEqual(events[0]["area"], "mail")
        self.assertEqual(events[0]["autonomy_level"], "teilautomatisch")
        self.assertEqual(events[0]["actor"], "buddha")

    def test_unzulaessige_stufen_und_bereiche(self):
        master = automation.AutomationMaster()
        with self.assertRaises(automation.AutomationSettingsError):
            master.set_autonomy("linkedin", "turbo", actor="buddha", reason="Test")
        with self.assertRaises(automation.AutomationSettingsError):
            master.set_autonomy(
                "gibtsnicht", "vollautomatisch", actor="buddha", reason="Test"
            )
        with self.assertRaises(automation.AutomationSettingsError):
            master.get_autonomy("gibtsnicht")

    def test_testmodus_kappt_wirksame_stufe(self):
        events = []
        master = automation.AutomationMaster(event_recorder=events.append)
        master.set_autonomy(
            "linkedin", "vollautomatisch", actor="buddha", reason="Test"
        )
        master.set_test_mode(True, actor="buddha", reason="Testmodus an")
        self.assertTrue(master.is_test_mode())
        self.assertEqual(master.get_autonomy("linkedin"), "vollautomatisch")
        self.assertEqual(master.get_effective_autonomy("linkedin"), "teilautomatisch")
        settings = master.get_autonomy_settings("linkedin")
        self.assertEqual(settings.area, "linkedin")
        self.assertEqual(settings.autonomy_level, "vollautomatisch")
        self.assertEqual(settings.effective_level, "teilautomatisch")
        self.assertTrue(settings.test_mode)
        self.assertEqual(events[1]["event"], "test_mode.changed")
        self.assertTrue(events[1]["enabled"])

    def test_json_rundlauf(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "automation.json"
            master = automation.AutomationMaster(path=path)
            master.set_autonomy("mail", "teilautomatisch", actor="buddha", reason="Test")
            master.set_test_mode(True, actor="buddha", reason="Testmodus an")
            master.budget.set_limit("linkedin", 5000)
            master.budget.record_spend(
                "linkedin", 400, purpose="Kampagne", actor="claude-konsole"
            )
            master.metrics.record_outcome("linkedin", True)
            reloaded = automation.AutomationMaster(path=path)
            self.assertEqual(reloaded.get_autonomy("mail"), "teilautomatisch")
            self.assertTrue(reloaded.is_test_mode())
            self.assertEqual(reloaded.budget.get_limit("linkedin"), 5000)
            self.assertEqual(reloaded.budget.get_spent("linkedin"), 400)
            metrics = reloaded.metrics.get_metrics("linkedin")
            self.assertEqual(metrics["outcomes_total"], 1)
            self.assertEqual(metrics["outcomes_success"], 1)

    def test_arbeitsspeicher_master_unabhaengig(self):
        one = automation.AutomationMaster()
        two = automation.AutomationMaster()
        one.set_autonomy("linkedin", "vollautomatisch", actor="buddha", reason="Test")
        self.assertEqual(one.get_autonomy("linkedin"), "vollautomatisch")
        self.assertEqual(two.get_autonomy("linkedin"), "manuell")


class BudgetGovernanceTests(unittest.TestCase):
    """Limits, Ausgaben, Overrides."""

    def test_budgetablauf(self):
        master = automation.AutomationMaster()
        master.budget.set_limit("linkedin", 5000)
        allowed, reason = master.budget.check_spend_allowed("linkedin", 4000)
        self.assertTrue(allowed)
        self.assertIn("Budget ok", reason)
        master.budget.record_spend(
            "linkedin", 4000, purpose="Kampagne", actor="claude-konsole"
        )
        allowed, reason = master.budget.check_spend_allowed("linkedin", 2000)
        self.assertFalse(allowed)
        self.assertIn("Budget überschritten", reason)
        with self.assertRaises(automation.AutomationSettingsError):
            master.budget.record_spend(
                "linkedin", 2000, purpose="Kampagne", actor="claude-konsole"
            )
        self.assertEqual(master.budget.get_spent("linkedin"), 4000)

    def test_override_erhoeht_wirksames_limit(self):
        master = automation.AutomationMaster()
        master.budget.set_limit("youtube", 1000)
        entry = master.budget.grant_override(
            "youtube",
            granted_by="buddha",
            reason="Produktlaunch",
            extra_budget_cents=5000,
            hours=2,
        )
        self.assertTrue(entry["override_id"].startswith("ovr-"))
        self.assertEqual(master.budget.effective_limit("youtube"), 6000)
        master.budget.record_spend(
            "youtube", 6000, purpose="Produktlaunch", actor="buddha"
        )
        self.assertEqual(master.budget.get_spent("youtube"), 6000)

    def test_abgelaufener_override_zaehlt_nicht(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "automation.json"
            master = automation.AutomationMaster(path=path)
            master.budget.set_limit("youtube", 1000)
            master.budget.grant_override(
                "youtube",
                granted_by="buddha",
                reason="Produktlaunch",
                extra_budget_cents=5000,
                hours=2,
            )
            data = json.loads(path.read_text(encoding="utf-8"))
            data["budget"]["overrides"][0]["expires_at"] = "2000-01-01T00:00:00+00:00"
            path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            reloaded = automation.AutomationMaster(path=path)
            self.assertEqual(reloaded.budget.effective_limit("youtube"), 1000)
            allowed, reason = reloaded.budget.check_spend_allowed("youtube", 2000)
            self.assertFalse(allowed)
            self.assertEqual(reloaded.budget.get_overrides(active_only=True), [])
            self.assertEqual(len(reloaded.budget.get_overrides()), 1)

    def test_override_und_schutzregeln(self):
        master = automation.AutomationMaster()
        with self.assertRaises(automation.AutomationSettingsError):
            master.budget.grant_override(
                "youtube",
                granted_by="codex",
                reason="Test",
                extra_budget_cents=100,
                hours=1,
            )
        with self.assertRaises(automation.AutomationSettingsError):
            master.budget.record_spend(
                "mail", 100, purpose="Test", actor="claude-konsole"
            )
        allowed, reason = master.budget.check_spend_allowed(
            "bildschirmsteuerung", 1000000
        )
        self.assertTrue(allowed)
        self.assertIn("keine Budget-Governance", reason)


class MetricsTests(unittest.TestCase):
    """Messung je Bereich."""

    def test_metriken_und_qualitaetsrate(self):
        master = automation.AutomationMaster()
        master.metrics.record_outcome("linkedin", True)
        master.metrics.record_outcome("linkedin", False)
        master.metrics.record_outcome("linkedin", True)
        master.metrics.record_error("linkedin")
        master.metrics.record_intervention("linkedin", "human")
        master.metrics.record_intervention("linkedin", "override")
        metrics = master.metrics.get_metrics("linkedin")
        self.assertEqual(metrics["outcomes_total"], 3)
        self.assertEqual(metrics["outcomes_success"], 2)
        self.assertEqual(metrics["errors"], 1)
        self.assertEqual(metrics["interventions_human"], 1)
        self.assertEqual(metrics["interventions_override"], 1)
        self.assertEqual(master.metrics.quality_rate("linkedin"), 2 / 3)
        self.assertIsNone(master.metrics.quality_rate("youtube"))
        with self.assertRaises(automation.AutomationSettingsError):
            master.metrics.record_intervention("linkedin", "alien")

    def test_alle_bereiche_im_snapshot(self):
        master = automation.AutomationMaster()
        all_metrics = master.metrics.get_metrics()
        self.assertEqual(tuple(sorted(all_metrics)), tuple(sorted(automation.AREAS)))


class DecideTests(unittest.TestCase):
    """decide läuft über delegation-authority mit der wirksamen Stufe."""

    def test_decide_ueber_die_stufen(self):
        events = []
        master = automation.AutomationMaster(event_recorder=events.append)
        master.set_autonomy(
            "linkedin", "vollautomatisch", actor="buddha", reason="Test"
        )
        decision = master.decide("linkedin", "codex")
        self.assertEqual(decision.decision, "erlaubt")
        self.assertTrue(decision.inform)
        master.set_test_mode(True, actor="buddha", reason="Testmodus an")
        decision = master.decide("linkedin", "codex")
        self.assertEqual(decision.decision, "rueckfrage")
        self.assertFalse(decision.inform)
        decision = master.decide("linkedin", "codex", direct_order=True)
        self.assertEqual(decision.decision, "erlaubt")
        self.assertFalse(decision.inform)
        decide_events = [
            event for event in events if event.get("event") == "automation.decide"
        ]
        self.assertEqual(len(decide_events), 3)
        self.assertEqual(decide_events[0]["module"], "ellmos-automation-master")

    def test_decide_unbekannter_akteur(self):
        master = automation.AutomationMaster()
        with self.assertRaises(delegation.PermissionDenied):
            master.decide("linkedin", "unbekannt")

    def test_modul_decide_direkt(self):
        decision = automation.decide(
            "linkedin", "codex", autonomy_level="vollautomatisch"
        )
        self.assertEqual(decision.decision, "erlaubt")
        self.assertTrue(decision.inform)


if __name__ == "__main__":
    unittest.main()