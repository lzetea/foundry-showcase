"""Scenario adapter for the multi-agent (MAF HandoffBuilder) workflow on ACA.

Like scenario 02, the agent's "asset identity" in Foundry is the project
connection created by ``deploy_and_register.py``
(``contoso-travel-multiagent-endpoint``). The adapter invokes the APIM
``/agents/maf`` Responses API directly with the APIM subscription key pulled
from Key Vault.
"""

from __future__ import annotations

import time

from agents.shared.aca_connection import apim_agents_client, current_revision
from agents.shared.config import MAF_MODEL_NAME
from agents.shared.registry import AgentHandle

AGENT_NAME = "contoso-travel-multiagent"
CONTAINER_APP_NAME = "ca-maf-agent"
CONNECTION_NAME = "contoso-travel-multiagent-endpoint"
APIM_SUBROUTE = "maf"

# A scaled-to-zero revision returns an empty-output 200 on the first (cold-start)
# request; retry through it instead of crashing on response.output_text (which
# iterates response.output and raises TypeError when it is None).
_MAX_ATTEMPTS = 8


def build_handle() -> AgentHandle:
    client = apim_agents_client(APIM_SUBROUTE)
    version = current_revision(CONTAINER_APP_NAME)

    def invoke(query: str) -> str:
        last = "no response"
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                response = client.responses.create(input=query, model=MAF_MODEL_NAME)
                # output_text iterates response.output and raises when it is None
                # (the empty envelope a cold-starting container returns).
                if getattr(response, "output", None):
                    text = response.output_text
                    if text:
                        return text
                last = "empty output (cold start / error envelope)"
            except Exception as exc:  # noqa: BLE001 - surface + retry transient failures
                last = repr(exc)
            time.sleep(min(3 * attempt, 20))
        return f"[no response after {_MAX_ATTEMPTS} attempts: {last}]"

    return AgentHandle(
        scenario="03_multi_agent",
        name=AGENT_NAME,
        version=version,
        invoke=invoke,
    )
