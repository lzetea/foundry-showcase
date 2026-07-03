"""
Contoso Travel LangGraph Agent — runs on Azure Container Apps, fronted by
an APIM AI Gateway, and registered as a custom agent in Microsoft Foundry.

Control flow:
  START -> llm_call -┬- (tool calls?) -> tool_node -> llm_call (loop)
                     `-- (no tools)   -> END

Model access:
  - When ``AZURE_OPENAI_ENDPOINT`` + ``AZURE_OPENAI_API_KEY`` are set, the LLM
    call routes through the APIM AI Gateway (token governance, circuit
    breaker, emit-token-metric, semantic cache).
  - Otherwise it falls back to direct Foundry with AAD auth.

Server:
  ``FoundryCorrelatedAdapter(agent).run()`` binds an HTTP server on
  0.0.0.0:8088 exposing the OpenAI Responses API contract.
"""

import json
import os
import logging

import pandas as pd
from dotenv import load_dotenv
from typing_extensions import Literal

from langchain.chat_models import init_chat_model
from langchain_core.messages import SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import END, START, MessagesState, StateGraph

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from azure.ai.agentserver.langgraph import LangGraphAdapter

load_dotenv(override=True)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MODEL_DEPLOYMENT = os.getenv("MODEL_DEPLOYMENT_NAME", os.getenv("AZURE_AI_MODEL_DEPLOYMENT_NAME", "gpt-5"))
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
INSTRUCTIONS_DIR = os.path.join(os.path.dirname(__file__), "instructions")

# Foundry Control Plane correlates a *registered custom agent* to its traces via
# the ``gen_ai.agent.id`` / ``gen_ai.agent.name`` span attributes (see
# https://aka.ms/foundry/register-custom-agent). The value must match the
# "OpenTelemetry agent ID" set at registration -- or, when that field is left
# blank, the agent's display name. We read ``AGENT_NAME`` (the same variable the
# agentserver's own tracer uses) so a single env var drives the whole correlation.
AGENT_IDENTIFIER = os.getenv("AGENT_NAME", "contoso-travel-langgraph-agent")

# ---------------------------------------------------------------------------
# Load Contoso Travel data
# ---------------------------------------------------------------------------
flights_df = pd.read_csv(os.path.join(DATA_DIR, "flights.csv"))
hotels_df = pd.read_csv(os.path.join(DATA_DIR, "hotels.csv"))
car_rentals_df = pd.read_csv(os.path.join(DATA_DIR, "car_rentals.csv"))


# ---------------------------------------------------------------------------
# Tool definitions (LangChain @tool decorator)
# ---------------------------------------------------------------------------
@tool
def search_flights(
    origin: str = "",
    destination: str = "",
    cabin_class: str = "",
    max_price: float = 0,
) -> str:
    """Search for available flights. Filter by origin, destination, cabin class, or max price."""
    results = flights_df.copy()
    if origin:
        results = results[results["origin"].str.lower() == origin.lower()]
    if destination:
        results = results[results["destination"].str.lower() == destination.lower()]
    if cabin_class:
        results = results[results["cabin_class"].str.lower() == cabin_class.lower()]
    if max_price > 0:
        results = results[results["price_usd"] <= max_price]
    if results.empty:
        return json.dumps({"message": "No flights found matching your criteria."})
    return results.to_json(orient="records")


@tool
def search_hotels(
    city: str = "",
    min_stars: int = 0,
    max_price: float = 0,
    amenity: str = "",
) -> str:
    """Search for available hotels. Filter by city, star rating, price, or amenity."""
    results = hotels_df.copy()
    if city:
        results = results[results["city"].str.lower() == city.lower()]
    if min_stars > 0:
        results = results[results["star_rating"] >= min_stars]
    if max_price > 0:
        results = results[results["price_per_night_usd"] <= max_price]
    if amenity:
        results = results[results["amenities"].str.lower().str.contains(
            amenity.lower(), regex=False, na=False
        )]
    if results.empty:
        return json.dumps({"message": "No hotels found matching your criteria."})
    return results.to_json(orient="records")


@tool
def search_car_rentals(
    city: str = "",
    car_type: str = "",
    max_price: float = 0,
) -> str:
    """Search for available car rentals. Filter by city, car type, or max daily price."""
    results = car_rentals_df.copy()
    if city:
        results = results[results["city"].str.lower() == city.lower()]
    if car_type:
        results = results[results["car_type"].str.lower() == car_type.lower()]
    if max_price > 0:
        results = results[results["price_per_day_usd"] <= max_price]
    results = results[results["available"] == True]  # noqa: E712
    if results.empty:
        return json.dumps({"message": "No car rentals found matching your criteria."})
    return results.to_json(orient="records")


# ---------------------------------------------------------------------------
# LLM initialization
# ---------------------------------------------------------------------------
tools = [search_flights, search_hotels, search_car_rentals]
tools_by_name = {t.name: t for t in tools}

_llm_with_tools = None


def llm_with_tools():
    """Lazily initialize the LLM with bound tools.

    Prefers the APIM AI Gateway when ``AZURE_OPENAI_ENDPOINT`` and
    ``AZURE_OPENAI_API_KEY`` are present in the environment; otherwise falls
    back to direct Foundry auth via managed identity.
    """
    global _llm_with_tools
    if _llm_with_tools is not None:
        return _llm_with_tools

    apim_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "").strip().rstrip("/")
    # The APIM AI-Gateway URL is published with an ``/openai`` suffix, but the
    # Azure OpenAI SDK re-appends ``/openai/deployments/...`` itself. Strip it so
    # we don't end up calling ``/openai/openai/...`` (404 Resource not found).
    if apim_endpoint.endswith("/openai"):
        apim_endpoint = apim_endpoint[: -len("/openai")]
    apim_key = os.getenv("AZURE_OPENAI_API_KEY", "").strip()
    api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21")

    if apim_endpoint and apim_key:
        logger.info("Routing model calls through APIM AI Gateway: %s", apim_endpoint)
        # APIM authenticates the caller with its subscription key in the
        # ``Ocp-Apim-Subscription-Key`` header; the SDK's ``api-key`` header is
        # not treated as the APIM subscription key.
        llm = init_chat_model(
            f"azure_openai:{MODEL_DEPLOYMENT}",
            azure_endpoint=apim_endpoint,
            api_key=apim_key,
            api_version=api_version,
            default_headers={"Ocp-Apim-Subscription-Key": apim_key},
        )
    else:
        logger.info("Routing model calls direct to Foundry with AAD auth.")
        credential = DefaultAzureCredential()
        token_provider = get_bearer_token_provider(
            credential, "https://cognitiveservices.azure.com/.default"
        )
        llm = init_chat_model(
            f"azure_openai:{MODEL_DEPLOYMENT}",
            azure_ad_token_provider=token_provider,
        )

    _llm_with_tools = llm.bind_tools(tools)
    return _llm_with_tools


# ---------------------------------------------------------------------------
# Graph nodes
# ---------------------------------------------------------------------------
with open(os.path.join(INSTRUCTIONS_DIR, "concierge.md"), encoding="utf-8") as _fh:
    SYSTEM_MESSAGE = SystemMessage(content=_fh.read())


def llm_call(state: MessagesState):
    """LLM node — decides whether to call tools or respond directly."""
    return {
        "messages": [
            llm_with_tools().invoke([SYSTEM_MESSAGE] + state["messages"])
        ]
    }


def tool_node(state: MessagesState):
    """Tool execution node — runs the requested tools and returns results."""
    results = []
    for tool_call in state["messages"][-1].tool_calls:
        tool_fn = tools_by_name[tool_call["name"]]
        observation = tool_fn.invoke(tool_call["args"])
        results.append(
            ToolMessage(content=str(observation), tool_call_id=tool_call["id"])
        )
    return {"messages": results}


# ---------------------------------------------------------------------------
# Conditional routing
# ---------------------------------------------------------------------------
def should_continue(state: MessagesState) -> Literal["tool_node", "__end__"]:
    """Route to tool_node if the LLM requested tools, otherwise end."""
    last_message = state["messages"][-1]
    if last_message.tool_calls:
        return "tool_node"
    return END


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------
def build_agent():
    """Build and compile the Contoso Travel LangGraph agent."""
    builder = StateGraph(MessagesState)

    # Add nodes
    builder.add_node("llm_call", llm_call)
    builder.add_node("tool_node", tool_node)

    # Add edges
    builder.add_edge(START, "llm_call")
    builder.add_conditional_edges(
        "llm_call",
        should_continue,
        {"tool_node": "tool_node", END: END},
    )
    builder.add_edge("tool_node", "llm_call")

    # ``name`` becomes the graph's runnable name, which the OpenTelemetry tracer
    # reports as ``gen_ai.agent.name`` on the ``invoke_agent`` span (otherwise it
    # defaults to the generic "LangGraph").
    return builder.compile(name=AGENT_IDENTIFIER)


# ---------------------------------------------------------------------------
# Agent server adapter
# ---------------------------------------------------------------------------
class FoundryCorrelatedAdapter(LangGraphAdapter):
    """LangGraph adapter that stamps the registered Foundry agent identity onto
    each run's OpenTelemetry spans.

    The agentserver auto-creates an ``AzureAIOpenTelemetryTracer`` with only a
    ``name`` (its ``agent_id`` defaults to ``None``), so ``gen_ai.agent.id`` comes
    out empty and the Foundry Control Plane can't tie the traces to the registered
    custom agent. We inject ``agent_id`` into the runnable config metadata; the
    tracer reads it and stamps ``gen_ai.agent.id`` onto the ``invoke_agent`` span.
    """

    def ensure_runnable_config(self, input_arguments, context):
        super().ensure_runnable_config(input_arguments, context)
        config = input_arguments.get("config") or {}
        metadata = config.get("metadata") or {}
        metadata.setdefault("agent_id", AGENT_IDENTIFIER)
        config["metadata"] = metadata
        input_arguments["config"] = config


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    try:
        agent = build_agent()
        adapter = FoundryCorrelatedAdapter(agent)
        print("Contoso Travel LangGraph Agent running on http://localhost:8088")
        adapter.run()
    except Exception:
        logger.exception("LangGraph agent failed to start")
        raise
