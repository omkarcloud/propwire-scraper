"""Live endpoint smoke tests: one call per /propwire/* route against a running
service, with example values proven to return data (2026-11-02, through
https://propwire-scraper.omkar.cloud). The listing tooling reads these calls
as each route's working example.

Skipped unless PROPWIRE_BASE points at a running service:

    ONLY_SCRAPER=propwire python run.py            # or any bottle runner
    PROPWIRE_BASE=http://127.0.0.1:6002 python -m pytest propwire/test_endpoints.py -q
"""
import os

import pytest

BASE = os.environ.get("PROPWIRE_BASE", "").rstrip("/")

pytestmark = pytest.mark.skipif(not BASE, reason="set PROPWIRE_BASE to run live endpoint tests")


def call(path, status=200, **params):
    from curl_cffi import requests
    resp = requests.get(BASE + path, params=params, timeout=300)
    assert resp.status_code == status, f"{path} {params} -> {resp.status_code} {resp.text[:300]}"
    body = resp.json()
    assert body, f"{path} returned an empty body"
    return body


# ---- properties ------------------------------------------------------------------------

def test_property_details():
    malibu = call("/propwire/properties/details", property="27435249")
    assert malibu["id"] == 27435249 and malibu["address"]["city"] == "Malibu"
    assert malibu["owner"]["names"] and malibu["valuation"]["estimated_value"] and malibu["transfer_history"]
    link = call("/propwire/properties/details",
                property="https://propwire.com/realestate/9-Beverly-Park-Beverly-Hills-CA/45945640/property-details")
    assert link["id"] == 45945640 and link["building"]["bedrooms"]
    call("/propwire/properties/details", status=404, property="999999999999")


def test_properties_search():
    body = call("/propwire/properties/search", location="Beverly Hills, CA", per_page="5")
    assert body["count"] > 1000 and len(body["results"]) == 5 and body["next"]
    first = body["results"][0]
    assert first["id"] and first["link"] and first["address"]["city"] == "Beverly Hills"
    listed = call("/propwire/properties/search", location="Beverly Hills, CA", lead_type="mls_active",
                  sort="list_price", per_page="5")
    prices = [r["mls"]["list_price"] for r in listed["results"]]
    assert prices == sorted(prices, reverse=True)
    assert call("/propwire/properties/search", lat="34.0736", lng="-118.4004", radius_miles="1", per_page="2")["results"]


def test_properties_lookup():
    body = call("/propwire/properties/lookup", address="1600 Pennsylvania Ave NW, Washington, DC")
    assert body["results"][0]["property_id"] and body["results"][0]["state"] == "DC"


def test_locations_autocomplete():
    body = call("/propwire/locations/autocomplete", query="Beverly Hills")
    assert any(r["type"] == "city" and r["state"] == "CA" for r in body["results"])


# ---- people ---------------------------------------------------------------------------

def test_people_search():
    agents = call("/propwire/people/search", type="agent", location="Beverly Hills, CA", per_page="5")
    assert agents["count"] > 100 and agents["results"][0]["phone"]
    buyers = call("/propwire/people/search", type="cash_buyer", location="Miami, FL", per_page="5")
    assert buyers["results"][0]["type"] == "cash_buyer"


def test_person_details():
    agent = call("/propwire/people/details", person="ef9d74b9a15893cbdf8d30b874d4e89c")
    assert agent["type"] == "agent" and agent["name"] and agent["listings"]
    call("/propwire/people/details", status=404, person="0000000000000000000000000000dead")


# ---- markets --------------------------------------------------------------------------

def test_market_stats():
    body = call("/propwire/markets/stats", location="90210")
    assert body["summary"]["zip"]["metrics"]["median_sale_price"]["value"] and body["place"]["zip"] == "90210"
    assert call("/propwire/markets/stats", location="Beverly Hills, CA")["trends"]
