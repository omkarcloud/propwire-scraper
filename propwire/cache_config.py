"""Cache TTL per /propwire/* endpoint (cache.py, keyed on the validated
params). Propwire's property records are county assessor / recorder data
refreshed on a weekly-to-monthly cadence; only the MLS snapshot (status,
list price, days on market) moves daily, so a day of caching on a record and
a quarter of a day on a search never serves a materially stale row.
"""
from datetime import timedelta

# properties/search: a results page; MLS status and new recordings move daily.
SEARCH_CACHE = timedelta(hours=6)
# properties/details: assessor + recorder record, weeks between changes.
DETAILS_CACHE = timedelta(hours=24)
# properties/lookup + locations/autocomplete: addresses and place names are stable.
LOOKUP_CACHE = timedelta(days=7)
AUTOCOMPLETE_CACHE = timedelta(days=30)
# a ZIP -> state resolution (auto_complete) never changes.
ZIP_CACHE = timedelta(days=30)
# people/search: agents and cash buyers gain a transaction a month at most.
PEOPLE_SEARCH_CACHE = timedelta(hours=12)
# the matching-people count of one filter set (shared by every page of it).
PEOPLE_COUNT_CACHE = timedelta(hours=12)
# people/details: a profile's sales history moves with the same cadence.
PERSON_CACHE = timedelta(hours=24)
# markets/stats: Redfin-style monthly market rows and census demographics.
MARKET_CACHE = timedelta(days=7)
