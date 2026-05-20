"""
Shared agent definition for the Contoso Travel prompt agent.

Lifecycle rules for this scenario:

* ``create_and_invoke.py`` is the **only** script that bumps the agent
  version (via :func:`get_or_create_agent`).
* Every other script (``scenario.py`` used by trace/evaluate/redteam) reuses
  the latest existing version via :func:`get_latest_agent` and never mutates
  server state, so re-running the shared scripts doesn't spam new versions.
* ``cleanup.py`` removes the agent and all its versions.
"""

from __future__ import annotations

import json

from azure.ai.projects.models import FunctionTool, PromptAgentDefinition
from openai.types.responses.response_input_param import FunctionCallOutput

from agents.shared.tools import TOOL_MAP

AGENT_NAME = "contoso-travel-prompt-agent"

SYSTEM_PROMPT = """\
You are the Contoso Travel Concierge — a friendly, knowledgeable travel assistant.

Your capabilities:
- Search flights by origin, destination, cabin class, or max price
- Search hotels by city, star rating, price, or amenity
- Search car rentals by city, car type, or max daily price

Guidelines:
1. Always use the available tools to look up real inventory before answering.
2. Present results clearly with prices, ratings, and key details.
3. If a query spans multiple categories (flight + hotel + car), search all of them.
4. Be conversational and helpful. If you cannot find results, say so honestly.
"""

FLIGHT_TOOL = FunctionTool(
    name="search_flights",
    description="Search for available flights. Filter by origin city, destination city, cabin class, or maximum price.",
    parameters={
        "type": "object",
        "properties": {
            "origin": {"type": "string", "description": "Departure city name"},
            "destination": {"type": "string", "description": "Arrival city name"},
            "cabin_class": {
                "type": "string",
                "description": "Cabin class",
                "enum": ["Economy", "Business", "First"],
            },
            "max_price": {"type": "number", "description": "Maximum ticket price in USD"},
        },
        "required": [],
        "additionalProperties": False,
    },
    strict=False,
)

HOTEL_TOOL = FunctionTool(
    name="search_hotels",
    description="Search for available hotels. Filter by city, minimum star rating, maximum nightly price, or specific amenity.",
    parameters={
        "type": "object",
        "properties": {
            "city": {"type": "string", "description": "City name"},
            "min_stars": {"type": "integer", "description": "Minimum star rating (1-5)"},
            "max_price": {"type": "number", "description": "Maximum price per night in USD"},
            "amenity": {"type": "string", "description": "Required amenity (e.g. Pool, Spa, WiFi)"},
        },
        "required": [],
        "additionalProperties": False,
    },
    strict=False,
)

CAR_RENTAL_TOOL = FunctionTool(
    name="search_car_rentals",
    description="Search for available car rentals. Filter by city, car type, or maximum daily price.",
    parameters={
        "type": "object",
        "properties": {
            "city": {"type": "string", "description": "City name"},
            "car_type": {
                "type": "string",
                "description": "Vehicle type",
                "enum": ["Economy", "SUV", "Luxury", "Minivan"],
            },
            "max_price": {"type": "number", "description": "Maximum price per day in USD"},
        },
        "required": [],
        "additionalProperties": False,
    },
    strict=False,
)

TOOLS = [FLIGHT_TOOL, HOTEL_TOOL, CAR_RENTAL_TOOL]


def get_definition(model_name: str) -> PromptAgentDefinition:
    """Return the PromptAgentDefinition for agent creation."""
    return PromptAgentDefinition(
        model=model_name,
        instructions=SYSTEM_PROMPT,
        tools=TOOLS,
    )


def get_or_create_agent(project_client, model_name: str):
    """Create a **new** version of the agent. Use from bootstrap scripts only."""
    return project_client.agents.create_version(
        agent_name=AGENT_NAME,
        definition=get_definition(model_name),
    )


def get_latest_agent(project_client, model_name: str):
    """Return the latest existing version, creating one on first use.

    Safe to call from the shared trace/evaluate/redteam scripts: it will not
    bump the version unless the agent doesn't exist at all yet.
    """
    try:
        versions = list(project_client.agents.list_versions(agent_name=AGENT_NAME))
    except Exception:
        versions = []
    if versions:
        # The service returns versions in creation order; the newest is last.
        return versions[-1]
    return get_or_create_agent(project_client, model_name)


def run_tool_loop(
    openai_client,
    agent_name: str,
    conversation_id: str,
    query: str,
    *,
    max_rounds: int = 5,
    verbose: bool = False,
) -> str:
    """Run one user query through the agent, dispatching any function_call items.

    Returns the final ``output_text``. Used by both ``scenario.py`` (silent)
    and ``create_and_invoke.py`` (``verbose=True``) so the function-call
    dispatch loop lives in exactly one place.
    """
    response = openai_client.responses.create(
        conversation=conversation_id,
        extra_body={
            "agent_reference": {"name": agent_name, "type": "agent_reference"},
        },
        input=query,
    )

    for _ in range(max_rounds):
        tool_outputs: list[FunctionCallOutput] = []
        for item in response.output:
            if item.type != "function_call":
                continue
            func = TOOL_MAP.get(item.name)
            if func is None:
                if verbose:
                    print(f"  [!] Unknown tool: {item.name}")
                continue
            args = json.loads(item.arguments)
            if verbose:
                print(f"  [tool] {item.name}({args})")
            tool_outputs.append(
                FunctionCallOutput(
                    type="function_call_output",
                    call_id=item.call_id,
                    output=func(**args),
                )
            )
        if not tool_outputs:
            break
        response = openai_client.responses.create(
            conversation=conversation_id,
            extra_body={
                "agent_reference": {"name": agent_name, "type": "agent_reference"},
            },
            input=tool_outputs,
        )

    if verbose and response.usage is not None:
        print(f"  Tokens: {response.usage}")
    return response.output_text or ""
