"""Raw Propwire JSON (and the one HTML page) -> clean dicts for every
/propwire/* endpoint. Pure functions, no I/O.

Upstream shapes (propwire/fixtures/, captured 2026-10-31):

  * search_*.json           api.propwire.com/api/property_search — the
                            search-card record (61 fields: address, specs,
                            valuation, owner name + mailing address, lead
                            flags, MLS snapshot, tax assessment, the full
                            ListHub record for an MLS listing)
  * details_*.json          propwire.com/property-details/<id> — the full
                            record: current mortgages, mortgage + transfer
                            history, foreclosure, owner + portfolio, parcel,
                            tax, building (interior / exterior / amenities /
                            structures), MLS listing + photos
  * people_*.json           propwire.com/people-search — agent and cash
                            buyer rows (+ the site's own ad tiles, dropped)
  * agent_profile.json, cash_buyer_profile.json — /people/agents/<id>,
                            /people/cash-buyers/<id>
  * market_stats_*.json     propwire.com/local_markets/search — Redfin-style
                            market cards (summary) and the city / ZIP record
                            with census demographics + monthly trend rows
  * autocomplete_*.json     api.propwire.com/api/auto_complete
  * homepage.html           the Inertia page: `data-page` JSON carries the
                            guest JWT (`props.token`) a session needs

Value conventions (shared with the other scraper packages): snake_case
keys, `link` not `url`, booleans as questions (is_/has_), ISO dates as the
site already sends them, numbers as numbers (the site sends some as
strings: "0.189868267", "30.26724"), and null for every absent value — the
site's own placeholders ("Unknown", "Type Not Specified", "NEED TO MAP",
"NOT DECLARED") are null too.
"""
import html
import json
import re

from propwire.refs import (AUTOCOMPLETE_TYPE_NAMES, PROPERTY_TYPE_NAMES, SITE, person_link,
                           property_link)

# the site's own "no value" markers
_UNKNOWN = {"", "unknown", "type not specified", "need to map", "not declared", "n/a", "na", "none"}

_DATA_PAGE_RE = re.compile(r'data-page="([^"]*)"')
_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


# ---- value helpers -----------------------------------------------------------------

def _clean(value):
    """A string with whitespace collapsed; placeholders and empties -> None."""
    if value is None:
        return None
    if isinstance(value, (int, float, bool, list, dict)):
        return value
    text = " ".join(str(value).split())
    return None if text.lower() in _UNKNOWN else text


def _num(value):
    """int / float / numeric string -> number (int when whole); else None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else value
    text = _clean(value)
    if text is None:
        return None
    try:
        number = float(text.replace(",", ""))
    except ValueError:
        return None
    return int(number) if number.is_integer() else number


def _code(value):
    """An identifier the site may send as a number (census tract 7702) -> str."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return str(_num(value))
    return _clean(value)


def _fips(value):
    """A county FIPS code is 5 digits; the market record drops California's
    leading zero ("6037" for Los Angeles, 2026-11-02), so pad it back."""
    code = _code(value)
    return code.zfill(5) if code and code.isdigit() and len(code) < 5 else code


def _int(value):
    number = _num(value)
    return int(number) if isinstance(number, (int, float)) else None


def _bool(value):
    """True/False stay; "Yes"/"No"/"Y"/"N"/1/0 map; placeholders -> None."""
    if isinstance(value, bool):
        return value
    if value in (0, 1):
        return bool(value)
    text = _clean(value)
    if text is None:
        return None
    low = text.lower()
    if low in ("yes", "y", "true", "t"):
        return True
    if low in ("no", "n", "false", "f"):
        return False
    return None


def _lower(value):
    text = _clean(value)
    return text.lower() if text else None


def _lower_list(values):
    return [v.lower() for v in (values or []) if isinstance(v, str) and v.strip()]


def _get(obj, *path):
    for key in path:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key)
    return obj


def _property_type(value):
    text = _clean(value)
    if text is None:
        return None
    return PROPERTY_TYPE_NAMES.get(text.upper(), text.lower())


def _coords(lat, lng):
    lat, lng = _num(lat), _num(lng)
    if lat is None and lng is None:
        return None
    return {"latitude": lat, "longitude": lng}


def _snake(name):
    """ListHub's RESO CamelCase -> snake_case, with the RESO suffixes turned
    into our conventions: *YN -> has_* / is_*, *URL -> *_link."""
    name = name.lstrip("@")
    if name.endswith("YN"):
        base = name[:-2]
        prefix = "is_" if base.startswith(("Waterfront", "Attached")) else "has_"
        return prefix + _CAMEL_RE.sub("_", base).lower()
    name = re.sub(r"(URL|Url)$", "Link", name)
    return _CAMEL_RE.sub("_", name).lower().replace("__", "_")


# ---- the Inertia page ---------------------------------------------------------------

def parse_inertia_props(page_html):
    """The `props` of an Inertia page (the JSON in the root element's
    data-page attribute). ValueError when the page carries none (a block
    page, a plain redirect)."""
    match = _DATA_PAGE_RE.search(page_html or "")
    if not match:
        raise ValueError("no Inertia data-page attribute in the page")
    try:
        page = json.loads(html.unescape(match.group(1)))
    except ValueError:
        raise ValueError("the data-page attribute is not JSON")
    props = page.get("props") if isinstance(page, dict) else None
    if not isinstance(props, dict):
        raise ValueError("the Inertia page carries no props")
    return props


def guest_token(page_html):
    """The guest JWT a propwire.com page ships for api.propwire.com."""
    token = parse_inertia_props(page_html).get("token")
    if not isinstance(token, str) or token.count(".") != 2:
        raise ValueError("the page carries no guest token")
    return token


# ---- address / owner blocks ----------------------------------------------------------

def _card_address(block):
    block = block if isinstance(block, dict) else {}
    return {
        "street": _clean(block.get("address")),
        "city": _clean(block.get("city")),
        "state": _clean(block.get("state")),
        "zip": _clean(block.get("zip")),
    }


def _card_mailing_address(block):
    if not isinstance(block, dict):
        return None
    out = {
        "street": _clean(block.get("owners_mailing_address")),
        "city": _clean(block.get("owners_mailing_city")),
        "state": _clean(block.get("owners_mailing_state")),
        "zip": _clean(block.get("owners_mailing_zip")),
        "zip4": _clean(block.get("owners_mailing_zip4")),
        "is_private": _bool(block.get("owners_mail_privacy")),
    }
    return out if any(v is not None for v in out.values()) else None


def _detail_address(block):
    """address_details / owner_mailing_address_details -> one shape."""
    if not isinstance(block, dict):
        return None
    return {
        "street": _clean(block.get("address")),
        "house_number": _clean(block.get("house")),
        "street_name": _clean(block.get("street")),
        "street_type": _clean(block.get("street_type")),
        "city": _clean(block.get("city")),
        "county": _clean(block.get("county")),
        "state": _clean(block.get("state")),
        "zip": _clean(block.get("zip")),
        "zip4": _clean(block.get("zip4")),
        "label": _clean(block.get("label")),
        "fips": _clean(block.get("fips")),
        "carrier_route": _clean(block.get("carrier_route")),
        "jurisdiction": _clean(block.get("jurisdiction")),
        "congressional_district": _clean(block.get("congressional_district")),
        "is_private": _bool(block.get("property_address_privacy") if "property_address_privacy" in block
                            else block.get("owner_mail_privacy")),
    }


def _lead_types(value):
    """The card's {flag: true/false/null} map or the record's list -> the
    flags that are on, lower-cased."""
    if isinstance(value, dict):
        return sorted(k for k, v in value.items() if v is True)
    if isinstance(value, list):
        return sorted(_lower_list(value))
    return []


def _tax_assessment(block):
    if not isinstance(block, dict):
        return None
    return {
        "year": _int(block.get("year_assessed")),
        "total": _num(block.get("total")),
        "improvements": _num(block.get("improvements")),
        "land": _num(block.get("land")),
        "improvements_percent": _num(block.get("improvements_percentage")),
        "previous_total": _num(block.get("previous_total")),
    }


def _garage(block):
    if not isinstance(block, dict):
        return None
    return {
        "type": _clean(block.get("garage_type")),
        "area_sqft": _num(block.get("garage_area_sf")),
        "finished_area_sqft": _num(block.get("garage_area_sf_finished")),
        "unfinished_area_sqft": _num(block.get("garage_area_sf_unfinished")),
    }


def _basement(block):
    if not isinstance(block, dict):
        return None
    return {
        "type": _clean(block.get("basement_type")),
        "area_sqft": _num(block.get("basement_sf")),
        "finished_area_sqft": _num(block.get("basement_sf_finished")),
        "unfinished_area_sqft": _num(block.get("basement_sf_unfinished")),
        "finished_percent": _num(block.get("basement_finished_percentage")),
    }


# ---- ListHub (RESO) listing --------------------------------------------------------------

_LISTING_DROP = {"@odata.id", "InternetAddressDisplayYN", "InternetAutomatedValuationDisplayYN",
                 "InternetConsumerCommentYN"}
_CUSTOM_DROP = {"GeocodeOptions", "CustomSourceId"}
_AGENT_PREFIX, _OFFICE_PREFIX, _BROKERAGE_PREFIX = "ListAgent", "ListOffice", "ListBrokerage"
_SCHOOL_KEYS = ("ElementarySchool", "ElementarySchoolDistrict", "MiddleOrJuniorSchool",
                "MiddleOrJuniorSchoolDistrict", "HighSchool", "HighSchoolDistrict")


def _reso_value(value):
    if isinstance(value, str):
        return _clean(value)
    if isinstance(value, list):
        return [_reso_value(v) for v in value]
    if isinstance(value, dict):
        return {_snake(k): _reso_value(v) for k, v in value.items()}
    return value


def parse_listing(listhub):
    """A ListHub (RESO Web API) listing -> a grouped record: identity and
    price, then the agent / office / brokerage / schools / source groups,
    photos as plain links, every other RESO field snake_cased under
    `details`. None when the record is absent."""
    if not isinstance(listhub, dict) or not listhub:
        return None
    custom = listhub.get("CustomFields") if isinstance(listhub.get("CustomFields"), dict) else {}
    agent, office, brokerage, schools, details = {}, {}, {}, {}, {}
    for key, value in listhub.items():
        if key in _LISTING_DROP or key == "CustomFields":
            continue
        if key.startswith(_AGENT_PREFIX):
            agent[_snake(key[len(_AGENT_PREFIX):]) or "name"] = _reso_value(value)
        elif key.startswith(_OFFICE_PREFIX):
            office[_snake(key[len(_OFFICE_PREFIX):])] = _reso_value(value)
        elif key in _SCHOOL_KEYS:
            schools[_snake(key)] = _reso_value(value)
        else:
            details[_snake(key)] = _reso_value(value)
    for key, value in custom.items():
        if key in _CUSTOM_DROP:
            continue
        if key.startswith(_BROKERAGE_PREFIX):
            brokerage[_snake(key[len(_BROKERAGE_PREFIX):])] = _reso_value(value)
        elif key.startswith(_OFFICE_PREFIX):
            office[_snake(key[len(_OFFICE_PREFIX):])] = _reso_value(value)
        else:
            details[_snake(key)] = _reso_value(value)
    photos = []
    for item in listhub.get("Media") or []:
        link = item.get("MediaURL") if isinstance(item, dict) else item
        if isinstance(link, str) and link:
            photos.append(link)
    details.pop("media", None)
    if "listing_link" in details:
        details["link"] = details.pop("listing_link")
    for group in (agent, office, brokerage):
        if "full_name" in group:
            group["name"] = group.pop("full_name")
    return {
        "key": _clean(listhub.get("ListingKey")),
        "id": _clean(listhub.get("ListingId")),
        "status": _clean(listhub.get("StandardStatus")),
        "list_price": _num(listhub.get("ListPrice")),
        "list_price_low": _num(listhub.get("ListPriceLow")),
        "currency": _clean(custom.get("ListPriceCurrencyType")) or "USD",
        "listing_contract_date": _clean(listhub.get("ListingContractDate")),
        "on_market_date": _clean(listhub.get("OnMarketDate")),
        "modified_at": _clean(listhub.get("ModificationTimestamp")),
        "property_type": _clean(listhub.get("PropertyType")),
        "property_sub_type": _clean(listhub.get("PropertySubType")),
        "public_remarks": _clean(listhub.get("PublicRemarks")),
        "link": _clean(custom.get("ListingURL")),
        "photos_count": _int(listhub.get("PhotosCount")),
        "photos": photos,
        "agent": agent or None,
        "office": office or None,
        "brokerage": brokerage or None,
        "schools": schools or None,
        "source": {
            "system_id": _clean(listhub.get("SourceSystemID")),
            "system_name": _clean(listhub.get("SourceSystemName")),
            "disclaimer": _clean(listhub.get("Disclaimer")),
        },
        "details": {k: v for k, v in details.items()
                    if k not in ("listing_key", "listing_id", "standard_status", "list_price",
                                 "list_price_low", "listing_contract_date", "on_market_date",
                                 "modification_timestamp", "property_type", "property_sub_type",
                                 "public_remarks", "photos_count", "source_system_id",
                                 "source_system_name", "disclaimer", "list_price_currency_type")},
    }


# ---- properties/search ---------------------------------------------------------------------

def parse_property_card(card):
    """One property_search row -> the public card record."""
    if not isinstance(card, dict):
        return None
    property_id = _int(card.get("id"))
    address = _card_address(card.get("address"))
    geo = card.get("geo_location") if isinstance(card.get("geo_location"), dict) else {}
    lead_flags = card.get("lead_type")
    return {
        "id": property_id,
        "link": property_link(property_id, address) if property_id else None,
        "address": address,
        "location": _coords(geo.get("latitude"), geo.get("longitude")),
        "property_type": _property_type(card.get("property_type")),
        "bedrooms": _num(card.get("bedrooms")),
        "bathrooms": _num(card.get("bathrooms")),
        "units": _num(card.get("units")),
        "year_built": _int(card.get("year_built")),
        "building_area_sqft": _num(card.get("building_area_sf")),
        "living_area_sqft": _num(card.get("living_area_sf")),
        "lot_size_sqft": _num(card.get("lot_size_sf")),
        "lot_size_acres": _num(card.get("lot_size_acres")),
        "valuation": {
            "estimated_value": _num(card.get("estimated_value")),
            "estimated_equity": _num(card.get("estimated_equity")),
            "estimated_equity_percent": _num(card.get("estimated_equity_percentage")),
            "estimated_ltv": _num(card.get("estimated_ltv")),
            "price_per_sqft": _num(card.get("estimated_price_per_sf")),
            "zip_price_per_sqft": _num(card.get("estimated_zip_price_per_sf")),
        },
        "last_sale": {
            "price": _num(card.get("last_sold_price")),
            "date": _clean(card.get("last_sold_date")),
        },
        "owner": {
            "names": [n.strip() for n in (card.get("owner_name") or []) if isinstance(n, str) and n.strip()]
            if isinstance(card.get("owner_name"), list)
            else [n for n in [_clean(card.get("owner_name"))] if isinstance(n, str)],
            "mailing_address": _card_mailing_address(card.get("owner_mailing_address")),
            "is_owner_occupied": _bool(card.get("owner_occupied")),
            "is_individual_owned": _bool(card.get("individual_owned")),
            "is_company_owned": _bool(card.get("company_owned")),
            "is_trust_owned": _bool(card.get("trust_owned")),
            "is_investor_owned": _bool(card.get("investor_owned")),
            "is_government_owned": _bool(card.get("government_owned")),
            "ownership_months": _int(card.get("months_of_ownership")),
            "ownership_years": _int(card.get("years_of_ownership")),
        },
        "lead_types": _lead_types(lead_flags),
        "mls": {
            "listing_key": _clean(card.get("listing_key")),
            "status": _clean(card.get("mls_attom_last_status")),
            "status_date": _clean(card.get("mls_attom_last_status_date")),
            "list_price": _num(card.get("mls_list_price")),
            "list_date": _clean(card.get("mls_list_date")),
            "list_price_per_sqft": _num(card.get("mls_list_price_per_sf")),
            "sold_price": _num(card.get("mls_sold_price")),
            "sold_date": _clean(card.get("mls_sold_date")),
            "sold_price_per_sqft": _num(card.get("mls_sold_price_per_sf")),
            "last_price": _num(card.get("mls_attom_price")),
            "last_price_per_sqft": _num(card.get("mls_attom_price_per_sf")),
            "days_on_market": _int(card.get("days_on_market")),
            "first_photo_link": _clean(card.get("mls_first_photo_url")),
        },
        "listing": parse_listing(card.get("listhub")),
        "foreclosure": {
            "is_active": _bool(card.get("foreclosure")),
            "auction_date": _clean(card.get("auction_date")),
            "auction_time": _clean(card.get("auction_time")),
        },
        "features": {
            "cooling_type": _clean(card.get("cooling_type")),
            "heating_type": _clean(card.get("heating_type")),
            "heating_fuel": _clean(card.get("heating_fuel")),
            "has_fireplace": _bool(card.get("fireplace")),
            "fireplace_type": _clean(card.get("fireplace_type")),
            "fireplace_count": _int(card.get("fireplace_count")),
            "pool": {
                "has_pool": _bool(card.get("pool")),
                "type": _clean(card.get("pool_type")),
                "area_sqft": _num(card.get("pool_area_sf")),
            },
            "garage": _garage(card.get("garage_details")),
            "basement": _basement(card.get("basement_details")),
        },
        "tax_assessment": _tax_assessment(card.get("tax_assessed_values")),
    }


def parse_search_page(payload):
    """A property_search payload -> {results, total_count, lead_type_counts}.
    `count:true` payloads carry {"count": N} in place of rows (results [])."""
    payload = payload if isinstance(payload, dict) else {}
    rows = payload.get("response")
    results = [parse_property_card(r) for r in rows] if isinstance(rows, list) else []
    total = _int(payload.get("result_count"))
    if total is None and isinstance(rows, dict):
        total = _int(rows.get("count"))
    counts = payload.get("lead_type_counts")
    return {
        "results": [r for r in results if r],
        "total_count": total if total is not None else 0,
        "lead_type_counts": {k: _int(v) for k, v in counts.items()} if isinstance(counts, dict) else {},
    }


# ---- properties/details ----------------------------------------------------------------------

def _rename(block, mapping):
    """{new_key: (old_key, converter)} applied to one upstream block."""
    block = block if isinstance(block, dict) else {}
    return {new: conv(block.get(old)) for new, (old, conv) in mapping.items()}


def _mortgage(row):
    out = _rename(row, {
        "transaction_id": ("transactionid", _int),
        "transaction_type": ("transaction_type", _clean),
        "recording_date": ("recording_date", _clean),
        "grantee_name": ("grantee_name", lambda v: _clean((v or "").strip(", ")) if isinstance(v, str) else None),
        "loan_amount": ("loan_amount", _num),
        "loan_balance": ("loan_balance", _num),
        "interest_rate": ("interest_rate", _num),
        "interest_rate_type": ("interest_rate_type", _clean),
        "interest_rate_source": ("interest_rate_source", _clean),
        "estimated_payment": ("estimated_loan_payment", _num),
        "estimated_balance": ("estimated_loan_balance", _num),
        "is_adjustable": ("adjustable", _bool),
        "is_assumable": ("assumable", _bool),
        "has_balloon": ("balloon", _bool),
        "is_carryback": ("carryback", _bool),
        "is_private_lender": ("private_lender", _bool),
        "is_seller_financed": ("seller_finance", _bool),
        "loan_type": ("loan_type", _clean),
        "loan_type_code": ("loan_type_code", _clean),
        "maturity_date": ("loan_maturity_date", _clean),
        "term": ("term", _int),
        "term_type": ("term_type", _lower),
        "position": ("position", _clean),
    })
    out["lender"] = {
        "name": _clean(row.get("lender_name")),
        "code": _clean(row.get("lender_code")),
        "type": _clean(row.get("lender_type")),
    }
    return out


def _mortgage_history_row(row):
    out = _rename(row, {
        "transaction_id": ("transactionid", _int),
        "transaction_type": ("transaction_type", _clean),
        "transaction_type_code": ("transaction_type_code", _clean),
        "deed_type": ("deed_type", _clean),
        "recording_date": ("recording_date", _clean),
        "document_date": ("document_date", _clean),
        "grantee_name": ("grantee_name", _clean),
        "is_multiple_parcels": ("multiple_parcels", _bool),
        "document_number": ("mortgage_document_number_formatted", _clean),
        "instrument_number": ("mortgage_instrument_number", _clean),
        "book": ("mortgage_book", _clean),
        "page": ("mortgage_page", _clean),
        "amount": ("mortgage_amount", _num),
        "is_adjustable": ("mortgage_adjustable", _bool),
        "is_assumable": ("mortgage_assumable", _bool),
        "interest_rate": ("mortgage_interest_rate", _num),
        "interest_rate_type": ("mortgage_interest_rate_type", _clean),
        "loan_type": ("mortgage_loan_type", _clean),
        "loan_type_code": ("mortgage_loan_type_code", _clean),
        "maturity_date": ("mortgage_loan_maturity_date", _clean),
        "mortgage_recording_date": ("mortgage_recording_date", _clean),
        "term": ("mortgage_term", _int),
        "term_type": ("mortgage_term_type", _lower),
        "recorder_position": ("recorder_position", _int),
    })
    out["lender"] = {
        "name": _clean(row.get("mortgage_lender_name")),
        "code": _clean(row.get("mortgage_lender_code")),
        "type": _clean(row.get("mortgage_lender_type")),
    }
    return out


def _transfer(row):
    return _rename(row, {
        "transaction_id": ("transactionid", _int),
        "recording_date": ("recording_date", _clean),
        "document_date": ("document_date", _clean),
        "amount": ("transfer_amount", _num),
        "grantor_name": ("grantor_name", _clean),
        "grantee_name": ("grantee_name", _clean),
        "deed_type": ("deed_type", _clean),
        "transaction_type": ("transaction_type", _clean),
        "transaction_type_code": ("transaction_type_code", _clean),
        "is_arms_length": ("arms_length_transaction", _bool),
        "is_multi_parcel": ("multiparcel_transaction", _bool),
    })


def _foreclosure(block):
    if not isinstance(block, dict):
        return None
    return {
        "is_active": _bool(block.get("active")),
        "foreclosure_id": _clean(block.get("foreclosure_id")),
        "type": _clean(block.get("foreclosure_type")),
        "notice": {
            "type": _clean(block.get("notice_type")),
            "code": _clean(block.get("notice_type_code")),
            "recording_date": _clean(block.get("recording_date")),
        },
        "auction": {
            "date": _clean(block.get("auction_date")),
            "time": _clean(block.get("auction_time")),
            "city_state": _clean(block.get("auction_city_state")),
            "courthouse": _clean(block.get("auction_courthouse")),
            "location": _clean(block.get("auction_location")),
            "opening_bid": _num(block.get("opening_bid")),
        },
        "borrower_name": _clean(block.get("borrower_name")),
        "case_number": _clean(block.get("case_number")),
        "default_amount": _num(block.get("default_amount")),
        "original_loan_amount": _num(block.get("original_loan_amount")),
        "judgment": {
            "amount": _num(block.get("judgment_amount")),
            "date": _clean(block.get("judgment_date")),
        },
        "lender_name": _clean(block.get("lender_name")),
        "servicer_name": _clean(block.get("servicer_name")),
        "trustee": {
            "name": _clean(block.get("trustee_name")),
            "address": _clean(block.get("trustee_address")),
            "phone": _clean(block.get("trustee_phone")),
            "reference_number": _clean(block.get("trustee_reference_number")),
        },
    }


def _tax(block):
    if not isinstance(block, dict):
        return None
    exemptions = block.get("tax_exemptions") if isinstance(block.get("tax_exemptions"), dict) else {}
    return {
        "assessment_year": _int(block.get("assessment_year")),
        "assessed": {
            "total": _num(block.get("assessed_total_value")),
            "improvements": _num(block.get("assessed_improvement_value")),
            "land": _num(block.get("assessed_land_value")),
            "improvements_percent": _num(block.get("assessed_improvement_percentage")),
            "previous_total": _num(block.get("previous_assessed_total_value")),
        },
        "market": {
            "total": _num(block.get("market_total_value")),
            "improvements": _num(block.get("market_improvement_value")),
            "land": _num(block.get("market_land_value")),
            "improvements_percent": _num(block.get("market_improvement_percentage")),
        },
        "bill": {
            "amount": _num(block.get("tax_billed_amount")),
            "year": _int(block.get("tax_year")),
        },
        "exemptions": {k: _bool(v) for k, v in exemptions.items()},
        "delinquent_year": _int(block.get("tax_delinquent_year")),
    }


def _snake_block(block, skip=()):
    """A flat upstream block whose keys are already snake_case -> values
    cleaned (numbers as numbers, placeholders null), minus `skip`."""
    if not isinstance(block, dict):
        return None
    out = {}
    for key, value in block.items():
        if key in skip:
            continue
        if isinstance(value, bool) or value is None:
            out[key] = value
        elif isinstance(value, (int, float)):
            out[key] = _num(value)
        elif isinstance(value, str):
            number = _num(value)
            out[key] = number if number is not None and re.fullmatch(r"-?[\d.,]+", value.strip()) else _clean(value)
        else:
            out[key] = value
    return out


def _building(details):
    details = details if isinstance(details, dict) else {}
    building = details.get("building_details") if isinstance(details.get("building_details"), dict) else {}
    interior = details.get("building_interior_details") if isinstance(details.get("building_interior_details"), dict) else {}
    parking = details.get("parking_details") if isinstance(details.get("parking_details"), dict) else {}
    return {
        "style": _clean(building.get("building_style")),
        "building_area_sqft": _num(building.get("building_area_sf")),
        "living_area_sqft": _num(building.get("living_area_sf")),
        "year_built": _int(building.get("year_built")),
        "stories": _num(building.get("stories")),
        "units": _num(building.get("units")),
        "construction": _clean(building.get("construction")),
        "exterior_type": _clean(building.get("exterior_type")),
        "foundation": _clean(building.get("foundation")),
        "roof_construction": _clean(building.get("roof_construction")),
        "roof_material": _clean(building.get("roof_material")),
        "fire_resistance_class": _clean(building.get("fire_resistance_class")),
        "interior_style": _clean(building.get("interior_style")),
        "bedrooms": _num(interior.get("bedrooms")),
        "bathrooms": _num(interior.get("bathrooms")),
        "partial_bathrooms": _num(interior.get("partial_bathrooms")),
        "rooms": _snake_block(interior.get("room_details")),
        "floors": {
            "first_floor_sqft": _num(interior.get("area_1st_floor_sf")),
            "second_floor_sqft": _num(interior.get("area_2nd_floor_sf")),
            "upper_floors_sqft": _num(interior.get("area_upper_floors_sf")),
            "attic": _clean(interior.get("attic")),
            "attic_sqft": _num(interior.get("attic_area")),
        },
        "cooling_type": _clean(interior.get("cooling_type")),
        "heating_type": _clean(interior.get("heating_type")),
        "heating_fuel": _clean(interior.get("heating_fuel")),
        "has_fireplace": _bool(interior.get("fireplace")),
        "fireplace_type": _clean(interior.get("fireplace_type")),
        "fireplace_count": _int(interior.get("fireplace_count")),
        "plumbing_fixtures_count": _int(interior.get("plumbing_fixtures_count")),
        "has_fire_sprinklers": _bool(interior.get("safety_fire_sprinklers")),
        "garage": _garage(details.get("garage_details")),
        "basement": _basement(details.get("basement_details")),
        "parking": {
            "spaces": _num(parking.get("parking_spaces")),
            "carport": _clean(parking.get("carport")),
            "carport_area_sqft": _num(parking.get("carport_area_sf")),
            "rv_parking": _clean(parking.get("rv_parking")),
        },
        "exterior": _snake_block(details.get("building_exterior_details")),
        "exterior_amenities": _snake_block(details.get("exterior_amenities")),
        "interior_amenities": _snake_block(details.get("interior_amenities")),
        "other_structures": _snake_block(details.get("other_structures")),
        "utilities": _snake_block(details.get("utility_details")),
    }


def parse_property_details(payload, property_id=None):
    """A /property-details/<id> payload -> the full public record. None
    when the payload carries no record (unknown id)."""
    payload = payload if isinstance(payload, dict) else {}
    rows = payload.get("response")
    record = rows[0] if isinstance(rows, list) and rows and isinstance(rows[0], dict) else None
    if record is None:
        return None
    details = record.get("property_details") if isinstance(record.get("property_details"), dict) else {}
    parcel = record.get("parcel_details") if isinstance(record.get("parcel_details"), dict) else {}
    equity = record.get("equity_details") if isinstance(record.get("equity_details"), dict) else {}
    owner = record.get("owner_details") if isinstance(record.get("owner_details"), dict) else {}
    portfolio = record.get("owner_portfolio_details") if isinstance(record.get("owner_portfolio_details"), dict) else {}
    geo = parcel.get("geolocation") if isinstance(parcel.get("geolocation"), dict) else {}
    pid = _int(record.get("id")) or property_id
    address = _detail_address(details.get("address_details")) or {}
    images = record.get("images") if isinstance(record.get("images"), dict) else {}
    photos = [u for u in (images.get("urls") or []) if isinstance(u, str) and u]
    return {
        "id": pid,
        "link": property_link(pid, address) if pid else None,
        "address": address or None,
        "location": _coords(geo.get("latitude"), geo.get("longitude")) and {
            **_coords(geo.get("latitude"), geo.get("longitude")),
            "geocode_quality": _clean(geo.get("geocode_quality")),
        },
        "property_type": _property_type(parcel.get("property_type")),
        "property_use": {
            "code": _clean(parcel.get("property_use_code")),
            "description": _clean(parcel.get("property_use_code_description")),
            "class": _clean(parcel.get("property_class")),
            "land_use": _clean(parcel.get("land_use")),
            "zoning": _clean(parcel.get("zoning")),
        },
        "parcel": {
            "apn": _clean(parcel.get("apn")),
            "apn_unformatted": _clean(parcel.get("apn_unformatted")),
            "legal_description": _clean(parcel.get("legal_description")),
            "subdivision": _clean(parcel.get("subdivision")),
            "lot_number": _clean(parcel.get("lot_number")),
            "census": {   # codes, not quantities: strings even when the site sends numbers
                "tract": _code(parcel.get("census_tract")),
                "block": _code(parcel.get("census_block")),
                "block_group": _code(parcel.get("census_block_group")),
            },
        },
        "lot": {
            "size_sqft": _num(parcel.get("lot_size_sf")),
            "size_acres": _num(parcel.get("lot_size_acres")),
            "width": _num(parcel.get("area_lot_width")),
            "depth": _num(parcel.get("area_lot_depth")),
            "topography": _clean(parcel.get("topography_type")),
            "view": _clean(parcel.get("view_description")),
        },
        "building": _building(details),
        "valuation": {
            "estimated_value": _num(equity.get("estimated_value")),
            "estimated_equity": _num(equity.get("estimated_equity")),
            "estimated_equity_percent": _num(equity.get("estimated_equity_percentage")),
            "price_per_sqft": _num(equity.get("estimated_price_per_sf")),
            "zip_price_per_sqft": _num(equity.get("estimated_zip_price_per_sf")),
        },
        "last_sale": {
            "price": _num(record.get("last_sold_price")),
            "date": _clean(record.get("last_sold_date")),
        },
        "owner": {
            "names": [n for n in (owner.get("owner_names") or []) if isinstance(n, str) and n.strip()],
            "types": _lower_list(owner.get("owner_type")),
            "relationship_type": _clean(owner.get("owner_relationship_type")),
            "is_owner_occupied": _bool(owner.get("owner_occupied")),
            "ownership_months": _int(owner.get("ownership_length_in_months")),
            "ownership_years": _int(owner.get("ownership_length_in_years")),
            "mailing_address": _detail_address(owner.get("owner_mailing_address_details")),
            "is_hidden": _bool(record.get("hide_owner")),
        },
        "portfolio": {
            "properties_owned": _int(portfolio.get("properties_owned")),
            "value": _num(portfolio.get("portfolio_value")),
            "estimated_equity": _num(portfolio.get("portfolio_estimated_equity")),
            "estimated_mortgage_balance": _num(portfolio.get("portfolio_estimated_mortgage_balance")),
            "purchased_last_6_months": _int(portfolio.get("properties_purchased_last_6_months")),
            "purchased_last_12_months": _int(portfolio.get("properties_purchased_last_12_months")),
            "linked_property_ids": [i for i in (_int(x) for x in (portfolio.get("linked_properties") or []))
                                    if i is not None],
        },
        "lead_types": _lead_types(record.get("lead_type")),
        "lead_type_details": record.get("lead_type_details") if isinstance(record.get("lead_type_details"), list) else [],
        "foreclosure": _foreclosure(record.get("foreclosure_details")),
        "mortgages": [_mortgage(m) for m in (record.get("current_mortgages") or []) if isinstance(m, dict)],
        "mortgage_history": [_mortgage_history_row(m) for m in (record.get("mortgage_history") or [])
                             if isinstance(m, dict)],
        "transfer_history": [_transfer(t) for t in (record.get("transfer_history") or []) if isinstance(t, dict)],
        "tax": _tax(record.get("tax_details")),
        "mls": {
            "days_on_market": _int(record.get("days_on_market")),
            "history": record.get("mls_history") if isinstance(record.get("mls_history"), list) else [],
            "listing": parse_listing(record.get("listhub")),
        },
        "photos": photos,
    }


# ---- people ----------------------------------------------------------------------------------

def _person_type(value):
    text = _lower(value)
    return "cash_buyer" if text in ("cash_buyer", "cash_buyers", "cashbuyer") else text


def parse_person_row(row):
    """One people-search row (agent or cash buyer)."""
    if not isinstance(row, dict):
        return None
    person_id = _clean(row.get("id"))
    kind = _person_type(row.get("profile_type"))
    return {
        "id": person_id,
        "link": person_link(kind, person_id) if person_id and kind else None,
        "type": kind,
        "name": _clean(row.get("full_name")),
        "company": _clean(row.get("company_name")),
        "status": _lower(row.get("status")),
        "phone": _clean(row.get("agent_phone")),
        "license": {
            "number": _clean(row.get("license_number")),
            "state": _clean(row.get("license_state")),
        } if kind == "agent" else None,
        "stats": {
            "transactions": _int(row.get("transactions_count")),
            "avg_sale_price": _num(row.get("avg_sale_price")),
            "properties_owned": _int(row.get("properties_owned")),
            "last_transaction_date": _clean(row.get("last_transaction_date")),
        },
        "location": {
            "city": _clean(row.get("city")),
            "county": _clean(row.get("county")),
            "zip": _clean(row.get("zip")),
            "latitude": _num(row.get("latitude")),
            "longitude": _num(row.get("longitude")),
        },
        "lead_types": _lower_list(row.get("lead_types")),
    }


def parse_people_page(payload):
    """A people-search payload -> the rows (the site's promotional
    `cta_tiles` are dropped; `result_count` is always 0 here — the total
    comes from /people-search/count)."""
    payload = payload if isinstance(payload, dict) else {}
    rows = payload.get("response")
    return [p for p in (parse_person_row(r) for r in (rows if isinstance(rows, list) else [])) if p]


def parse_people_count(payload):
    payload = payload if isinstance(payload, dict) else {}
    return _int(payload.get("result_count")) or 0


def _profile_address(parts):
    """"421 Rio Grande Loop, Georgetown, TX, 78633" + the split fields."""
    return {
        "street": _clean(parts.get("street")),
        "city": _clean(parts.get("city")),
        "state": _clean(parts.get("state")),
        "zip": _clean(parts.get("zip")),
        "label": _clean(parts.get("address")),
    }


def _agent_listing(row):
    pid = _int(row.get("attomid"))
    return {
        "property_id": pid,
        "link": property_link(pid, {"street": row.get("street"), "city": row.get("city"),
                                    "state": row.get("state")}) if pid else None,
        "address": _profile_address(row),
        "price": _num(row.get("price")),
        "bedrooms": _num(row.get("beds")),
        "bathrooms": _num(row.get("baths")),
        "living_area_sqft": _num(row.get("sqft")),
        "property_type": _property_type(row.get("property_type")),
        "represented": _lower(row.get("represented")),
        "status": _clean(row.get("status")),
        "date": _clean(row.get("date")),
        "thumbnail_link": _clean(row.get("thumbnail_url")),
    }


def parse_agent_profile(payload):
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return None
    person_id = _clean(data.get("id"))
    return {
        "id": person_id,
        "link": person_link("agent", person_id) if person_id else None,
        "type": "agent",
        "name": _clean(data.get("full_name")),
        "brokerage": _clean(data.get("brokerage")),
        "phone": _clean(data.get("phone")),
        "email": _clean(data.get("email")),
        "license": {
            "number": _clean(data.get("license_number")),
            "state": _clean(data.get("license_state")),
        },
        "mls_id": _clean(data.get("mls_id")),
        "location": {"city": _clean(data.get("city")), "state": _clean(data.get("state"))},
        "photo_link": _clean(data.get("photo_url")),
        "description": _clean(data.get("description")),
        "stats": {
            "sold_last_12_months": _int(data.get("sold_12m")),
            "sold_total": _int(data.get("total_sold_lifetime")),
            "avg_sold_price": _num(data.get("avg_sold_price")),
            "max_sold_price": _num(data.get("max_sold_price")),
            "min_sold_price": _num(data.get("min_sold_price")),
            "avg_days_on_market": _num(data.get("avg_days_on_market")),
        },
        "listings": [_agent_listing(r) for r in (data.get("listings") or []) if isinstance(r, dict)],
    }


def _portfolio_item(row):
    pid = _int(row.get("attomid"))
    return {
        "property_id": pid,
        "link": property_link(pid, {"street": row.get("street"), "city": row.get("city"),
                                    "state": row.get("state")}) if pid else None,
        "address": _profile_address(row),
        "property_type": _property_type(row.get("property_type")),
        "bedrooms": _num(row.get("beds")),
        "bathrooms": _num(row.get("baths")),
        "lot_size_sqft": _num(row.get("lot_sqft")),
        "year_built": _int(row.get("year_built")),
        "estimated_value": _num(row.get("estimated_value")),
        "estimated_equity": _num(row.get("estimated_equity")),
        "mortgage_balance": _num(row.get("mortgage_balance")),
    }


def parse_cash_buyer_profile(payload):
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return None
    person_id = _clean(data.get("id"))
    portfolio = data.get("portfolio") if isinstance(data.get("portfolio"), dict) else {}
    mailing = data.get("mailing_address") if isinstance(data.get("mailing_address"), dict) else None
    buy_box = data.get("buy_box_summary") if isinstance(data.get("buy_box_summary"), dict) else {}
    return {
        "id": person_id,
        "link": person_link("cash_buyer", person_id) if person_id else None,
        "type": "cash_buyer",
        "name": _clean(data.get("full_name")),
        "status": _lower(data.get("status")),
        "profile_access": _lower(data.get("profile_access")),
        "skip_trace_status": _lower(data.get("skip_trace_status")),
        "mailing_address": {
            "street": _clean(mailing.get("address")),
            "city": _clean(mailing.get("city")),
            "state": _clean(mailing.get("state")),
            "zip": _clean(mailing.get("zip")),
        } if mailing else None,
        "photo_link": _clean(data.get("photo_url")),
        "description": _clean(data.get("description")),
        "buy_box": {k: _bool(v) for k, v in buy_box.items()},
        "stats": {
            "properties_owned": _int(data.get("properties_owned")),
            "past_transactions": _int(data.get("past_transactions_count")),
        },
        "portfolio": {
            "properties_owned": _int(portfolio.get("properties_owned")),
            "value": _num(portfolio.get("portfolio_value")),
            "mortgage_balance": _num(portfolio.get("mortgage_balance")),
            "total_equity": _num(portfolio.get("total_equity")),
            "properties": [_portfolio_item(r) for r in (portfolio.get("items") or []) if isinstance(r, dict)],
        },
    }


# ---- markets/stats -----------------------------------------------------------------------------

_TREND_METRICS = (
    "median_sale_price", "median_list_price", "median_ppsf", "median_list_ppsf", "homes_sold",
    "pending_sales", "new_listings", "inventory", "months_of_supply", "median_dom",
    "avg_sale_to_list", "sold_above_list", "price_drops", "off_market_in_two_weeks",
)
_TREND_NAMES = {"median_ppsf": "median_price_per_sqft", "median_list_ppsf": "median_list_price_per_sqft",
                "median_dom": "median_days_on_market"}


def _iso_date(value):
    """"11/01/2021" (the trend rows) -> "2021-11-01"; ISO dates pass through."""
    text = _clean(value)
    if not text:
        return None
    match = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", text)
    if match:
        return f"{match.group(3)}-{int(match.group(1)):02d}-{int(match.group(2)):02d}"
    return text


def parse_market_card(card):
    """One Redfin-style market row (a summary card or a trend row) -> the
    period, the region and every metric as {value, month_over_month,
    year_over_year}."""
    if not isinstance(card, dict):
        return None
    metrics = {}
    for key in _TREND_METRICS:
        metrics[_TREND_NAMES.get(key, key)] = {
            "value": _num(card.get(key)),
            "month_over_month": _num(card.get(f"{key}_mom")),
            "year_over_year": _num(card.get(f"{key}_yoy")),
        }
    return {
        "region": {
            "type": _clean(card.get("region_type")),
            "name": _clean(card.get("region")),
            "city": _clean(card.get("city")),
            "state": _clean(card.get("state")),
            "state_code": _clean(card.get("state_code")),
            "metro": _clean(card.get("parent_metro_region")),
            "metro_code": _int(card.get("parent_metro_region_metro_code")),
        },
        "period": {
            "begin": _iso_date(card.get("period_begin")),
            "end": _iso_date(card.get("period_end")),
            "days": _int(card.get("period_duration")),
            "is_seasonally_adjusted": _bool(card.get("is_seasonally_adjusted")),
        },
        "property_type": _clean(card.get("property_type")),
        "metrics": metrics,
        "last_updated": _clean(card.get("last_updated")),
    }


def parse_market_summary(payload):
    """The summary:true payload -> {zip, city, county, neighborhood} cards."""
    payload = payload if isinstance(payload, dict) else {}
    return {
        "zip": parse_market_card(payload.get("zip_card")),
        "city": parse_market_card(payload.get("city_card")),
        "county": parse_market_card(payload.get("county_card")),
        "neighborhood": parse_market_card(payload.get("neighborhood_card")),
    }


_DEMOGRAPHIC_GROUPS = {
    "age": ("age_",),
    "income": ("income_",),
    "education": ("education_",),
    "race": ("race_", "hispanic"),
    "housing": ("home_ownership", "housing_units", "home_value", "rent_median", "rent_burden"),
    "household": ("married", "divorced", "never_married", "widowed", "family_size", "family_dual_income",
                  "male", "female"),
    "economy": ("labor_force_participation", "unemployment_rate", "poverty", "commute_time",
                "health_uninsured", "disabled", "limited_english", "veteran"),
}
_PLACE_KEYS = ("city", "city_ascii", "city_alt", "state", "state_name", "county_fips", "county_name",
               "county_fips_all", "county_name_all", "lat", "lng", "population", "population_proper",
               "density", "timezone", "ranking", "zips", "city_id", "cbsa_fips", "cbsa_name", "cbsa_metro",
               "csa_fips", "csa_name", "zip", "zcta", "parent_zcta", "source", "military", "incorporated",
               "cdp", "township", "county_names_all", "county_weights", "imprecise")


def parse_market_place(payload):
    """The summary:false payload (a city or ZIP record) -> {place,
    demographics, trends}. None when the site knows no such place."""
    if not isinstance(payload, dict) or not payload:
        return None
    # an unknown ZIP answers a shell: no place fields, only state-level
    # trend rows; that is "no such place", not a record
    if not any(payload.get(k) for k in ("city", "zip", "county_fips", "population")):
        return None
    place = {
        "city": _clean(payload.get("city_ascii") or payload.get("city")),
        "state": _clean(payload.get("state")),
        "state_name": _clean(payload.get("state_name")),
        "zip": _clean(payload.get("zip")),
        "county": _clean(payload.get("county_name")),
        "county_fips": _fips(payload.get("county_fips")),
        "counties": [c for c in (payload.get("county_name_all") or payload.get("county_names_all") or "").split("|")
                     if c] or None,
        "location": _coords(payload.get("lat"), payload.get("lng")),
        "timezone": _clean(payload.get("timezone")),
        "population": _int(payload.get("population")),
        "population_proper": _int(payload.get("population_proper")),
        "density": _num(payload.get("density")),
        "zips": (payload.get("zips") or "").split() or None,
        "metro": {
            "cbsa_code": _clean(payload.get("cbsa_fips")),
            "cbsa_name": _clean(payload.get("cbsa_name")),
            "is_metro": _bool(payload.get("cbsa_metro")),
            "csa_code": _clean(payload.get("csa_fips")),
            "csa_name": _clean(payload.get("csa_name")),
        },
    }
    demographics = {group: {} for group in _DEMOGRAPHIC_GROUPS}
    for key, value in payload.items():
        if key in _PLACE_KEYS or key == "market_trends":
            continue
        for group, prefixes in _DEMOGRAPHIC_GROUPS.items():
            if any(key == p or key.startswith(p) for p in prefixes):
                demographics[group][key] = _num(value)
                break
    demographics = {g: v for g, v in demographics.items() if v}
    trends = [parse_market_card(r) for r in (payload.get("market_trends") or []) if isinstance(r, dict)]
    return {"place": place, "demographics": demographics or None, "trends": [t for t in trends if t]}


# ---- autocomplete / lookup --------------------------------------------------------------------

def parse_autocomplete(payload):
    """auto_complete rows -> places and addresses (an address row carries
    the property id, so it links straight to properties/details)."""
    payload = payload if isinstance(payload, dict) else {}
    out = []
    for row in payload.get("data") or []:
        if not isinstance(row, dict):
            continue
        kind = AUTOCOMPLETE_TYPE_NAMES.get(row.get("searchType"), _lower(row.get("searchType")))
        item = {
            "type": kind,
            "title": _clean(row.get("title")),
            "city": _clean(row.get("city")),
            "county": _clean(row.get("county")),
            "state": _clean(row.get("state")),
            "zip": _clean(row.get("zip")),
        }
        if kind == "address":
            pid = _int(row.get("id"))
            item.update({
                "property_id": pid,
                "link": property_link(pid, {"street": row.get("street"), "city": row.get("city"),
                                            "state": row.get("state")}) if pid else None,
                "street": _clean(row.get("street")),
                "address": _clean(row.get("address")),
                "apn": _clean(row.get("apn")),
                "location": _coords(row.get("latitude"), row.get("longitude")),
                "is_fuzzy_match": _bool(row.get("fuzzy")),
            })
        out.append(item)
    return out
