"""
Contoso Travel multi-agent workflow — Microsoft Agent Framework ``HandoffBuilder``
orchestration served by ``from_agent_framework(agent).run()`` on ACA.

Topology (handoff graph):

                         ┌──────────┐
                         │  triage  │
                         └────┬─────┘
             ┌────────────────┼────────────────┐
             ▼                ▼                ▼
      ┌───────────┐    ┌───────────┐    ┌──────────────┐
      │  flights  │    │   hotels  │    │   car rent   │
      └─────┬─────┘    └─────┬─────┘    └──────┬───────┘
            └────────────────┼───────────────────┘
                             ▼
                      ┌────────────┐
                      │  budget    │
                      │ validator  │
                      └─────┬──────┘
                            ▼
                        (back to triage)

Model access:
  - When ``AZURE_OPENAI_ENDPOINT`` + ``AZURE_OPENAI_API_KEY`` are set, model
    calls route through the APIM AI Gateway (token limits, emit-token metric,
    circuit breaker). This is the production path.
  - Otherwise it falls back to direct Foundry with AAD auth.

Server:
  ``from_agent_framework(WorkflowAgent(workflow)).run()`` binds an HTTP server
  on 0.0.0.0:8088 exposing the OpenAI Responses API contract.
"""

import json
import logging
import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from agent_framework import WorkflowAgent
from agent_framework.openai import OpenAIChatClient
from agent_framework.foundry import FoundryChatClient
from agent_framework.orchestrations import HandoffBuilder

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from azure.ai.agentserver.agentframework import from_agent_framework

load_dotenv(override=True)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MODEL_DEPLOYMENT = os.getenv(
    "MODEL_DEPLOYMENT_NAME",
    os.getenv("AZURE_AI_MODEL_DEPLOYMENT_NAME", "gpt-4.1"),
)
PROJECT_ENDPOINT = os.getenv("AZURE_AI_PROJECT_ENDPOINT", "").strip()
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

    if apim_endpoint and apim_key:
        logger.info("Multi-agent model calls routed through APIM: %s", apim_endpoint)
        return OpenAIChatClient(
            model=MODEL_DEPLOYMENT,
            azure_endpoint=apim_endpoint,
            api_key=apim_key,
            api_version=api_version,
        )

    logger.info("Multi-agent model calls routed direct to Foundry (AAD).")
    if not PROJECT_ENDPOINT:
        raise RuntimeError(
            "AZURE_AI_PROJECT_ENDPOINT must be set when no APIM endpoint is configured."
        )
    credential = DefaultAzureCredential()
    return FoundryChatClient(
        project_endpoint=PROJECT_ENDPOINT,
        model=MODEL_DEPLOYMENT,
        credential=credential,
    )


# ---------------------------------------------------------------------------
# Specialist instructions
# ---------------------------------------------------------------------------
TRIAGE_INSTRUCTIONS = """\
You are the Contoso Travel **Triage** agent — the single entry point for the
traveller.

Your job:
1. Understand what the traveller is trying to book (flights, hotels, cars,
   or any combination) and their budget if mentioned.
2. Hand off to the right specialist(s):
   - ``flights_specialist`` for any air-travel question
   - ``hotels_specialist`` for accommodation
   - ``cars_specialist`` for ground transport
3. When the specialists have returned proposed options, hand off to the
   ``budget_validator`` to confirm the total trip cost is within policy.
4. Only respond to the traveller yourself when the validator has signed off
   or when the request is a simple greeting / clarification.

Do not try to call search tools yourself — delegate.
"""

FLIGHTS_INSTRUCTIONS = """\
You are the Contoso Travel **Flights Specialist**. Use the ``search_flights``
tool to find available flights that match the request. Present the top 3
options with origin, destination, cabin class, airline, and price. After
proposing options, hand off back to ``triage``.
"""

HOTELS_INSTRUCTIONS = """\
You are the Contoso Travel **Hotels Specialist**. Use the ``search_hotels``
tool to find available hotels that match the request. Present the top 3
options with name, city, star rating, nightly price, and key amenities.
After proposing options, hand off back to ``triage``.
"""

CARS_INSTRUCTIONS = """\
You are the Contoso Travel **Car Rentals Specialist**. Use the
``search_car_rentals`` tool to find available vehicles that match the
request. Present the top 3 options with car type, daily price, and vendor.
After proposing options, hand off back to ``triage``.
"""

BUDGET_INSTRUCTIONS = """\
You are the Contoso Travel **Budget Validator**. Read the proposed trip
from the conversation so far and compute the total cost. Contoso corporate
policy is **USD 3,500 per trip** unless the traveller explicitly states a
different budget.

If the total is within budget, reply with a one-line confirmation and hand
off back to ``triage``. If it exceeds budget, flag the overage in dollars,
suggest which component(s) to reduce, and hand off back to ``triage``.
"""


# ---------------------------------------------------------------------------
# Build the workflow
# ---------------------------------------------------------------------------
def build_workflow_agent() -> WorkflowAgent:
    chat = build_chat_client()

    triage = chat.as_agent(
        name="triage",
        description="Entry-point travel coordinator that routes to specialists.",
        instructions=TRIAGE_INSTRUCTIONS,
    )
    flights = chat.as_agent(
        name="flights_specialist",
        description="Searches Contoso Travel's flight inventory.",
        instructions=FLIGHTS_INSTRUCTIONS,
        tools=[search_flights],
    )
    hotels = chat.as_agent(
        name="hotels_specialist",
        description="Searches Contoso Travel's hotel inventory.",
        instructions=HOTELS_INSTRUCTIONS,
        tools=[search_hotels],
    )
    cars = chat.as_agent(
        name="cars_specialist",
        description="Searches Contoso Travel's car-rental inventory.",
        instructions=CARS_INSTRUCTIONS,
        tools=[search_car_rentals],
    )
    validator = chat.as_agent(
        name="budget_validator",
        description="Validates proposed trip totals against corporate policy (USD 3,500 default).",
        instructions=BUDGET_INSTRUCTIONS,
    )

    workflow = (
        HandoffBuilder(
            name="contoso-travel-multiagent",
            participants=[triage, flights, hotels, cars, validator],
        )
        .with_start_agent(triage)
        .add_handoff(triage, [flights, hotels, cars, validator])
        .add_handoff(flights, [triage])
        .add_handoff(hotels, [triage])
        .add_handoff(cars, [triage])
        .add_handoff(validator, [triage])
        .build()
    )

    return WorkflowAgent(
        workflow,
        name="contoso-travel-multiagent",
        description="Multi-agent Contoso Travel concierge (Triage + specialists + budget validator).",
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    agent = build_workflow_agent()
    from_agent_framework(agent).run()
