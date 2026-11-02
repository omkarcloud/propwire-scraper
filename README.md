# 🏠 Propwire Scraper

Propwire Scraper is a **free and open-source** scraper that gets you **unlimited** detailed Propwire property, owner and lead data for free.

## ✨ What Can I Get?

- 🏠 **Full records on 157M+ US properties** — owner & mailing address, mortgages, sale history, foreclosure, tax & MLS photos
- 🎯 **25 motivated-seller lead filters** — absentee owners, high equity, pre-foreclosures, vacant homes, tired landlords & more
- 📇 **Agents & cash buyers in all 50 states** — phones, emails, licenses, deal counts & portfolios
- 📈 **4+ years of market trends for US ZIPs, cities & counties** — median prices, inventory, days on market & demographics

## 🎥 Example: A Full Propwire Property

```json
{
  "id": 27435249,
  "link": "https://propwire.com/realestate/33360-Pacific-Coast-Hwy-Malibu-CA/27435249/property-details",
  "address": { "street": "33360 Pacific Coast Hwy", "city": "Malibu", "county": "Los Angeles", "state": "CA", "zip": "90265" },
  "property_type": "single_family",
  "building": { "year_built": 1981, "bedrooms": 3, "bathrooms": 3, "living_area_sqft": 3592 },
  "lot": { "size_sqft": 26748, "size_acres": 0.614 },
  "valuation": { "estimated_value": 31859220, "estimated_equity": 17532067, "estimated_equity_percent": 55 },
  "last_sale": { "price": 28000000, "date": "2019-11-01" },
  "owner": {
    "names": ["Fg Trust"],
    "is_owner_occupied": false,
    "mailing_address": { "city": "Encinitas", "state": "CA", "zip": "92024" }
  },
  "lead_types": ["absentee_owner", "adjustable_loan", "cash_buyer", "mls_active", "tired_landlord"],
  "mortgages": [
    { "loan_amount": 11935000, "loan_balance": 10199087.26, "interest_rate": 3.5, "is_adjustable": true, "maturity_date": "2049-12-18" }
  ],
  "transfer_history": [
    { "recording_date": "2019-11-01", "amount": 28000000, "grantor_name": "Adelaide Lake Llc", "grantee_name": "Fg Trust" }
  ],
  "tax": { "assessed": { "total": 31234529 }, "bill": { "amount": 371283.37, "year": 2025 } },
  "mls": {
    "days_on_market": 82,
    "listing": { "status": "Active", "list_price": 39500000, "currency": "USD", "agent": { "name": "Chad Pittman" }, "office": { "name": "W Real Estate" } }
  },
  "photos": ["https://images.propwire.com/properties/27435249/c28715b25c2dc98f33db4cf96f4f1aec/73814a8b6edca6995ea55d9334c1a081.webp"]
}
```

*Trimmed for readability.*

## 🚀 Unlimited Free Propwire Data — Get It in 60 Seconds

1️⃣ Clone and install:
```bash
git clone https://github.com/omkarcloud/propwire-scraper
cd propwire-scraper
python -m pip install -r requirements.txt
```

2️⃣ Start the API:
```bash
python run.py
```

3️⃣ Get your first data:
```bash
curl "http://localhost:8000/properties/details?property=27435249"
```

```json
{
  "id": 27435249,
  "link": "https://propwire.com/realestate/33360-Pacific-Coast-Hwy-Malibu-CA/27435249/property-details",
  "address": { "street": "33360 Pacific Coast Hwy", "city": "Malibu", "state": "CA", "zip": "90265" },
  "property_type": "single_family",
  "valuation": { "estimated_value": 31859220, "estimated_equity": 17532067, "estimated_equity_percent": 55 },
  "last_sale": { "price": 28000000, "date": "2019-11-01" },
  "owner": { "names": ["Fg Trust"], "is_owner_occupied": false },
  "lead_types": ["absentee_owner", "adjustable_loan", "cash_buyer", "mls_active", "tired_landlord"],
  "mls": {
    "days_on_market": 82,
    "listing": { "status": "Active", "list_price": 39500000, "currency": "USD" }
  }
}
```

All 7 endpoints are now live at `http://localhost:8000`.

Running it on a cloud server? Propwire's anti-bot refuses datacenter IPs on the property search, so set `PROPWIRE_PROXY` to a US residential proxy (`PROPWIRE_PROXY=http://user:pass@host:port python run.py`). From a home connection you don't need one.

## 📚 Endpoints

7 endpoints cover everything you need.

| Endpoint | Path | Returns |
|---|---|---|
| Property Details | `/properties/details` | Owner, mortgages, sale history, foreclosure, tax, specs & MLS photos |
| Search Properties | `/properties/search` | Owner leads with equity and 25 motivated-seller filters, 250 per page |
| Autocomplete Locations | `/locations/autocomplete` | Cities, ZIPs, counties, states and addresses as you type |
| Lookup Property by Address | `/properties/lookup` | Property ID, APN and coordinates for any US address |
| Search Agents and Cash Buyers | `/people/search` | Agents with phones and licenses, cash buyers with deal counts |
| Agent or Cash Buyer Details | `/people/details` | An agent's email and recent sales, or a cash buyer's portfolio |
| Market Stats | `/markets/stats` | Median prices, inventory, days on market, demographics and trends |

## 🔍 Exploring Parameters

The same API is published on RapidAPI, and its playground is the easiest place to try parameters and see raw responses. Once a request looks right, run it locally for **unlimited free** data.

1. [Subscribe to the free plan](https://rapidapi.com/OmkarCloud/api/best-propwire-scraper-free-1000-calls/pricing) — 1,000 calls/month, no credit card.
2. [Try the endpoints in the playground](https://rapidapi.com/OmkarCloud/api/best-propwire-scraper-free-1000-calls/playground) — every param is pre-filled, so you see real data in one click.
3. Copy the generated code and replace `https://best-propwire-scraper-free-1000-calls.p.rapidapi.com` with `http://localhost:8000`. It will now run against your local API.

```python
import requests

# generated by the playground, host swapped for the local API
response = requests.get(
    "http://localhost:8000/properties/search",
    params={"location": "Beverly Hills, CA", "lead_type": "high_equity"},
)
print(response.json())
```

## 💬 Have Questions? We Have Answers.

You're a developer — we know how hard completing a project can be. So we offer full support: just message us and we'll reply ✅ with a solution within 1 working day.

[![Message Us on WhatsApp about Propwire Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/whatsapp-us.png)](https://api.whatsapp.com/send?phone=918178804274&text=I%20need%20help%20using%20the%20Propwire%20Scraper%20API.)

[![Ask Us by Email about Propwire Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/ask-on-email.png)](mailto:happy.to.help@omkar.cloud?subject=Help%20with%20Propwire%20Scraper%20API&body=I%20need%20help%20using%20the%20Propwire%20Scraper%20API.)

## ⚡ Popular Scrapers by Omkar Cloud

- [**Google Maps Scraper (3,100+ GitHub Stars)**](https://github.com/omkarcloud/google-maps-scraper) — type "dentists in New York", get every business as a ready-to-call lead list: phones, emails, websites & reviews. Up to 100K free leads/month.
- [**G2 Scraper**](https://www.omkar.cloud/tools/g2-scraper) — G2 product details, ratings & AI-found contacts
- [**Website Email Contact Scraper**](https://www.omkar.cloud/tools/website-email-contact-scraper) — emails, phones & socials from any website
- [**AliExpress Scraper**](https://www.omkar.cloud/tools/aliexpress-scraper-api) — live product details, SKU variants, stock & shipping
- [**Booking Scraper**](https://www.omkar.cloud/tools/booking-scraper) — Booking.com hotels: prices, ratings, rooms & amenities
- [**Etsy Scraper**](https://www.omkar.cloud/tools/etsy-scraper) — Etsy products: prices, discounts, shops & variations

## ⭐ Love It? [Star It ⭐!](https://github.com/omkarcloud/propwire-scraper)

Star the repo ⭐ and become my star hero!

It's just 1 click, but it means the world to me.

[![Star us on GitHub](https://raw.githubusercontent.com/omkarcloud/google-maps-scraper/master/screenshots/star-us.png)](https://github.com/omkarcloud/propwire-scraper)
