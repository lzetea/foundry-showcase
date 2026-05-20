"""Scenario adapter for the Foundry built-in tools agent.

All tool execution happens server-side, so the invoke loop is trivial: fire
off a single Responses call and return ``output_text``.

``build_handle`` reuses the **latest existing agent version** via
:func:`agent_def.get_latest_agent`; only ``create_and_invoke.py`` bumps
versions.
"""

from __future__ import annotations

from agents.shared.config import MODEL_NAME, get_clients
from agents.shared.registry import AgentHandle

from .agent_def import AGENT_NAME, get_latest_agent


def build_handle() -> AgentHandle:
    project_client, openai_client = get_clients()
    agent = get_latest_agent(project_client, openai_client, MODEL_NAME)

    def invoke(query: str) -> str:
        conversation = openai_client.conversations.create()
        try:
            response = openai_client.responses.create(
                conversation=conversation.id,
                extra_body={
                    "agent_reference": {
                        "name": agent.name,
                        "type": "agent_reference",
                    }
                },
                input=query,
            )
            return response.output_text or ""
        finally:
            openai_client.conversations.delete(conversation.id)

    return AgentHandle(
        scenario="04_foundry_tools_agent",
        name=AGENT_NAME,
        version=agent.version,
        invoke=invoke,
    )
