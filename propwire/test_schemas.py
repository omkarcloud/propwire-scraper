"""Offline tests for the /propwire/* request schemas.

    python -m pytest propwire/test_schemas.py -q
"""
import os
import sys

import pytest
from marshmallow import ValidationError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from propwire import refs, schemas  # noqa: E402


def _load(schema, params):
    return schema().load(params)


def _rejects(schema, params, field=None, fragment=None):
    with pytest.raises(ValidationError) as info:
        schema().load(params)
    messages = info.value.normalized_messages()
    if field:
        assert field in messages, messages
    if fragment:
        assert fragment in str(messages), messages
    return messages


# ---- properties/search ---------------------------------------------------------------------

def test_search_accepts_places_and_links():
    loaded = _load(schemas.PropertiesSearchSchema, {"location": "Austin, TX"})
    assert loaded["location"] == {"locations": [{"city": "Austin", "state": "TX"}], "filters": {}}
    assert loaded["page"] == 1 and loaded["per_page"] == schemas.SEARCH_PAGE_SIZE and loaded["order"] == "desc"
    assert loaded["sort"] is None and loaded["lead_type"] is None
    link = ("https://propwire.com/search?filters=%7B%22locations%22%3A%5B%7B%22state%22%3A%22FL%22%7D%5D"
            "%2C%22lead_type%22%3A%5B%22preforeclosure%22%5D%7D")
    loaded = _load(schemas.PropertiesSearchSchema, {"location": link})
    assert loaded["location"] == {"locations": [{"state": "FL"}], "filters": {"lead_type": ["preforeclosure"]}}
    for value, expected in [("78701", {"zip": "78701"}), ("tx", {"state": "TX"}),
                            ("Travis County, TX", {"county": "Travis", "state": "TX"})]:
        assert _load(schemas.PropertiesSearchSchema, {"location": value})["location"]["locations"] == [expected]


def test_search_filters_map_to_tokens():
    loaded = _load(schemas.PropertiesSearchSchema, {
        "location": "78701", "lead_type": "High_Equity, absentee_owner,high_equity",
        "property_type": "single_family,Multi_Family_2_4", "beds_min": "3", "baths_min": "2.5",
        "value_min": "250000", "value_max": "900000", "equity_percent_min": "60",
        "last_sold_after": "2024-01-01", "owner_type": "Company,individual", "owner_occupied": "false",
        "has_pool": "yes", "notice_type": "notice_of_default", "sort": "Equity_Percent", "order": "ASC",
        "page": "3", "per_page": "100", "tax_delinquent_since": "2022", "year_built_min": "1990",
    })
    assert loaded["lead_type"] == ["high_equity", "absentee_owner"]
    assert loaded["property_type"] == ["sfr", "mfh_2_to_4"]
    assert loaded["beds_min"] == 3 and loaded["baths_min"] == 2.5
    assert loaded["value_min"] == 250000 and loaded["value_max"] == 900000 and loaded["equity_percent_min"] == 60
    assert loaded["last_sold_after"] == "2024-01-01"
    assert loaded["owner_type"] == ["company", "individual"]
    assert loaded["owner_occupied"] is False and loaded["has_pool"] is True
    assert loaded["notice_type"] == "NOD"
    assert loaded["sort"] == "estimated_equity_percentage" and loaded["order"] == "asc"
    assert loaded["page"] == 3 and loaded["per_page"] == 100
    assert loaded["tax_delinquent_since"] == 2022 and loaded["year_built_min"] == 1990


def test_search_map_point():
    loaded = _load(schemas.PropertiesSearchSchema, {"lat": "30.2672", "lng": "-97.7431", "radius_miles": "2"})
    assert loaded["location"] is None and loaded["lat"] == 30.2672 and loaded["radius_miles"] == 2
    _rejects(schemas.PropertiesSearchSchema, {"lat": "30.2672"}, "lat", "go together")
    _rejects(schemas.PropertiesSearchSchema, {"location": "TX", "radius_miles": "2"}, "radius_miles")
    _rejects(schemas.PropertiesSearchSchema, {"lat": "95", "lng": "0"}, "lat")
    _rejects(schemas.PropertiesSearchSchema, {"lat": "30", "lng": "-97", "radius_miles": "500"}, "radius_miles")


def test_search_requires_a_where():
    _rejects(schemas.PropertiesSearchSchema, {}, "location", "Give a location")
    _rejects(schemas.PropertiesSearchSchema, {"location": ""}, "location")
    _rejects(schemas.PropertiesSearchSchema, {"location": "Austin"}, "location", "City, ST")
    _rejects(schemas.PropertiesSearchSchema, {"location": "https://example.com/search?filters=%7B%7D"}, "location")


def test_search_rejects_premium_lead_types_and_unknown_tokens():
    messages = _rejects(schemas.PropertiesSearchSchema, {"location": "TX", "lead_type": "bankruptcy"}, "lead_type")
    assert "bankruptcy" in str(messages)
    _rejects(schemas.PropertiesSearchSchema, {"location": "TX", "property_type": "castle"}, "property_type")
    _rejects(schemas.PropertiesSearchSchema, {"location": "TX", "sort": "price"}, "sort")
    _rejects(schemas.PropertiesSearchSchema, {"location": "TX", "order": "up"}, "order")
    _rejects(schemas.PropertiesSearchSchema, {"location": "TX", "notice_type": "lis"}, "notice_type")
    _rejects(schemas.PropertiesSearchSchema, {"location": "TX", "owner_type": "llc"}, "owner_type")
    _rejects(schemas.PropertiesSearchSchema, {"location": "TX", "owner_occupied": "maybe"}, "owner_occupied")
    _rejects(schemas.PropertiesSearchSchema, {"location": "TX", "last_sold_after": "01/02/2024"}, "last_sold_after")


def test_search_rejects_inverted_ranges_and_the_cap():
    _rejects(schemas.PropertiesSearchSchema, {"location": "TX", "beds_min": "5", "beds_max": "2"}, "beds_max",
             "beds_min must not exceed beds_max")
    _rejects(schemas.PropertiesSearchSchema, {"location": "TX", "last_sold_after": "2025-01-01",
                                              "last_sold_before": "2024-01-01"}, "last_sold_before")
    _load(schemas.PropertiesSearchSchema, {"location": "TX", "page": "40", "per_page": "250"})   # row 10,000
    _rejects(schemas.PropertiesSearchSchema, {"location": "TX", "page": "41", "per_page": "250"}, "page", "10,000")
    _rejects(schemas.PropertiesSearchSchema, {"location": "TX", "per_page": "251"}, "per_page")
    _rejects(schemas.PropertiesSearchSchema, {"location": "TX", "page": "0"}, "page")


def test_search_rejects_sibling_params():
    _rejects(schemas.PropertiesSearchSchema, {"location": "TX", "url": "https://propwire.com/search"}, "url")
    _rejects(schemas.PropertiesSearchSchema, {"location": "TX", "id": "109721"}, "id")


# ---- properties/details + lookup ------------------------------------------------------------

def test_details_schema():
    assert _load(schemas.PropertyDetailsSchema, {"property": "109721"}) == {"property": 109721}
    link = "https://propwire.com/realestate/5400-Halsted-Ave/109721/property-details"
    assert _load(schemas.PropertyDetailsSchema, {"property": link}) == {"property": 109721}
    _rejects(schemas.PropertyDetailsSchema, {}, "property")
    _rejects(schemas.PropertyDetailsSchema, {"property": "5400 Halsted Ave"}, "property", "propwire.com property link")
    _rejects(schemas.PropertyDetailsSchema, {"property": "109721", "id": "109721"}, "id")


def test_lookup_schema():
    assert _load(schemas.PropertiesLookupSchema, {"address": " 5400 Halsted Ave,  Carmichael "}) == \
        {"address": "5400 Halsted Ave, Carmichael"}
    _rejects(schemas.PropertiesLookupSchema, {}, "address")
    _rejects(schemas.PropertiesLookupSchema, {"address": ""}, "address")
    _rejects(schemas.PropertiesLookupSchema, {"address": "x" * 201}, "address")


# ---- people -----------------------------------------------------------------------------------

def test_people_search_schema():
    loaded = _load(schemas.PeopleSearchSchema, {"type": "Cash_Buyer", "location": "78701"})
    assert loaded["type"] == "cash_buyers_unverified" and loaded["location"] == {"zip": "78701"}
    assert loaded["per_page"] == schemas.PEOPLE_PAGE_SIZE and loaded["page"] == 1
    loaded = _load(schemas.PeopleSearchSchema, {
        "type": "agent", "location": "Austin, TX", "name": " Keri ", "transactions_min": "10",
        "avg_sale_price_max": "1000000", "last_transaction_after": "2025-01-01", "sort": "transactions",
        "order": "asc", "per_page": "250"})
    assert loaded["type"] == "agent" and loaded["name"] == "Keri" and loaded["transactions_min"] == 10
    assert loaded["sort"] == "transactions_count" and loaded["order"] == "asc" and loaded["per_page"] == 250
    _rejects(schemas.PeopleSearchSchema, {"location": "TX"}, "type")
    _rejects(schemas.PeopleSearchSchema, {"type": "agent"}, "location")
    _rejects(schemas.PeopleSearchSchema, {"type": "wholesaler", "location": "TX"}, "type")
    _rejects(schemas.PeopleSearchSchema, {"type": "agent", "location": "https://propwire.com/search?filters=%7B%7D"},
             "location")
    _rejects(schemas.PeopleSearchSchema, {"type": "agent", "location": "TX", "per_page": "251"}, "per_page")
    _rejects(schemas.PeopleSearchSchema, {"type": "agent", "location": "TX", "page": "41", "per_page": "250"}, "page")
    _rejects(schemas.PeopleSearchSchema, {"type": "agent", "location": "TX", "transactions_min": "9",
                                          "transactions_max": "3"}, "transactions_max")
    _rejects(schemas.PeopleSearchSchema, {"type": "agent", "location": "TX", "sort": "name"}, "sort")


def test_person_details_schema():
    assert _load(schemas.PersonDetailsSchema, {"person": "3a9251b23d22b92d4ca29d8b60fe4183"}) == \
        {"person": {"type": None, "id": "3a9251b23d22b92d4ca29d8b60fe4183"}}
    assert _load(schemas.PersonDetailsSchema,
                 {"person": "https://propwire.com/cash-buyers/a2af0c8eb6b4633fab47d873a8e2368c"}) == \
        {"person": {"type": "cash_buyer", "id": "a2af0c8eb6b4633fab47d873a8e2368c"}}
    _rejects(schemas.PersonDetailsSchema, {}, "person")
    _rejects(schemas.PersonDetailsSchema, {"person": "keri gann"}, "person", "32 hex")
    _rejects(schemas.PersonDetailsSchema, {"person": "3a9251b23d22b92d4ca29d8b60fe4183", "url": "x"}, "url")


# ---- markets + autocomplete ---------------------------------------------------------------------

def test_market_stats_schema():
    assert _load(schemas.MarketStatsSchema, {"location": "78701"}) == {"location": {"zip": "78701"}}
    assert _load(schemas.MarketStatsSchema, {"location": "austin, tx"}) == \
        {"location": {"city": "Austin", "state": "TX"}}
    assert _load(schemas.MarketStatsSchema, {"location": "Travis County, TX"}) == \
        {"location": {"county": "Travis", "state": "TX"}}
    _rejects(schemas.MarketStatsSchema, {"location": "TX"}, "location", "not a whole state")
    _rejects(schemas.MarketStatsSchema, {}, "location")
    _rejects(schemas.MarketStatsSchema, {"location": "Paris"}, "location")


def test_autocomplete_schema():
    assert _load(schemas.AutocompleteSchema, {"query": "Aus"}) == {"query": "Aus", "types": None}
    assert _load(schemas.AutocompleteSchema, {"query": "Aus", "types": "City, zip,address"}) == \
        {"query": "Aus", "types": ["C", "Z", "A"]}
    _rejects(schemas.AutocompleteSchema, {}, "query")
    _rejects(schemas.AutocompleteSchema, {"query": "Aus", "types": "street"}, "types")
    assert set(refs.AUTOCOMPLETE_TYPES.values()) == {"C", "Z", "N", "T", "A"}
