"""
Unified evaluation entrypoint.

Usage:
    python -m agents.shared.evaluate --scenario 01_prompt_agent
    python -m agents.shared.evaluate --scenario 02_langgraph_aca --suite quality safety

Runs quality / safety / agentic evaluations against every scenario using the
**local-generation + remote-judges** pattern (see ``eval_utils``): responses
are produced by ``handle.invoke`` inside OTel spans tagged with the eval
run name, and the pre-generated items are submitted to Foundry evals via a
``jsonl`` data source. This gives a single uniform code path across all 4
scenarios — including scenarios 02 / 03 whose "asset" is a Foundry project
connection rather than a registered PromptAgent.
"""

from __future__ import annotations

import argparse

from agents.shared.config import MODEL_NAME, get_clients
from agents.shared.eval_utils import (
    run_agentic_evaluation,
    run_quality_evaluation,
    run_safety_evaluation,
)
from agents.shared.registry import SCENARIOS, get_handle

SUITES = {"quality", "safety", "agentic"}


def main():
    parser = argparse.ArgumentParser(description="Unified agent evaluation.")
    parser.add_argument("--scenario", required=True, choices=SCENARIOS)
    parser.add_argument(
        "--suite",
        nargs="+",
        choices=sorted(SUITES),
        default=sorted(SUITES),
        help="Evaluation suites to run (default: all).",
    )
    args = parser.parse_args()

    handle = get_handle(args.scenario)
    _, openai_client = get_clients()
    print(f"Agent: {handle.name} v{handle.version}  (scenario {handle.scenario})")

    if "quality" in args.suite:
        run_quality_evaluation(openai_client, handle, MODEL_NAME)
    if "safety" in args.suite:
        run_safety_evaluation(openai_client, handle)
    if "agentic" in args.suite:
        run_agentic_evaluation(openai_client, handle)

    print("\n" + "=" * 70)
    print("Evaluation complete. View results in the Foundry portal → Evaluations.")
    print("Filter the Tracing pane by ``evaluation.run_name`` to see the")
    print("agent traces that backed each row of the eval run.")
    print("=" * 70)


if __name__ == "__main__":
    main()
