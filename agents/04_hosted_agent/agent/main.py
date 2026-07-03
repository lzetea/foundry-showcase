"""Contoso Travel concierge - a Microsoft Foundry **hosted agent**.

This is the same kind of agent-server container as scenarios 02 (LangGraph) and
03 (multi-agent MAF), but with a completely different operational model: **Foundry
builds and runs this container for you** on managed, per-session-isolated
infrastructure with a dedicated Microsoft Entra agent identity. There is:

  * no Azure Container Apps environment to manage,
  * no APIM AI-gateway in front (the agent reaches the model directly through the
    Foundry project using ``DefaultAzureCredential`` -> the platform-injected
    managed identity, so there are no gateway keys to broker), and
  * no infrastructure Bicep beyond the shared Foundry project.

The entry point is ``ResponsesHostServer(agent).run()`` from
``agent_framework_foundry_hosting``, which serves the OpenAI-compatible Responses
protocol on port 8088 - exactly what the Foundry hosting runtime invokes and what
``azd ai agent invoke`` / the portal playground call.
"""

import csv
import os
from pathlib import Path
from typing import Any

from agent_framework import Agent, tool
from agent_framework.foundry import FoundryChatClient
from agent_framework_foundry_hosting import ResponsesHostServer
from azure.ai.agentserver.optimization import load_config
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv
from pydantic import Field
from typing_extensions import Annotated

# override=False so the values Foundry injects at runtime (FOUNDRY_PROJECT_ENDPOINT,
# AZURE_AI_MODEL_DEPLOYMENT_NAME, APPLICATIONINSIGHTS_CONNECTION_STRING) win over any
# local .env used for `azd ai agent run` / bare `python main.py`.
load_dotenv(override=False)

_DATA_DIR = Path(__file__).parent / "data"
# System instructions now live in .agent_configs/baseline/instructions.md (seeded from
# instructions/concierge.md) and are loaded via load_config() so Foundry's Agent Optimizer
# can tune the prompt without code changes.


# ---------------------------------------------------------------------------
# Data loaders (read once at import - no I/O on the hot path)
# ---------------------------------------------------------------------------
def _load_csv(name: str) -> list[dict[str, str]]:
    with (_DATA_DIR / name).open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


_FLIGHTS = _load_csv("flights.csv")
_HOTELS = _load_csv("hotels.csv")
_CAR_RENTALS = _load_csv("car_rentals.csv")


def _format(rows: list[dict[str, Any]], columns: list[str], limit: int = 5) -> str:
    if not rows:
        return "No matches found in the Contoso Travel inventory for those criteria."
    lines = []
    for row in rows[:limit]:
        lines.append(" | ".join(f"{col}={row.get(col, '')}" for col in columns))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tools (registered on the agent via the @tool decorator)
# ---------------------------------------------------------------------------
@tool(approval_mode="never_require")
def search_flights(
    origin: Annotated[str | None, Field(description="Origin city, e.g. 'Seattle'. Optional.")] = None,
    destination: Annotated[str | None, Field(description="Destination city, e.g. 'Paris'. Optional.")] = None,
    cabin_class: Annotated[str | None, Field(description="Cabin class: Economy, Business, or First. Optional.")] = None,
    max_price: Annotated[float, Field(description="Maximum price in USD. 0 means no limit.")] = 0.0,
) -> str:
    """Search Contoso Travel flights by origin, destination, cabin class, or max price (USD)."""

    def keep(row: dict[str, str]) -> bool:
        if origin and row["origin"].lower() != origin.lower():
            return False
        if destination and row["destination"].lower() != destination.lower():
            return False
        if cabin_class and row["cabin_class"].lower() != cabin_class.lower():
            return False
        if max_price and float(row["price_usd"]) > max_price:
            return False
        return True

    hits = [r for r in _FLIGHTS if keep(r)]
    return _format(
        hits,
        ["airline", "origin", "destination", "departure_date", "cabin_class", "price_usd"],
    )


@tool(approval_mode="never_require")
def search_hotels(
    city: Annotated[str | None, Field(description="City to stay in, e.g. 'Paris'. Optional.")] = None,
    min_stars: Annotated[int, Field(description="Minimum star rating (1-5). 0 means no minimum.")] = 0,
    max_price: Annotated[float, Field(description="Maximum nightly price in USD. 0 means no limit.")] = 0.0,
    amenity: Annotated[str | None, Field(description="Required amenity keyword, e.g. 'Gym' or 'Pool'. Optional.")] = None,
) -> str:
    """Search Contoso Travel hotels by city, minimum star rating, max nightly price (USD), or amenity."""

    def keep(row: dict[str, str]) -> bool:
        if city and row["city"].lower() != city.lower():
            return False
        if min_stars and int(row["star_rating"]) < min_stars:
            return False
        if max_price and float(row["price_per_night_usd"]) > max_price:
            return False
        if amenity and amenity.lower() not in row["amenities"].lower():
            return False
        return True

    hits = [r for r in _HOTELS if keep(r)]
    return _format(
        hits,
        ["name", "city", "star_rating", "price_per_night_usd", "amenities"],
    )


@tool(approval_mode="never_require")
def search_car_rentals(
    city: Annotated[str | None, Field(description="City to rent in, e.g. 'Paris'. Optional.")] = None,
    car_type: Annotated[str | None, Field(description="Car type: Economy, SUV, Luxury, or Minivan. Optional.")] = None,
    max_price: Annotated[float, Field(description="Maximum daily price in USD. 0 means no limit.")] = 0.0,
) -> str:
    """Search Contoso Travel car rentals by city, car type, or max daily price (USD)."""

    def keep(row: dict[str, str]) -> bool:
        if row["available"].lower() != "true":
            return False
        if city and row["city"].lower() != city.lower():
            return False
        if car_type and row["car_type"].lower() != car_type.lower():
            return False
        if max_price and float(row["price_per_day_usd"]) > max_price:
            return False
        return True

    hits = [r for r in _CAR_RENTALS if keep(r)]
    return _format(
        hits,
        ["company", "city", "car_type", "price_per_day_usd", "pickup_date", "return_date"],
    )


# ---------------------------------------------------------------------------
# Agent + hosted runtime
# ---------------------------------------------------------------------------
def build_agent() -> Agent:
    # FOUNDRY_PROJECT_ENDPOINT is injected by the Foundry hosting runtime; fall back
    # to AZURE_AI_PROJECT_ENDPOINT for local `azd ai agent run` / `python main.py`.
    project_endpoint = os.environ.get("FOUNDRY_PROJECT_ENDPOINT") or os.environ["AZURE_AI_PROJECT_ENDPOINT"]

    # Agent Optimizer wiring: load_config() reads .agent_configs/baseline/ (instructions +
    # model) at startup, and lets Foundry's `azd ai agent optimize` inject candidate
    # configurations at eval time so the prompt/model can be tuned without code changes.
    config = load_config()

    client = FoundryChatClient(
        project_endpoint=project_endpoint,
        model=config.model,
        credential=DefaultAzureCredential(),
    )
    return Agent(
        client=client,
        name="contoso-travel-hosted",
        instructions=config.compose_instructions(),
        tools=[search_flights, search_hotels, search_car_rentals],
        default_options={"store": False},
    )


def main() -> None:
    server = ResponsesHostServer(build_agent())
    server.run()


if __name__ == "__main__":
    main()
