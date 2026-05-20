"""
Unified adversarial red-team entrypoint.

Usage:
    python -m agents.shared.redteam --scenario 01_prompt_agent

Runs the shared red-team suite (Flip / Base64 / IndirectJailbreak across
prohibited-actions, task-adherence, sensitive-data-leakage) against the
scenario's registered agent.

**Scope:** the server-side red-team orchestrator targets Foundry-registered
agent assets via ``AzureAIAgentTarget(name, version)``. That works for
scenarios 01 and 04 (PromptAgents). Scenarios 02 and 03 are backed by a
Foundry project connection (not an agent asset), so this script prints a
clear "not-supported" message and points at the callback-based red-team in
``azure-ai-evaluation.red_team.RedTeam`` — see ``eval_utils.run_redteam``.
"""

from __future__ import annotations

import argparse

from agents.shared.config import get_clients
from agents.shared.eval_utils import run_redteam
from agents.shared.registry import SCENARIOS, get_handle


def main():
    parser = argparse.ArgumentParser(description="Unified agent red-team.")
    parser.add_argument("--scenario", required=True, choices=SCENARIOS)
    args = parser.parse_args()

    handle = get_handle(args.scenario)
    project_client, openai_client = get_clients()
    print(f"Agent: {handle.name} v{handle.version}  (scenario {handle.scenario})")

    run_redteam(project_client, openai_client, handle)

    print("\n" + "=" * 70)
    print("Red-team complete. View results in the Foundry portal → Evaluations → Red Team.")
    print("=" * 70)


if __name__ == "__main__":
    main()
