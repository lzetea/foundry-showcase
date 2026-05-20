"""
Scenario registry — maps a scenario name to an :class:`AgentHandle`.

Each scenario module under ``agents/<scenario>/`` exposes a ``scenario.py``
with a module-level ``build_handle()`` function returning an ``AgentHandle``.
The registry lazy-imports scenario modules so that missing optional
dependencies (e.g. LangGraph, Agent Framework) in one scenario do not break
the others.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Callable

# Scenarios are identified by the folder name under ``agents/``.
SCENARIOS: list[str] = [
    "01_prompt_agent",
    "02_langgraph_aca",
    "03_multi_agent",
    "04_foundry_tools_agent",
]


@dataclass
class AgentHandle:
    """Everything shared scripts need to target an agent.

    Attributes:
        scenario: Folder name (e.g. ``"01_prompt_agent"``).
        name: Foundry agent asset name (used as the eval/red-team target).
        version: Agent version (or ``"latest"`` for external agents).
        invoke: ``(query: str) -> str`` callable used by ``trace.py``.
            Scenarios that do not run locally (e.g. external ACA agents)
            should still expose an ``invoke`` that calls the registered
            agent through the Foundry Responses API so tracing works.
    """

    scenario: str
    name: str
    version: str
    invoke: Callable[[str], str]


def get_handle(scenario: str) -> AgentHandle:
    """Lazy-import the scenario adapter and return its handle."""
    if scenario not in SCENARIOS:
        raise ValueError(
            f"Unknown scenario {scenario!r}. Known: {', '.join(SCENARIOS)}"
        )
    # Scenario folder names start with digits, which is not a valid Python
    # identifier prefix — but importlib accepts the string path just fine.
    module = importlib.import_module(f"agents.{scenario}.scenario")
    return module.build_handle()
