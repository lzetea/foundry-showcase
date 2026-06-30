"""Scenario adapter for the multi-agent (MAF HandoffBuilder) workflow on ACA.

Like scenario 02, the agent's "asset identity" in Foundry is the project
connection created by ``deploy_and_register.py``
(``contoso-travel-multiagent-endpoint``). The adapter invokes the APIM
``/agents/maf`` Responses API directly with the APIM subscription key pulled
from Key Vault.
"""

from __future__ import annotations

from agents.shared.aca_connection import apim_agents_client, current_revision
from agents.shared.config import MODEL_NAME
from agents.shared.registry import AgentHandle

AGENT_NAME = "contoso-travel-multiagent"
CONTAINER_APP_NAME = "ca-maf-agent"
CONNECTION_NAME = "contoso-travel-multiagent-endpoint"
APIM_SUBROUTE = "maf"


def build_handle() -> AgentHandle:
    client = apim_agents_client(APIM_SUBROUTE)
    version = current_revision(CONTAINER_APP_NAME)

    def invoke(query: str) -> str:
        response = client.responses.create(input=query, model=MODEL_NAME)
        return response.output_text or ""

    return AgentHandle(
        scenario="03_multi_agent",
        name=AGENT_NAME,
        version=version,
        invoke=invoke,
    )
