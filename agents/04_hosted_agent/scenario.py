"""Scenario adapter for the Foundry **hosted agent** (scenario 04).

Unlike scenarios 02 / 03 - containers the customer runs on Azure Container Apps
behind the APIM AI Gateway - this agent is **hosted by Foundry**: ``azd deploy
contoso-travel-hosted`` builds the container (remote build in ACR) and Foundry
runs it on managed, per-session-isolated infrastructure with a dedicated Entra
agent identity.

A hosted agent is **not** reachable through the generic project Responses
endpoint - that resolves ``model`` as a deployment name and 404s on the agent
name. It has its own per-agent endpoint at
``<project>/agents/<name>/endpoint/protocols/openai/responses?api-version=v1``,
authenticated with an Entra bearer token - the same endpoint the Foundry
playground and ``azd ai agent invoke`` use. ``build_handle`` never mutates
server state; it targets whatever version ``azd deploy`` last published.
"""

from __future__ import annotations

import os

from azure.identity import get_bearer_token_provider
from openai import OpenAI

from agents.shared.config import ENDPOINT, get_clients, get_credential
from agents.shared.registry import AgentHandle

# Must match ``agent.yaml`` ``name:`` and the ``azure.yaml`` service key.
AGENT_NAME = "contoso-travel-hosted"

# Entra scope for the Foundry data plane (Responses API).
_SCOPE = "https://ai.azure.com/.default"


def _agent_base_url() -> str:
    """OpenAI base URL for the hosted agent's own Responses endpoint."""
    project_endpoint = os.environ.get("FOUNDRY_PROJECT_ENDPOINT") or ENDPOINT
    return f"{project_endpoint.rstrip('/')}/agents/{AGENT_NAME}/endpoint/protocols/openai"


def _latest_version(project_client) -> str:
    """Best-effort highest deployed version; ``"latest"`` if it can't be read."""
    try:
        versions = list(project_client.agents.list_versions(agent_name=AGENT_NAME))
        numbers = [int(v.version) for v in versions if str(v.version).isdigit()]
        if numbers:
            return str(max(numbers))
    except Exception:
        pass
    return "latest"


def build_handle() -> AgentHandle:
    project_client, _ = get_clients()
    token_provider = get_bearer_token_provider(get_credential(), _SCOPE)
    base_url = _agent_base_url()

    def invoke(query: str) -> str:
        # Hosted agents are addressed on their own per-agent endpoint with an
        # Entra bearer token and api-version=v1 (NOT the generic project /openai
        # route, which 404s on the agent name). A fresh token per call avoids
        # expiry across long eval runs; store=False keeps runs stateless.
        client = OpenAI(
            base_url=base_url,
            api_key="placeholder",  # overridden by the Authorization header
            default_query={"api-version": "v1"},
            default_headers={"Authorization": f"Bearer {token_provider()}"},
        )
        response = client.responses.create(
            model=AGENT_NAME,
            input=query,
            extra_body={"store": False},
        )
        return response.output_text or ""

    return AgentHandle(
        scenario="04_hosted_agent",
        name=AGENT_NAME,
        version=_latest_version(project_client),
        invoke=invoke,
    )
