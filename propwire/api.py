"""The /propwire/* endpoint functions (route_glue's route_table calls them
with the schema's loaded kwargs). Every endpoint caches its own response
through cache.cached_call keyed on the validated params (propwire/cache_config);
the people count of one filter set is cached once and shared by every page
of it, and a ZIP's state (an auto_complete lookup) is cached for a month.
"""
import math

from cache import cached_call
from propwire import cache_config as ttl
from propwire import parsers, refs
from propwire.fetch import (PropwireNotFound, fetch_agent_profile, fetch_autocomplete,
                            fetch_cash_buyer_profile, fetch_market_stats, fetch_people_count,
                            fetch_people_search, fetch_property_details, fetch_property_search)

DEFAULT_RADIUS_MILES = 1


def _range(low, high):
    out = {}
    if low is not None:
        out["min"] = low
    if high is not None:
        out["max"] = high
    return out or None


def _set(body, key, value):
    if value is not None:
        body[key] = value


# ---- places ------------------------------------------------------------------------

def _zip_state(zip_code):
    """The state a ZIP lies in, from the site's own autocomplete (cached a
    month). NotFound for a ZIP the site does not index: property_search
    answers such a ZIP with a bare 500 and people-search requires the state."""
    def lookup(zip_code):
        rows = parsers.parse_autocomplete(fetch_autocomplete(zip_code, ["Z"]))
        for row in rows:
            if row.get("zip") == zip_code and row.get("state"):
                return {"state": row["state"]}
        raise PropwireNotFound(f"ZIP {zip_code} is not in Propwire's index")
    return cached_call("propwire.zip", {"zip_code": zip_code}, lookup, ttl.ZIP_CACHE)["state"]


def _with_state(place):
    """A {zip} place gets its state (the people search requires one and the
    property search 500s on an unknown ZIP); other places pass through."""
    if "zip" in place and "state" not in place:
        return {"state": _zip_state(place["zip"]), "zip": place["zip"]}
    return dict(place)


# ---- properties/search ---------------------------------------------------------------

def _search_body(data):
    """The site's property_search payload for the validated params: a
    pasted search link's filters first, then the explicit params on top."""
    where = data.get("location") or {"locations": [], "filters": {}}
    body = dict(where.get("filters") or {})
    locations = [_with_state(p) for p in (where.get("locations") or [])]
    if locations:
        body["locations"] = locations
    if data.get("lat") is not None:
        body["latitude"] = data["lat"]
        body["longitude"] = data["lng"]
        body["radius"] = data.get("radius_miles") or DEFAULT_RADIUS_MILES
    _set(body, "lead_type", data.get("lead_type"))
    _set(body, "property_type", data.get("property_type"))
    _set(body, "beds", _range(data.get("beds_min"), data.get("beds_max")))
    _set(body, "baths", _range(data.get("baths_min"), data.get("baths_max")))
    _set(body, "estimated_value", _range(data.get("value_min"), data.get("value_max")))
    _set(body, "estimated_equity", _range(data.get("equity_min"), data.get("equity_max")))
    _set(body, "estimated_equity_percent", _range(data.get("equity_percent_min"), data.get("equity_percent_max")))
    _set(body, "last_sold_price", _range(data.get("last_sold_price_min"), data.get("last_sold_price_max")))
    _set(body, "last_sold_date", _range(data.get("last_sold_after"), data.get("last_sold_before")))
    _set(body, "mls_list_price", _range(data.get("list_price_min"), data.get("list_price_max")))
    _set(body, "days_on_market", _range(data.get("days_on_market_min"), data.get("days_on_market_max")))
    _set(body, "assessed_total_value", _range(data.get("assessed_value_min"), data.get("assessed_value_max")))
    _set(body, "building_area", _range(data.get("sqft_min"), data.get("sqft_max")))
    _set(body, "lot_size_sf", _range(data.get("lot_sqft_min"), data.get("lot_sqft_max")))
    _set(body, "year_built", _range(data.get("year_built_min"), data.get("year_built_max")))
    _set(body, "stories", _range(data.get("stories_min"), data.get("stories_max")))
    _set(body, "units", _range(data.get("units_min"), data.get("units_max")))
    _set(body, "owner_type", data.get("owner_type"))
    _set(body, "owner_occupied", data.get("owner_occupied"))
    _set(body, "out_of_state_owner", data.get("out_of_state_owner"))
    _set(body, "years_owned", _range(data.get("years_owned_min"), data.get("years_owned_max")))
    _set(body, "properties_owned", _range(data.get("properties_owned_min"), data.get("properties_owned_max")))
    _set(body, "portfolio_value", _range(data.get("portfolio_value_min"), data.get("portfolio_value_max")))
    _set(body, "tax_delinquent_year", _range(data.get("tax_delinquent_since"), None))
    _set(body, "pool", data.get("has_pool"))
    _set(body, "vacant_home", data.get("vacant"))
    _set(body, "notice_type", data.get("notice_type"))
    _set(body, "notice_date", _range(data.get("notice_after"), data.get("notice_before")))
    _set(body, "auction_date", _range(data.get("auction_after"), data.get("auction_before")))
    if data.get("sort"):
        body["sort"] = {data["sort"]: data.get("order") or "desc"}
    for key in ("size", "result_index", "count", "ids_only", "ids"):
        body.pop(key, None)
    return body


def _properties_search(**data):
    page, size = data["page"], data["per_page"]
    filters = _search_body(data)
    body = {**filters, "size": size, "result_index": (page - 1) * size}
    parsed = parsers.parse_search_page(fetch_property_search(body))
    total = parsed["total_count"]
    reachable = min(total, refs.MAX_RESULTS)
    return {
        "query": filters,
        "link": refs.search_link(filters),
        "results": parsed["results"],
        "reachable_count": reachable,
        "lead_type_counts": parsed["lead_type_counts"],
        "pagination": {
            "page": page,
            "items_per_page": size,
            "total_pages": math.ceil(reachable / size) if reachable else 0,
            "total_count": total,
        },
    }


def properties_search(**data):
    """Search US properties by place or map point with motivated-seller lead
    filters (absentee owner, high equity, pre-foreclosure...), value, equity,
    size, owner and foreclosure filters; each row carries the owner's name
    and mailing address, valuation, lead flags and MLS snapshot. Up to
    10,000 rows per search."""
    return cached_call("propwire.search", data, _properties_search, ttl.SEARCH_CACHE)


# ---- properties/details ----------------------------------------------------------------

def _property_details(property):
    record = parsers.parse_property_details(fetch_property_details(property), property)
    if record is None:
        raise PropwireNotFound(f"property {property} not found")
    return record


def property_details(**data):
    """The full record of one property: owner and mailing address, owner
    portfolio, current mortgages, mortgage and transfer history, foreclosure
    and auction details, tax assessment, parcel and zoning, building specs,
    and the MLS listing with photos when it is for sale."""
    return cached_call("propwire.details", data, _property_details, ttl.DETAILS_CACHE)


# ---- properties/lookup -----------------------------------------------------------------

def _properties_lookup(address):
    rows = parsers.parse_autocomplete(fetch_autocomplete(address, ["A"]))
    return {"query": address, "count": len(rows), "results": rows}


def properties_lookup(**data):
    """Match a street address (or APN) to Propwire property ids, with county,
    APN and coordinates."""
    return cached_call("propwire.lookup", data, _properties_lookup, ttl.LOOKUP_CACHE)


# ---- people/search ----------------------------------------------------------------------

def _people_filters(data):
    body = {
        "people_lead_type": [data["type"]],
        "locations": [_with_state(data["location"])],
    }
    _set(body, "name", data.get("name"))
    _set(body, "transactions_count", _range(data.get("transactions_min"), data.get("transactions_max")))
    _set(body, "properties_owned", _range(data.get("properties_owned_min"), data.get("properties_owned_max")))
    _set(body, "avg_sale_price", _range(data.get("avg_sale_price_min"), data.get("avg_sale_price_max")))
    _set(body, "last_transaction_date",
         _range(data.get("last_transaction_after"), data.get("last_transaction_before")))
    return body


def _people_count(**filters):
    return parsers.parse_people_count(fetch_people_count(filters))


def _people_search(**data):
    page, size = data["page"], data["per_page"]
    filters = _people_filters(data)
    body = dict(filters)
    if data.get("sort"):
        body["sort"] = {data["sort"]: data.get("order") or "desc"}
    body.update({"size": size, "result_index": (page - 1) * size})
    rows = parsers.parse_people_page(fetch_people_search(body))
    total = cached_call("propwire.people_count", filters, _people_count, ttl.PEOPLE_COUNT_CACHE)
    reachable = min(total, refs.MAX_RESULTS)
    return {
        "query": {**filters, "people_lead_type": refs.PEOPLE_TYPE_NAMES.get(data["type"], data["type"])},
        "results": rows,
        "reachable_count": reachable,
        "pagination": {
            "page": page,
            "items_per_page": size,
            "total_pages": math.ceil(reachable / size) if reachable else 0,
            "total_count": total,
        },
    }


def people_search(**data):
    """Find real estate agents (phone, license, deal count) or cash buyers
    (portfolio size, deal count) in a ZIP, city or county, filtered by
    transactions, properties owned, average sale price and last deal date."""
    return cached_call("propwire.people", data, _people_search, ttl.PEOPLE_SEARCH_CACHE)


# ---- people/details -----------------------------------------------------------------------

def _person_details(person):
    kind, person_id = person["type"], person["id"]
    if kind == "agent":
        return parsers.parse_agent_profile(fetch_agent_profile(person_id))
    if kind == "cash_buyer":
        return parsers.parse_cash_buyer_profile(fetch_cash_buyer_profile(person_id))
    # a bare hash: the site keys agents and cash buyers apart, try both
    try:
        record = parsers.parse_agent_profile(fetch_agent_profile(person_id))
    except PropwireNotFound:
        record = None
    if record is None:
        try:
            record = parsers.parse_cash_buyer_profile(fetch_cash_buyer_profile(person_id))
        except PropwireNotFound:
            record = None
    if record is None:
        raise PropwireNotFound(f"no agent or cash buyer profile {person_id}")
    return record


def person_details(**data):
    """One agent profile (phone, email, license, 12-month sales, recent deals)
    or cash buyer profile (mailing address, portfolio value, owned properties)."""
    record = cached_call("propwire.person", data, _person_details, ttl.PERSON_CACHE)
    if record is None:
        raise PropwireNotFound(f"no profile {data['person']['id']}")
    return record


# ---- markets/stats ------------------------------------------------------------------------

def _market_stats(location):
    place = _with_state(location)
    summary = parsers.parse_market_summary(fetch_market_stats(place, True))
    detail = parsers.parse_market_place(fetch_market_stats(place, False))
    if not any(summary.values()) and detail is None:
        raise PropwireNotFound(f"no market data for {', '.join(f'{k}={v}' for k, v in place.items())}")
    place_record = (detail or {}).get("place")
    if place_record and place.get("county") and not place_record.get("county"):
        place_record["county"] = place["county"]   # the county record names itself only by FIPS
    return {
        "query": place,
        "place": place_record,
        "summary": summary,
        "demographics": (detail or {}).get("demographics"),
        "trends": (detail or {}).get("trends") or [],
    }


def market_stats(**data):
    """Housing market stats for a ZIP, city or county: median sale and list
    prices, inventory, days on market with month and year changes, census
    demographics and monthly market trends."""
    return cached_call("propwire.markets", data, _market_stats, ttl.MARKET_CACHE)


# ---- locations/autocomplete ----------------------------------------------------------------

def _autocomplete(query, types):
    letters = types or list(refs.AUTOCOMPLETE_TYPES.values())
    rows = parsers.parse_autocomplete(fetch_autocomplete(query, letters))
    return {"query": query, "count": len(rows), "results": rows}


def locations_autocomplete(**data):
    """Suggest cities, ZIP codes, counties, states and street addresses for
    the start of a place name."""
    return cached_call("propwire.autocomplete", data, _autocomplete, ttl.AUTOCOMPLETE_CACHE)
