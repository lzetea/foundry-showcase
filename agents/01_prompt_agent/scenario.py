"""
Scenario adapter for the Foundry-managed Prompt Agent.

Exposes ``build_handle()`` for ``agents.shared.registry`` so the shared
``trace`` / ``evaluate`` / ``redteam`` scripts can target this scenario.

``build_handle`` looks up the **latest existing agent version** (see
:func:`agent_def.get_latest_agent`) and never bumps a new version. Only
``create_and_invoke.py`` is allowed to mutate server state.
"""

from __future__ import annotations

from agents.shared.config import MODEL_NAME, get_clients
from agents.shared.registry import AgentHandle

from .agent_def import AGENT_NAME, get_latest_agent, run_tool_loop


def build_handle() -> AgentHandle:
    """Return an :class:`AgentHandle` for the prompt agent."""
    project_client, openai_client = get_clients()
    agent = get_latest_agent(project_client, MODEL_NAME)

    def invoke(query: str) -> str:
        conversation = openai_client.conversations.create()
        try:
            return run_tool_loop(
                openai_client,
                agent_name=agent.name,
                conversation_id=conversation.id,
                query=query,
            )
        finally:
            openai_client.conversations.delete(conversation.id)

    return AgentHandle(
        scenario="01_prompt_agent",
        name=AGENT_NAME,
        version=agent.version,
        invoke=invoke,
    )
