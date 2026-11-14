# -*- coding: utf-8 -*-
from pathlib import Path
import importlib.util
import sys
import pytest

src_file = Path(__file__).parent.parent / "src" / "agents.py"
spec = importlib.util.spec_from_file_location("standalone_agents_mod", src_file)
agents_mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = agents_mod
spec.loader.exec_module(agents_mod)
AgentRegistry = agents_mod.AgentRegistry
AgentMetadata = agents_mod.AgentMetadata


def test_agent_registration():
    reg = AgentRegistry()
    assert reg.register_agent(
        name="bueroassistent",
        role="Büroorganisation und Ablage",
        category="office",
        is_boss=True,
        skills=["briefe", "rechnungen"],
    ) is True

    agent = reg.get_agent("bueroassistent")
    assert agent is not None
    assert agent.is_boss is True
    assert "briefe" in agent.skills


def test_agent_filtering_and_summary():
    reg = AgentRegistry()
    reg.register_agent(name="boss_1", is_boss=True, tier="thinker_reviewer")
    reg.register_agent(name="expert_1", is_boss=False, tier="worker")
    reg.register_agent(name="expert_2", is_boss=False, tier="light_worker")

    summary = reg.get_status_summary()
    assert summary["total_agents"] == 3
    assert summary["bosses"] == 1
    assert summary["experts"] == 2

    workers = reg.list_agents(tier="worker")
    assert len(workers) == 1
    assert workers[0].name == "expert_1"


def test_agent_routing():
    reg = AgentRegistry()
    reg.register_agent(
        name="steuer_experte",
        role="Finanzen und Belege",
        category="finance",
        skills=["steuer", "belege"],
    )
    reg.register_agent(
        name="code_experte",
        role="Software und Testing",
        category="dev",
        skills=["python", "pytest"],
    )

    routed = reg.route_task("Bitte prüfe die Steuer der letzten Belege", category="finance")
    assert routed is not None
    assert routed.name == "steuer_experte"

    routed_dev = reg.route_task("Schreibe einen Python Unit-Test")
    assert routed_dev is not None
    assert routed_dev.name == "code_experte"
