"""Scenario adapter for the LangGraph-on-ACA agent (behind the APIM AI Gateway).

The agent's "asset identity" in Foundry is the project connection created by
``deploy_and_register.py`` (``contoso-travel-langgraph-aca-endpoint``). There
is no PromptAgent wrapper — ``azure-ai-projects 2.0.0`` doesn't yet expose a
tool type that treats an external Responses-API endpoint as a connected agent.

The adapter therefore invokes the APIM ``/agents/langgraph/responses`` surface
directly via the ``openai`` client, using the APIM subscription key pulled from
Key Vault. The ``AgentHandle.version`` reflects the current ACA revision so
every evaluation run is tagged with the exact image tag it targeted.
"""

from __future__ import annotations

from agents.shared.aca_connection import apim_agents_client, current_revision
from agents.shared.config import MODEL_NAME
from agents.shared.registry import AgentHandle

AGENT_NAME = "contoso-travel-langgraph-aca"
CONTAINER_APP_NAME = "ca-langgraph-agent"
CONNECTION_NAME = "contoso-travel-langgraph-aca-endpoint"
APIM_SUBROUTE = "langgraph"


def build_handle() -> AgentHandle:
    client = apim_agents_client(APIM_SUBROUTE)
    version = current_revision(CONTAINER_APP_NAME)

    def invoke(query: str) -> str:
        response = client.responses.create(input=query, model=MODEL_NAME)
        return response.output_text or ""

    return AgentHandle(
        scenario="02_langgraph_aca",
        name=AGENT_NAME,
        version=version,
        invoke=invoke,
    )
