"""Reference resolvers and the vocabulary tables for /propwire/*.

ONE param per input (tripadvisor QueryOrIdField convention):

  * `property`  a numeric Propwire property id OR any propwire.com property
                link (/realestate/<address-slug>/<id>[/<tab>],
                /realestate/property/<id>, /search/<tab>/<id>). The slug is
                decorative: the numeric id is the key.
  * `person`    a 32-hex profile hash OR a propwire.com /agents/<hash> or
                /cash-buyers/<hash> link (the link also tells the type).
  * `location`  free text — a 5-digit ZIP, a 2-letter state, "City, ST",
                "Travis County, TX" — OR a propwire.com search link whose
                `filters` JSON (the site's own search payload) is replayed.

Resolvers raise ValueError with a user-facing message (RefField -> 400).

The vocabularies come from the site itself (captured 2026-10-30/31): the
lead-type tiers from the `config.lead_type_filter` prop every page ships,
the property-type and sort tokens from the search bundle
(DevPropertySearchPayload / SimpleFilter chunks), each one verified against
api.propwire.com/api/property_search.
"""
import json
import re
from urllib.parse import parse_qs, unquote, urlparse

SITE = "https://propwire.com"
API = "https://api.propwire.com/api"

US_STATES = frozenset("""
AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC
ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY PR VI GU
""".split())

# Lead types a guest session may filter on (verified 2026-10-31: every one
# returns a count; AND semantics when several are sent). The site's other
# 45 flags sit behind Premium Leads, Gold, Contractor Leads Pro or Listing
# Leads Pro memberships and answer 403 (PREMIUM_LEAD_TYPES), or are
# always-empty product stubs (warm_call_leads, foreclosure).
FREE_LEAD_TYPES = (
    "absentee_owner", "adjustable_loan", "assumable_loan", "auction", "bank_owned",
    "cash_buyer", "empty_nester", "flipped_property", "free_and_clear", "high_equity",
    "intrafamily_transfer", "low_equity", "negative_equity", "out_of_state_owner",
    "preforeclosure", "preprobate", "private_lender", "tired_landlord", "vacant_home",
    "vacant_lot", "zombie_property", "mls_active", "mls_pending", "mls_sold", "mls_failed",
)

PREMIUM_LEAD_TYPES = (
    "abandoned_homes", "bankruptcy", "code_violation", "divorce", "lien_misc", "lien_tax",
    "tax_dodgers", "ultra_liens", "ultra_violations",                           # Premium Leads
    "bargain_properties", "cash_flow_rentals", "creative_financing", "desperate_landlords",
    "hidden_gems_mls", "sub_to_mls", "sub_to_off_market",                       # Gold
    "adu_potential", "basement_finishing", "foundation_issues", "hvac_leads", "landscaping",
    "luxury_remodels", "maintenance_leads", "make_it_mine", "outdoor_upgrades", "pool_repair",
    "rehab_leads", "remodelers", "renovations", "roofing_leads", "roofing_motivated",
    "siding_leads", "vacation_homes",                                           # Contractor Leads Pro
    "burned_out_landlords", "expired_listings_new", "expireds_follow_up", "expireds_re_engage",
    "high_equity_motivated", "listing_leads", "move_up_sellers", "portfolio_landlords",
    "ready_to_list", "sellable_distressed", "silver_sellers",                   # Listing Leads Pro
)

# public value -> the site's property_type token (and the reverse for records)
PROPERTY_TYPES = {
    "single_family": "sfr",
    "condo": "condo",
    "mobile": "mobile",
    "multi_family_2_4": "mfh_2_to_4",
    "multi_family_5_plus": "mfh_5_plus",
    "land": "land",
    "commercial": "commercial",
    "other": "other",
}
PROPERTY_TYPE_NAMES = {token.upper(): name for name, token in PROPERTY_TYPES.items()}

# public sort name -> the site's sort field (verified 2026-10-31: the API
# wants `sort` as an object {field: "asc"|"desc"}; an unknown field is an
# Elasticsearch 500)
SORT_FIELDS = {
    "estimated_value": "estimated_value",
    "estimated_equity": "estimated_equity",
    "equity_percent": "estimated_equity_percentage",
    "list_price": "mls_list_price",
    "list_price_per_sqft": "mls_list_price_per_sf",
    "days_on_market": "days_on_market",
    "last_sold_price": "last_sold_price",
    "last_sold_date": "last_sold_date",
    "living_area": "living_area_sf",
    "year_built": "year_built",
}

NOTICE_TYPES = {
    "lis_pendens": "LIS",
    "notice_of_default": "NOD",
    "notice_of_trustee_sale": "NTS",
    "notice_of_sale": "NOS",
    "reo": "REO",
}

OWNER_TYPES = ("individual", "company", "bank")

# people/search `type` -> the site's people_lead_type token. "cash_buyers_active"
# exists too but answers an empty page to guests (2026-10-31), so it is not offered.
PEOPLE_TYPES = {"agent": "agent", "cash_buyer": "cash_buyers_unverified"}
PEOPLE_TYPE_NAMES = {token: name for name, token in PEOPLE_TYPES.items()}

PEOPLE_SORT_FIELDS = {
    "transactions": "transactions_count",
    "avg_sale_price": "avg_sale_price",
    "properties_owned": "properties_owned",
    "last_transaction_date": "last_transaction_date",
}

# locations/autocomplete `types` -> the site's search_types letters
AUTOCOMPLETE_TYPES = {"city": "C", "zip": "Z", "county": "N", "state": "T", "address": "A"}
AUTOCOMPLETE_TYPE_NAMES = {v: k for k, v in AUTOCOMPLETE_TYPES.items()}

# Both searches stop serving rows past this offset (verified 2026-10-31:
# property_search answers an empty page at result_index 10000, people-search
# a 422 "The total number of results cannot exceed 10,000").
MAX_RESULTS = 10_000

_ID_RE = re.compile(r"^[0-9]{1,12}$")
_HASH_RE = re.compile(r"^[0-9a-f]{32}$", re.I)
_LINK_PROPERTY_RE = re.compile(r"/(?:realestate/[^/]+|search/[^/]+)/([0-9]{1,12})(?:/|$|\?)")
_LINK_PERSON_RE = re.compile(r"/(?:people/)?(agents|cash-buyers)/([0-9a-f]{32})(?:/|$|\?)", re.I)
_ZIP_RE = re.compile(r"^([0-9]{5})(?:-[0-9]{4})?$")
_CITY_STATE_RE = re.compile(r"^(.+?)[\s,]+([A-Za-z]{2})\.?$")
_COUNTY_RE = re.compile(r"^(.+?)\s+county$", re.I)


def _is_link(value):
    return value.startswith(("http://", "https://", "//"))


def _as_url(value):
    return value if not value.startswith("//") else "https:" + value


def _host_is_propwire(url):
    host = (urlparse(url).hostname or "").lower()
    return host == "propwire.com" or host.endswith(".propwire.com")


def resolve_property(value):
    """Bare numeric id or a propwire.com property link -> int id."""
    value = (value or "").strip()
    if _ID_RE.match(value):
        return int(value)
    if _is_link(value):
        url = _as_url(value)
        if not _host_is_propwire(url):
            raise ValueError("Must be a propwire.com link.")
        match = _LINK_PROPERTY_RE.search(urlparse(url).path)
        if match:
            return int(match.group(1))
        raise ValueError("Must be a propwire.com property link "
                         "(https://propwire.com/realestate/<address>/<id>/property-details).")
    raise ValueError("Must be a Propwire property id (109721) or a propwire.com property link.")


def resolve_person(value):
    """Bare 32-hex profile hash or an /agents/<hash> | /cash-buyers/<hash>
    link -> {"type": "agent" | "cash_buyer" | None, "id": hash}. A bare
    hash carries no type; people_details tries both profile kinds."""
    value = (value or "").strip()
    if _HASH_RE.match(value):
        return {"type": None, "id": value.lower()}
    if _is_link(value):
        url = _as_url(value)
        if not _host_is_propwire(url):
            raise ValueError("Must be a propwire.com link.")
        match = _LINK_PERSON_RE.search(urlparse(url).path)
        if match:
            kind = "agent" if match.group(1).lower() == "agents" else "cash_buyer"
            return {"type": kind, "id": match.group(2).lower()}
        raise ValueError("Must be a propwire.com agent or cash buyer link "
                         "(https://propwire.com/agents/<id>, https://propwire.com/cash-buyers/<id>).")
    raise ValueError("Must be a Propwire profile id (32 hex characters, from people/search) "
                     "or a propwire.com /agents/<id> or /cash-buyers/<id> link.")


_SAINT_RE = re.compile(r"^st\.?\s+", re.I)


def _title(value):
    """Title-case a place name the way Propwire indexes it: "austin" ->
    "Austin", and "St. Louis" / "St Louis" -> "Saint Louis" (the index
    spells Saint out; the abbreviated forms match nothing, 2026-10-31)."""
    value = _SAINT_RE.sub("Saint ", value.strip())
    return " ".join(w[:1].upper() + w[1:].lower() for w in value.split())


def parse_place(value):
    """Free text -> one `locations` entry for the search API:
    "78701" -> {zip}, "TX" -> {state}, "Austin, TX" -> {city, state},
    "Travis County, TX" -> {county, state}. ValueError otherwise."""
    text = " ".join((value or "").split())
    match = _ZIP_RE.match(text)
    if match:
        return {"zip": match.group(1)}
    if len(text) == 2 and text.upper() in US_STATES:
        return {"state": text.upper()}
    match = _CITY_STATE_RE.match(text)
    if match and match.group(2).upper() in US_STATES:
        place, state = match.group(1).strip(" ,"), match.group(2).upper()
        county = _COUNTY_RE.match(place)
        if county:
            return {"county": _title(county.group(1)), "state": state}
        if place:
            return {"city": _title(place), "state": state}
    raise ValueError('Must be a 5-digit ZIP, a 2-letter state, "City, ST" or '
                     '"<Name> County, ST" (e.g. 78701, TX, "Austin, TX", "Travis County, TX").')


# keys of the site's search payload that a pasted search link may carry and
# that are safe to replay (the caller's own params override them)
_LINK_FILTER_KEYS = {
    "locations", "lead_type", "property_type", "beds", "baths", "estimated_value",
    "estimated_equity", "estimated_equity_percent", "last_sold_price", "last_sold_date",
    "year_built", "building_area", "lot_size_sf", "stories", "years_owned",
    "properties_owned", "portfolio_value", "tax_delinquent_year", "assessed_total_value",
    "assessed_land_value", "assessed_improvement_value", "owner_type", "owner_occupied",
    "out_of_state_owner", "cash_buyer", "pool", "vacant_home", "notice_type", "notice_date",
    "auction_date", "opening_bid", "mls_list_price", "days_on_market", "latitude", "longitude",
    "radius", "polygons", "sort", "units", "private_lender", "preforeclosure", "estimated_ltv",
}


def _clean_link_location(entry):
    """A search link's location entry carries UI fields (title, stateName,
    searchType); keep what the API keys on."""
    if not isinstance(entry, dict):
        return None
    out = {}
    for key in ("state", "city", "zip", "county"):
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            out[key] = value.strip()
    return out or None


def parse_search_link(url):
    """A propwire.com/search?filters=<json> link -> the site's own filter
    payload, restricted to the replayable keys. ValueError when the link
    carries no usable filters."""
    if not _host_is_propwire(url):
        raise ValueError("Must be a propwire.com link.")
    parsed = urlparse(url)
    if not parsed.path.rstrip("/").endswith("/search") and not parsed.path.startswith("/properties"):
        raise ValueError("Must be a propwire.com search link (https://propwire.com/search?filters=...).")
    raw = (parse_qs(parsed.query).get("filters") or [None])[0]
    try:
        filters = json.loads(unquote(raw)) if raw else None
    except ValueError:
        filters = None
    if not isinstance(filters, dict):
        raise ValueError("The search link carries no filters= JSON.")
    out = {k: v for k, v in filters.items() if k in _LINK_FILTER_KEYS and v not in (None, "", [], {})}
    locations = [loc for loc in (_clean_link_location(e) for e in (out.get("locations") or [])) if loc]
    if locations:
        out["locations"] = locations
    else:
        out.pop("locations", None)
    if not out:
        raise ValueError("The search link carries no usable filters.")
    return out


def resolve_location(value):
    """`location` -> {"locations": [...], "filters": {...}}: a place string
    gives one location and no filters; a search link gives the link's
    locations (possibly none, for a map-only search) and its filters."""
    value = (value or "").strip()
    if _is_link(value):
        filters = parse_search_link(_as_url(value))
        locations = filters.pop("locations", [])
        return {"locations": locations, "filters": filters}
    return {"locations": [parse_place(value)], "filters": {}}


# ---- links ------------------------------------------------------------------------

def _slug(*parts):
    text = " ".join(p for p in parts if p)
    text = re.sub(r"[,#]", "", text)
    return "-".join(text.split()) or "property"


def property_link(property_id, address=None):
    """The site's own property link: /realestate/<address slug>/<id>/property-details
    (the frontend builds the slug from the street address; any slug serves)."""
    address = address or {}
    slug = _slug(address.get("street") or address.get("address"), address.get("city"), address.get("state"))
    return f"{SITE}/realestate/{slug}/{property_id}/property-details"


def person_link(kind, person_id):
    return f"{SITE}/{'agents' if kind == 'agent' else 'cash-buyers'}/{person_id}"


def search_link(filters):
    """A propwire.com search link that reproduces one API payload."""
    from urllib.parse import quote
    return f"{SITE}/search?filters={quote(json.dumps(filters, separators=(',', ':')))}"
