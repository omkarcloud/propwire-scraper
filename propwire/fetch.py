"""Propwire transport: plain curl_cffi with browser-impersonated TLS, no
browser. Every surface is JSON the site's own React app calls; a session
first GETs the homepage once, which mints what the calls need:

  * the guest JWT in the Inertia page's `data-page` props (`token`, HS256,
    valid 2 h) — the Bearer every api.propwire.com call and the people
    routes want. It is bound to the session that minted it (a token replayed
    from another exit draws the DataDome captcha), so it is never shared.
  * the `XSRF-TOKEN` cookie, echoed as the X-XSRF-Token header on the
    propwire.com POSTs (Laravel's CSRF check: 419 otherwise), read from the
    jar right before each request because Laravel rotates it.
  * the `datadome` cookie, which api.propwire.com/api/property_search
    requires (a captcha 403 without it).

Two session kinds, one of each per thread (config's "--- Propwire ---"
block, pod probe 2026-10-31):

  * WEB     propwire.com JSON (property-details, people-search, profiles,
            local_markets) and api.propwire.com/api/auto_complete — open
            from the pod's own IP; config.PROPWIRE_WEB_EXIT ("direct").
  * SEARCH  api.propwire.com/api/property_search — DataDome refuses the
            pod's own IP and every datacenter exit for every curl TLS
            profile, and passes 4 of 6 US residential exits; one sticky US
            residential exit per session, dropped on a block so the retry
            rides a fresh one; config.PROPWIRE_EXIT ("us").

Failure taxonomy (scraper_errors, mapped to HTTP by route_glue):
  PropwireUpstreamError  transport failure / 5xx                — retryable
  PropwireBlocked        DataDome 403 / 401 token / 419 CSRF /  — retryable on a
                         429 / non-JSON                            fresh session
  PropwireBadRequest     400 / 422 validation, a membership-only — never retried
                         lead type (403 *Forbidden)
  PropwireNotFound       404 / an empty record                   — never retried
"""
import json
import os
import sys
import threading
import time
from urllib.parse import unquote

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import egress
from scraper_errors import BadRequest, Blocked, NotFound, UpstreamError
from propwire import parsers
from propwire.refs import API, SITE

# curl TLS profiles tried in order on the SAME exit when the homepage is
# refused (owner rule: try another fingerprint before blaming the IP). In
# the pod chrome and safari17_0 pass and fail on the same exits (probe
# 2026-10-31); from a home ISP on 2026-11-02 DataDome refused chrome and
# served safari17_0. chrome136 / edge101 / firefox135 are refused outright.
IMPERSONATE_PROFILES = ("chrome", "safari17_0")
IMPERSONATE = IMPERSONATE_PROFILES[0]
PAGE_TIMEOUT = 30      # the homepage is ~240 KB
JSON_TIMEOUT = 30

WEB, SEARCH = "web", "search"

# membership-only lead types: the API's own refusal codes (never retried)
_MEMBERSHIP_ERRORS = ("PremiumLeadsForbidden", "NewPremiumForbidden", "GoldForbidden",
                      "CLPForbidden", "LLPForbidden")


class PropwireUpstreamError(UpstreamError):
    """Transport failure or 5xx — retryable."""


class PropwireBlocked(PropwireUpstreamError, Blocked):
    """DataDome / token / CSRF refusal — retryable on a fresh session."""


class PropwireBadRequest(BadRequest):
    """The API rejected the parameters — never retried."""


class PropwireNotFound(NotFound):
    """Unknown property / profile — never retried."""


# ---- sessions ------------------------------------------------------------------

class _State:
    __slots__ = ("session", "token", "minted_at", "proxy")

    def __init__(self, session, token, proxy):
        self.session, self.token, self.proxy = session, token, proxy
        self.minted_at = time.monotonic()


_local = threading.local()


def _proxy_for(kind):
    return config.propwire_proxy() if kind == SEARCH else config.propwire_web_proxy()


def _mint(kind):
    """A new curl session on a fresh exit, warmed on the homepage. A refused
    homepage tries the next TLS profile on the same exit before raising."""
    proxy = _proxy_for(kind)
    blocked = None
    for profile in IMPERSONATE_PROFILES:
        try:
            return _mint_with(profile, proxy)
        except PropwireBlocked as e:
            blocked = e
    raise blocked


def _mint_with(profile, proxy):
    from curl_cffi import requests as curl_requests
    sess = curl_requests.Session(impersonate=profile)
    if proxy:
        sess.proxies = {"http": proxy, "https": proxy}
    headers = {
        "accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
                   "image/avif,image/webp,*/*;q=0.8"),
        "accept-language": egress.accept_language(proxy),
        "upgrade-insecure-requests": "1",
    }
    try:
        resp = sess.get(SITE + "/", headers=headers, timeout=PAGE_TIMEOUT)
    except Exception as e:
        sess.close()
        raise PropwireUpstreamError(f"homepage request failed: {type(e).__name__}: {e}")
    if resp.status_code in (401, 403, 429, 503):
        sess.close()
        raise PropwireBlocked(f"homepage HTTP {resp.status_code} (anti-bot) on this exit ({profile})")
    if resp.status_code != 200:
        sess.close()
        raise PropwireUpstreamError(f"homepage HTTP {resp.status_code}")
    try:
        token = parsers.guest_token(resp.text)
    except ValueError as e:
        sess.close()
        raise PropwireBlocked(f"homepage carried no guest token: {e}")
    sess.headers["accept-language"] = headers["accept-language"]
    return _State(sess, token, proxy)


def _state(kind):
    states = getattr(_local, "states", None)
    if states is None:
        states = _local.states = {}
    state = states.get(kind)
    if state is not None and time.monotonic() - state.minted_at > config.PROPWIRE_SESSION_TTL:
        _drop_session(kind)
        state = None
    if state is None:
        state = states[kind] = _mint(kind)
    return state


def _drop_session(kind):
    """Close the thread's session of one kind so the retry mints a new one
    (on a fresh exit for the SEARCH kind)."""
    states = getattr(_local, "states", None) or {}
    state = states.pop(kind, None)
    if state is not None:
        try:
            state.session.close()
        except Exception:
            pass


def _cookie(sess, name):
    """A cookie's current value from the jar (curl_cffi 0.16 and 0.17 expose
    the jar differently; walking it works on both)."""
    value = None
    try:
        for cookie in (getattr(sess.cookies, "jar", None) or sess.cookies):
            if getattr(cookie, "name", None) == name:
                value = cookie.value
    except Exception:
        value = None
    return unquote(value) if value else ""


def _retrying(fn, kind):
    """Run fn() under the shared retry policy: PropwireUpstreamError (and so
    Blocked) drops the session and retries; NotFound / BadRequest surface
    at once."""
    last = None
    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            return fn()
        except PropwireUpstreamError as e:
            last = e
            _drop_session(kind)
            if attempt < config.MAX_RETRIES:
                time.sleep(config.RETRY_BACKOFF * attempt)
    raise last


# ---- the response taxonomy --------------------------------------------------------

def _json_or_none(resp):
    try:
        return resp.json()
    except Exception:
        return None


def _message(payload, fallback):
    if isinstance(payload, dict):
        for key in ("message", "error"):
            if isinstance(payload.get(key), str) and payload[key]:
                text = payload[key]
                details = payload.get("details") or payload.get("errors")
                if details:
                    text += f": {json.dumps(details, ensure_ascii=False)[:300]}"
                return text
    return fallback


def _classify(resp, label):
    """HTTP status -> the taxonomy; returns the parsed JSON on 200."""
    status = resp.status_code
    payload = _json_or_none(resp)
    if status == 200:
        if payload is None:
            raise PropwireBlocked(f"non-JSON answer for {label}: {resp.text[:120]!r}")
        return payload
    if status == 404:
        raise PropwireNotFound(_message(payload, f"{label} not found"))
    if status in (400, 422):
        raise PropwireBadRequest(_message(payload, f"HTTP {status} for {label}"))
    if status == 403:
        error = payload.get("error") if isinstance(payload, dict) else None
        if error in _MEMBERSHIP_ERRORS:
            raise PropwireBadRequest(_message(payload, "this lead type needs a paid Propwire membership"))
        raise PropwireBlocked(f"HTTP 403 for {label} (anti-bot) on this exit")
    if status in (401, 419, 429, 503):
        raise PropwireBlocked(f"HTTP {status} for {label}")
    raise PropwireUpstreamError(f"HTTP {status} for {label}")


def _api_headers(state):
    return {
        "accept": "application/json",
        "content-type": "application/json",
        "origin": SITE,
        "referer": SITE + "/",
        "authorization": f"Bearer {state.token}",
        "x-api-key": config.PROPWIRE_FRONTEND_KEY,
    }


def _web_headers(state):
    return {
        "accept": "application/json",
        "content-type": "application/json",
        "referer": SITE + "/search",
        "x-requested-with": "XMLHttpRequest",
        "authorization": f"Bearer {state.token}",
        "x-xsrf-token": _cookie(state.session, "XSRF-TOKEN"),
    }


def _post(kind, url, body, label, headers_for):
    def once():
        state = _state(kind)
        try:
            resp = state.session.post(url, json=body, headers=headers_for(state), timeout=JSON_TIMEOUT)
        except Exception as e:
            raise PropwireUpstreamError(f"request failed for {label}: {type(e).__name__}: {e}")
        return _classify(resp, label)
    return _retrying(once, kind)


def _get(kind, url, label, headers_for, params=None):
    def once():
        state = _state(kind)
        try:
            resp = state.session.get(url, headers=headers_for(state), params=params, timeout=JSON_TIMEOUT)
        except Exception as e:
            raise PropwireUpstreamError(f"request failed for {label}: {type(e).__name__}: {e}")
        return _classify(resp, label)
    return _retrying(once, kind)


# ---- the surfaces ---------------------------------------------------------------------

def fetch_property_search(body):
    """POST api.propwire.com/api/property_search (the SEARCH session). Body
    = the site's own payload: locations / lead_type / ranges / sort / size /
    result_index / count / ids. Returns the raw payload."""
    return _post(SEARCH, API + "/property_search", body, "property search", _api_headers)


def fetch_autocomplete(term, types):
    """POST api/auto_complete: {search, search_types: [C, Z, N, T, A]}."""
    return _post(WEB, API + "/auto_complete", {"search": term, "search_types": list(types)},
                 "autocomplete", _api_headers)


def fetch_property_details(property_id):
    """GET propwire.com/property-details/<id> (JSON). Unknown ids answer 404
    "Property not found."; an empty `response` is treated the same."""
    payload = _get(WEB, f"{SITE}/property-details/{int(property_id)}", f"property {property_id}", _web_headers)
    rows = payload.get("response") if isinstance(payload, dict) else None
    if not rows:
        raise PropwireNotFound(f"property {property_id} not found")
    return payload


def fetch_people_search(body):
    """POST propwire.com/people-search (one people_lead_type, state required)."""
    return _post(WEB, SITE + "/people-search", body, "people search", _web_headers)


def fetch_people_count(body):
    """POST propwire.com/people-search/count -> {"result_count": N}."""
    return _post(WEB, SITE + "/people-search/count", body, "people count", _web_headers)


def fetch_agent_profile(person_id):
    """GET propwire.com/people/agents/<hash>; 404 "No such profile found."."""
    return _get(WEB, f"{SITE}/people/agents/{person_id}", f"agent {person_id}", _web_headers)


def fetch_cash_buyer_profile(person_id):
    """GET propwire.com/people/cash-buyers/<hash>."""
    return _get(WEB, f"{SITE}/people/cash-buyers/{person_id}", f"cash buyer {person_id}", _web_headers)


def fetch_market_stats(place, summary):
    """POST propwire.com/local_markets/search: {zip} | {city, state} |
    {county, state} + summary (true = the market cards, false = the place
    record with demographics and monthly trend rows)."""
    return _post(WEB, SITE + "/local_markets/search", {**place, "summary": bool(summary)},
                 "market stats", _web_headers)
