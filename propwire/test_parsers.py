"""Offline tests for the Propwire parsers and reference resolvers.

    python -m pytest propwire/test_parsers.py -q

Fixtures are real upstream payloads captured 2026-10-31 (propwire/fixtures/):
search pages (a ZIP page, an MLS-listed row, a pre-foreclosure row, a
count-only payload, a by-ids payload, a past-the-end page), full property
records (plain SFR, MLS listing with photos, pre-foreclosure), the API's
error bodies, people pages (agents, cash buyers, count), both profile
kinds, market stats (ZIP summary + record, city record, county summary),
autocomplete payloads and the homepage. No network.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from propwire import parsers as P, refs  # noqa: E402

FX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def fixture(name):
    with open(os.path.join(FX, name), encoding="utf-8") as f:
        return json.load(f) if name.endswith(".json") else f.read()


# ---- refs ------------------------------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    ("109721", 109721),
    (" 51608674 ", 51608674),
    ("https://propwire.com/realestate/5400-Halsted-Ave/109721/property-details", 109721),
    ("https://www.propwire.com/realestate/4055-Britt-Rd-Mount-Dora-FL/51608674", 51608674),
    ("https://propwire.com/realestate/x/51608674/owner-details?foo=bar", 51608674),
    ("https://propwire.com/search/property-details/22564", 22564),
    ("//propwire.com/realestate/property/128162", 128162),
])
def test_resolve_property(value, expected):
    assert refs.resolve_property(value) == expected


@pytest.mark.parametrize("value", [
    "", "abc", "5400 Halsted Ave", "https://example.com/realestate/x/109721/property-details",
    "https://propwire.com/agents/3a9251b23d22b92d4ca29d8b60fe4183", "https://propwire.com/search?filters=%7B%7D",
])
def test_resolve_property_invalid(value):
    with pytest.raises(ValueError):
        refs.resolve_property(value)


@pytest.mark.parametrize("value,expected", [
    ("3a9251b23d22b92d4ca29d8b60fe4183", {"type": None, "id": "3a9251b23d22b92d4ca29d8b60fe4183"}),
    ("3A9251B23D22B92D4CA29D8B60FE4183", {"type": None, "id": "3a9251b23d22b92d4ca29d8b60fe4183"}),
    ("https://propwire.com/agents/3a9251b23d22b92d4ca29d8b60fe4183",
     {"type": "agent", "id": "3a9251b23d22b92d4ca29d8b60fe4183"}),
    ("https://propwire.com/cash-buyers/a2af0c8eb6b4633fab47d873a8e2368c?x=1",
     {"type": "cash_buyer", "id": "a2af0c8eb6b4633fab47d873a8e2368c"}),
    ("https://propwire.com/people/agents/3a9251b23d22b92d4ca29d8b60fe4183",
     {"type": "agent", "id": "3a9251b23d22b92d4ca29d8b60fe4183"}),
])
def test_resolve_person(value, expected):
    assert refs.resolve_person(value) == expected


@pytest.mark.parametrize("value", [
    "", "keri gann", "3a9251b23d22b92d4ca29d8b60fe418", "https://propwire.com/realestate/x/109721",
    "https://example.com/agents/3a9251b23d22b92d4ca29d8b60fe4183",
])
def test_resolve_person_invalid(value):
    with pytest.raises(ValueError):
        refs.resolve_person(value)


@pytest.mark.parametrize("value,expected", [
    ("78701", {"zip": "78701"}),
    ("78701-1234", {"zip": "78701"}),
    ("tx", {"state": "TX"}),
    ("Austin, TX", {"city": "Austin", "state": "TX"}),
    ("austin tx", {"city": "Austin", "state": "TX"}),
    ("FORT WORTH, tx", {"city": "Fort Worth", "state": "TX"}),
    ("St. Louis, MO", {"city": "Saint Louis", "state": "MO"}),
    ("Travis County, TX", {"county": "Travis", "state": "TX"}),
    ("travis county tx", {"county": "Travis", "state": "TX"}),
])
def test_parse_place(value, expected):
    assert refs.parse_place(value) == expected


@pytest.mark.parametrize("value", ["", "Austin", "Austin, Texas", "1234", "XX", "Paris, FR"])
def test_parse_place_invalid(value):
    with pytest.raises(ValueError):
        refs.parse_place(value)


def test_resolve_location_search_link():
    link = ("https://propwire.com/search?filters=%7B%22locations%22%3A%5B%7B%22searchType%22%3A%22T%22%2C"
            "%22state%22%3A%22FL%22%2C%22title%22%3A%22Florida%2C%20USA%22%2C%22stateName%22%3A%22Florida"
            "%22%7D%5D%2C%22lead_type%22%3A%5B%22preforeclosure%22%5D%2C%22size%22%3A250%7D")
    assert refs.resolve_location(link) == {"locations": [{"state": "FL"}],
                                           "filters": {"lead_type": ["preforeclosure"]}}
    assert refs.resolve_location("Austin, TX") == {"locations": [{"city": "Austin", "state": "TX"}], "filters": {}}


@pytest.mark.parametrize("value", [
    "https://propwire.com/search", "https://propwire.com/search?filters=notjson",
    "https://propwire.com/search?filters=%7B%22size%22%3A5%7D", "https://example.com/search?filters=%7B%7D",
    "https://propwire.com/realestate/x/109721/property-details",
])
def test_resolve_location_bad_links(value):
    with pytest.raises(ValueError):
        refs.resolve_location(value)


def test_links():
    assert refs.property_link(109721, {"street": "5400 Halsted Ave", "city": "Carmichael", "state": "CA"}) == \
        "https://propwire.com/realestate/5400-Halsted-Ave-Carmichael-CA/109721/property-details"
    assert refs.property_link(5) == "https://propwire.com/realestate/property/5/property-details"
    assert refs.person_link("agent", "abc") == "https://propwire.com/agents/abc"
    assert refs.person_link("cash_buyer", "abc") == "https://propwire.com/cash-buyers/abc"
    assert refs.search_link({"locations": [{"state": "WY"}]}).startswith("https://propwire.com/search?filters=%7B")


# ---- value helpers ---------------------------------------------------------------------------

def test_value_helpers():
    assert P._num("0.189868267") == 0.189868267
    assert P._num("30.26724") == 30.26724
    assert P._num("4260") == 4260 and P._num(5.0) == 5 and P._num(True) is None
    assert P._num("Unknown") is None and P._num(None) is None
    assert P._clean("  Type Not Specified ") is None and P._clean("NEED TO MAP") is None
    assert P._clean("Central") == "Central"
    assert P._bool("Yes") is True and P._bool("f") is False and P._bool("Unknown") is None and P._bool(True) is True
    assert P._snake("AttachedGarageYN") == "is_attached_garage"
    assert P._snake("PoolPrivateYN") == "has_pool_private"
    assert P._snake("VirtualTourURLBranded") == "virtual_tour_url_branded"
    assert P._snake("ListAgentURL") == "list_agent_link"
    assert P._snake("BathroomsTotalInteger") == "bathrooms_total_integer"
    assert P._iso_date("11/01/2021") == "2021-11-01" and P._iso_date("2026-03-01") == "2026-03-01"
    assert P._fips("6037") == "06037" and P._fips(6037) == "06037" and P._fips("48453") == "48453"
    assert P._fips(None) is None and P._fips("") is None


# ---- the homepage ------------------------------------------------------------------------------

def test_guest_token_from_homepage():
    token = P.guest_token(fixture("homepage.html"))
    assert token.startswith("eyJ") and token.count(".") == 2
    props = P.parse_inertia_props(fixture("homepage.html"))
    assert props["feature_flags"]["core_api_property_search"] is True
    with pytest.raises(ValueError):
        P.guest_token("<html><body>Please enable JS</body></html>")


# ---- properties/search -------------------------------------------------------------------------

@pytest.fixture(scope="module")
def zip_page():
    return P.parse_search_page(fixture("search_zip_page.json"))


def test_search_page_shape(zip_page):
    assert zip_page["total_count"] == 8224
    assert len(zip_page["results"]) == 3
    assert zip_page["lead_type_counts"]["high_equity"] == 5568


def test_search_card(zip_page):
    card = zip_page["results"][0]
    assert card["id"] == 4826134
    assert card["link"] == "https://propwire.com/realestate/408-E-6th-St-Austin-TX/4826134/property-details"
    assert card["address"] == {"street": "408 E 6th St", "city": "Austin", "state": "TX", "zip": "78701"}
    assert card["location"] == {"latitude": 30.26724, "longitude": -97.7388}
    assert card["property_type"] == "commercial"
    assert card["valuation"]["estimated_value"] == 983810 and card["valuation"]["estimated_ltv"] is None
    assert card["last_sale"] == {"price": 40625000, "date": "2019-12-31"}
    assert card["owner"]["names"] == ["SRPF B/PECAN STREET LP"]
    assert card["owner"]["mailing_address"]["city"] == "DALLAS"
    assert card["owner"]["is_owner_occupied"] is False and card["owner"]["is_individual_owned"] is True
    assert card["owner"]["is_company_owned"] is None
    assert card["owner"]["ownership_years"] == 15
    assert card["lead_types"] == ["absentee_owner", "cash_buyer", "free_and_clear", "high_equity"]
    assert card["mls"]["list_price"] is None and card["listing"] is None
    assert card["features"]["cooling_type"] is None            # "Unknown" -> null
    assert card["features"]["pool"]["has_pool"] is None         # "Unknown"
    assert card["features"]["garage"]["type"] is None and card["features"]["garage"]["area_sqft"] == 0
    assert card["features"]["basement"]["type"] == "NO BASEMENT"
    assert card["tax_assessment"] == {"year": 2025, "total": 964520, "improvements": 0, "land": 964520,
                                      "improvements_percent": 0, "previous_total": 1509739}
    assert card["lot_size_acres"] == 0.059


def test_search_mls_card_has_listing():
    card = P.parse_search_page(fixture("search_mls_active.json"))["results"][0]
    assert card["property_type"] == "single_family"
    assert "mls_active" in card["lead_types"] and "tired_landlord" in card["lead_types"]
    assert card["mls"]["list_price"] == 499990 and card["mls"]["days_on_market"] == 17
    assert card["mls"]["first_photo_link"].startswith("http://lh.rdcpix.com/")
    assert card["valuation"]["estimated_ltv"] == 0.189868267
    assert card["features"]["has_fireplace"] is True and card["features"]["garage"]["type"] == "Garage, Attached"
    listing = card["listing"]
    assert listing["key"] == "3yd-SMABOR-627585" and listing["status"] == "Active"
    assert listing["list_price"] == 499990 and listing["currency"] == "USD"
    assert listing["agent"]["name"] == "Carolyn G. Abbott" and listing["agent"]["email"]
    assert listing["office"]["name"] == "All City Real Estate"
    assert listing["brokerage"]["name"] == "All City Real Estate, Ltd. Co."
    assert listing["brokerage"]["website_link"] == "https://allcityrealestate.com"
    assert listing["schools"]["elementary_school_district"] == "Leander ISD"
    assert listing["link"].startswith("https://www.realtor.com/")
    assert len(listing["photos"]) == 31 and listing["photos_count"] == 31
    assert listing["source"]["system_name"] == "Central Texas Multiple Listing Service"
    assert listing["details"]["is_attached_garage"] is True
    assert listing["details"]["appliances"] == ["Dishwasher", "Disposal", "GasRange"]
    assert listing["details"]["taxes"][0]["tax_annual_amount"] == 10522
    assert "media" not in listing["details"] and "odata.id" not in listing["details"]


def test_search_count_only_and_past_end():
    count = P.parse_search_page(fixture("search_count_only.json"))
    assert count["results"] == [] and count["total_count"] == 340828
    assert count["lead_type_counts"]["preforeclosure"] == 176
    end = P.parse_search_page(fixture("search_past_end.json"))
    assert end == {"results": [], "total_count": 0, "lead_type_counts": {}}


def test_search_by_ids_and_preforeclosure_rows():
    rows = P.parse_search_page(fixture("search_by_ids.json"))["results"]
    assert [r["id"] for r in rows] == [109721, 54254226]
    pre = P.parse_search_page(fixture("search_preforeclosure.json"))["results"][0]
    assert "preforeclosure" in pre["lead_types"]
    assert pre["foreclosure"] == {"is_active": True, "auction_date": "2026-09-01", "auction_time": "10:00 AM"}
    assert P.parse_property_card({"owner_name": " ACME LLC "})["owner"]["names"] == ["ACME LLC"]


def test_search_page_tolerates_garbage():
    assert P.parse_search_page(None) == {"results": [], "total_count": 0, "lead_type_counts": {}}
    assert P.parse_search_page({"response": [None, 3, {"id": "x"}]})["results"][0]["id"] is None
    assert P.parse_property_card({}) ["lead_types"] == []


# ---- properties/details ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def sfr():
    return P.parse_property_details(fixture("details_sfr_109721.json"))


def test_details_identity_and_address(sfr):
    assert sfr["id"] == 109721
    assert sfr["link"] == "https://propwire.com/realestate/5400-Halsted-Ave-Carmichael-CA/109721/property-details"
    assert sfr["address"]["street"] == "5400 Halsted Ave" and sfr["address"]["county"] == "Sacramento"
    assert sfr["address"]["zip4"] == "5126" and sfr["address"]["fips"] == "06067"
    assert sfr["location"] == {"latitude": 38.606104, "longitude": -121.339168, "geocode_quality": "Rooftop"}
    assert sfr["property_type"] == "single_family"
    assert sfr["property_use"]["description"] == "Single Family Residence" and sfr["property_use"]["zoning"] == "RD-5"
    assert sfr["parcel"]["apn"] == "283-0131-011-0000" and sfr["parcel"]["legal_description"] == "CARLDON ESTATES, LOT 47"
    assert sfr["parcel"]["census"]["tract"] == "7702"
    assert sfr["lot"]["size_sqft"] == 10454 and sfr["lot"]["size_acres"] == 0.24 and sfr["lot"]["view"] is None


def test_details_building(sfr):
    b = sfr["building"]
    assert b["year_built"] == 1958 and b["stories"] == 1 and b["living_area_sqft"] == 1824
    assert b["bedrooms"] == 3 and b["bathrooms"] == 3 and b["construction"] == "Wood"
    assert b["roof_material"] == "Other (Not Classified)"
    assert b["floors"]["first_floor_sqft"] == 1174
    assert b["cooling_type"] == "Central" and b["has_fireplace"] is True and b["fireplace_count"] == 1
    assert b["garage"]["area_sqft"] == 435 and b["garage"]["type"] is None
    assert b["basement"]["type"] == "NO BASEMENT"
    assert b["parking"]["spaces"] == 2
    assert b["exterior_amenities"]["pool"] is True and b["exterior_amenities"]["pool_area_sf"] == 3179
    assert b["exterior_amenities"]["pool_type"] is None       # "Type Not Specified"
    assert b["other_structures"]["buildings_count"] == 1
    assert b["rooms"]["rooms_count"] is not None or "rooms_count" in b["rooms"]


def test_details_money_owner_portfolio(sfr):
    assert sfr["valuation"] == {"estimated_value": 657672, "estimated_equity": 70562,
                                "estimated_equity_percent": 11, "price_per_sqft": 360.565789474,
                                "zip_price_per_sqft": 337.026470733}
    assert sfr["last_sale"] == {"price": 605000, "date": "2023-10-05"}
    owner = sfr["owner"]
    assert owner["names"] == ["Hetzler Jason M", "Held Kacey C"] and owner["types"] == ["trust"]
    assert owner["relationship_type"] == "Joint Tenants"
    assert owner["is_owner_occupied"] is True and owner["ownership_years"] == 14 and owner["is_hidden"] is False
    assert owner["mailing_address"]["label"] == "5400 Halsted Ave, Carmichael, CA 95608"
    port = sfr["portfolio"]
    assert port["properties_owned"] == 1 and port["value"] == 657672
    assert port["purchased_last_6_months"] is None            # "NEED TO MAP"
    assert port["linked_property_ids"] == [109721] or port["linked_property_ids"][0] > 0


def test_details_mortgages_transfers_tax(sfr):
    m = sfr["mortgages"][0]
    assert m["transaction_id"] == 1019710042 and m["loan_amount"] == 586850 and m["loan_balance"] == 569493.14
    assert m["interest_rate"] == 7.49 and m["interest_rate_source"] == "Estimated"
    assert m["lender"] == {"name": "GUILD MORTGAGE CO", "code": "M", "type": "MORTGAGE COMPANY"}
    assert m["loan_type"] == "CONVENTIONAL" and m["maturity_date"] == "2053-11-01" and m["term"] == 361
    assert m["term_type"] == "month" and m["position"] == "First" and m["is_adjustable"] is None
    assert m["grantee_name"] == "JASON M HETZLER, KACEY C HELD"
    h = sfr["mortgage_history"][0]
    assert h["deed_type"] == "Grant Deed" and h["instrument_number"] == "202310050484"
    assert h["is_adjustable"] is False and h["lender"]["name"] == "GUILD MORTGAGE CO" and h["amount"] == 586850
    assert len(sfr["mortgage_history"]) == 8 and len(sfr["transfer_history"]) == 10
    t = sfr["transfer_history"][0]
    assert t["amount"] == 605000 and t["is_arms_length"] is True and t["grantor_name"].startswith("Johanna")
    tax = sfr["tax"]
    assert tax["assessment_year"] == 2026 and tax["assessed"]["total"] == 629441
    assert tax["bill"] == {"amount": 7382.08, "year": 2025}
    assert tax["exemptions"]["home_owner"] is True and tax["exemptions"]["senior"] is None
    assert tax["delinquent_year"] is None
    assert sfr["foreclosure"]["is_active"] is None and sfr["foreclosure"]["type"] is None   # NOT DECLARED
    assert sfr["foreclosure"]["notice"]["type"] is None                                      # UNKNOWN
    assert sfr["mls"] == {"days_on_market": None, "history": [], "listing": None}
    assert sfr["photos"] == []


def test_details_mls_listing_and_preforeclosure():
    mls = P.parse_property_details(fixture("details_mls_listing.json"))
    assert len(mls["photos"]) == 31 and mls["photos"][0].startswith("https://images.propwire.com/")
    assert mls["mls"]["listing"]["status"] == "Active" and mls["mls"]["listing"]["list_price"] == 499990
    assert mls["mls"]["listing"]["agent"]["name"] == "Carolyn G. Abbott"
    assert mls["owner"]["is_owner_occupied"] is False and mls["owner"]["mailing_address"]["state"] == "CA"
    assert "mls_active" in mls["lead_types"]
    pre = P.parse_property_details(fixture("details_preforeclosure.json"))
    f = pre["foreclosure"]
    assert f["is_active"] is True and f["notice"]["code"] == "NTS" and f["notice"]["recording_date"] == "2026-06-25"
    assert f["auction"]["date"] == "2026-09-01" and f["auction"]["location"] == "1000 Guadalupe Street"
    assert f["lender_name"] == "Wells Fargo Bank, N.A." and f["trustee"]["name"] == "MCCARTHY & HOLTHUS LLP"
    assert f["judgment"] == {"amount": 0, "date": None}
    assert pre["photos"][0].startswith("https://images.propwire.com/")
    assert "preforeclosure" in pre["lead_types"]


def test_details_not_found_and_garbage():
    assert P.parse_property_details(fixture("details_not_found_404.json")) is None
    assert P.parse_property_details({"response": []}) is None
    assert P.parse_property_details(None) is None
    sparse = P.parse_property_details({"response": [{"id": 7}]}, 7)
    assert sparse["id"] == 7 and sparse["address"] is None and sparse["building"]["year_built"] is None
    assert sparse["mortgages"] == [] and sparse["tax"] is None and sparse["lead_types"] == []


# ---- people -----------------------------------------------------------------------------------

def test_people_pages():
    agents = P.parse_people_page(fixture("people_agents_page.json"))
    assert len(agents) == 3
    a = agents[0]
    assert a["id"] == "3a9251b23d22b92d4ca29d8b60fe4183" and a["type"] == "agent"
    assert a["link"] == "https://propwire.com/agents/3a9251b23d22b92d4ca29d8b60fe4183"
    assert a["name"] == "Keri Gann" and a["company"] == "THE STACY GROUP" and a["phone"] == "512-775-3067"
    assert a["license"] == {"number": "0627115", "state": "TX"}
    assert a["stats"]["transactions"] == 154 and a["stats"]["last_transaction_date"] == "2026-06-10"
    assert a["location"]["county"] == "WILLIAMSON" and a["location"]["latitude"] == 30.487111
    buyers = P.parse_people_page(fixture("people_cash_buyers_page.json"))
    b = buyers[0]
    assert b["type"] == "cash_buyer" and b["link"].startswith("https://propwire.com/cash-buyers/")
    assert b["status"] == "unverified" and b["license"] is None and b["phone"] is None
    assert b["stats"]["properties_owned"] == 27 and b["lead_types"] == ["cash_buyers_unverified"]
    assert P.parse_people_count(fixture("people_count.json")) == 21351
    assert P.parse_people_page({"response": "nope"}) == [] and P.parse_people_count(None) == 0


def test_agent_profile():
    agent = P.parse_agent_profile(fixture("agent_profile.json"))
    assert agent["type"] == "agent" and agent["name"] == "Keri Gann" and agent["email"] == "keri@thestacygroup.com"
    assert agent["brokerage"] == "THE STACY GROUP" and agent["license"]["number"] == "0627115"
    assert agent["location"] == {"city": "Georgetown", "state": "TX"}
    assert agent["stats"]["sold_last_12_months"] == 10 and agent["stats"]["sold_total"] == 154
    assert agent["stats"]["avg_days_on_market"] == 70.271604938
    first = agent["listings"][0]
    assert first["property_id"] == 33715820 and first["price"] == 400000 and first["represented"] == "seller"
    assert first["link"] == "https://propwire.com/realestate/421-Rio-Grande-Loop-Georgetown-TX/33715820/property-details"
    assert first["address"]["zip"] == "78633" and first["property_type"] == "single_family"
    assert P.parse_agent_profile(fixture("profile_not_found_404.json")) is None


def test_cash_buyer_profile():
    buyer = P.parse_cash_buyer_profile(fixture("cash_buyer_profile.json"))
    assert buyer["type"] == "cash_buyer" and buyer["name"] == "CITIBANK NA" and buyer["status"] == "unverified"
    assert buyer["mailing_address"]["city"] == "COPPELL" and buyer["profile_access"] == "restricted"
    assert buyer["buy_box"]["has_price_range"] is True
    assert buyer["stats"] == {"properties_owned": 27, "past_transactions": 20}
    assert buyer["portfolio"]["value"] == 7752072 and buyer["portfolio"]["total_equity"] == 2942261
    item = buyer["portfolio"]["properties"][0]
    assert item["property_id"] == 1137361 and item["estimated_value"] == 188652 and item["year_built"] is None
    assert item["link"].endswith("/1137361/property-details")
    assert P.parse_cash_buyer_profile({}) is None


# ---- markets ------------------------------------------------------------------------------------

def test_market_summary_cards():
    cards = P.parse_market_summary(fixture("market_stats_zip.json"))
    assert cards["city"] is None and cards["county"] is None and cards["neighborhood"] is None
    z = cards["zip"]
    assert z["region"]["name"] == "78701" and z["region"]["metro"] == "Austin, TX" and z["region"]["metro_code"] == 12420
    assert z["period"] == {"begin": "2026-03-01", "end": "2026-05-31", "days": 90, "is_seasonally_adjusted": False}
    assert z["metrics"]["median_sale_price"] == {"value": 541000, "month_over_month": -0.033929, "year_over_year": -0.16124}
    assert z["metrics"]["median_days_on_market"]["value"] == 124.5
    assert z["metrics"]["months_of_supply"] == {"value": None, "month_over_month": None, "year_over_year": None}
    assert z["last_updated"] == "2026-06-02 14:33:24"
    county = P.parse_market_summary(fixture("market_stats_county.json"))
    assert county["county"]["region"]["type"] and county["zip"] is None


def test_market_place_records():
    city = P.parse_market_place(fixture("market_stats_city_full.json"))
    place = city["place"]
    assert place["city"] == "Austin" and place["counties"] == ["Travis", "Williamson", "Hays"]
    assert place["population"] == 1940039 and "78701" in place["zips"] and place["timezone"] == "America/Chicago"
    assert place["metro"]["cbsa_name"] == "Austin-Round Rock-San Marcos, TX" and place["metro"]["is_metro"] is True
    demo = city["demographics"]
    assert demo["income"]["income_household_median"] == 93658 and demo["age"]["age_median"] == 34.7
    assert demo["housing"]["home_value"] == 552730 and demo["education"]["education_bachelors"] == 36.6
    assert demo["race"]["hispanic"] == 31.9 and demo["economy"]["unemployment_rate"] == 4.7
    assert demo["household"]["married"] == 41.6
    assert len(city["trends"]) == 55
    assert city["trends"][0]["period"]["begin"] == "2021-11-01" and city["trends"][0]["region"]["type"] == "place"
    zipr = P.parse_market_place(fixture("market_stats_zip_full.json"))
    assert zipr["place"]["zip"] == "78701" and zipr["place"]["population"] == 11824
    assert zipr["place"]["counties"] == ["Travis"]          # the ZIP record spells it county_names_all
    assert P.parse_market_place({}) is None and P.parse_market_place(None) is None
    # an unknown ZIP answers a shell with state-level trend rows only
    assert P.parse_market_place({"zip": None, "city": None, "market_trends": [{"region": "Alabama"}]}) is None


# ---- autocomplete --------------------------------------------------------------------------------

def test_autocomplete():
    rows = P.parse_autocomplete(fixture("autocomplete_city.json"))
    assert rows[0] == {"type": "county", "title": "Austin, TX", "city": None, "county": "Austin", "state": "TX", "zip": None}
    assert rows[1]["type"] == "city" and rows[1]["city"] == "Austin" and rows[1]["state"] == "AR"
    addr = P.parse_autocomplete(fixture("autocomplete_address.json"))[0]
    assert addr["type"] == "address" and addr["property_id"] == 109721 and addr["apn"] == "283-0131-011-0000"
    assert addr["link"] == "https://propwire.com/realestate/5400-Halsted-Ave-Carmichael-CA/109721/property-details"
    assert addr["location"] == {"latitude": 38.606104, "longitude": -121.339168} and addr["is_fuzzy_match"] is False
    assert P.parse_autocomplete(fixture("autocomplete_none.json")) == []
    assert P.parse_autocomplete(None) == []
