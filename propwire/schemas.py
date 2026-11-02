"""Marshmallow request schemas for every /propwire/* route.

ONE param per input (tripadvisor QueryOrIdField convention, never a sibling
`url` / `id` pair):

    property   a numeric Propwire property id OR any propwire.com property link
    person     a 32-hex profile id (from people/search) OR a propwire.com
               /agents/<id> or /cash-buyers/<id> link
    location   "78701" | "TX" | "Austin, TX" | "Travis County, TX" OR, for
               properties/search, a propwire.com search link whose filters
               are replayed (explicit params override the link's)

Both searches page through at most 10,000 rows (the site's own cap), so
page x per_page is validated against it instead of faking later pages.
"""
from marshmallow import ValidationError, fields, missing, validate, validates_schema

from propwire import refs
from schema_fields import (BaseSchema, ChoiceField, CommaListField, DateField, Flag, NonNegativeNumber,
                           PageField, PageSizeField, PositiveInt, Price, QueryField, RefField,
                           StrippedString)

SEARCH_PAGE_SIZE = 50        # default rows per properties/search page
SEARCH_MAX_PAGE_SIZE = 250   # the API serves up to 1,000; 250 keeps a page ~0.5 MB
PEOPLE_PAGE_SIZE = 50
PEOPLE_MAX_PAGE_SIZE = 250   # the site's own ceiling ("The size must not be greater than 250")
MAX_RADIUS_MILES = 50


class PropertyRefField(RefField):
    resolver = staticmethod(refs.resolve_property)


class PersonRefField(RefField):
    resolver = staticmethod(refs.resolve_person)


class LocationField(RefField):
    """A place string or a propwire.com search link -> {locations, filters}."""
    resolver = staticmethod(refs.resolve_location)


class PlaceField(RefField):
    """A place string only -> one {zip | state | city+state | county+state}."""
    resolver = staticmethod(refs.parse_place)


def _d(text):
    return {"description": text}


class _Coordinate(fields.Float):
    def __init__(self, low, high, **kwargs):
        kwargs.setdefault("load_default", None)
        kwargs.setdefault("validate", validate.Range(min=low, max=high))
        super().__init__(**kwargs)


def _check_ranges(data, pairs):
    for low, high in pairs:
        if data.get(low) is not None and data.get(high) is not None and data[low] > data[high]:
            raise ValidationError(f"{low} must not exceed {high}.", high)


def _check_cap(data):
    if data.get("page", 1) * data.get("per_page", 1) > refs.MAX_RESULTS:
        raise ValidationError(
            f"Propwire serves at most {refs.MAX_RESULTS:,} rows per search (page x per_page); "
            "narrow the location or filters to reach the rest.", "page")


_SEARCH_PAIRS = (
    ("beds_min", "beds_max"), ("baths_min", "baths_max"), ("value_min", "value_max"),
    ("equity_min", "equity_max"), ("equity_percent_min", "equity_percent_max"),
    ("last_sold_price_min", "last_sold_price_max"), ("list_price_min", "list_price_max"),
    ("assessed_value_min", "assessed_value_max"), ("portfolio_value_min", "portfolio_value_max"),
    ("sqft_min", "sqft_max"), ("lot_sqft_min", "lot_sqft_max"), ("year_built_min", "year_built_max"),
    ("stories_min", "stories_max"), ("units_min", "units_max"), ("years_owned_min", "years_owned_max"),
    ("properties_owned_min", "properties_owned_max"), ("days_on_market_min", "days_on_market_max"),
    ("last_sold_after", "last_sold_before"), ("auction_after", "auction_before"),
    ("notice_after", "notice_before"),
)


class PropertiesSearchSchema(BaseSchema):
    location = LocationField(required=False, load_default=None, metadata=_d(
        'where to search: a ZIP ("78701"), a state ("TX"), "City, ST" ("Austin, TX"), '
        '"<Name> County, ST" ("Travis County, TX"), or a propwire.com search link '
        '(https://propwire.com/search?filters=...) whose filters are replayed; '
        'or give lat + lng + radius_miles instead'))
    lat = _Coordinate(-90, 90, metadata=_d("map-point search: latitude (with lng and radius_miles)"))
    lng = _Coordinate(-180, 180, metadata=_d("map-point search: longitude"))
    radius_miles = NonNegativeNumber(validate=validate.Range(min=0.1, max=MAX_RADIUS_MILES), metadata=_d(
        f"map-point search: radius around lat/lng in miles (default 1, max {MAX_RADIUS_MILES})"))
    lead_type = CommaListField(allowed=refs.FREE_LEAD_TYPES, upper=False, max_items=5, metadata=_d(
        "comma list of motivated-seller flags; a property must carry EVERY flag given (AND). "
        "One of: " + ", ".join(refs.FREE_LEAD_TYPES)))
    property_type = CommaListField(value_map=refs.PROPERTY_TYPES, upper=False, max_items=8, metadata=_d(
        "comma list of property types (any of them): " + ", ".join(refs.PROPERTY_TYPES)))
    beds_min = PositiveInt(max_value=50, metadata=_d("minimum bedrooms"))
    beds_max = PositiveInt(max_value=50, metadata=_d("maximum bedrooms"))
    baths_min = NonNegativeNumber(metadata=_d("minimum bathrooms (2.5 allowed)"))
    baths_max = NonNegativeNumber(metadata=_d("maximum bathrooms"))
    value_min = Price(metadata=_d("minimum estimated value, USD"))
    value_max = Price(metadata=_d("maximum estimated value, USD"))
    equity_min = Price(metadata=_d("minimum estimated equity, USD"))
    equity_max = Price(metadata=_d("maximum estimated equity, USD"))
    equity_percent_min = NonNegativeNumber(validate=validate.Range(min=0, max=100), metadata=_d(
        "minimum estimated equity as a percentage of value (60 = the site's own high-equity threshold)"))
    equity_percent_max = NonNegativeNumber(validate=validate.Range(min=0, max=100), metadata=_d(
        "maximum estimated equity percentage"))
    last_sold_price_min = Price(metadata=_d("minimum last sale price, USD"))
    last_sold_price_max = Price(metadata=_d("maximum last sale price, USD"))
    last_sold_after = DateField(metadata=_d("last sold on or after this date (YYYY-MM-DD)"))
    last_sold_before = DateField(metadata=_d("last sold on or before this date (YYYY-MM-DD)"))
    list_price_min = Price(metadata=_d("minimum MLS list price, USD (listed properties only)"))
    list_price_max = Price(metadata=_d("maximum MLS list price, USD"))
    days_on_market_min = PositiveInt(max_value=10_000, metadata=_d("minimum days on market (listed properties only)"))
    days_on_market_max = PositiveInt(max_value=10_000, metadata=_d("maximum days on market"))
    assessed_value_min = Price(metadata=_d("minimum tax-assessed total value, USD"))
    assessed_value_max = Price(metadata=_d("maximum tax-assessed total value, USD"))
    sqft_min = PositiveInt(max_value=10_000_000, metadata=_d("minimum building area, square feet"))
    sqft_max = PositiveInt(max_value=10_000_000, metadata=_d("maximum building area, square feet"))
    lot_sqft_min = PositiveInt(max_value=1_000_000_000, metadata=_d("minimum lot size, square feet (an acre is 43,560)"))
    lot_sqft_max = PositiveInt(max_value=1_000_000_000, metadata=_d("maximum lot size, square feet"))
    year_built_min = PositiveInt(validate=validate.Range(min=1600, max=2100), metadata=_d("built in or after this year"))
    year_built_max = PositiveInt(validate=validate.Range(min=1600, max=2100), metadata=_d("built in or before this year"))
    stories_min = PositiveInt(max_value=200, metadata=_d("minimum stories"))
    stories_max = PositiveInt(max_value=200, metadata=_d("maximum stories"))
    units_min = PositiveInt(max_value=10_000, metadata=_d("minimum units (multi-family)"))
    units_max = PositiveInt(max_value=10_000, metadata=_d("maximum units"))
    owner_type = CommaListField(allowed=refs.OWNER_TYPES, upper=False, max_items=3, metadata=_d(
        "who holds the title, comma list of: " + ", ".join(refs.OWNER_TYPES)))
    owner_occupied = Flag(metadata=_d("true = owner lives there, false = absentee owner"))
    out_of_state_owner = Flag(metadata=_d("true = the owner's mailing address is in another state"))
    years_owned_min = PositiveInt(max_value=200, metadata=_d("owned by the current owner for at least this many years"))
    years_owned_max = PositiveInt(max_value=200, metadata=_d("owned for at most this many years"))
    properties_owned_min = PositiveInt(max_value=100_000, metadata=_d("the owner holds at least this many properties"))
    properties_owned_max = PositiveInt(max_value=100_000, metadata=_d("the owner holds at most this many properties"))
    portfolio_value_min = Price(metadata=_d("minimum value of the owner's whole portfolio, USD"))
    portfolio_value_max = Price(metadata=_d("maximum portfolio value, USD"))
    tax_delinquent_since = PositiveInt(validate=validate.Range(min=1990, max=2100), metadata=_d(
        "only properties with unpaid property taxes going back to this year or later"))
    has_pool = Flag(metadata=_d("true = only properties recorded with a swimming pool"))
    vacant = Flag(metadata=_d("true = only properties flagged vacant"))
    notice_type = ChoiceField(refs.NOTICE_TYPES, metadata=_d(
        "foreclosure filing recorded: " + ", ".join(refs.NOTICE_TYPES)))
    notice_after = DateField(metadata=_d("foreclosure notice recorded on or after (YYYY-MM-DD)"))
    notice_before = DateField(metadata=_d("foreclosure notice recorded on or before (YYYY-MM-DD)"))
    auction_after = DateField(metadata=_d("foreclosure auction on or after (YYYY-MM-DD)"))
    auction_before = DateField(metadata=_d("foreclosure auction on or before (YYYY-MM-DD)"))
    sort = ChoiceField(refs.SORT_FIELDS, metadata=_d(
        "order the rows by one of: " + ", ".join(refs.SORT_FIELDS) + " (the site's own order otherwise)"))
    order = ChoiceField(["desc", "asc"], load_default="desc", metadata=_d("sort direction (default desc)"))
    page = PageField(max_page=refs.MAX_RESULTS, metadata=_d("1-based page"))
    per_page = PageSizeField(default=SEARCH_PAGE_SIZE, max_size=SEARCH_MAX_PAGE_SIZE, metadata=_d(
        f"rows per page (default {SEARCH_PAGE_SIZE}, max {SEARCH_MAX_PAGE_SIZE})"))

    @validates_schema
    def _where(self, data, **kwargs):
        has_point = data.get("lat") is not None or data.get("lng") is not None
        if has_point and (data.get("lat") is None or data.get("lng") is None):
            raise ValidationError("lat and lng go together.", "lat")
        if not has_point and not data.get("location"):
            raise ValidationError("Give a location (ZIP, state, \"City, ST\", \"<Name> County, ST\" or a "
                                  "propwire.com search link) or lat + lng.", "location")
        if data.get("radius_miles") is not None and not has_point:
            raise ValidationError("radius_miles needs lat and lng.", "radius_miles")
        _check_ranges(data, _SEARCH_PAIRS)
        _check_cap(data)


class PropertyDetailsSchema(BaseSchema):
    property = PropertyRefField(metadata=_d(
        "Propwire property id (109721) or a propwire.com property link "
        "(https://propwire.com/realestate/5400-Halsted-Ave/109721/property-details)"))


class PropertiesLookupSchema(BaseSchema):
    address = QueryField(max_length=200, metadata=_d(
        'a US street address ("5400 Halsted Ave, Carmichael, CA 95608") or an assessor parcel number'))


_PEOPLE_PAIRS = (
    ("transactions_min", "transactions_max"), ("properties_owned_min", "properties_owned_max"),
    ("avg_sale_price_min", "avg_sale_price_max"), ("last_transaction_after", "last_transaction_before"),
)


class PeopleSearchSchema(BaseSchema):
    type = ChoiceField(refs.PEOPLE_TYPES, required=True, load_default=missing, metadata=_d(
        "who to find: agent (phone + license) or cash_buyer (companies and investors buying without a mortgage)"))
    location = PlaceField(metadata=_d(
        'where: a ZIP ("78701"), a state ("TX"), "City, ST" or "<Name> County, ST"'))
    name = StrippedString(validate=validate.Length(min=1, max=100), load_default=None, metadata=_d(
        "only people or companies whose name contains this text"))
    transactions_min = PositiveInt(max_value=1_000_000, metadata=_d("at least this many recorded transactions"))
    transactions_max = PositiveInt(max_value=1_000_000, metadata=_d("at most this many transactions"))
    properties_owned_min = PositiveInt(max_value=1_000_000, metadata=_d("currently owns at least this many properties"))
    properties_owned_max = PositiveInt(max_value=1_000_000, metadata=_d("owns at most this many properties"))
    avg_sale_price_min = Price(metadata=_d("average deal size at least this much, USD"))
    avg_sale_price_max = Price(metadata=_d("average deal size at most this much, USD"))
    last_transaction_after = DateField(metadata=_d("most recent purchase or sale on or after (YYYY-MM-DD)"))
    last_transaction_before = DateField(metadata=_d("most recent purchase or sale on or before (YYYY-MM-DD)"))
    sort = ChoiceField(refs.PEOPLE_SORT_FIELDS, metadata=_d(
        "order by one of: " + ", ".join(refs.PEOPLE_SORT_FIELDS)))
    order = ChoiceField(["desc", "asc"], load_default="desc", metadata=_d("sort direction (default desc)"))
    page = PageField(max_page=refs.MAX_RESULTS, metadata=_d("1-based page"))
    per_page = PageSizeField(default=PEOPLE_PAGE_SIZE, max_size=PEOPLE_MAX_PAGE_SIZE, metadata=_d(
        f"rows per page (default {PEOPLE_PAGE_SIZE}, max {PEOPLE_MAX_PAGE_SIZE})"))

    @validates_schema
    def _check(self, data, **kwargs):
        _check_ranges(data, _PEOPLE_PAIRS)
        _check_cap(data)


class PersonDetailsSchema(BaseSchema):
    person = PersonRefField(metadata=_d(
        "profile id from people/search (32 hex characters) or a propwire.com "
        "https://propwire.com/agents/<id> or https://propwire.com/cash-buyers/<id> link"))


class MarketStatsSchema(BaseSchema):
    location = PlaceField(metadata=_d('a ZIP ("78701"), "City, ST" ("Austin, TX") or "<Name> County, ST"'))

    @validates_schema
    def _not_a_state(self, data, **kwargs):
        place = data.get("location") or {}
        if place and set(place) == {"state"}:
            raise ValidationError('Market stats need a ZIP, "City, ST" or "<Name> County, ST", not a whole state.',
                                  "location")


class AutocompleteSchema(BaseSchema):
    query = QueryField(max_length=120, metadata=_d("the start of a city, county, state, ZIP or street address"))
    types = CommaListField(value_map=refs.AUTOCOMPLETE_TYPES, upper=False, max_items=5, metadata=_d(
        "comma list restricting the kinds returned: " + ", ".join(refs.AUTOCOMPLETE_TYPES) + " (default all)"))
