"""Unit tests for the shared Contoso Travel search tools.

These cover the pure, deterministic filtering logic in ``agents.shared.tools``
(no Azure, no network). Expected values are derived from the loaded dataframes
so the tests stay robust if the sample CSVs are edited.
"""

import json

from agents.shared import tools


def _payload(raw: str):
    return json.loads(raw)


# ---------------------------------------------------------------------------
# search_flights
# ---------------------------------------------------------------------------
def test_search_flights_no_args_returns_all_rows():
    rows = _payload(tools.search_flights())
    assert isinstance(rows, list)
    assert len(rows) == len(tools.flights_df)


def test_search_flights_filters_by_origin_case_insensitively():
    origin = str(tools.flights_df.iloc[0]["origin"])
    rows = _payload(tools.search_flights(origin=origin.lower()))
    assert rows, "expected at least one flight for an origin from the data"
    assert all(r["origin"].lower() == origin.lower() for r in rows)


def test_search_flights_respects_max_price():
    cheapest = float(tools.flights_df["price_usd"].min())
    rows = _payload(tools.search_flights(max_price=cheapest))
    assert rows
    assert all(float(r["price_usd"]) <= cheapest for r in rows)


def test_search_flights_no_match_returns_message():
    out = _payload(tools.search_flights(origin="Atlantis"))
    assert out == {"message": "No flights found matching your criteria."}


# ---------------------------------------------------------------------------
# search_hotels
# ---------------------------------------------------------------------------
def test_search_hotels_filters_by_city():
    city = str(tools.hotels_df.iloc[0]["city"])
    rows = _payload(tools.search_hotels(city=city))
    assert rows
    assert all(r["city"].lower() == city.lower() for r in rows)


def test_search_hotels_min_stars_filter():
    rows = _payload(tools.search_hotels(min_stars=5))
    if isinstance(rows, list):
        assert all(int(r["star_rating"]) >= 5 for r in rows)
    else:
        assert rows == {"message": "No hotels found matching your criteria."}


def test_search_hotels_amenity_is_substring_match():
    first_amenity = str(tools.hotels_df.iloc[0]["amenities"]).split(",")[0].strip()
    rows = _payload(tools.search_hotels(amenity=first_amenity))
    assert rows, "the first hotel should match its own amenity"
    assert all(first_amenity.lower() in str(r["amenities"]).lower() for r in rows)


# ---------------------------------------------------------------------------
# search_car_rentals
# ---------------------------------------------------------------------------
def test_search_car_rentals_only_returns_available():
    rows = _payload(tools.search_car_rentals())
    assert isinstance(rows, list) and rows
    assert all(r.get("available") for r in rows)


def test_search_car_rentals_filters_by_car_type():
    available = tools.car_rentals_df[tools.car_rentals_df["available"] == True]  # noqa: E712
    car_type = str(available.iloc[0]["car_type"])
    rows = _payload(tools.search_car_rentals(car_type=car_type))
    assert rows
    assert all(r["car_type"].lower() == car_type.lower() for r in rows)


def test_search_car_rentals_no_match_returns_message():
    out = _payload(tools.search_car_rentals(city="Atlantis"))
    assert out == {"message": "No car rentals found matching your criteria."}


# ---------------------------------------------------------------------------
# dispatcher
# ---------------------------------------------------------------------------
def test_tool_map_exposes_all_three_tools():
    assert set(tools.TOOL_MAP) == {
        "search_flights",
        "search_hotels",
        "search_car_rentals",
    }


def test_tool_map_dispatch_runs():
    out = _payload(tools.TOOL_MAP["search_flights"]())
    assert isinstance(out, list)
