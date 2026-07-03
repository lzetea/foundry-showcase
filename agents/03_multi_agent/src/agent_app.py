"""
Contoso Travel multi-agent concierge — Microsoft Agent Framework agents-as-tools
orchestration served by ``from_agent_framework(agent).run()`` on ACA.

Topology (the triage coordinator calls each specialist as a tool):

                         ┌──────────┐
                         │  triage  │   orchestrator ChatAgent
                         └────┬─────┘
          ┌───────────┬───────┴───────┬───────────────┐
          ▼           ▼               ▼               ▼
    ┌──────────┐ ┌──────────┐ ┌──────────────┐ ┌──────────────┐
    │ flights  │ │  hotels  │ │  car rentals │ │    budget    │
    │specialist│ │specialist│ │  specialist  │ │  validator   │
    └──────────┘ └──────────┘ └──────────────┘ └──────────────┘

Each specialist is a ChatAgent exposed to triage via ``agent.as_tool()``. One
Responses call runs triage, which calls the relevant specialist tools; every
specialist run emits its own ``invoke_agent`` span nested under triage, so a
single trace shows the full multi-agent interaction and every specialist that ran
appears in traces/evaluations. This replaced a ``HandoffBuilder`` workflow whose
request-info (human-in-the-loop) pauses don't survive the stateless, plain-text
Responses contract that batch/continuous evals and the Foundry portal use.

Model access:
  - When ``AZURE_OPENAI_ENDPOINT`` + ``AZURE_OPENAI_API_KEY`` are set, model
    calls route through the APIM AI Gateway (token limits, emit-token metric,
    circuit breaker). This is the production path.
  - Otherwise it falls back to direct Foundry with AAD auth.

Server:
  ``from_agent_framework(triage).run()`` binds an HTTP server on 0.0.0.0:8088
  exposing the OpenAI Responses API contract.
"""

import json
import logging
import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from agent_framework.azure import AzureOpenAIChatClient

from azure.ai.agentserver.agentframework import from_agent_framework

load_dotenv(override=True)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MODEL_DEPLOYMENT = os.getenv(
    "MODEL_DEPLOYMENT_NAME",
    os.getenv("AZURE_AI_MODEL_DEPLOYMENT_NAME", "gpt-5"),
)
PROJECT_ENDPOINT = os.getenv("AZURE_AI_PROJECT_ENDPOINT", "").strip()
# Identity used to correlate this agent's traces to the registered Foundry custom
# agent. Must match the registration's "OpenTelemetry agent ID". The Control Plane
# correlates a whole trace once ONE span carries gen_ai.agent.id = this value.
# It is applied as the triage coordinator's id: triage is the root ChatAgent every
# request enters through, so its invoke_agent span anchors the whole trace. The
# specialists triage calls (via .as_tool()) emit their own child invoke_agent spans.
# Override via AGENT_NAME.
AGENT_IDENTIFIER = os.getenv("AGENT_NAME", "contoso-travel-maf-agent")
DATA_DIR = Path(__file__).resolve().parent / "data"

flights_df = pd.read_csv(DATA_DIR / "flights.csv")
hotels_df = pd.read_csv(DATA_DIR / "hotels.csv")
car_rentals_df = pd.read_csv(DATA_DIR / "car_rentals.csv")


# ---------------------------------------------------------------------------
# Domain tools
# ---------------------------------------------------------------------------
def search_flights(
    origin: str = "",
    destination: str = "",
    cabin_class: str = "",
    max_price: float = 0,
) -> str:
    """Search Contoso Travel flights. Filter by origin, destination, cabin class, or max price (USD)."""
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


def search_hotels(
    city: str = "",
    min_stars: int = 0,
    max_price: float = 0,
    amenity: str = "",
) -> str:
    """Search Contoso Travel hotels. Filter by city, min star rating, max nightly price (USD), or amenity keyword."""
    results = hotels_df.copy()
    if city:
        results = results[results["city"].str.lower() == city.lower()]
    if min_stars > 0:
        results = results[results["star_rating"] >= min_stars]
    if max_price > 0:
        results = results[results["price_per_night_usd"] <= max_price]
    if amenity:
        results = results[results["amenities"].str.lower().str.contains(
            amenity.lower(), regex=False, na=False,
        )]
    if results.empty:
        return json.dumps({"message": "No hotels found matching your criteria."})
    return results.to_json(orient="records")


def search_car_rentals(
    city: str = "",
    car_type: str = "",
    max_price: float = 0,
) -> str:
    """Search Contoso Travel car rentals. Filter by city, car type, or max daily price (USD)."""
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
# Chat client — APIM gateway when available, direct Foundry as fallback
# ---------------------------------------------------------------------------
def build_chat_client():
    apim_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "").strip()
    apim_key = os.getenv("AZURE_OPENAI_API_KEY", "").strip()
    api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21")

    if not (apim_endpoint and apim_key):
        raise RuntimeError(
            "AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY must be set so the "
            "multi-agent workflow reaches the model through the APIM AI Gateway."
        )

    # The APIM AI Gateway authenticates callers with the subscription key in the
    # ``Ocp-Apim-Subscription-Key`` header (not the ``api-key`` header the Azure
    # OpenAI SDK sends by default), so pass it via ``default_headers``. The
    # endpoint is the APIM base; the SDK appends ``/openai/deployments/...``.
    logger.info("Multi-agent model calls routed through APIM: %s", apim_endpoint)
    return AzureOpenAIChatClient(
        endpoint=apim_endpoint,
        deployment_name=MODEL_DEPLOYMENT,
        api_key=apim_key,
        api_version=api_version,
        default_headers={"Ocp-Apim-Subscription-Key": apim_key},
    )


# ---------------------------------------------------------------------------
# Specialist instructions (versioned, ASCII-only Markdown under instructions/)
# ---------------------------------------------------------------------------
INSTRUCTIONS_DIR = Path(__file__).resolve().parent / "instructions"


def _load_instructions(name: str) -> str:
    return (INSTRUCTIONS_DIR / name).read_text(encoding="utf-8")


TRIAGE_INSTRUCTIONS = _load_instructions("triage.md")
FLIGHTS_INSTRUCTIONS = _load_instructions("flights.md")
HOTELS_INSTRUCTIONS = _load_instructions("hotels.md")
CARS_INSTRUCTIONS = _load_instructions("cars.md")
BUDGET_INSTRUCTIONS = _load_instructions("budget.md")


# ---------------------------------------------------------------------------
# Build the orchestrator agent (triage + specialists exposed as tools)
# ---------------------------------------------------------------------------
def build_agent():
    chat = build_chat_client()

    # Each specialist is a ChatAgent with its own domain tool. Exposed to triage
    # via .as_tool(), a specialist runs on demand and emits its OWN invoke_agent
    # span, so a single Responses call produces one trace that covers every agent
    # that ran (triage -> flights/hotels/cars -> budget) and every specialist shows
    # up in traces and evaluations.
    flights = chat.create_agent(
        name="flights_specialist",
        description="Searches Contoso Travel's flight inventory.",
        instructions=FLIGHTS_INSTRUCTIONS,
        tools=[search_flights],
    )
    hotels = chat.create_agent(
        name="hotels_specialist",
        description="Searches Contoso Travel's hotel inventory.",
        instructions=HOTELS_INSTRUCTIONS,
        tools=[search_hotels],
    )
    cars = chat.create_agent(
        name="cars_specialist",
        description="Searches Contoso Travel's car-rental inventory.",
        instructions=CARS_INSTRUCTIONS,
        tools=[search_car_rentals],
    )
    validator = chat.create_agent(
        name="budget_validator",
        description="Validates proposed trip totals against corporate policy (USD 3,500 default).",
        instructions=BUDGET_INSTRUCTIONS,
    )

    # triage is BOTH the orchestrator and the trace-correlation anchor: its id is the
    # registered OTel agent ID (every request enters through it), and it calls the
    # specialists as tools. A plain ChatAgent completes its run per request, so there
    # is no HandoffBuilder request-info pause to trip evals / the Foundry portal.
    triage = chat.create_agent(
        id=AGENT_IDENTIFIER,
        name="triage",
        description="Entry-point travel coordinator that orchestrates the specialist agents.",
        instructions=TRIAGE_INSTRUCTIONS,
        tools=[
            flights.as_tool(
                name="consult_flights_specialist",
                description="Delegate an air-travel search to the flights specialist agent.",
                arg_name="request",
                arg_description="Self-contained flight request: origin, destination, dates, cabin, budget.",
            ),
            hotels.as_tool(
                name="consult_hotels_specialist",
                description="Delegate a hotel search to the hotels specialist agent.",
                arg_name="request",
                arg_description="Self-contained hotel request: city, dates, star rating, amenities, budget.",
            ),
            cars.as_tool(
                name="consult_cars_specialist",
                description="Delegate a car-rental search to the cars specialist agent.",
                arg_name="request",
                arg_description="Self-contained car request: city, dates, car type, budget.",
            ),
            validator.as_tool(
                name="consult_budget_validator",
                description="Ask the budget validator agent to check the proposed trip total against policy.",
                arg_name="request",
                arg_description="Proposed trip components with prices and the traveller's stated budget.",
            ),
        ],
    )
    return triage


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    agent = build_agent()
    from_agent_framework(agent).run()
