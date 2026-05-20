"""
Contoso Travel search tools — shared across all agent types.

These functions load CSV data and filter it based on user criteria.
They return JSON strings so they can be used directly as tool outputs.
"""

import json
import pandas as pd
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "contoso-travel"

# ---------------------------------------------------------------------------
# Load data once at import time
# ---------------------------------------------------------------------------
flights_df = pd.read_csv(DATA_DIR / "flights.csv")
hotels_df = pd.read_csv(DATA_DIR / "hotels.csv")
car_rentals_df = pd.read_csv(DATA_DIR / "car_rentals.csv")


# ---------------------------------------------------------------------------
# Search functions (return JSON strings)
# ---------------------------------------------------------------------------
def search_flights(
    origin: str | None = None,
    destination: str | None = None,
    cabin_class: str | None = None,
    max_price: float | None = None,
) -> str:
    """Search for available flights matching the given criteria."""
    results = flights_df.copy()
    if origin:
        results = results[results["origin"].str.lower() == origin.lower()]
    if destination:
        results = results[results["destination"].str.lower() == destination.lower()]
    if cabin_class:
        results = results[results["cabin_class"].str.lower() == cabin_class.lower()]
    if max_price is not None:
        results = results[results["price_usd"] <= float(max_price)]
    if results.empty:
        return json.dumps({"message": "No flights found matching your criteria."})
    return results.to_json(orient="records")


def search_hotels(
    city: str | None = None,
    min_stars: int | None = None,
    max_price: float | None = None,
    amenity: str | None = None,
) -> str:
    """Search for available hotels matching the given criteria."""
    results = hotels_df.copy()
    if city:
        results = results[results["city"].str.lower() == city.lower()]
    if min_stars is not None:
        results = results[results["star_rating"] >= int(min_stars)]
    if max_price is not None:
        results = results[results["price_per_night_usd"] <= float(max_price)]
    if amenity:
        results = results[
            results["amenities"].str.lower().str.contains(
                amenity.lower(), regex=False, na=False
            )
        ]
    if results.empty:
        return json.dumps({"message": "No hotels found matching your criteria."})
    return results.to_json(orient="records")


def search_car_rentals(
    city: str | None = None,
    car_type: str | None = None,
    max_price: float | None = None,
) -> str:
    """Search for available car rentals matching the given criteria."""
    results = car_rentals_df.copy()
    if city:
        results = results[results["city"].str.lower() == city.lower()]
    if car_type:
        results = results[results["car_type"].str.lower() == car_type.lower()]
    if max_price is not None:
        results = results[results["price_per_day_usd"] <= float(max_price)]
    results = results[results["available"] == True]  # noqa: E712
    if results.empty:
        return json.dumps({"message": "No car rentals found matching your criteria."})
    return results.to_json(orient="records")


# ---------------------------------------------------------------------------
# Tool-call dispatcher (used by prompt-agent tool-call loop)
# ---------------------------------------------------------------------------
TOOL_MAP = {
    "search_flights": search_flights,
    "search_hotels": search_hotels,
    "search_car_rentals": search_car_rentals,
}
