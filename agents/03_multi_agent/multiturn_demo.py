"""Multi-turn demo driver for the Contoso Travel multi-agent (MAF) workflow.

Sends a coherent, multi-turn trip-planning conversation through the APIM
``/agents/maf`` Responses API, chaining each turn with ``previous_response_id``
so the workflow keeps context across turns. Every turn is routed by the triage
coordinator to a different specialist -> flights, hotels, cars, then the budget
validator -> exercising the full ``HandoffBuilder`` graph. Each turn produces a
rich multi-agent trace under the registered Foundry asset
(Operate > Assets > contoso-travel-maf-agent > Traces).

Run it (from the repo root, with PYTHONPATH set to the repo root):

    $env:PYTHONPATH = (Get-Location).Path
    python agents\\03_multi_agent\\multiturn_demo.py
"""

from __future__ import annotations

import time

from agents.shared.aca_connection import apim_agents_client, current_revision
from agents.shared.config import MAF_MODEL_NAME

CONTAINER_APP_NAME = "ca-maf-agent"
APIM_SUBROUTE = "maf"

# (expected specialist, user message). The turns build on each other (Tokyo,
# the same dates, the running total) so the conversation only makes sense with
# context carried across turns -- which is exactly what shows the orchestration.
TURNS: list[tuple[str, str]] = [
    (
        "flights",
        "I'm planning a business trip from San Francisco to Tokyo, leaving next "
        "month for 3 nights. Find me business-class flight options.",
    ),
    (
        "hotels",
        "Great. Now find a 4-star-or-better hotel in Tokyo that has a gym.",
    ),
    (
        "cars",
        "Add a midsize car rental in Tokyo for those same dates.",
    ),
    (
        "budget validator",
        "My total company travel budget is $5,000. Do the flights, hotel, and "
        "car together fit within it?",
    ),
]


def _invoke(client, message: str, previous_id: str | None, *, max_attempts: int = 10):
    """POST one turn; retry through cold-start empty responses.

    Returns ``(text, response_id)``. Falls back to a stateless turn if the
    server rejects ``previous_response_id`` (conversation chaining unsupported).
    """
    kwargs: dict[str, object] = {"input": message, "model": MAF_MODEL_NAME}
    if previous_id:
        kwargs["previous_response_id"] = previous_id

    last = "no response"
    for attempt in range(1, max_attempts + 1):
        try:
            resp = client.responses.create(**kwargs)
            # ``output_text`` iterates ``resp.output`` and raises when it is None
            # (the empty-envelope a cold-starting container returns), so guard it.
            if getattr(resp, "output", None):
                text = resp.output_text
                if text:
                    return text, resp.id
            last = "empty output (cold start / error envelope)"
        except Exception as exc:  # noqa: BLE001 - surface + retry transient failures
            last = repr(exc)
            if "previous_response_id" in kwargs and (
                "previous_response" in last or "not found" in last.lower()
            ):
                # Server doesn't support response chaining -> continue statelessly.
                kwargs.pop("previous_response_id", None)
        time.sleep(min(3 * attempt, 20))

    return f"[turn did not complete: {last}]", previous_id


def main() -> None:
    client = apim_agents_client(APIM_SUBROUTE)
    version = current_revision(CONTAINER_APP_NAME)

    print("=" * 72)
    print(f"Multi-turn multi-agent demo - contoso-travel-maf-agent ({version})")
    print(f"APIM route: {client.base_url}")
    print("=" * 72)

    previous_id: str | None = None
    for i, (hint, message) in enumerate(TURNS, 1):
        print(f"\n[Turn {i}] expected specialist: {hint}")
        print(f"User: {message}")
        text, previous_id = _invoke(client, message, previous_id)
        print(f"Assistant: {text}")

    print("\n" + "=" * 72)
    print("Done. Each turn produced a multi-agent trace under the Foundry asset:")
    print("  Operate > Assets > contoso-travel-maf-agent > Traces")
    print("=" * 72)


if __name__ == "__main__":
    main()
