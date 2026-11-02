"""Use the scraper straight from Python — no server needed.

    python main.py

Every function returns the same JSON the API does; results are written to
output/*.json. Params go through the same schemas the API uses, so defaults
are filled in and a property id or link both work.
"""
import json
import os

from propwire import api, schemas

os.makedirs("output", exist_ok=True)


def save(name, data):
    path = os.path.join("output", name)
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"saved {path}")


def run(schema_cls, fn, **params):
    return fn(**schema_cls().load(params))


if __name__ == "__main__":
    # a property id or any propwire.com property link — owner, mortgages, sale history, tax, MLS photos
    save("property_malibu_oceanfront.json",
         run(schemas.PropertyDetailsSchema, api.property_details, property="27435249"))

    # owner leads by place: 25 motivated-seller flags, value / equity / size / owner filters, up to 250 a page
    save("search_beverly_hills_high_equity.json",
         run(schemas.PropertiesSearchSchema, api.properties_search,
             location="Beverly Hills, CA", lead_type="high_equity", per_page="25"))

    # median prices, inventory, days on market, demographics and monthly trends for a ZIP
    save("market_90210.json", run(schemas.MarketStatsSchema, api.market_stats, location="90210"))
