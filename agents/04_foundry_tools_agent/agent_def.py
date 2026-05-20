"""Shared agent definition for the Foundry built-in tools showcase.

Scenario 04 uses **Foundry-native tools** (no function tools, no container):

- ``FileSearchTool``       — a vector store built from travel policy docs.
- ``CodeInterpreterTool``  — for itinerary math / budget calculations.
- ``BingGroundingTool``    — optional, only added when the env var
  ``BING_GROUNDING_CONNECTION_ID`` points at a Bing Grounding resource
  wired into the Foundry project.

The vector store is provisioned lazily the first time the agent is created,
and its id is persisted to ``.vector_store_id`` next to this file so
subsequent script runs re-use it instead of re-uploading the docs.
"""

from __future__ import annotations

import os
from pathlib import Path

from azure.ai.projects.models import (
    BingGroundingSearchConfiguration,
    BingGroundingSearchToolParameters,
    BingGroundingTool,
    CodeInterpreterTool,
    FileSearchTool,
    PromptAgentDefinition,
    Tool,
)

AGENT_NAME = "contoso-travel-foundry-tools"
VECTOR_STORE_NAME = "contoso-travel-policies"

_DATA_DIR = Path(__file__).resolve().parent / "data"
_VECTOR_STORE_ID_FILE = Path(__file__).resolve().parent / ".vector_store_id"

SYSTEM_PROMPT = """\
You are the Contoso Travel Concierge — a senior travel advisor with access to
the company's internal policy library and live web search.

Your tools:
- **file_search**: Contoso Travel's internal knowledge base (baggage rules,
  loyalty program details, trip insurance plans, visa requirements).
- **code_interpreter**: use this for any arithmetic — itinerary cost totals,
  mile redemption math, baggage-fee calculations, currency conversions.
  Never do arithmetic in your head; call the tool.
- **bing_grounding** (if available): for current events, real-time flight
  status, hotel availability and weather at the destination.

Guidelines:
1. Ground policy answers in ``file_search`` results. Cite the source document
   when you quote a policy.
2. For any numeric question with more than a trivial calculation, call
   ``code_interpreter``.
3. If the user asks about something likely to change (airport delays,
   exchange rates, events), use ``bing_grounding`` when available; otherwise
   say so.
4. Be concise. Prefer tables for comparisons.
"""


# =============================================================================
# Vector store lifecycle
# =============================================================================
def ensure_vector_store(openai_client) -> str:
    """Return the vector-store id, creating it (and uploading the policy docs)
    on first run. The id is cached in ``.vector_store_id`` in this folder.
    """
    if _VECTOR_STORE_ID_FILE.exists():
        existing_id = _VECTOR_STORE_ID_FILE.read_text(encoding="utf-8").strip()
        try:
            openai_client.vector_stores.retrieve(existing_id)
            return existing_id
        except Exception:
            # Store no longer exists — fall through and recreate.
            _VECTOR_STORE_ID_FILE.unlink(missing_ok=True)

    file_ids: list[str] = []
    for md_path in sorted(_DATA_DIR.glob("*.md")):
        with md_path.open("rb") as fh:
            uploaded = openai_client.files.create(file=fh, purpose="assistants")
        file_ids.append(uploaded.id)
        print(f"  [upload] {md_path.name} -> {uploaded.id}")

    store = openai_client.vector_stores.create(
        name=VECTOR_STORE_NAME,
        file_ids=file_ids,
    )
    _VECTOR_STORE_ID_FILE.write_text(store.id, encoding="utf-8")
    print(f"  [vector_store] {store.name} -> {store.id}")
    return store.id


def delete_vector_store(openai_client) -> None:
    """Delete the cached vector store (and its files). Idempotent."""
    if not _VECTOR_STORE_ID_FILE.exists():
        return
    store_id = _VECTOR_STORE_ID_FILE.read_text(encoding="utf-8").strip()
    try:
        # Files attached to the store don't delete automatically.
        for f in openai_client.vector_stores.files.list(store_id):
            try:
                openai_client.files.delete(f.id)
            except Exception:
                pass
        openai_client.vector_stores.delete(store_id)
        print(f"  [deleted] vector store {store_id}")
    except Exception as exc:
        print(f"  [warn] vector store {store_id} could not be deleted: {exc}")
    _VECTOR_STORE_ID_FILE.unlink(missing_ok=True)


# =============================================================================
# Tool assembly
# =============================================================================
def build_tools(vector_store_id: str) -> list[Tool]:
    tools: list[Tool] = [
        FileSearchTool(vector_store_ids=[vector_store_id], max_num_results=5),
        CodeInterpreterTool(),
    ]

    bing_conn_id = os.environ.get("BING_GROUNDING_CONNECTION_ID", "").strip()
    if bing_conn_id:
        tools.append(
            BingGroundingTool(
                bing_grounding=BingGroundingSearchToolParameters(
                    search_configurations=[
                        BingGroundingSearchConfiguration(
                            project_connection_id=bing_conn_id,
                            count=5,
                        ),
                    ],
                ),
            )
        )
    return tools


def get_definition(openai_client, model_name: str) -> PromptAgentDefinition:
    vector_store_id = ensure_vector_store(openai_client)
    return PromptAgentDefinition(
        model=model_name,
        instructions=SYSTEM_PROMPT,
        tools=build_tools(vector_store_id),
    )


def get_or_create_agent(project_client, openai_client, model_name: str):
    """Create a **new** version of the agent. Use from bootstrap scripts only."""
    return project_client.agents.create_version(
        agent_name=AGENT_NAME,
        definition=get_definition(openai_client, model_name),
    )


def get_latest_agent(project_client, openai_client, model_name: str):
    """Return the latest existing agent version, creating one on first use.

    Used by ``scenario.py`` so that the shared trace/evaluate/redteam scripts
    never mutate server state: they reuse whatever version
    ``create_and_invoke.py`` last registered.
    """
    try:
        versions = list(project_client.agents.list_versions(agent_name=AGENT_NAME))
    except Exception:
        versions = []
    if versions:
        return versions[-1]
    return get_or_create_agent(project_client, openai_client, model_name)
